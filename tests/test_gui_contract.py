"""Headless GUI contract tests for Phase 2B.

The tests below inspect source and use small fake sentinels.  They do *not*
construct Tk/CustomTkinter widgets and therefore do not claim real display,
drag-and-drop, scrolling, or EXE evidence.
"""

from __future__ import annotations

import ast
import ctypes
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ctypes import wintypes

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import aitool_desktop.app as app_module


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

    def test_dock_restore_rechecks_position_after_restore_block(self) -> None:
        restore = _source(_function("_finish_geometry_restore"))
        self.assertIn("self._dock_restore_blocked = False", restore)
        self.assertIn("self._observe_window_position()", restore)

    def test_dock_position_observation_uses_outer_screen_rect(self) -> None:
        observe = _source(_function("_observe_window_position"))
        self.assertIn("self._window_outer_rect()", observe)
        self.assertIn("outer_top", observe)
        self.assertIn("abs(outer_top - area.top) > self._DOCK_EDGE_THRESHOLD", observe)

    def test_native_quiet_resize_block_reobserves_top_for_normal_window(self) -> None:
        class FakeDock:
            _geometry_restoring = False
            _dock_restore_blocked = False
            _dock_dragging = False
            _dock_native_interaction = True
            _dock_native_size_changed = True
            _dock_resize_blocked = False
            _dock_state = "free"
            _dock_undock_blocked = False
            _native_window_style_applied = True
            _DOCK_EDGE_THRESHOLD = app_module.DesktopToolApp._DOCK_EDGE_THRESHOLD
            _DOCK_DEBOUNCE_MS = app_module.DesktopToolApp._DOCK_DEBOUNCE_MS
            _DOCK_SIZE_CHANGE_THRESHOLD = app_module.DesktopToolApp._DOCK_SIZE_CHANGE_THRESHOLD
            _dock_pause_count = 0
            _on_top_debounce = app_module.DesktopToolApp._on_top_debounce

            _native_resize_capability_available = (
                app_module.DesktopToolApp._native_resize_capability_available
            )

            def __init__(self) -> None:
                self.scheduled = []
                self.geometry = app_module.WindowGeometry(100, 0, 500, 840)

            def _current_window_geometry(self):
                return self.geometry

            def _window_outer_rect(self):
                return (100, 0, 600, 840)

            def _window_is_maximized(self):
                return False

            def _dock_area_for_geometry(self, _geometry):
                return app_module.WorkArea(0, 0, 1920, 1040)

            def _cancel_dock_job(self, _attribute):
                pass

            def after(self, delay, callback):
                self.scheduled.append((delay, callback))
                return "job"

            def _schedule_geometry_save(self):
                pass

            _observe_window_position = app_module.DesktopToolApp._observe_window_position

        fake = FakeDock()
        app_module.DesktopToolApp._finish_native_titlebar_interaction(fake)
        self.assertFalse(fake._dock_resize_blocked)
        self.assertEqual(fake.scheduled[0][0], fake._DOCK_DEBOUNCE_MS)
        self.assertIs(fake.scheduled[0][1].__func__, app_module.DesktopToolApp._on_top_debounce)

    def test_top_edge_threshold_still_controls_dock_observation(self) -> None:
        class FakeDock:
            _geometry_restoring = False
            _dock_restore_blocked = False
            _dock_dragging = False
            _dock_native_interaction = False
            _dock_resize_blocked = False
            _dock_state = "free"
            _dock_undock_blocked = False
            _native_window_style_applied = True
            _DOCK_EDGE_THRESHOLD = app_module.DesktopToolApp._DOCK_EDGE_THRESHOLD
            _DOCK_DEBOUNCE_MS = app_module.DesktopToolApp._DOCK_DEBOUNCE_MS
            _dock_pause_count = 0

            _native_resize_capability_available = (
                app_module.DesktopToolApp._native_resize_capability_available
            )

            def __init__(self, outer_top: int) -> None:
                self.outer_top = outer_top
                self.scheduled = []

            def _current_window_geometry(self):
                return app_module.WindowGeometry(100, self.outer_top, 500, 840)

            def _window_outer_rect(self):
                return (100, self.outer_top, 600, self.outer_top + 840)

            def _window_is_maximized(self):
                return False

            def _dock_area_for_geometry(self, _geometry):
                return app_module.WorkArea(0, 0, 1920, 1040)

            def _cancel_dock_job(self, _attribute):
                pass

            def after(self, delay, callback):
                self.scheduled.append((delay, callback))
                return "job"

            _on_top_debounce = app_module.DesktopToolApp._on_top_debounce

        outside = FakeDock(13)
        app_module.DesktopToolApp._observe_window_position(outside)
        self.assertEqual(outside.scheduled, [])

        at_edge = FakeDock(12)
        app_module.DesktopToolApp._observe_window_position(at_edge)
        self.assertEqual(at_edge.scheduled[0][0], at_edge._DOCK_DEBOUNCE_MS)

    def test_native_titlebar_interaction_fences_dock_automation(self) -> None:
        maximized = _source(_function("_window_is_maximized"))
        self.assertIn('"zoomed", "maximized"', maximized)

        begin = _source(_function("_begin_native_titlebar_interaction"))
        for job in (
            'self._cancel_dock_jobs()',
            'self._cancel_geometry_save_job()',
            'self._DOCK_NATIVE_QUIET_MS',
        ):
            self.assertIn(job, begin)

        finish = _source(_function("_finish_native_titlebar_interaction"))
        self.assertIn("self._window_is_maximized()", finish)
        self.assertIn("self._dock_resize_blocked = True", finish)
        self.assertIn("self._observe_window_position()", finish)

        schedule = _source(_function("_schedule_geometry_save"))
        self.assertIn("self._begin_native_titlebar_interaction(", schedule)
        self.assertIn("self._dock_native_interaction", schedule)

    def test_native_snap_and_resize_states_cannot_start_or_continue_auto_dock(self) -> None:
        observe = _source(_function("_observe_window_position"))
        self.assertIn("self._window_is_maximized()", observe)
        self.assertIn("self._dock_native_interaction", observe)
        self.assertIn("self._dock_native_size_changed", observe)
        self.assertIn("self._DOCK_SIZE_CHANGE_THRESHOLD", observe)
        self.assertIn("self._dock_resize_blocked", observe)

        debounce = _source(_function("_on_top_debounce"))
        self.assertIn("self._dock_native_interaction", debounce)
        self.assertIn("self._dock_resize_blocked", debounce)
        self.assertIn("self._window_is_maximized()", debounce)

        animation = _source(_function("_start_dock_animation"))
        self.assertIn("self._dock_native_interaction", animation)
        self.assertIn("self._window_is_maximized()", animation)

        autohide = _source(_function("_autohide_if_pointer_left"))
        self.assertIn("self._dock_native_interaction", autohide)
        self.assertIn("self._dock_resize_blocked", autohide)

    def test_native_titlebar_style_removes_resize_and_snap_capabilities(self) -> None:
        style = _source(_function("_disable_native_resize_and_maximize"))
        for symbol in (
            "GWL_STYLE",
            "GetWindowLongPtrW",
            "SetWindowLongPtrW",
            "WS_THICKFRAME",
            "WS_SIZEBOX",
            "WS_MAXIMIZEBOX",
            "WS_CAPTION",
            "WS_SYSMENU",
            "WS_MINIMIZEBOX",
            "SWP_NOMOVE",
            "SWP_NOSIZE",
            "SWP_NOZORDER",
            "SWP_NOACTIVATE",
            "SWP_FRAMECHANGED",
        ):
            self.assertIn(symbol, style)
        self.assertIn("GA_ROOT", APP_SOURCE)

        init = _source(_function("_init_window"))
        self.assertIn("self.overrideredirect(False)", init)
        self.assertNotIn("overrideredirect(True)", APP_SOURCE)
        self.assertIn("self._apply_native_window_style_once()", init)
        self.assertIn("self._schedule_native_window_style_reapply()", init)

        apply_once = _source(_function("_apply_native_window_style_once"))
        self.assertIn("self._native_window_style_applied", apply_once)
        self.assertIn("self.winfo_id()", apply_once)

        reapply = _source(_function("_reapply_native_window_style_after_map"))
        self.assertIn("self.update_idletasks()", reapply)
        self.assertIn("self.winfo_id()", reapply)
        self.assertIn("_disable_native_resize_and_maximize(hwnd)", reapply)

        schedule = _source(_function("_schedule_native_window_style_reapply"))
        self.assertIn("self._native_window_style_reapply_scheduled", schedule)
        self.assertIn('self.bind(\"<Map>\"', schedule)
        self.assertIn("self.after_idle(self._reapply_native_window_style_after_map)", schedule)

    def test_native_style_resolves_visible_root_hwnd_from_tk_client_hwnd(self) -> None:
        class FakeGetAncestor:
            def __init__(self, visible_hwnd: int) -> None:
                self.visible_hwnd = visible_hwnd
                self.calls = []
                self.argtypes = None
                self.restype = None

            def __call__(self, hwnd, flags):
                self.calls.append((hwnd, flags))
                return self.visible_hwnd

        class FakeGetParent:
            def __init__(self) -> None:
                self.calls = []
                self.argtypes = None
                self.restype = None

            def __call__(self, hwnd):
                self.calls.append(hwnd)
                return 0

        tk_hwnd = 0x12345678
        visible_hwnd = 0x23456789
        get_ancestor = FakeGetAncestor(visible_hwnd)
        get_parent = FakeGetParent()
        user32 = SimpleNamespace(GetAncestor=get_ancestor, GetParent=get_parent)

        with patch.object(app_module.os, "name", "nt"), patch.object(
            app_module.ctypes, "windll", SimpleNamespace(user32=user32)
        ):
            self.assertEqual(
                app_module._resolve_native_window_hwnd(tk_hwnd),
                visible_hwnd,
            )

        self.assertEqual(len(get_ancestor.calls), 1)
        self.assertEqual(get_ancestor.calls[0][0].value, tk_hwnd)
        self.assertEqual(get_ancestor.calls[0][1], app_module.GA_ROOT)
        self.assertEqual(get_parent.calls, [])

    def test_window_outer_rect_queries_the_resolved_native_root_hwnd(self) -> None:
        class FakeGetWindowRect:
            def __init__(self) -> None:
                self.calls = []

            def __call__(self, hwnd, rect_pointer):
                self.calls.append((hwnd, rect_pointer))
                rect = rect_pointer._obj
                rect.left = 10
                rect.top = 20
                rect.right = 310
                rect.bottom = 420
                return 1

        get_window_rect = FakeGetWindowRect()
        user32 = SimpleNamespace(GetWindowRect=get_window_rect)
        fake_window = SimpleNamespace(winfo_id=lambda: 0x1234)
        resolved_hwnd = 0x5678

        with patch.object(app_module.os, "name", "nt"), patch.object(
            app_module.ctypes, "windll", SimpleNamespace(user32=user32)
        ), patch.object(
            app_module, "_resolve_native_window_hwnd", return_value=resolved_hwnd
        ) as resolve_hwnd:
            self.assertEqual(
                app_module.DesktopToolApp._window_outer_rect(fake_window),
                (10, 20, 310, 420),
            )

        resolve_hwnd.assert_called_once_with(0x1234)
        self.assertEqual(get_window_rect.calls[0][0], resolved_hwnd)

    def test_tray_restore_relies_on_persistent_map_style_reapply(self) -> None:
        restore = _source(_function("_restore_from_tray"))
        schedule = _source(_function("_schedule_native_window_style_reapply"))
        self.assertIn("self.deiconify()", restore)
        self.assertNotIn("_schedule_native_window_style_reapply", restore)
        self.assertIn('self.bind("<Map>", self._reapply_native_window_style_after_map, add="+")', schedule)

    def test_native_style_uses_pointer_sized_ctypes_and_verifies_second_read(self) -> None:
        class FakeGetWindowLongPtr:
            def __init__(self, style: int) -> None:
                self.style = style
                self.calls = []
                self.argtypes = None
                self.restype = None

            def __call__(self, hwnd, index):
                self.calls.append((hwnd, index))
                return self.style

        class FakeSetWindowLongPtr:
            def __init__(self, getter: FakeGetWindowLongPtr) -> None:
                self.getter = getter
                self.calls = []
                self.argtypes = None
                self.restype = None

            def __call__(self, hwnd, index, value):
                self.calls.append((hwnd, index, value))
                previous = self.getter.style
                self.getter.style = int(getattr(value, "value", value))
                return previous

        class FakeSetWindowPos:
            def __init__(self) -> None:
                self.calls = []
                self.argtypes = None
                self.restype = None

            def __call__(self, *args):
                self.calls.append(args)
                return 1

        hwnd = 0x1234567887654321
        getter = FakeGetWindowLongPtr(0x16CF0008)
        setter = FakeSetWindowLongPtr(getter)
        set_pos = FakeSetWindowPos()
        user32 = SimpleNamespace(
            GetWindowLongPtrW=getter,
            SetWindowLongPtrW=setter,
            SetWindowPos=set_pos,
        )

        with patch.object(app_module.os, "name", "nt"), patch.object(
            app_module.ctypes, "windll", SimpleNamespace(user32=user32)
        ):
            self.assertTrue(app_module._disable_native_resize_and_maximize(hwnd))

        self.assertEqual(getter.argtypes, [wintypes.HWND, ctypes.c_int])
        self.assertIs(getter.restype, app_module._LONG_PTR)
        self.assertEqual(setter.argtypes, [wintypes.HWND, ctypes.c_int, app_module._LONG_PTR])
        self.assertIs(setter.restype, app_module._LONG_PTR)
        self.assertIs(set_pos.restype, wintypes.BOOL)
        self.assertEqual(getter.calls[0][0].value, hwnd)
        self.assertEqual(len(getter.calls), 3, "style must be read before and after both native updates")
        self.assertEqual(setter.calls[0][0].value, hwnd)
        self.assertIsInstance(setter.calls[0][2], app_module._LONG_PTR)
        self.assertEqual(set_pos.calls[0][0].value, hwnd)
        self.assertEqual(getter.style & app_module._NATIVE_STYLE_MASK, 0)

    def test_negative_outer_position_uses_native_positioning_and_expected_token(self) -> None:
        class FakeWindow:
            def __init__(self) -> None:
                self.geometry_calls = []

            def _current_window_geometry(self):
                return app_module.WindowGeometry(100, 100, 500, 840)

            def _geometry_for_outer_position(self, x, y, geometry):
                return app_module.WindowGeometry(x, y, geometry.width, geometry.height)

            def winfo_id(self):
                return 0x1234

            def _set_window_geometry(self, geometry, **kwargs):
                self.geometry_calls.append((geometry, kwargs))


        fake = FakeWindow()
        with patch.object(app_module.os, "name", "nt"), patch.object(
            app_module, "_set_native_window_position", return_value=True
        ) as native_position:
            app_module.DesktopToolApp._set_window_outer_position(fake, 200, -810)

        native_position.assert_called_once_with(0x1234, 200, -810)
        self.assertEqual(len(fake.geometry_calls), 1)
        geometry, kwargs = fake.geometry_calls[0]
        self.assertEqual(geometry, app_module.WindowGeometry(200, -810, 500, 840))
        self.assertEqual(kwargs, {
            "expected_outer_position": (200, -810),
            "write_geometry": False,
        })

    def test_negative_outer_position_failure_never_falls_back_to_tk_geometry(self) -> None:
        class FakeWindow:
            def __init__(self) -> None:
                self.geometry_calls = []
                self.expected_geometry = "token"

            def _current_window_geometry(self):
                return app_module.WindowGeometry(100, 100, 500, 840)

            def _geometry_for_outer_position(self, x, y, geometry):
                return app_module.WindowGeometry(x, y, geometry.width, geometry.height)

            def winfo_id(self):
                return 0x1234

            def _set_window_geometry(self, geometry, **kwargs):
                self.geometry_calls.append((geometry, kwargs))

            def _clear_expected_geometry(self):
                self.expected_geometry = None

        fake = FakeWindow()
        with patch.object(app_module.os, "name", "nt"), patch.object(
            app_module, "_set_native_window_position", return_value=False
        ) as native_position:
            result = app_module.DesktopToolApp._set_window_outer_position(fake, 200, -810)

        self.assertFalse(result)
        native_position.assert_called_once_with(0x1234, 200, -810)
        self.assertEqual(len(fake.geometry_calls), 1)
        self.assertEqual(fake.geometry_calls[0][1]["write_geometry"], False)
        self.assertIsNone(fake.expected_geometry)

    def test_outer_position_returns_success_for_positive_tk_fallback(self) -> None:
        class FakeWindow:
            def __init__(self) -> None:
                self.geometry_calls = []

            def _current_window_geometry(self):
                return app_module.WindowGeometry(100, 100, 500, 840)

            def _geometry_for_outer_position(self, x, y, geometry):
                return app_module.WindowGeometry(x, y, geometry.width, geometry.height)

            def _set_window_geometry(self, geometry, **kwargs):
                self.geometry_calls.append((geometry, kwargs))

        fake = FakeWindow()
        self.assertTrue(app_module.DesktopToolApp._set_window_outer_position(fake, 200, 300))
        self.assertEqual(len(fake.geometry_calls), 1)
        self.assertEqual(fake.geometry_calls[0][0], app_module.WindowGeometry(200, 300, 500, 840))

    def test_current_geometry_accepts_tk_native_negative_coordinate_token(self) -> None:
        fake_window = SimpleNamespace(geometry=lambda: "500x840+200+-810")
        self.assertEqual(
            app_module.DesktopToolApp._current_window_geometry(fake_window),
            app_module.WindowGeometry(200, -810, 500, 840),
        )

    def test_native_positioning_declares_reliable_set_window_pos_contract(self) -> None:
        class FakeSetWindowPos:
            def __init__(self):
                self.argtypes = None
                self.restype = None
                self.calls = []

            def __call__(self, *args):
                self.calls.append(args)
                return 1

        set_pos = FakeSetWindowPos()
        user32 = SimpleNamespace(SetWindowPos=set_pos)
        with patch.object(app_module.os, "name", "nt"), patch.object(
            app_module.ctypes, "windll", SimpleNamespace(user32=user32)
        ), patch.object(
            app_module, "_resolve_native_window_hwnd", return_value=0x5678
        ):
            self.assertTrue(app_module._set_native_window_position(0x1234, 200, -810))

        self.assertEqual(
            set_pos.argtypes,
            [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ],
        )
        self.assertIs(set_pos.restype, wintypes.BOOL)
        self.assertEqual(set_pos.calls[0][0].value, 0x5678)
        self.assertEqual(set_pos.calls[0][2:6], (200, -810, 0, 0))
        self.assertEqual(
            set_pos.calls[0][6],
            app_module.SWP_NOSIZE | app_module.SWP_NOZORDER | app_module.SWP_NOACTIVATE,
        )

    def test_collapse_target_preserves_outer_height_and_requests_collapsed_state(self) -> None:
        class FakeDock:
            _dock_state = "docked_expanded"
            _dock_pause_count = 0
            _dock_native_interaction = False
            _dock_resize_blocked = False
            _dock_work_area = app_module.WorkArea(0, 0, 1920, 1040)
            _dock_handle_height = 30

            def __init__(self):
                self.animation = None

            def _window_is_maximized(self):
                return False

            def _current_window_geometry(self):
                return app_module.WindowGeometry(100, 0, 500, 840)

            def _window_outer_height(self):
                return 840

            def _start_dock_animation(self, target_y, final_state):
                self.animation = (target_y, final_state)

        fake = FakeDock()
        app_module.DesktopToolApp._request_dock_collapse(fake)
        self.assertEqual(fake.animation, (-810, "collapsed"))

    def test_programmatic_geometry_is_acknowledged_before_native_detection(self) -> None:
        setter = _source(_function("_set_window_outer_position"))
        self.assertIn("expected_outer_position=(x, y)", setter)
        self.assertIn("write_geometry=False", setter)

        configure = _source(_function("_schedule_geometry_save"))
        self.assertIn("self._configure_matches_expected_geometry(", configure)
        self.assertIn("self._clear_expected_geometry()", configure)
        self.assertIn("if not expected_event:", configure)

        animation_cancel = _source(_function("_cancel_dock_animation"))
        self.assertIn("self._clear_expected_geometry()", animation_cancel)

    def test_native_quiet_timer_rearms_and_modal_binding_does_not_double_pause(self) -> None:
        begin = _source(_function("_begin_native_titlebar_interaction"))
        schedule = _source(_function("_arm_native_titlebar_quiet_timer"))
        self.assertIn("self._arm_native_titlebar_quiet_timer", begin)
        self.assertIn("self._cancel_dock_job(\"_dock_native_interaction_job\")", schedule)

        modal = _source(_function("_bind_dock_modal"))
        self.assertIn("self._dock_modal_windows.add(key)", modal)
        self.assertNotIn("self._dock_pause()", modal)
        present = _source(_function("_dock_modal_present"))
        self.assertIn("self._dock_modal_windows", present)

    def test_dock_autohide_polling_survives_enter_and_blocked_states(self) -> None:
        enter = _source(_function("_on_dock_enter"))
        self.assertIn('self._dock_state == "docked_expanded"', enter)
        self.assertIn("self._schedule_dock_autohide()", enter)
        self.assertNotIn('_cancel_dock_job("_dock_autohide_job")', enter)

        autohide = _source(_function("_autohide_if_pointer_left"))
        self.assertIn('if self._dock_modal_present():', autohide)
        self.assertIn('if self._is_pointer_inside_window():', autohide)
        self.assertGreaterEqual(autohide.count("self.after(250, self._autohide_if_pointer_left)"), 2)

        schedule = _source(_function("_schedule_dock_autohide"))
        self.assertIn("self._dock_resize_blocked", schedule)
        self.assertIn("delay = 250", schedule)

    def test_dock_autohide_clears_stale_resize_block_and_collapses(self) -> None:
        class FakeDock:
            _dock_state = "docked_expanded"
            _dock_native_interaction = False
            _dock_resize_blocked = True
            _native_window_style_applied = True

            def __init__(self) -> None:
                self.scheduled = []
                self.collapses = 0

            def _window_is_maximized(self) -> bool:
                return False

            def after(self, delay, callback):
                self.scheduled.append((delay, callback))
                return "retry-job"

            _autohide_if_pointer_left = app_module.DesktopToolApp._autohide_if_pointer_left

            def _request_dock_collapse(self) -> None:
                self.collapses += 1

            def _dock_modal_present(self) -> bool:
                return False

            def _is_pointer_inside_window(self) -> bool:
                return False

            _native_resize_capability_available = app_module.DesktopToolApp._native_resize_capability_available

        fake = FakeDock()
        app_module.DesktopToolApp._autohide_if_pointer_left(fake)
        self.assertFalse(fake._dock_resize_blocked)
        self.assertEqual(fake.collapses, 1)
        self.assertEqual(fake.scheduled, [])

    def test_dock_autohide_does_not_collapse_during_native_interaction(self) -> None:
        class FakeDock:
            _dock_state = "docked_expanded"
            _dock_native_interaction = True
            _dock_resize_blocked = True
            _native_resize_capability_available = app_module.DesktopToolApp._native_resize_capability_available

            def __init__(self) -> None:
                self.scheduled = []
                self.collapses = 0

            def _window_is_maximized(self) -> bool:
                return False

            def after(self, delay, callback):
                self.scheduled.append((delay, callback))
                return "retry-job"

            def _request_dock_collapse(self) -> None:
                self.collapses += 1

            _autohide_if_pointer_left = app_module.DesktopToolApp._autohide_if_pointer_left

        fake = FakeDock()
        app_module.DesktopToolApp._autohide_if_pointer_left(fake)
        self.assertEqual(fake.collapses, 0)
        self.assertEqual(fake.scheduled[0][0], 250)

    def test_destroyed_modal_restores_docked_autohide_polling(self) -> None:
        class FakeDialog:
            def __init__(self) -> None:
                self.callback = None

            def __str__(self) -> str:
                return "dialog"

            def bind(self, _sequence, callback, add=None):
                self.callback = callback

        class FakeDock:
            _dock_modal_windows = set()
            _dock_state = "docked_expanded"

            def __init__(self) -> None:
                self.scheduled = 0

            def _schedule_dock_autohide(self) -> None:
                self.scheduled += 1

        fake = FakeDock()
        dialog = FakeDialog()
        app_module.DesktopToolApp._bind_dock_modal(fake, dialog)
        self.assertIn("dialog", fake._dock_modal_windows)
        dialog.callback(SimpleNamespace(widget=dialog))
        self.assertNotIn("dialog", fake._dock_modal_windows)
        self.assertEqual(fake.scheduled, 1)

    def test_pointer_inside_prefers_tk_client_rect_with_outer_fallback(self) -> None:
        pointer = _source(_function("_is_pointer_inside_window"))
        for api in ("winfo_rootx", "winfo_rooty", "winfo_width", "winfo_height"):
            self.assertIn(f"self.{api}()", pointer)
        self.assertIn("self._window_outer_rect()", pointer)
        self.assertIn("client_width > 0 and client_height > 0", pointer)

    def test_pointer_inside_uses_native_client_rect_before_tk_fallback(self) -> None:
        class FakeWin32Call:
            def __init__(self, callback) -> None:
                self.callback = callback
                self.argtypes = None
                self.restype = None

            def __call__(self, *args):
                return self.callback(*args)

        cursor = {"x": 40, "y": 20}

        def get_client_rect(_hwnd, rect_pointer):
            rect = rect_pointer._obj
            rect.left, rect.top, rect.right, rect.bottom = 0, 0, 300, 200
            return 1

        def client_to_screen(_hwnd, point_pointer):
            point = point_pointer._obj
            point.x, point.y = 10, 30
            return 1

        def get_cursor_pos(point_pointer):
            point = point_pointer._obj
            point.x, point.y = cursor["x"], cursor["y"]
            return 1

        user32 = SimpleNamespace(
            GetClientRect=FakeWin32Call(get_client_rect),
            ClientToScreen=FakeWin32Call(client_to_screen),
            GetCursorPos=FakeWin32Call(get_cursor_pos),
        )
        fake_window = SimpleNamespace(
            winfo_id=lambda: 0x1234,
            winfo_pointerx=lambda: (_ for _ in ()).throw(AssertionError("Tk fallback used")),
            winfo_pointery=lambda: (_ for _ in ()).throw(AssertionError("Tk fallback used")),
        )

        with patch.object(app_module.os, "name", "nt"), patch.object(
            app_module.ctypes, "windll", SimpleNamespace(user32=user32)
        ):
            # The cursor is in the native caption (above the client origin).
            self.assertFalse(app_module.DesktopToolApp._is_pointer_inside_window(fake_window))
            cursor.update(x=40, y=80)
            self.assertTrue(app_module.DesktopToolApp._is_pointer_inside_window(fake_window))

        for call in (user32.GetClientRect, user32.ClientToScreen, user32.GetCursorPos):
            self.assertIs(call.restype, wintypes.BOOL)
            self.assertIsNotNone(call.argtypes)

    def test_dock_handle_registration_reaches_real_target_registration(self) -> None:
        handle = _source(_function("_register_dock_handle_dnd"))
        target = _source(_function("_register_dnd_target"))
        self.assertIn("self._register_dnd_target(self._dock_handle)", handle)
        self.assertIn("self._register_dnd_recursive(child, _generation_started=True)", handle)
        self.assertIn("drop_target_register(DND_FILES, DND_TEXT)", target)
        self.assertIn('dnd_bind("<<Drop>>", self._on_global_drop)', target)
        self.assertIn('dnd_bind("<<DragEnter>>", self._on_global_drag_enter)', target)
        self.assertIn('dnd_bind("<<DragLeave>>", self._on_global_drag_leave)', target)

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

    def test_display_adjustments_contract(self) -> None:
        """Verify the specific display text/adjustments required by the user."""
        self.assertIn("就绪，拖动至桌面上边缘可隐藏", APP_SOURCE)
        statusbar = _source(_function("_build_statusbar"))
        dock_icon = _source(_function("_draw_dock_handle_icon"))
        self.assertIn("tk.Canvas(", statusbar)
        self.assertIn("highlightthickness=0", statusbar)
        self.assertIn("self._draw_dock_handle_icon", statusbar)
        self.assertEqual(dock_icon.count("create_line"), 3)
        self.assertIn('self._t("secondary")', dock_icon)
        self.assertIn("width=1", dock_icon)
        self.assertEqual(dock_icon.count('capstyle="round"'), 3)
        self.assertEqual(dock_icon.count('tags="dock_handle_icon"'), 3)
        self.assertEqual(dock_icon.count("center_y"), 9)
        self.assertIn("icon_center_y = center_y + 2", dock_icon)
        self.assertIn("icon_center_y - 3", dock_icon)
        self.assertIn("icon_center_y + 3", dock_icon)
        self.assertNotIn('text="⌄"', APP_SOURCE)
        self.assertNotIn("⌄", APP_SOURCE)
        self.assertNotIn('font=(FONT, 11, "bold")', statusbar)
        self.assertNotIn("═══中转站═══", APP_SOURCE)
        self.assertIn("pin_text", THEME_SOURCE)
        add_button = _source(_function("_refresh_cards"))
        self.assertIn('text_color=self._t("add_button_text")', add_button)

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
