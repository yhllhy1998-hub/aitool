"""Headless source contracts for the Phase 2A window layout.

These tests deliberately parse ``app.py`` instead of importing or constructing
the GUI.  They protect the names and ownership boundaries that a real Tk
window would expose without pretending that an off-screen test is GUI
evidence.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "src" / "aitool_desktop" / "app.py"
APP_SOURCE = APP_PATH.read_text(encoding="utf-8")
APP_TREE = ast.parse(APP_SOURCE, filename=str(APP_PATH))


def _method(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(APP_TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"app.py does not define {name}()")


def _method_source(name: str) -> str:
    node = _method(name)
    lines = APP_SOURCE.splitlines()
    return "\n".join(lines[node.lineno - 1 : node.end_lineno])


def _self_assignments(name: str) -> list[ast.Assign | ast.AnnAssign]:
    assignments: list[ast.Assign | ast.AnnAssign] = []
    for node in ast.walk(APP_TREE):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            targets = node.targets
        if any(
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr == name
            for target in targets
        ):
            assignments.append(node)
    return assignments


def _assigned_call(name: str) -> ast.Call:
    for node in _self_assignments(name):
        value = node.value
        if isinstance(value, ast.Call):
            return value
    raise AssertionError(f"self.{name} is not assigned from a constructor call")


class AppLayoutSourceTests(unittest.TestCase):
    """AST/source-only checks; no Tk root, display, or CustomTkinter is used."""

    def test_named_layout_regions_are_stable_single_assignments(self) -> None:
        expected = {
            "content",
            "station_section",
            "station_scroll",
            "actions_scroll",
            "statusbar",
            "station_scrollbar",
            "actions_scrollbar",
            "_station_item_host",
            "_action_item_host",
        }
        for name in expected:
            self.assertEqual(
                len(_self_assignments(name)),
                1,
                f"self.{name} must have one stable layout definition",
            )

    def test_named_regions_have_the_approved_parent_relationships(self) -> None:
        expected_parents = {
            "content": "self",
            "station_section": "self.content",
            "station_scroll": "self.station_section",
            "actions_scroll": "self.content",
            "statusbar": "self",
        }
        for name, expected_parent in expected_parents.items():
            call = _assigned_call(name)
            self.assertGreaterEqual(len(call.args), 1, f"self.{name} needs an explicit parent")
            self.assertEqual(ast.unparse(call.args[0]), expected_parent)

    def test_each_region_is_laid_out_by_its_own_builder(self) -> None:
        expected_builders = {
            "content": "_build_ui",
            "station_section": "_build_station_area",
            "station_scroll": "_build_station_area",
            "actions_scroll": "_build_card_area",
            "statusbar": "_build_statusbar",
        }
        for name, builder in expected_builders.items():
            source = _method_source(builder)
            self.assertRegex(source, rf"self\.{re.escape(name)}\s*=")
            self.assertRegex(source, rf"self\.{re.escape(name)}\.grid\(")

        self.assertIn("self._station_item_host =", _method_source("_build_station_area"))
        self.assertIn("self._action_item_host =", _method_source("_build_card_area"))

    def test_refreshes_clear_only_their_named_item_hosts(self) -> None:
        station = _method_source("_refresh_station")
        cards = _method_source("_refresh_cards")

        self.assertIn("self._station_item_host.winfo_children()", station)
        self.assertIn("w.destroy()", station)
        self.assertNotIn("_action_item_host", station)
        self.assertNotIn("statusbar", station)
        self.assertNotIn("scrollbar", station)

        self.assertIn("self._action_item_host.winfo_children()", cards)
        self.assertIn("w.destroy()", cards)
        self.assertNotIn("_station_item_host", cards)
        self.assertNotIn("statusbar", cards)
        self.assertNotIn("scrollbar", cards)

    def test_refresh_code_has_no_implicit_child_order_dependency(self) -> None:
        """Indexing a child list is forbidden even when it looks harmless."""

        for node in ast.walk(APP_TREE):
            if not isinstance(node, ast.Subscript):
                continue
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                self.assertNotEqual(
                    value.func.attr,
                    "winfo_children",
                    "refresh/layout code must not index winfo_children()",
                )
            if isinstance(value, ast.Name):
                self.assertNotEqual(value.id, "children", "children[...] is not a stable layout contract")
            if isinstance(value, ast.Attribute):
                self.assertNotEqual(value.attr, "children", "widget.children[...] is not allowed")

        self.assertIsNone(re.search(r"winfo_children\s*\(\s*\)\s*\[", APP_SOURCE))
        self.assertIsNone(re.search(r"\bchildren\s*\[", APP_SOURCE))

    def test_geometry_theme_dnd_and_exit_lifecycle_symbols_are_wired(self) -> None:
        self.assertIn("MIN_WINDOW_WIDTH", APP_SOURCE)
        self.assertIn("MIN_WINDOW_HEIGHT", APP_SOURCE)
        self.assertIn("load_and_place_window_geometry(", _method_source("_init_window"))
        self.assertIn("save_window_geometry", APP_SOURCE)
        self.assertIn("_schedule_geometry_save", APP_SOURCE)
        self.assertIn("self.after(350, self._save_window_geometry_now)", APP_SOURCE)

        self.assertIn("parse_theme_mode(", APP_SOURCE)
        self.assertIn("resolve_theme_mode(", APP_SOURCE)
        self.assertIn("theme_tokens(", APP_SOURCE)
        self.assertIn("ctk.set_appearance_mode(self.effective_theme)", APP_SOURCE)
        self.assertIn("self._tokens", APP_SOURCE)

        self.assertIn("from tkinterdnd2 import DND_FILES, DND_TEXT, TkinterDnD", APP_SOURCE)
        self.assertIn("drop_target_register(DND_FILES, DND_TEXT)", APP_SOURCE)
        self.assertIn("drag_source_register(1, DND_FILES)", APP_SOURCE)
        self.assertIn("_register_dnd_recursive", APP_SOURCE)
        self.assertIn("get_dnd_diagnostics", APP_SOURCE)
        self.assertIn("reset_dnd_diagnostics", APP_SOURCE)

        self.assertIn('self.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)', APP_SOURCE)
        self.assertIn("def _quit_from_tray", APP_SOURCE)
        self.assertIn("self.quit()", _method_source("_quit_from_tray"))
        self.assertIn("self.after(0, self._quit_from_tray)", APP_SOURCE)

    def test_disabled_theme_tokens_are_used_for_native_textbox(self) -> None:
        source = _method_source("_configure_disabled_textbox")
        self.assertIn("textbox.configure(", source)
        self.assertIn('self._t("disabled_foreground")', source)
        self.assertIn('self._t("disabled_background")', source)
        self.assertIn("text_color=", source)
        self.assertIn("fg_color=", source)
        self.assertNotIn("textbox._textbox.configure", source)

        # This is a source contract, not live GUI readability evidence.  The
        # caller owns the widget state transition after the public styling API.
        self.assertRegex(APP_SOURCE, r'review_text\.configure\(state=["\']disabled["\']\)')


if __name__ == "__main__":
    unittest.main()
