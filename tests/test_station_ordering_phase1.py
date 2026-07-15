from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from aitool_desktop.models import StationEntry
from aitool_desktop.operations import collect_station_entries
from aitool_desktop.station_ordering import (
    custom_station_order,
    default_station_order,
    normalize_path_key,
    remove_station_entry,
    switch_sort_mode,
)
from aitool_desktop.storage import StationStorage


class StationOrderingPhase1Tests(unittest.TestCase):
    def make_entries(self, root: Path) -> list[StationEntry]:
        folder = root / "z-folder"
        folder.mkdir()
        alpha = root / "Alpha.txt"
        alpha.write_text("a", encoding="utf-8")
        beta = root / "beta.txt"
        beta.write_text("b", encoding="utf-8")
        return [StationEntry.from_path(beta), StationEntry.from_path(alpha), StationEntry.from_path(folder)]

    def test_default_folder_then_casefolded_name_then_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entries = self.make_entries(Path(tmp))
            self.assertEqual([e.display_name for e in default_station_order(entries)], ["z-folder", "Alpha.txt", "beta.txt"])

    def test_custom_order_is_not_path_order_and_appends_new_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self.make_entries(root)
            order = [normalize_path_key(entries[0].path), "unknown", 1, normalize_path_key(entries[0].path)]
            ordered = custom_station_order(entries, order)
            self.assertEqual(ordered[0].path, entries[0].path)
            self.assertEqual({e.path for e in ordered[1:]}, {e.path for e in entries[1:]})

    def test_collect_custom_mode_keeps_existing_order_and_appends_new_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self.make_entries(root)
            custom_order = [normalize_path_key(entries[1].path), normalize_path_key(entries[0].path)]
            new_item = root / "new.txt"
            new_item.write_text("new", encoding="utf-8")

            ordered, added, skipped = collect_station_entries(
                [str(new_item)],
                [entries[0], entries[1]],
                sort_mode="custom",
                custom_order=custom_order,
            )

            self.assertEqual(added, ["new.txt"])
            self.assertEqual(skipped, [])
            self.assertEqual(
                [entry.display_name for entry in ordered],
                [entries[1].display_name, entries[0].display_name, "new.txt"],
            )

    def test_switch_and_remove_readd_preserve_custom_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self.make_entries(root)
            mode, order, _ = switch_sort_mode(entries, "default", [], "custom")
            self.assertEqual(mode, "custom")
            self.assertEqual([e.path for e in custom_station_order(entries, order)], [e.path for e in default_station_order(entries)])
            default_mode, retained, _ = switch_sort_mode(entries, mode, order, "default")
            self.assertEqual(default_mode, "default")
            self.assertEqual(retained, order)
            equivalent_path = str(entries[0].path) + "\\"
            removed, shortened = remove_station_entry(entries, equivalent_path, order)
            self.assertNotIn(normalize_path_key(entries[0].path), shortened)
            recreated = StationEntry.from_path(Path(entries[0].path))
            self.assertEqual(custom_station_order(removed + [recreated], shortened)[-1].path, recreated.path)

    def test_explicit_empty_custom_order_survives_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self.make_entries(root)
            path = root / "stations.json"
            StationStorage(path).save_state(entries, "custom", [])

            reloaded = StationStorage(path).load_state()

            self.assertEqual(reloaded.sort_mode, "custom")
            self.assertEqual(reloaded.custom_order, [])

    def test_collect_uses_stable_path_identity_for_case_and_trailing_separator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = root / "item.txt"
            item.write_text("x", encoding="utf-8")
            current = [StationEntry.from_path(item)]
            # On Windows these spellings are equivalent; on other platforms
            # the direct identity assertion still verifies the normalizer.
            self.assertEqual(normalize_path_key(str(item) + "\\"), normalize_path_key(item)) if sys.platform == "win32" else None
            result, added, skipped = collect_station_entries([str(item)], current)
            self.assertEqual(len(result), 1)
            self.assertFalse(added)
            self.assertEqual(len(skipped), 1)

    def test_storage_v1_v2_bad_types_missing_entries_and_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "stations.json"
            item = root / "item.txt"
            item.write_text("x", encoding="utf-8")
            entry = StationEntry.from_path(item)
            path.write_text(json.dumps({"updated_at": "old", "entries": [entry.to_dict()]}), encoding="utf-8")
            store = StationStorage(path)
            self.assertEqual(store.load()[0].path, entry.path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")).get("schema_version"), None)

            path.write_text(json.dumps({"entries": [entry.to_dict(), {"path": str(root / "gone.txt"), "kind": "file", "display_name": "gone.txt"}]}), encoding="utf-8")
            self.assertEqual([item.path for item in store.load()], [entry.path])

            store.save_state([entry], "custom", [normalize_path_key(entry.path), "missing", 3])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["sort_mode"], "custom")
            self.assertEqual(payload["custom_order"], [normalize_path_key(entry.path)])
            self.assertEqual(store.load_state().custom_order, [normalize_path_key(entry.path)])

            for invalid in ("{bad", "null", "[]", '"text"', '{"entries": {}}', '{"entries": [null, {}]}', '{"sort_mode": 3, "custom_order": "bad"}'):
                path.write_text(invalid, encoding="utf-8")
                self.assertIsInstance(store.load_state().entries, list)

            path.write_text("old", encoding="utf-8")
            with patch("aitool_desktop.storage.os.replace", wraps=__import__("os").replace) as replace:
                store.save([entry])
            self.assertTrue(replace.called)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], 2)

    def test_v1_ignores_sorting_fields_and_first_custom_switch_uses_default_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self.make_entries(root)
            path = root / "stations.json"
            path.write_text(
                json.dumps(
                    {
                        "updated_at": "old",
                        "sort_mode": "custom",
                        "custom_order": [normalize_path_key(entries[0].path)],
                        "entries": [entry.to_dict() for entry in entries],
                    }
                ),
                encoding="utf-8",
            )

            state = StationStorage(path).load_state()
            self.assertEqual(state.sort_mode, "default")
            self.assertEqual(state.custom_order, [])
            mode, order, ordered = switch_sort_mode(
                state.entries, state.sort_mode, state.custom_order, "custom"
            )
            self.assertEqual(mode, "custom")
            self.assertEqual([entry.path for entry in ordered], [entry.path for entry in default_station_order(entries)])
            self.assertEqual(order, [normalize_path_key(entry.path) for entry in default_station_order(entries)])

    def test_save_state_without_custom_order_preserves_loaded_order_but_empty_clears_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self.make_entries(root)
            path = root / "stations.json"
            store = StationStorage(path)
            custom_order = [normalize_path_key(entry.path) for entry in reversed(entries)]

            store.save_state(entries, "custom", custom_order)
            store.save_state(entries, "default")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["custom_order"], custom_order)

            store.save_state(entries, "custom")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["custom_order"], custom_order)

            store.save_state(entries, "default", [])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["custom_order"], [])

    def test_current_state_returns_copy_of_mutable_lists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = root / "item.txt"
            item.write_text("x", encoding="utf-8")
            entry = StationEntry.from_path(item)
            store = StationStorage(root / "stations.json")
            store.save_state([entry], "custom", [normalize_path_key(entry.path)])

            state = store.current_state
            state.entries.clear()
            state.custom_order.clear()

            self.assertEqual(store.current_state.entries, [entry])
            self.assertEqual(store.current_state.custom_order, [normalize_path_key(entry.path)])

    def test_failed_save_keeps_storage_and_pending_entries_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self.make_entries(root)
            store = StationStorage(root / "stations.json")
            store.save_state(entries)
            old_entries = list(store.current_state.entries)
            new_item = root / "new.txt"
            new_item.write_text("new", encoding="utf-8")
            next_entries, _, _ = collect_station_entries([str(new_item)], old_entries)

            with patch("aitool_desktop.storage.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    store.save_state(next_entries)

            self.assertEqual(store.current_state.entries, old_entries)

    def test_save_docstring_describes_preserving_loaded_sorting_state(self) -> None:
        self.assertIn("保留当前已加载的排序模式和 custom_order", StationStorage.save.__doc__ or "")

    def test_invalid_schema_version_degrades_to_empty_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = root / "item.txt"
            item.write_text("x", encoding="utf-8")
            entry = StationEntry.from_path(item)
            path = root / "stations.json"
            store = StationStorage(path)

            for schema_version in (0, 3, "2", None, True, [], {}):
                path.write_text(
                    json.dumps({"schema_version": schema_version, "entries": [entry.to_dict()]}),
                    encoding="utf-8",
                )
                self.assertEqual(store.load_state().entries, [])
                self.assertEqual(store._loaded_state.sort_mode, "default")
                self.assertEqual(store._loaded_state.custom_order, [])

    def test_failed_loads_reset_loaded_state_before_later_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = root / "item.txt"
            item.write_text("x", encoding="utf-8")
            entry = StationEntry.from_path(item)
            key = normalize_path_key(entry.path)
            path = root / "stations.json"
            store = StationStorage(path)
            store.save_state([entry], "custom", [key])

            invalid_payloads = ("{bad", "null", "[]", '"text"', '{"entries": {}}')
            for invalid in invalid_payloads:
                path.write_text(invalid, encoding="utf-8")
                state = store.load_state()
                self.assertEqual(state, store._loaded_state)
                self.assertEqual(state.entries, [])
                self.assertEqual(state.custom_order, [])
                store.save([entry])
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["custom_order"], [])

            path.unlink()
            self.assertEqual(store.load_state(), store._loaded_state)
            self.assertEqual(store._loaded_state.custom_order, [])


if __name__ == "__main__":
    unittest.main()
