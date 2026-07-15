"""Headless GUI contract tests for Phase 2B.

The tests below inspect source and use small fake sentinels.  They do *not*
construct Tk/CustomTkinter widgets and therefore do not claim real display,
drag-and-drop, scrolling, or EXE evidence.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "src" / "aitool_desktop" / "app.py"
THEME_PATH = REPO_ROOT / "src" / "aitool_desktop" / "theme.py"
APP_SOURCE = APP_PATH.read_text(encoding="utf-8")
THEME_SOURCE = THEME_PATH.read_text(encoding="utf-8")
APP_TREE = ast.parse(APP_SOURCE, filename=str(APP_PATH))


def _function(name: str, *, tree: ast.AST = APP_TREE) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}()")


def _source(node: ast.AST, source: str = APP_SOURCE) -> str:
    lines = source.splitlines()
    lineno = getattr(node, "lineno")
    end_lineno = getattr(node, "end_lineno")
    return "\n".join(lines[lineno - 1 : end_lineno])


def _dict_keys(node: ast.AST) -> set[str]:
    if not isinstance(node, ast.Dict):
        return set()
    return {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


class GuiContractTests(unittest.TestCase):
    """Source/fake checks only; this class intentionally has no real Tk setup."""

    REGION_PARENTS = {
        "content": "self",
        "station_section": "self.content",
        "station_scroll": "self.station_section",
        "actions_scroll": "self.content",
        "statusbar": "self",
    }

    def test_five_named_regions_are_explicit_and_owned_by_the_approved_parent(self) -> None:
        """This verifies the declared hierarchy, not a live widget hierarchy."""

        for name, parent in self.REGION_PARENTS.items():
            matching: list[ast.Call] = []
            for node in ast.walk(APP_TREE):
                if not isinstance(node, ast.Assign):
                    continue
                if not any(
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr == name
                    for target in node.targets
                ):
                    continue
                if isinstance(node.value, ast.Call):
                    matching.append(node.value)
            self.assertEqual(len(matching), 1, f"{name} must have one constructor owner")
            self.assertEqual(ast.unparse(matching[0].args[0]), parent)

        self.assertIn("self.station_scrollbar", APP_SOURCE)
        self.assertIn("self.actions_scrollbar", APP_SOURCE)

    def test_refresh_ownership_is_exclusive_and_statusbar_is_not_refresh_owned(self) -> None:
        station = _source(_function("_refresh_station"))
        cards = _source(_function("_refresh_cards"))

        self.assertIn("_station_item_host.winfo_children()", station)
        self.assertNotIn("_action_item_host", station)
        self.assertNotIn("statusbar", station)
        self.assertIn("_action_item_host.winfo_children()", cards)
        self.assertNotIn("_station_item_host", cards)
        self.assertNotIn("statusbar", cards)
        self.assertNotIn("self.content.destroy", APP_SOURCE)
        self.assertNotIn("self.statusbar.destroy", APP_SOURCE)

    def test_source_has_no_child_order_refresh_contract(self) -> None:
        for node in ast.walk(APP_TREE):
            if not isinstance(node, ast.Subscript):
                continue
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                self.assertNotEqual(value.func.attr, "winfo_children")
            if isinstance(value, ast.Name):
                self.assertNotEqual(value.id, "children")
            if isinstance(value, ast.Attribute):
                self.assertNotEqual(value.attr, "children")

    def test_diagnostic_apis_and_schema_are_stable(self) -> None:
        dnd_expected = {"generation", "targets", "sources", "failures"}
        dnd_initial: ast.Dict | None = None
        for node in ast.walk(APP_TREE):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "_DND_DIAGNOSTICS"
                for target in node.targets
            ):
                if isinstance(node.value, ast.Dict):
                    dnd_initial = node.value
                    break
        self.assertIsNotNone(dnd_initial)
        self.assertEqual(_dict_keys(dnd_initial), dnd_expected)  # type: ignore[arg-type]

        dnd_get = _source(_function("get_dnd_diagnostics"))
        for key in dnd_expected:
            self.assertIn(f'"{key}"', dnd_get)
        for kind in ("targets", "sources"):
            nested = next(
                value
                for key, value in zip(dnd_initial.keys, dnd_initial.values)
                if isinstance(key, ast.Constant) and key.value == kind
            )
            self.assertIsInstance(nested, ast.Dict)
            self.assertEqual(_dict_keys(nested), {"attempted", "succeeded", "failed"})
        record = _source(_function("_record_dnd_registration"))
        for key in ("widget_id", "kind", "error_type", "error_message"):
            self.assertIn(f'"{key}"', record)

        icon_class = next(
            node
            for node in APP_TREE.body
            if isinstance(node, ast.ClassDef) and node.name == "WindowsIconCache"
        )
        icon_methods = {
            node.name
            for node in icon_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertTrue({"reset_diagnostics", "diagnostics_snapshot"} <= icon_methods)
        icon_source = _source(icon_class)
        for key in ("requests", "successes", "failures", "fallbacks", "last"):
            self.assertIn(f'"{key}"', icon_source)
        for key in ("path_or_extension", "real_icon", "fallback", "error_type", "error_message"):
            self.assertIn(f'"{key}"', icon_source)

    def test_shell_and_dnd_failure_paths_remain_observable(self) -> None:
        self.assertIn("logger.warning(\"DND %s registration failed", APP_SOURCE)
        self.assertIn("_record_dnd_registration(\"target\", self, False, exc)", APP_SOURCE)
        self.assertIn("_record_dnd_registration(\"source\", w, False, exc)", APP_SOURCE)
        self.assertIn("shell_error =", APP_SOURCE)
        self.assertIn("fallback=True", APP_SOURCE)
        self.assertIn("cls._record_diagnostic", APP_SOURCE)

    def test_disabled_tokens_are_defined_and_connected_to_native_tk_text(self) -> None:
        """Token wiring is source-checked; native widget readability is manual GUI evidence."""

        for token in ("disabled_foreground", "disabled_background"):
            self.assertIn(f'"{token}"', THEME_SOURCE)
            self.assertIn(f'self._t("{token}")', APP_SOURCE)
        configure = _source(_function("_configure_disabled_textbox"))
        self.assertIn("textbox.configure(", configure)
        self.assertIn("text_color=", configure)
        self.assertIn("fg_color=", configure)
        self.assertNotIn("textbox._textbox.configure", configure)
        self.assertRegex(APP_SOURCE, r'review_text\.configure\(state=["\']disabled["\']\)')

    def test_fake_named_host_sentinel_proves_refresh_scope_only(self) -> None:
        """A fake host proves ownership semantics and is not evidence of a Tk tree."""

        surface = _FakeSurface()
        status_before = list(surface.statusbar)
        station_before = list(surface.hosts["station"].items)
        surface.refresh("actions", ["action:new"])
        self.assertEqual(surface.hosts["actions"].items, ["action:new"])
        self.assertEqual(surface.statusbar, status_before)
        self.assertEqual(surface.hosts["station"].items, station_before)


class _FakeHost:
    def __init__(self, items: list[str]) -> None:
        self.items = list(items)

    def clear_and_rebuild(self, items: list[str]) -> None:
        self.items[:] = items


class _FakeSurface:
    """Test-only sentinel: no Tk classes, display, or widget calls."""

    def __init__(self) -> None:
        self.statusbar = ["fixed"]
        self.hosts = {
            "station": _FakeHost(["station:old"]),
            "actions": _FakeHost(["action:old"]),
        }

    def refresh(self, owner: str, items: list[str]) -> None:
        self.hosts[owner].clear_and_rebuild(items)


if __name__ == "__main__":
    unittest.main()
