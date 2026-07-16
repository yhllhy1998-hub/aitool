from __future__ import annotations

import sys
import unittest
import os
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aitool_desktop.theme import (  # noqa: E402
    ACTION_ICON_BY_KIND,
    ACTION_ICON_GLYPHS,
    DARK_THEME_TOKENS,
    LIGHT_THEME_TOKENS,
    THEME_TOKENS,
    SYSTEM_EFFECTIVE_THEME,
    action_icon_by_kind,
    get_theme_tokens,
    parse_theme_mode,
    resolve_theme,
    toggle_theme_mode,
)
from aitool_desktop.app import _startup_theme_mode  # noqa: E402


class ThemeTests(unittest.TestCase):
    EXPECTED_TOKEN_KEYS = {
        "window",
        "background",
        "surface",
        "elevated",
        "card",
        "text",
        "secondary",
        "muted",
        "border",
        "hover",
        "pressed",
        "focus",
        "primary",
        "danger",
        "success",
        "warning",
        "disabled_foreground",
        "disabled_background",
        "entry",
        "textbox",
        "canvas",
        "scrollbar",
        "progress",
        "toast",
        "action_icon",
        "add_button",
        "add_button_hover",
        "add_button_text",
        "pin_text",
    }
    EXPECTED_ACTION_KINDS = {
        "folder-copy",
        "launch-bat",
        "update-svn",
        "commit-svn",
        "open-web",
        "app-launch",
    }

    def test_three_startup_modes_resolve_to_effective_theme(self) -> None:
        self.assertEqual(resolve_theme("light"), "light")
        self.assertEqual(resolve_theme("dark"), "dark")
        self.assertEqual(resolve_theme("system"), SYSTEM_EFFECTIVE_THEME)
        self.assertEqual(resolve_theme("system", "light"), "light")
        self.assertEqual(resolve_theme("system", system_theme="dark"), "dark")
        self.assertEqual(parse_theme_mode("LIGHT"), "light")
        self.assertEqual(parse_theme_mode("not-a-theme"), "system")

    def test_app_startup_defaults_to_dark_without_environment_override(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_startup_theme_mode(), "dark")

    def test_app_startup_environment_override_accepts_all_supported_modes(self) -> None:
        for mode in ("light", "dark", "system"):
            with self.subTest(mode=mode):
                self.assertEqual(_startup_theme_mode({"AITOOL_THEME": mode}), mode)

    def test_token_dicts_are_complete_and_defensive(self) -> None:
        expected = self.EXPECTED_TOKEN_KEYS
        expected_schema = expected | {"action_icon_by_kind"}
        self.assertEqual(set(LIGHT_THEME_TOKENS), expected_schema)
        self.assertEqual(set(DARK_THEME_TOKENS), expected_schema)
        self.assertIsNot(LIGHT_THEME_TOKENS["action_icon_by_kind"], DARK_THEME_TOKENS["action_icon_by_kind"])
        self.assertEqual(set(THEME_TOKENS), {"light", "dark"})
        for mode in ("light", "dark", "system"):
            tokens = get_theme_tokens(mode)
            self.assertEqual(set(tokens), expected_schema)
            self.assertTrue(
                all(
                    isinstance(value, str) and value
                    for key, value in tokens.items()
                    if key != "action_icon_by_kind"
                )
            )
            action_mapping = tokens["action_icon_by_kind"]
            self.assertIsInstance(action_mapping, dict)
            self.assertEqual(set(action_mapping), self.EXPECTED_ACTION_KINDS)
            self.assertTrue(all(isinstance(value, str) and value for value in action_mapping.values()))
        copied = get_theme_tokens("dark")
        copied["background"] = "changed"
        copied["action_icon_by_kind"]["folder-copy"] = "changed"
        self.assertNotEqual(DARK_THEME_TOKENS["background"], copied["background"])
        self.assertNotEqual(
            DARK_THEME_TOKENS["action_icon_by_kind"]["folder-copy"],
            copied["action_icon_by_kind"]["folder-copy"],
        )

    def test_action_type_mapping(self) -> None:
        expected_colors = {
            "folder-copy": "#60a5fa",
            "launch-bat": "#fbbf24",
            "update-svn": "#4ade80",
            "commit-svn": "#f43f5e",
            "open-web": "#a855f7",
            "app-launch": "#38bdf8",
        }
        for kind, color in expected_colors.items():
            self.assertEqual(action_icon_by_kind[kind], color)
            self.assertEqual(ACTION_ICON_BY_KIND[kind], color)
            self.assertTrue(color.startswith("#"))

        self.assertEqual(ACTION_ICON_GLYPHS["folder-copy"], "📋")
        self.assertNotEqual(ACTION_ICON_GLYPHS["folder-copy"], action_icon_by_kind["folder-copy"])
        self.assertEqual(set(action_icon_by_kind), self.EXPECTED_ACTION_KINDS)
        self.assertIn("copy", ACTION_ICON_GLYPHS)

    def test_system_light_dark_and_invalid_effective_theme(self) -> None:
        self.assertEqual(resolve_theme("system", system_theme="light"), "light")
        self.assertEqual(resolve_theme("system", system_theme="dark"), "dark")
        self.assertEqual(toggle_theme_mode("light"), "dark")
        self.assertEqual(toggle_theme_mode("dark"), "light")
        self.assertEqual(toggle_theme_mode("system", system_theme="light"), "dark")
        with self.assertRaises(ValueError):
            resolve_theme("system", system_theme="not-a-theme")

    def test_named_host_refresh_is_a_pure_logic_phase_1_5a_sentinel(self) -> None:
        """This sentinel models ownership only; it does not claim Tk hierarchy coverage."""

        surface = _FakeSurface()
        statusbar_before = list(surface.statusbar)
        other_before = list(surface.hosts["other"].items)

        surface.refresh_named_host("actions", ["actions:new-1", "actions:new-2"])

        self.assertEqual(surface.hosts["actions"].items, ["actions:new-1", "actions:new-2"])
        self.assertEqual(surface.statusbar, statusbar_before)
        self.assertEqual(surface.hosts["other"].items, other_before)


class _FakeHost:
    """Test-only host with an owned item collection and refresh operation."""

    def __init__(self, name: str, items: list[str]) -> None:
        self.name = name
        self.items = list(items)

    def clear_and_rebuild(self, items: list[str]) -> None:
        self.items.clear()
        self.items.extend(items)


class _FakeSurface:
    """Pure-logic refresh sentinel, intentionally not a real Tk widget tree."""

    def __init__(self) -> None:
        self.statusbar = ["statusbar:keep"]
        self.hosts = {
            "actions": _FakeHost("actions", ["actions:old"]),
            "other": _FakeHost("other", ["other:keep"]),
        }

    def refresh_named_host(self, name: str, items: list[str]) -> None:
        self.hosts[name].clear_and_rebuild(items)


if __name__ == "__main__":
    unittest.main()
