from __future__ import annotations

import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from aitool_desktop.models import CustomModule, StationEntry
import aitool_desktop.app as app_module
from aitool_desktop.operations import (
    build_folder_copy_dry_run,
    collect_station_entries,
    copy_station_entry_to_directory,
    execute_folder_copy,
    execute_svn_update,
    launch_bat_script,
    preview_folder_copy,
    validate_bat_launch_path,
    validate_svn_document_update_path,
)
from aitool_desktop.storage import ModuleStorage


class DesktopToolLogicTests(unittest.TestCase):
    def test_missing_user_quick_actions_loads_builtin_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            builtin_data = root / "repo" / "data"
            builtin_data.mkdir(parents=True)
            builtin_actions = {"actions": [{"id": "builtin-action"}]}
            (builtin_data / "quick_actions.json").write_text(
                __import__("json").dumps(builtin_actions),
                encoding="utf-8",
            )

            with patch.object(app_module, "REPO_ROOT", root / "repo"), patch.object(
                app_module, "QUICK_ACTIONS_PATH", root / "user" / "quick_actions.json"
            ):
                actions = app_module.DesktopToolApp._load_quick_actions(object())

            self.assertEqual(actions, builtin_actions["actions"])

    def test_empty_user_quick_actions_do_not_restore_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            builtin_data = root / "repo" / "data"
            builtin_data.mkdir(parents=True)
            (builtin_data / "quick_actions.json").write_text(
                '{"actions": [{"id": "builtin-action"}]}',
                encoding="utf-8",
            )
            user_actions = root / "user" / "quick_actions.json"
            user_actions.parent.mkdir()
            user_actions.write_text('{"actions": []}', encoding="utf-8")

            with patch.object(app_module, "REPO_ROOT", root / "repo"), patch.object(
                app_module, "QUICK_ACTIONS_PATH", user_actions
            ):
                actions = app_module.DesktopToolApp._load_quick_actions(object())

            self.assertEqual(actions, [])

    def test_default_config_initialization_is_whitelisted_and_non_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            builtin_data = root / "repo" / "data"
            user_data = root / "user" / "AiTool"
            builtin_data.mkdir(parents=True)
            user_data.mkdir(parents=True)
            for filename in (
                "quick_actions.json",
                "custom_modules.json",
                "document_station_entries.json",
            ):
                (builtin_data / filename).write_text(f'{{"name": "builtin-{filename}"}}', encoding="utf-8")
            (builtin_data / "window_geometry.json").write_text("{}", encoding="utf-8")
            (builtin_data / "aitool.log").write_text("runtime log", encoding="utf-8")
            (builtin_data / ".user_guide_seen").write_text("seen", encoding="utf-8")

            existing_custom_modules = '{"modules": []}'
            (user_data / "custom_modules.json").write_text(existing_custom_modules, encoding="utf-8")

            with patch.object(app_module, "REPO_ROOT", root / "repo"), patch.object(
                app_module, "DATA_DIR", user_data
            ):
                app_module.DesktopToolApp._ensure_default_config(object())

            self.assertTrue((user_data / "quick_actions.json").exists())
            self.assertTrue((user_data / "document_station_entries.json").exists())
            self.assertEqual(
                (user_data / "custom_modules.json").read_text(encoding="utf-8"),
                existing_custom_modules,
            )
            self.assertFalse((user_data / "window_geometry.json").exists())
            self.assertFalse((user_data / "aitool.log").exists())
            self.assertFalse((user_data / ".user_guide_seen").exists())

    def test_collect_station_entries_dedupes_and_filters_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            existing_file = root / "alpha.txt"
            existing_file.write_text("alpha", encoding="utf-8")
            folder = root / "docs"
            folder.mkdir()

            current = [StationEntry.from_path(existing_file)]
            entries, added, skipped = collect_station_entries(
                [str(existing_file), str(folder), str(root / "missing.txt")],
                current,
            )

            self.assertEqual([item.display_name for item in entries], ["docs", "alpha.txt"])
            self.assertEqual(added, ["docs"])
            self.assertEqual(len(skipped), 2)

    def test_copy_station_entry_refuses_to_overwrite_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_file = root / "report.txt"
            source_file.write_text("report", encoding="utf-8")
            target_dir = root / "target"
            target_dir.mkdir()
            (target_dir / "report.txt").write_text("old", encoding="utf-8")

            entry = StationEntry.from_path(source_file)
            ok, message = copy_station_entry_to_directory(entry, target_dir)

            self.assertFalse(ok)
            self.assertIn("不会覆盖", message)

    def test_folder_copy_dry_run_reports_overlap_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "source"
            target = root / "target"
            (source / "nested").mkdir(parents=True)
            target.mkdir()
            (source / "a.txt").write_text("a", encoding="utf-8")
            (source / "nested" / "b.txt").write_text("b", encoding="utf-8")
            (target / "a.txt").write_text("old", encoding="utf-8")

            review = build_folder_copy_dry_run(source, target)

            self.assertEqual(review.mode, "dry-run")
            self.assertEqual(review.status, "warning")
            self.assertIn("覆盖复制评审", review.summary)
            self.assertTrue(any("命中 1 个同名项" in item for item in review.details))

    def test_validate_bat_launch_path_requires_existing_absolute_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            missing_review = validate_bat_launch_path(root / "missing.bat")
            self.assertEqual(missing_review.status, "blocked")

            script = root / "export.bat"
            script.write_text("@echo off\n", encoding="utf-8")
            ready_review = validate_bat_launch_path(script)

            self.assertEqual(ready_review.mode, "validate-only")
            self.assertEqual(ready_review.status, "warning")

    def test_validate_svn_document_update_path_keeps_write_action_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / ".svn").mkdir()

            review = validate_svn_document_update_path(workspace)

            self.assertEqual(review.mode, "validate-only")
            self.assertEqual(review.status, "warning")
            self.assertIn("路径已校验", review.summary)

    def test_preview_folder_copy_reports_overlap_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "a.txt").write_text("new", encoding="utf-8")
            (source / "b.txt").write_text("new", encoding="utf-8")
            (target / "a.txt").write_text("old", encoding="utf-8")

            review = preview_folder_copy(source, target)

            self.assertEqual(review.mode, "preview")
            self.assertEqual(review.status, "warning")
            self.assertTrue(any("覆盖 1 个同名项" in item for item in review.details))

    def test_preview_folder_copy_ready_when_target_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "source"
            source.mkdir()
            (source / "a.txt").write_text("a", encoding="utf-8")
            target = root / "target"

            review = preview_folder_copy(source, target)

            self.assertEqual(review.mode, "preview")
            self.assertEqual(review.status, "ready")

    def test_execute_folder_copy_copies_and_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "a.txt").write_text("new_a", encoding="utf-8")
            (source / "sub").mkdir()
            (source / "sub" / "b.txt").write_text("new_b", encoding="utf-8")
            (target / "a.txt").write_text("old_a", encoding="utf-8")
            (target / "keep.txt").write_text("keep", encoding="utf-8")

            review = execute_folder_copy(source, target)

            self.assertEqual(review.mode, "execute")
            self.assertEqual(review.status, "ready")
            self.assertEqual((target / "a.txt").read_text(encoding="utf-8"), "new_a")
            self.assertEqual((target / "sub" / "b.txt").read_text(encoding="utf-8"), "new_b")
            self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_execute_folder_copy_blocked_on_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "dir"
            source.mkdir()

            review = execute_folder_copy(source, source)

            self.assertEqual(review.status, "blocked")

    def test_execute_folder_copy_blocked_on_nested_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "parent"
            target = source / "child"
            source.mkdir()

            review = execute_folder_copy(source, target)

            self.assertEqual(review.status, "blocked")

    def test_launch_bat_success_returns_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            script = root / "ok.bat"
            script.write_text("@echo off\necho done\nexit 0", encoding="utf-8")

            review = launch_bat_script(script)

            self.assertEqual(review.action, "launch-bat")
            self.assertEqual(review.mode, "execute")
            self.assertEqual(review.status, "ready")
            self.assertTrue(any("退出码：0" in d for d in review.details))

    def test_launch_bat_failure_returns_blocked_with_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            script = root / "fail.bat"
            script.write_text("@echo off\necho error 1>&2\nexit 1", encoding="utf-8")

            review = launch_bat_script(script)

            self.assertEqual(review.mode, "execute")
            self.assertEqual(review.status, "blocked")
            self.assertTrue(any("退出码：1" in d for d in review.details))

    def test_launch_bat_blocked_on_missing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            missing = root / "nonexistent.bat"

            review = launch_bat_script(missing)

            self.assertEqual(review.status, "blocked")
            self.assertEqual(review.mode, "execute")

    def test_execute_svn_update_blocked_on_missing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            missing = root / "nonexistent"

            review = execute_svn_update(missing)

            self.assertEqual(review.status, "blocked")
            self.assertEqual(review.mode, "execute")

    def test_execute_svn_update_blocked_on_missing_svn_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / ".svn").mkdir()

            with patch(
                "aitool_desktop.operations._find_svn_executable",
                return_value=(None, "none"),
            ):
                review = execute_svn_update(workspace)

            self.assertEqual(review.mode, "execute")
            self.assertEqual(review.status, "blocked")
            self.assertIn("svn 客户端不可用", review.summary)

    def test_execute_svn_update_tortoise_popen_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / ".svn").mkdir()

            fake_exe = "C:\\Fake\\TortoiseProc.exe"
            with patch(
                "aitool_desktop.operations._find_svn_executable",
                return_value=(fake_exe, "tortoise"),
            ):
                with patch("aitool_desktop.operations.subprocess.Popen") as mock_popen:
                    review = execute_svn_update(workspace)

            mock_popen.assert_called_once_with(
                [fake_exe, "/command:update", f"/path:{workspace}", "/closeonend:0"],
                shell=False,
            )
            self.assertEqual(review.mode, "execute")
            self.assertEqual(review.status, "ready")

    def test_module_storage_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "modules.json"
            store = ModuleStorage(store_path)

            module = CustomModule(
                module_id="test123",
                name="我的覆盖复制",
                module_type="folder-copy",
                params={"source": "C:\\src", "target": "C:\\dst"},
            )
            store.save([module])
            loaded = store.load()

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].module_id, "test123")
            self.assertEqual(loaded[0].name, "我的覆盖复制")
            self.assertEqual(loaded[0].module_type, "folder-copy")
            self.assertEqual(loaded[0].params["source"], "C:\\src")
            self.assertEqual(loaded[0].params["target"], "C:\\dst")

    def test_module_storage_keeps_existing_empty_user_file_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "modules.json"
            store_path.write_text('{"modules": []}', encoding="utf-8")

            self.assertEqual(ModuleStorage(store_path).load(), [])

    def test_module_storage_filters_invalid_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "modules.json"
            store_path.write_text(
                '{"modules": [{"module_id": "x", "name": "bad", "module_type": "unknown", "params": {}}]}',
                encoding="utf-8",
            )
            store = ModuleStorage(store_path)
            loaded = store.load()

            self.assertEqual(len(loaded), 0)

    def test_module_storage_generate_id_unique(self) -> None:
        id1 = ModuleStorage.generate_id()
        id2 = ModuleStorage.generate_id()
        self.assertNotEqual(id1, id2)
        self.assertEqual(len(id1), 12)


if __name__ == "__main__":
    unittest.main()
