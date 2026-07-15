"""GUI-independent theme definitions and startup theme resolution."""

from __future__ import annotations

from copy import deepcopy
from typing import Final, Literal


ThemeMode = Literal["light", "dark", "system"]
EffectiveTheme = Literal["light", "dark"]

# The application historically starts with a dark palette.  Keeping the
# system fallback fixed makes startup deterministic and avoids importing any
# platform or GUI toolkit just to inspect an OS preference.
SYSTEM_EFFECTIVE_THEME: Final[EffectiveTheme] = "dark"


_LIGHT_ACTION_ICON_BY_KIND: Final[dict[str, str]] = {
    "folder-copy": "#60a5fa",
    "launch-bat": "#fbbf24",
    "update-svn": "#4ade80",
    "commit-svn": "#f43f5e",
    "open-web": "#a855f7",
    "app-launch": "#38bdf8",
}

_DARK_ACTION_ICON_BY_KIND: Final[dict[str, str]] = {
    "folder-copy": "#60a5fa",
    "launch-bat": "#fbbf24",
    "update-svn": "#4ade80",
    "commit-svn": "#f43f5e",
    "open-web": "#a855f7",
    "app-launch": "#38bdf8",
}


LIGHT_THEME_TOKENS: Final[dict[str, object]] = {
    "window": "#f5f7fb",
    "background": "#f5f7fb",
    "surface": "#ffffff",
    "elevated": "#ffffff",
    "card": "#ffffff",
    "text": "#182033",
    "secondary": "#4d5870",
    "muted": "#778198",
    "border": "#d5dbe7",
    "hover": "#e9edf5",
    "pressed": "#dfe4ef",
    "focus": "#6558d3",
    "primary": "#6558d3",
    "danger": "#cf3f4e",
    "success": "#21864b",
    "warning": "#a56b00",
    "disabled_foreground": "#a2a9b8",
    "disabled_background": "#e6e9f0",
    "entry": "#ffffff",
    "textbox": "#ffffff",
    "canvas": "#f5f7fb",
    "scrollbar": "#c3cada",
    "progress": "#6558d3",
    "toast": "#182033",
    "action_icon": "#6558d3",
    "action_icon_by_kind": _LIGHT_ACTION_ICON_BY_KIND,
}

DARK_THEME_TOKENS: Final[dict[str, object]] = {
    "window": "#1a1b2e",
    "background": "#1a1b2e",
    "surface": "#232438",
    "elevated": "#2a2b42",
    "card": "#262840",
    "text": "#f0f1f8",
    "secondary": "#b8bbd8",
    "muted": "#8a8db0",
    "border": "#353755",
    "hover": "#313349",
    "pressed": "#3b3d57",
    "focus": "#8b7ff5",
    "primary": "#7c6ef0",
    "danger": "#e85a5a",
    "success": "#4ade80",
    "warning": "#fbbf24",
    "disabled_foreground": "#666a87",
    "disabled_background": "#303248",
    "entry": "#232438",
    "textbox": "#232438",
    "canvas": "#1a1b2e",
    "scrollbar": "#4b4e6c",
    "progress": "#7c6ef0",
    "toast": "#2a2b42",
    "action_icon": "#7c6ef0",
    "action_icon_by_kind": _DARK_ACTION_ICON_BY_KIND,
}

THEME_TOKENS: Final[dict[EffectiveTheme, dict[str, object]]] = {
    "light": LIGHT_THEME_TOKENS,
    "dark": DARK_THEME_TOKENS,
}


# Compatibility mapping for callers that use the historic module-level name.
# The resolver contract above deliberately has no legacy copy/bat/svn aliases.
action_icon_by_kind: Final[dict[str, str]] = {
    "folder-copy": "#60a5fa",
    "launch-bat": "#fbbf24",
    "update-svn": "#4ade80",
    "commit-svn": "#f43f5e",
    "open-web": "#a855f7",
    "app-launch": "#38bdf8",
}

ACTION_ICON_BY_KIND = action_icon_by_kind


# Glyphs are presentation data and must not be used as theme color tokens.
ACTION_ICON_GLYPHS: Final[dict[str, str]] = {
    "folder-copy": "📋",
    "launch-bat": "⚡",
    "update-svn": "🔄",
    "commit-svn": "📤",
    "open-web": "🌐",
    "app-launch": "🚀",
    "copy": "📋",
    "bat": "⚡",
    "svn": "🔄",
}

ACTION_ICONS = ACTION_ICON_GLYPHS


def parse_theme_mode(value: object, *, fallback: ThemeMode = "system") -> ThemeMode:
    """Parse a persisted startup mode, using ``fallback`` when invalid."""

    if fallback not in ("light", "dark", "system"):
        raise ValueError("fallback must be light, dark, or system")
    if type(value) is str and value.lower() in ("light", "dark", "system"):
        return value.lower()  # type: ignore[return-value]
    return fallback


def parse_theme_mode_strict(value: object) -> ThemeMode:
    """Parse a theme mode and raise for invalid persisted values."""

    if type(value) is not str or value.lower() not in ("light", "dark", "system"):
        raise ValueError("theme mode must be light, dark, or system")
    return value.lower()  # type: ignore[return-value]


def _effective_theme(value: object) -> EffectiveTheme:
    if type(value) is bool:
        return "dark" if value else "light"
    if type(value) is str and value.lower() in ("light", "dark"):
        return value.lower()  # type: ignore[return-value]
    raise ValueError("effective system theme must be light or dark")


def resolve_theme_mode(
    mode: object = "system",
    system_effective: object = SYSTEM_EFFECTIVE_THEME,
    *,
    system_theme: object | None = None,
) -> EffectiveTheme:
    """Resolve ``light``/``dark``/``system`` to an effective palette.

    ``system`` does not inspect tkinter, customtkinter, the registry, or any
    other process-global setting.  Callers may provide a fixed effective
    system value explicitly; otherwise the deterministic dark fallback is
    used.  ``system_theme`` is a readable keyword alias for that value.
    """

    parsed = parse_theme_mode(mode)
    if parsed in ("light", "dark"):
        return parsed
    selected = system_effective if system_theme is None else system_theme
    return _effective_theme(selected)


resolve_theme = resolve_theme_mode
effective_theme = resolve_theme_mode


def theme_tokens(
    mode: object = "system",
    system_effective: object = SYSTEM_EFFECTIVE_THEME,
    *,
    system_theme: object | None = None,
) -> dict[str, object]:
    """Return a deep defensive copy of the complete effective token schema."""

    effective = resolve_theme_mode(mode, system_effective, system_theme=system_theme)
    return deepcopy(THEME_TOKENS[effective])


get_theme_tokens = theme_tokens


__all__ = [
    "ThemeMode",
    "EffectiveTheme",
    "SYSTEM_EFFECTIVE_THEME",
    "LIGHT_THEME_TOKENS",
    "DARK_THEME_TOKENS",
    "THEME_TOKENS",
    "ACTION_ICON_BY_KIND",
    "ACTION_ICON_GLYPHS",
    "ACTION_ICONS",
    "parse_theme_mode",
    "parse_theme_mode_strict",
    "resolve_theme_mode",
    "resolve_theme",
    "effective_theme",
    "theme_tokens",
    "get_theme_tokens",
    "action_icon_by_kind",
]
