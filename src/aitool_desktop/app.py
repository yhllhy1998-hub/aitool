from __future__ import annotations

import os
import sys
import threading
import weakref
from pathlib import Path
from tkinter import filedialog, messagebox
import ctypes
from ctypes import wintypes

from PIL import Image, ImageTk
import customtkinter as ctk
from tkinterdnd2 import DND_FILES, DND_TEXT, TkinterDnD

from .input_parsing import parse_input
from .models import ActionReview, CustomModule, MODULE_TYPES, StationEntry
from .operations import (
    build_folder_copy_dry_run,
    collect_station_entries,
    copy_station_entry_to_directory,
    execute_folder_copy,
    execute_svn_update,
    execute_svn_commit,
    execute_open_web,
    execute_app_launch,
    launch_bat_script,
    validate_bat_launch_path,
    validate_svn_document_update_path,
)
from .storage import ModuleStorage, StationStorage
from .station_ordering import normalize_path_key, remove_station_entry
from .theme import (
    ACTION_ICON_GLYPHS,
    parse_theme_mode,
    resolve_theme_mode,
    theme_tokens,
    toggle_theme_mode,
)
from .window_geometry import (
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    WorkArea,
    load_and_place_window_geometry,
    select_work_area,
    save_window_geometry,
    WindowGeometry,
)

import logging

logger = logging.getLogger(__name__)


GWL_STYLE = -16
WS_THICKFRAME = 0x00040000
WS_SIZEBOX = 0x00040000
WS_MAXIMIZEBOX = 0x00010000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
GA_ROOT = 2

# LONG_PTR is a signed pointer-sized value.  Do not use ctypes' default
# ``c_int`` for Get/SetWindowLongPtrW: that truncates the value on 64-bit
# Windows and can make a successful-looking style update a no-op.
_LONG_PTR = ctypes.c_int64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_int32
_NATIVE_STYLE_MASK = WS_THICKFRAME | WS_SIZEBOX | WS_MAXIMIZEBOX


def _resolve_native_window_hwnd(tk_hwnd: int) -> int:
    """Resolve Tk's client HWND to the visible top-level HWND on Windows.

    On Windows, ``winfo_id()`` for a Tk/CustomTkinter root is not necessarily
    the HWND which owns the native caption.  CustomTkinter itself resolves
    this relationship with ``GetParent(self.winfo_id())`` before calling DWM.
    Applying ``GWL_STYLE`` to the Tk client HWND consequently leaves the
    visible top-level frame unchanged.  ``GetAncestor(GA_ROOT)`` is the more
    explicit form and also handles a Tk build with an intermediate parent;
    the GetParent fallback keeps this compatible with older Windows/Tk builds.
    """

    candidate = int(tk_hwnd or 0)
    if os.name != "nt" or not candidate:
        return candidate

    try:
        user32 = ctypes.windll.user32

        get_ancestor = getattr(user32, "GetAncestor", None)
        if get_ancestor is not None:
            get_ancestor.argtypes = [wintypes.HWND, wintypes.UINT]
            get_ancestor.restype = wintypes.HWND
            root_hwnd = get_ancestor(wintypes.HWND(candidate), GA_ROOT)
            root_hwnd = int(getattr(root_hwnd, "value", root_hwnd) or 0)
            if root_hwnd:
                logger.debug(
                    "resolved Tk HWND %#x to visible root HWND %#x via GetAncestor",
                    candidate,
                    root_hwnd,
                )
                return root_hwnd

        get_parent = getattr(user32, "GetParent", None)
        if get_parent is not None:
            get_parent.argtypes = [wintypes.HWND]
            get_parent.restype = wintypes.HWND
            parent_hwnd = get_parent(wintypes.HWND(candidate))
            parent_hwnd = int(getattr(parent_hwnd, "value", parent_hwnd) or 0)
            if parent_hwnd:
                logger.debug(
                    "resolved Tk HWND %#x to visible parent HWND %#x via GetParent",
                    candidate,
                    parent_hwnd,
                )
                return parent_hwnd
    except Exception as exc:
        logger.debug(
            "native root HWND resolution failed for Tk HWND %#x: %s",
            candidate,
            exc,
        )

    # If the relationship cannot be queried, retain the original handle so
    # the verified API path can still be used by non-Windows/headless tests.
    logger.debug("using Tk HWND %#x as native style target", candidate)
    return candidate


def _set_native_window_position(hwnd: int, x: int, y: int) -> bool:
    """Move a visible top-level HWND to an absolute screen position.

    Tk interprets a negative geometry coordinate as an offset from the right
    or bottom of the screen.  The drawer's collapsed position is instead a
    negative *absolute* screen coordinate, so that case must bypass Tk's
    geometry parser.  Keep this helper position-only: in particular, do not
    change the native frame styles or the window size while docking.
    """

    if os.name != "nt" or not hwnd:
        return False

    try:
        user32 = ctypes.windll.user32
        set_window_pos = user32.SetWindowPos
        set_window_pos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        set_window_pos.restype = wintypes.BOOL

        native_hwnd_value = _resolve_native_window_hwnd(int(hwnd))
        if not native_hwnd_value:
            logger.warning("no visible native HWND resolved for position update")
            return False

        result = set_window_pos(
            wintypes.HWND(native_hwnd_value),
            wintypes.HWND(0),
            int(x),
            int(y),
            0,
            0,
            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
        )
        succeeded = bool(result)
        if not succeeded:
            logger.warning(
                "SetWindowPos failed for visible HWND %#x at (%d, %d)",
                native_hwnd_value,
                x,
                y,
            )
        return succeeded
    except Exception as exc:
        logger.debug("native window position update skipped: %s", exc)
        return False


def _disable_native_resize_and_maximize(hwnd: int) -> bool:
    """Keep the native title bar while removing Win32 resize/Snap affordances.

    This is deliberately a verified operation.  ``SetWindowLongPtrW`` can
    return a value that only describes the previous style, while
    ``SetWindowPos`` only refreshes the non-client frame.  Both calls and a
    second ``GetWindowLongPtrW`` are therefore required before returning true.
    """

    if os.name != "nt" or not hwnd:
        return False

    try:
        user32 = ctypes.windll.user32
        get_window_long_ptr = user32.GetWindowLongPtrW
        set_window_long_ptr = user32.SetWindowLongPtrW
        set_window_pos = user32.SetWindowPos

        get_window_long_ptr.argtypes = [wintypes.HWND, ctypes.c_int]
        get_window_long_ptr.restype = _LONG_PTR
        set_window_long_ptr.argtypes = [wintypes.HWND, ctypes.c_int, _LONG_PTR]
        set_window_long_ptr.restype = _LONG_PTR
        set_window_pos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        set_window_pos.restype = wintypes.BOOL

        tk_hwnd = int(hwnd)
        native_hwnd_value = _resolve_native_window_hwnd(tk_hwnd)
        if not native_hwnd_value:
            logger.warning("no visible native HWND resolved from Tk HWND %#x", tk_hwnd)
            return False

        # Convert the visible top-level handle through the declared HWND type
        # explicitly so this remains correct for a 64-bit frozen process as
        # well as for a 32-bit Python process.
        native_hwnd = wintypes.HWND(native_hwnd_value)
        style_mask = WS_THICKFRAME | WS_SIZEBOX | WS_MAXIMIZEBOX

        def _as_long_ptr_value(value) -> int:
            return int(getattr(value, "value", value))

        style_before = _as_long_ptr_value(get_window_long_ptr(native_hwnd, GWL_STYLE))
        if not style_before:
            logger.warning(
                "GetWindowLongPtrW returned no style for visible HWND %#x (Tk HWND %#x)",
                native_hwnd_value,
                tk_hwnd,
            )
            return False

        desired_style = (style_before & ~style_mask) | (
            WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX
        )
        previous_style = _as_long_ptr_value(
            set_window_long_ptr(native_hwnd, GWL_STYLE, _LONG_PTR(desired_style))
        )
        # For a real Tk top-level, the old style is non-zero.  A zero return
        # therefore indicates that SetWindowLongPtrW did not update this HWND;
        # do not report success based only on SetWindowPos in that case.
        if not previous_style:
            logger.warning(
                "SetWindowLongPtrW failed for visible HWND %#x (Tk HWND %#x)",
                native_hwnd_value,
                tk_hwnd,
            )
            return False

        style_after_set = _as_long_ptr_value(get_window_long_ptr(native_hwnd, GWL_STYLE))
        if style_after_set & style_mask:
            logger.warning(
                "native style still has resize/maximize bits after SetWindowLongPtrW: %#x",
                style_after_set,
            )
            return False

        frame_changed = bool(
            set_window_pos(
                native_hwnd,
                wintypes.HWND(0),
                0,
                0,
                0,
                0,
                SWP_NOMOVE
                | SWP_NOSIZE
                | SWP_NOZORDER
                | SWP_NOACTIVATE
                | SWP_FRAMECHANGED,
            )
        )
        if not frame_changed:
            logger.warning(
                "SetWindowPos(SWP_FRAMECHANGED) failed for visible HWND %#x (Tk HWND %#x)",
                native_hwnd_value,
                tk_hwnd,
            )
            return False

        # Tk can adjust the frame while the toplevel is first mapped.  Read it
        # again after FRAMECHANGED so callers never mistake an API call for a
        # verified style change.
        style_after_frame_change = _as_long_ptr_value(
            get_window_long_ptr(native_hwnd, GWL_STYLE)
        )
        if style_after_frame_change & style_mask:
            logger.warning(
                "native style verification failed for HWND %#x: %#x",
                native_hwnd_value,
                style_after_frame_change,
            )
            return False
        logger.debug(
            "native resize/maximize style disabled for HWND %#x: %#x -> %#x",
            native_hwnd_value,
            style_before,
            style_after_frame_change,
        )
        return True
    except Exception as exc:
        # Tk/headless test environments and restricted Windows sessions may
        # not expose a usable HWND.  The normal Tk title bar remains usable.
        logger.debug("native window style update skipped: %s", exc)
        return False


_DND_DIAGNOSTICS = {
    "generation": 0,
    "targets": {"attempted": 0, "succeeded": 0, "failed": 0},
    "sources": {"attempted": 0, "succeeded": 0, "failed": 0},
    "failures": [],
}


def reset_dnd_diagnostics() -> None:
    """Reset observable drag-and-drop registration counters."""

    _DND_DIAGNOSTICS["generation"] = 0
    for kind in ("targets", "sources"):
        _DND_DIAGNOSTICS[kind].update(attempted=0, succeeded=0, failed=0)
    _DND_DIAGNOSTICS["failures"].clear()


def get_dnd_diagnostics() -> dict:
    """Return a detached snapshot of drag-and-drop registration health."""

    return {
        "generation": _DND_DIAGNOSTICS["generation"],
        "targets": dict(_DND_DIAGNOSTICS["targets"]),
        "sources": dict(_DND_DIAGNOSTICS["sources"]),
        "failures": [dict(item) for item in _DND_DIAGNOSTICS["failures"]],
    }


def _dnd_widget_id(widget) -> str:
    try:
        return str(widget)
    except Exception:
        return f"{type(widget).__name__}@{id(widget):x}"


def _record_dnd_registration(kind: str, widget, success: bool, error: Exception | None = None) -> None:
    counters = _DND_DIAGNOSTICS["targets" if kind == "target" else "sources"]
    counters["attempted"] += 1
    if success:
        counters["succeeded"] += 1
        return

    counters["failed"] += 1
    failure = {
        "widget_id": _dnd_widget_id(widget),
        "kind": kind,
        "error_type": type(error).__name__ if error is not None else "RegistrationError",
        "error_message": str(error) if error is not None else "registration failed",
    }
    _DND_DIAGNOSTICS["failures"].append(failure)
    logger.warning("DND %s registration failed for %s: %s", kind, failure["widget_id"], failure["error_message"])


def _detect_system_effective_theme() -> str:
    """Read the Windows preference without making startup depend on it."""

    if os.name != "nt":
        return "dark"
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            for value_name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                try:
                    value, _ = winreg.QueryValueEx(key, value_name)
                    return "light" if int(value) else "dark"
                except (FileNotFoundError, OSError, TypeError, ValueError):
                    continue
    except Exception:
        pass

    # Registry access can be blocked by a locked-down profile.  A ctypes
    # fallback keeps the decision explicit; a failed probe is dark, never a
    # partially initialized palette.
    try:
        user32 = ctypes.windll.user32
        get_sys_color = getattr(user32, "GetSysColor", None)
        if get_sys_color is not None:
            # COLOR_WINDOWTEXT is a useful low-level signal when the registry
            # is unavailable: a very bright foreground normally means dark UI.
            rgb = int(get_sys_color(8))
            red, green, blue = rgb & 0xFF, (rgb >> 8) & 0xFF, (rgb >> 16) & 0xFF
            return "dark" if (red + green + blue) > 420 else "light"
    except Exception:
        pass
    return "dark"


def _startup_theme_mode(environ=None):
    """Choose the startup mode, keeping explicit environment overrides intact."""

    environment = os.environ if environ is None else environ
    return parse_theme_mode(environment.get("AITOOL_THEME", "dark"), fallback="dark")


def _get_windows_work_areas(host) -> tuple[list[WorkArea], int]:
    """Return monitor work areas, preferring the Win32 monitor API."""

    areas: list[WorkArea] = []
    primary_index = 0
    if os.name == "nt":
        try:
            class _Rect(ctypes.Structure):
                _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                            ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

            class _MonitorInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _Rect),
                            ("rcWork", _Rect), ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            callback_type = ctypes.WINFUNCTYPE(
                ctypes.c_int, wintypes.HANDLE, wintypes.HDC,
                ctypes.POINTER(_Rect), wintypes.LPARAM,
            )

            def _collect(monitor, _hdc, _rect, _data):
                nonlocal primary_index
                info = _MonitorInfo()
                info.cbSize = ctypes.sizeof(_MonitorInfo)
                if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    work = info.rcWork
                    areas.append(WorkArea(int(work.left), int(work.top), int(work.right), int(work.bottom)))
                    if info.dwFlags & 1:
                        primary_index = len(areas) - 1
                return 1

            callback = callback_type(_collect)
            if user32.EnumDisplayMonitors(None, None, callback, 0) and areas:
                return areas, primary_index
        except Exception as exc:
            logger.debug("Windows work-area enumeration unavailable: %s", exc)

    try:
        width = max(1, int(host.winfo_screenwidth()))
        height = max(1, int(host.winfo_screenheight()))
    except Exception:
        width, height = 1024, 768
    return [WorkArea.from_xywh(0, 0, width, height)], 0


if getattr(sys, "frozen", False):
    # 打包运行：为了保证用户添加的卡片和暂存文件在重启、重打包或覆盖后绝不丢失，
    # 存储路径应当设在用户本地的应用持久化目录 (APPDATA)，而不是只读的临时释放目录 sys._MEIPASS 内！
    REPO_ROOT = Path(sys._MEIPASS)
    DATA_DIR = Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "AiTool"
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    DATA_DIR = REPO_ROOT / "data"

STATE_PATH = DATA_DIR / "document_station_entries.json"
MODULE_STATE_PATH = DATA_DIR / "custom_modules.json"
QUICK_ACTIONS_PATH = DATA_DIR / "quick_actions.json"
WINDOW_GEOMETRY_PATH = DATA_DIR / "window_geometry.json"
DEFAULT_EXPORT_BAT = Path(r"F:\F_tunk\工具_指定配置文件导出.bat")
DEFAULT_SVN_ROOT = Path(r"F:\F_tunk")

MODULE_TYPE_LABELS = {
    "folder-copy": "文件夹覆盖复制",
    "launch-bat": "启动脚本",
    "update-svn": "SVN 更新",
    "commit-svn": "SVN 提交",
    "open-web": "打开网页",
    "app-launch": "打开应用",
}

FONT = "Microsoft YaHei UI"
FONT_MONO = "Consolas"

# 完美调优的间距系统 (4px 栅格)
SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 20,
    "card_padx": 12,
    "card_pady": 10,
    "icon_col": 52,
}

FS = {
    "section_title": 12,
    "card_title": 11,
    "card_desc": 9,
    "station_name": 11,
    "status": 11,
    "toast": 12,
    "dialog": 12,
}

QUICK_ACTION_DEFS = [
    {
        "id": "quick-copy",
        "type": "copy",
        "module_type": "folder-copy",
        "title": "文件夹覆盖复制",
        "desc": "全量覆盖目标目录",
        "param_fields": [
            {"key": "source", "label": "来源目录", "browse": "folder"},
            {"key": "target", "label": "目标目录", "browse": "folder"},
        ],
        "params": {},
    },
    {
        "id": "quick-bat",
        "type": "bat",
        "module_type": "launch-bat",
        "title": "启动脚本",
        "desc": "运行 .bat / .cmd 脚本",
        "param_fields": [
            {"key": "script", "label": "脚本路径", "browse": "file"},
        ],
        "params": {"script": str(DEFAULT_EXPORT_BAT)},
    },
    {
        "id": "quick-svn",
        "type": "svn",
        "module_type": "update-svn",
        "title": "SVN 更新",
        "desc": "svn update 工作副本",
        "param_fields": [
            {"key": "workspace", "label": "svn 工作目录", "browse": "folder"},
        ],
        "params": {"workspace": str(DEFAULT_SVN_ROOT)},
    },
]


def _load_json(path: Path, fallback):
    if not path.exists():
        # 极重要：如果是第一次打包或部署，将当前拥有的高品质双路径覆盖和 Jenkins 动作作为系统最高优先级的出厂默认配置！
        # 从而保证其他人双击打开 exe 就能立刻看到开箱即用的“双通道资源覆盖”和“Jenkins”两个漂亮的默认模块
        if "custom_modules" in str(path):
            return {
              "updated_at": "2026-07-10T16:55:00+08:00",
              "modules": [
                {
                  "module_id": "589d70dab9da",
                  "name": "Jenkins",
                  "module_type": "open-web",
                  "params": {
                    "url": "http://192.168.1.192:8080/view/%E4%BF%A1%E9%95%BF_trunk/job/All-%E4%BF%A1%E9%95%BF-04.%E5%90%8C%E6%AD%A5%E9%85%8D%E7%BD%AE%E5%88%B0Unity%E5%B7%A5%E7%A8%8B_trunk/"
                  }
                },
                {
                  "module_id": "multi-folder-copy-001",
                  "name": "双通道资源覆盖",
                  "module_type": "folder-copy",
                  "params": {
                    "source": "F:/F_tunk/resource/script/autocode",
                    "target": "F:/cehua/test",
                    "source2": "F:/F_tunk/ExcelRoot/Out/LuaFile",
                    "target2": "D:/JP_project/Project_P1/LuaCode/DB/Data"
                  }
                }
              ]
            }
        return fallback
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _save_json(path: Path, data) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_params(text: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        params[key.strip()] = value.strip()
    return params


def _review_to_dict(review: ActionReview) -> dict:
    return {
        "action": review.action,
        "status": review.status,
        "mode": review.mode,
        "summary": review.summary,
        "details": list(review.details),
    }


# ============================================================
# Windows 原汁原味 Shell 文件系统图标直接渲染器 (100% 真实原生像素提取)
# ============================================================
# win32gui 和 win32ui 进行延迟加载，避免启动时加载不必要的大 DLL 导致卡顿
_win32_imported = False
win32gui = None
win32ui = None

def _ensure_win32():
    global _win32_imported, win32gui, win32ui
    if not _win32_imported:
        try:
            import win32gui as wgui
            import win32ui as wui
            win32gui = wgui
            win32ui = wui
        except Exception:
            pass
        _win32_imported = True

class WindowsIconCache:
    """完美抓取 Windows 真实物理文件及关联后缀的 .ico 图像资源，并高速缓存在内存中供 Tkinter 渲染。"""
    _cache = {}
    _cache_errors = {}
    _diagnostics = {
        "requests": 0,
        "successes": 0,
        "failures": 0,
        "fallbacks": 0,
        "last": [],
    }

    @classmethod
    def reset_diagnostics(cls) -> None:
        cls._diagnostics = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "fallbacks": 0,
            "last": [],
        }

    @classmethod
    def diagnostics_snapshot(cls) -> dict:
        snapshot = dict(cls._diagnostics)
        snapshot["last"] = [dict(item) for item in cls._diagnostics["last"]]
        return snapshot

    @classmethod
    def _record_diagnostic(
        cls,
        path_or_extension: str,
        *,
        real_icon: bool,
        fallback: bool,
        error: Exception | None = None,
    ) -> None:
        cls._diagnostics["requests"] += 1
        if real_icon:
            cls._diagnostics["successes"] += 1
        if error is not None:
            cls._diagnostics["failures"] += 1
        if fallback:
            cls._diagnostics["fallbacks"] += 1
        cls._diagnostics["last"].append({
            "path_or_extension": path_or_extension,
            "real_icon": real_icon,
            "fallback": fallback,
            "error_type": type(error).__name__ if error is not None else None,
            "error_message": str(error) if error is not None else None,
        })
        del cls._diagnostics["last"][:-20]

    @classmethod
    def get_system_icon_image(cls, path_str: str, is_folder: bool = False) -> ImageTk.PhotoImage | None:
        """调用 Windows Shell API 抓取 16x16 绝对原生的文件关联物理图标像素位图。"""
        import ctypes
        from ctypes import wintypes

        class SHFILEINFOW(ctypes.Structure):
            _fields_ = [
                ("hIcon", wintypes.HANDLE),
                ("iIcon", ctypes.c_int),
                ("dwAttributes", wintypes.DWORD),
                ("szDisplayName", wintypes.WCHAR * 260),
                ("szTypeName", wintypes.WCHAR * 80)
            ]

        SHGFI_ICON = 0x000000100
        SHGFI_SMALLICON = 0x000000001
        SHGFI_USEFILEATTRIBUTES = 0x00000010
        FILE_ATTRIBUTE_DIRECTORY = 0x00000010
        FILE_ATTRIBUTE_NORMAL = 0x00000080

        p = Path(path_str)
        ext = "folder" if (is_folder or p.is_dir()) else p.suffix.lower()
        if ext in cls._cache:
            cached = cls._cache[ext]
            cached_error = cls._cache_errors.get(ext)
            cls._record_diagnostic(
                path_str or ext,
                real_icon=isinstance(cached, ImageTk.PhotoImage),
                fallback=not isinstance(cached, ImageTk.PhotoImage),
                error=cached_error,
            )
            return cached

        _ensure_win32()
        shell_error: Exception | None = None
        if win32gui and win32ui:
            try:
                shfileinfo = SHFILEINFOW()
                flags = SHGFI_ICON | SHGFI_SMALLICON | SHGFI_USEFILEATTRIBUTES
                attribs = FILE_ATTRIBUTE_DIRECTORY if (is_folder or p.is_dir()) else FILE_ATTRIBUTE_NORMAL
                dummy_path = "C:\\dummy_dir" if (is_folder or p.is_dir()) else f"C:\\dummy_file{ext}"
                
                res = ctypes.windll.shell32.SHGetFileInfoW(
                    dummy_path,
                    attribs,
                    ctypes.byref(shfileinfo),
                    ctypes.sizeof(shfileinfo),
                    flags
                )
                
                if res != 0 and shfileinfo.hIcon:
                    hdc = win32gui.GetDC(0)
                    hdc_mem = win32gui.CreateCompatibleDC(hdc)
                    hbmp = win32gui.CreateCompatibleBitmap(hdc, 16, 16)
                    hbmp_old = win32gui.SelectObject(hdc_mem, hbmp)
                    
                    win32gui.DrawIconEx(hdc_mem, 0, 0, shfileinfo.hIcon, 16, 16, 0, 0, 3)
                    
                    bmp = win32ui.CreateBitmapFromHandle(hbmp)
                    bmpinfo = bmp.GetInfo()
                    bmpstr = bmp.GetBitmapBits(True)
                    
                    img = Image.frombuffer(
                        'RGBA',
                        (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                        bmpstr, 'raw', 'BGRA', 0, 1
                    )
                    
                    win32gui.SelectObject(hdc_mem, hbmp_old)
                    win32gui.DeleteObject(hbmp)
                    win32gui.DeleteDC(hdc_mem)
                    win32gui.ReleaseDC(0, hdc)
                    ctypes.windll.user32.DestroyIcon(shfileinfo.hIcon)
                    
                    photo = ImageTk.PhotoImage(img)
                    cls._cache[ext] = photo
                    cls._record_diagnostic(path_str or ext, real_icon=True, fallback=False)
                    return photo
            except Exception as exc:
                shell_error = exc
        else:
            shell_error = RuntimeError("Windows Shell icon backend unavailable")

        fallback_emoji = "📁" if (is_folder or p.is_dir()) else "📄"
        if not (is_folder or p.is_dir()):
            icon_map = {
                ".txt": "📝", ".bat": "⚡", ".cmd": "⚡", ".exe": "⚙️", ".lnk": "🔗",
                ".zip": "📦", ".rar": "📦", ".7z": "📦", ".xlsx": "📊", ".xls": "📊",
                ".docx": "📘", ".doc": "📘", ".pptx": "📙", ".ppt": "📙", ".pdf": "📕",
                ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️", ".gif": "🖼️", ".json": "⚙️",
                ".yaml": "⚙️", ".yml": "⚙️", ".py": "🐍", ".html": "🌐", ".htm": "🌐", ".md": "📖"
            }
            fallback_emoji = icon_map.get(ext, "📄")
            
        cls._cache[ext] = fallback_emoji
        cls._cache_errors[ext] = shell_error or RuntimeError("Windows Shell icon lookup returned no icon")
        cls._record_diagnostic(path_str or ext, real_icon=False, fallback=True, error=cls._cache_errors[ext])
        return fallback_emoji

    @classmethod
    def get_icon(cls, path_str: str, is_folder: bool = False):
        return cls.get_system_icon_image(path_str, is_folder)


class DesktopToolApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self) -> None:
        super().__init__()
        self.theme_mode = _startup_theme_mode()
        self.effective_theme = resolve_theme_mode(
            self.theme_mode,
            system_theme=_detect_system_effective_theme(),
        )
        self._tokens = theme_tokens(self.effective_theme)
        ctk.set_appearance_mode(self.effective_theme)
        self.TkdndVersion = TkinterDnD._require(self)
        self._geometry_save_job = None
        self._geometry_restoring = True
        self._native_window_style_applied = False
        self._native_window_style_reapply_scheduled = False
        # Docking is deliberately separate from ``_pinned``.  The latter is
        # only the Windows Z-order preference; these fields describe the
        # temporary top-edge drawer transition.
        self._dock_state = "free"
        self._dock_work_area: WorkArea | None = None
        self._dock_debounce_job = None
        self._dock_autohide_job = None
        self._dock_animation_job = None
        self._dock_animation_serial = 0
        self._dock_restore_blocked = True
        self._dock_dragging = False
        self._dock_drag_moved = False
        self._dock_drag_expanded = False
        self._dock_undock_blocked = False
        self._dock_drag_origin = None
        self._dock_pause_count = 0
        self._dock_modal_windows: set[str] = set()
        self._dock_drop_active = False
        self._dock_handle_dnd_registered = False
        self._dock_native_interaction = False
        self._dock_native_interaction_job = None
        self._dock_native_baseline: WindowGeometry | None = None
        self._dock_native_size_changed = False
        self._dock_resize_blocked = False
        self._dock_expected_geometry: WindowGeometry | None = None
        self._dock_expected_outer_position: tuple[int, int] | None = None
        self._height_resizing = False
        self._height_resize_origin = None
        self._last_observed_geometry: WindowGeometry | None = None
        self._dnd_target_widgets = weakref.WeakSet()
        self._expanded_geometry: WindowGeometry | None = None
        self._tray_restore_was_docked = False
        self._tray_hidden = False
        self._dock_handle_height = 30
        self._init_storage()
        self._init_window()
        self._build_ui()
        self._refresh_all()
        self.after_idle(self._finish_geometry_restore)

        try:
            self.drop_target_register(DND_FILES, DND_TEXT)
            self.dnd_bind("<<Drop>>", self._on_global_drop)
            try:
                self._dnd_target_widgets.add(self)
            except TypeError:
                pass
            _record_dnd_registration("target", self, True)
        except Exception as exc:
            _record_dnd_registration("target", self, False, exc)

    def _t(self, name: str):
        """Resolve a visual token from the single startup palette."""

        return self._tokens[name]

    def _toggle_theme(self) -> None:
        """Switch palettes immediately without changing the startup contract."""

        self.theme_mode = toggle_theme_mode(self.effective_theme)
        self.effective_theme = resolve_theme_mode(self.theme_mode)
        self._refresh_theme()

    def _refresh_theme(self) -> None:
        """Apply the selected token palette to the complete main window.

        Most of the existing UI intentionally passes concrete token values to
        CustomTkinter and native Tk widgets.  Retint the existing widget tree,
        then rebuild only the two dynamic item hosts through their established
        refresh methods.  This keeps both canvas/scrollbar structures intact
        and avoids moving the user away from either list.
        """

        station_view = self._station_canvas.yview() if hasattr(self, "_station_canvas") else None
        actions_view = self._actions_canvas.yview() if hasattr(self, "_actions_canvas") else None

        old_tokens = self._tokens
        self._tokens = theme_tokens(self.effective_theme)
        ctk.set_appearance_mode(self.effective_theme)

        self.configure(fg_color=self._t("background"))
        for widget in tuple(self.winfo_children()):
            self._retint_widget_tree(widget, old_tokens)

        if hasattr(self, "_dock_handle_label"):
            self._dock_handle_label.configure(bg=self._t("surface"))
            self._draw_dock_handle_icon()

        if hasattr(self, "_app_icon_photo"):
            try:
                self._app_icon_photo = ImageTk.PhotoImage(self._create_app_icon())
                self.iconphoto(True, self._app_icon_photo)
            except Exception:
                pass

        self.btn_theme.configure(
            text="☀ 亮色" if self.effective_theme == "dark" else "☾ 暗色",
            fg_color=self._t("hover"),
            hover_color=self._t("elevated"),
            text_color=self._t("secondary"),
        )
        self.btn_pin.configure(
            fg_color=self._t("hover"),
            hover_color=self._t("elevated"),
            text_color=self._t("pin_text"),
        )
        self._refresh_station()
        self._refresh_cards()

        def restore_scroll_positions() -> None:
            if station_view and self._station_canvas.winfo_exists():
                self._station_canvas.yview_moveto(station_view[0])
            if actions_view and self._actions_canvas.winfo_exists():
                self._actions_canvas.yview_moveto(actions_view[0])

        self.after_idle(restore_scroll_positions)
        self._set_status(f"已切换至{'亮色' if self.effective_theme == 'light' else '暗色'}主题", "ready")

    def _retint_widget_tree(self, widget, old_tokens: dict[str, object]) -> None:
        """Update token-backed options on CustomTkinter and native Tk widgets."""

        def remap(value):
            for name, old_value in old_tokens.items():
                if isinstance(old_value, str) and value == old_value:
                    return self._t(name)
            return value

        for option in (
            "fg_color",
            "bg_color",
            "hover_color",
            "button_color",
            "button_hover_color",
            "border_color",
            "text_color",
        ):
            try:
                current = widget.cget(option)
                replacement = remap(current)
                if replacement != current:
                    widget.configure(**{option: replacement})
            except Exception:
                # Not every widget exposes every CustomTkinter option; native
                # Tk widgets are handled by the options below.
                pass

        for option in ("background", "foreground", "bg", "fg"):
            try:
                current = widget.cget(option)
                replacement = remap(current)
                if replacement != current:
                    widget.configure(**{option: replacement})
            except Exception:
                pass

        for child in widget.winfo_children():
            self._retint_widget_tree(child, old_tokens)

    def _finish_geometry_restore(self) -> None:
        self._geometry_restoring = False
        self._dock_restore_blocked = False
        self._clear_expected_geometry()
        self._last_observed_geometry = self._current_window_geometry()
        # A valid saved geometry may already touch the work-area edge.  Once
        # restoration is complete, run the same observation path as a normal
        # Configure event instead of requiring the user to move away first.
        self._observe_window_position()

    # ============================================================
    # 顶部抽屉停靠
    # ============================================================

    _DOCK_EDGE_THRESHOLD = 12
    _DOCK_DEBOUNCE_MS = 240
    _DOCK_AUTOHIDE_MS = 1000
    _DOCK_ANIMATION_STEPS = 14
    _DOCK_ANIMATION_STEP_MS = 16
    _DOCK_NATIVE_QUIET_MS = 180
    _DOCK_SIZE_CHANGE_THRESHOLD = 24

    def _cancel_dock_job(self, attribute: str) -> None:
        job = getattr(self, attribute, None)
        if job is None:
            return
        try:
            self.after_cancel(job)
        except Exception:
            pass
        setattr(self, attribute, None)

    def _cancel_dock_animation(self) -> None:
        self._dock_animation_serial += 1
        self._cancel_dock_job("_dock_animation_job")
        self._clear_expected_geometry()

    def _cancel_dock_jobs(self) -> None:
        self._cancel_dock_job("_dock_debounce_job")
        self._cancel_dock_job("_dock_autohide_job")
        self._cancel_dock_animation()

    def _window_is_maximized(self) -> bool:
        """Return the native maximized state without assuming a Windows API."""

        try:
            return str(self.state()).lower() in {"zoomed", "maximized"}
        except Exception:
            return False

    def _native_resize_capability_available(self) -> bool:
        """Return whether a native resize can still own Configure events.

        Once the visible frame style has been verified, this app no longer
        exposes native resize/Snap affordances.  A size change observed before
        that verification is kept behind the conservative resize fence; a
        verified non-resizable frame only needs the short native quiet period.
        Non-Windows/headless runs have no native resize owner either.
        """

        return os.name == "nt" and not bool(
            getattr(self, "_native_window_style_applied", False)
        )

    def _cancel_native_titlebar_interaction(self) -> None:
        self._cancel_dock_job("_dock_native_interaction_job")
        self._dock_native_interaction = False
        self._dock_native_baseline = None
        self._dock_native_size_changed = False
        self._clear_expected_geometry()

    def _begin_native_titlebar_interaction(self, geometry: WindowGeometry) -> None:
        """Fence dock automation while Configure events come from the WM.

        Tk does not expose a portable title-bar drag start/end event.  A short
        quiet period around root Configure events gives native move/resize and
        Windows Snap one owner of geometry at a time, while still allowing a
        normal title-bar move to the top edge to be observed after the drag.
        """

        if not self._dock_native_interaction:
            self._dock_native_baseline = geometry
            self._dock_native_size_changed = False
        self._dock_native_interaction = True
        self._cancel_dock_jobs()
        if self._dock_state in ("collapsing", "expanding"):
            self._release_dock()
        self._cancel_geometry_save_job()
        self._arm_native_titlebar_quiet_timer(self._DOCK_NATIVE_QUIET_MS)

    def _arm_native_titlebar_quiet_timer(self, delay: int) -> None:
        """Restart the native Configure quiet period after every WM update."""

        self._cancel_dock_job("_dock_native_interaction_job")
        self._dock_native_interaction_job = self.after(
            delay,
            self._finish_native_titlebar_interaction,
        )

    def _finish_native_titlebar_interaction(self) -> None:
        self._dock_native_interaction_job = None
        if not self._dock_native_interaction:
            return

        geometry = self._current_window_geometry()
        size_changed = self._dock_native_size_changed
        self._dock_native_interaction = False
        self._dock_native_baseline = None
        self._dock_native_size_changed = False

        if self._window_is_maximized():
            self._dock_resize_blocked = True
            self._cancel_dock_jobs()
            if self._dock_state != "free":
                self._release_dock()
            self._last_observed_geometry = geometry
            return

        if size_changed:
            self._dock_resize_blocked = True
        self._observe_window_position()
        if self._dock_state == "docked_expanded":
            self._schedule_dock_autohide()
        self._schedule_geometry_save()

    def _dock_pause(self) -> None:
        """Pause edge automation while a dialog or important operation owns UI."""

        self._dock_pause_count += 1
        self._cancel_dock_job("_dock_debounce_job")
        self._cancel_dock_job("_dock_autohide_job")

    def _dock_resume(self) -> None:
        self._dock_pause_count = max(0, self._dock_pause_count - 1)
        if self._dock_pause_count == 0 and self._dock_state == "docked_expanded":
            self._schedule_dock_autohide()

    def _bind_dock_modal(self, dialog) -> None:
        """Track this modal independently from other dock pauses."""

        key = str(dialog)
        if key in self._dock_modal_windows:
            return
        self._dock_modal_windows.add(key)

        def _on_destroy(event, target=dialog, target_key=key):
            if event.widget is target and target_key in self._dock_modal_windows:
                self._dock_modal_windows.discard(target_key)
                if self._dock_state == "docked_expanded":
                    self._schedule_dock_autohide()

        dialog.bind("<Destroy>", _on_destroy, add="+")

    def _dock_modal_present(self) -> bool:
        # Keep the registered-modal state authoritative from the instant a
        # dialog is bound.  ``grab_current`` can lag behind ``grab_set`` by a
        # Tk event turn, and the pause count may also be shared with another
        # operation.
        if self._dock_modal_windows or self._dock_pause_count:
            return True
        try:
            current_grab = self.grab_current()
            return current_grab is not None and current_grab is not self
        except Exception:
            return False

    @staticmethod
    def _geometry_to_string(geometry: WindowGeometry) -> str:
        x = f"+{geometry.x}" if geometry.x >= 0 else str(geometry.x)
        y = f"+{geometry.y}" if geometry.y >= 0 else str(geometry.y)
        return f"{geometry.width}x{geometry.height}{x}{y}"

    def _current_window_geometry(self) -> WindowGeometry | None:
        try:
            import re

            # Tk may expose a native negative absolute coordinate as
            # ``widthxheight+x+-y`` after SetWindowPos.  Accept that spelling
            # and normalize it back to the same WindowGeometry value; regular
            # ``+x+y`` and ``-x-y`` forms remain unchanged.
            match = re.fullmatch(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)", self.geometry())
            if match is None:
                return None

            def _parse_coordinate(value: str) -> int:
                return int(value[1:]) if value.startswith("+") else int(value)

            return WindowGeometry(
                _parse_coordinate(match.group(3)), _parse_coordinate(match.group(4)),
                int(match.group(1)), int(match.group(2)),
            )
        except Exception:
            return None

    def _window_outer_rect(self) -> tuple[int, int, int, int] | None:
        """Return the screen-space window rectangle, including the title bar."""

        if os.name == "nt":
            try:
                class _Rect(ctypes.Structure):
                    _fields_ = [
                        ("left", wintypes.LONG),
                        ("top", wintypes.LONG),
                        ("right", wintypes.LONG),
                        ("bottom", wintypes.LONG),
                    ]

                rect = _Rect()
                native_hwnd = _resolve_native_window_hwnd(int(self.winfo_id()))
                if ctypes.windll.user32.GetWindowRect(native_hwnd, ctypes.byref(rect)):
                    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
            except Exception:
                pass

        geometry = self._current_window_geometry()
        if geometry is None:
            return None
        return geometry.x, geometry.y, geometry.x + geometry.width, geometry.y + geometry.height

    def _window_outer_height(self) -> int:
        rect = self._window_outer_rect()
        if rect is not None:
            return max(1, rect[3] - rect[1])
        geometry = self._current_window_geometry()
        return max(1, geometry.height if geometry is not None else self.winfo_height())

    def _remember_expanded_geometry(self, geometry: WindowGeometry | None = None) -> None:
        candidate = geometry or self._current_window_geometry()
        if candidate is not None:
            self._expanded_geometry = candidate

    def _geometry_for_outer_position(
        self,
        x: int,
        y: int,
        geometry: WindowGeometry | None = None,
    ) -> WindowGeometry | None:
        current = geometry or self._current_window_geometry()
        if current is None:
            return None
        rect = self._window_outer_rect()
        if rect is None:
            return WindowGeometry(x, y, current.width, current.height)
        return WindowGeometry(
            current.x + x - rect[0],
            current.y + y - rect[1],
            current.width,
            current.height,
        )

    def _set_window_outer_position(self, x: int, y: int) -> bool:
        # After a native negative move, Tk may report ``+x+-y`` temporarily,
        # which is not a parseable Tk geometry string.  The native outer rect
        # remains authoritative; retain the last acknowledged dimensions so
        # later animation ticks do not stop after the first negative step.
        current = (
            self._current_window_geometry()
            or self._dock_expected_geometry
            or self._last_observed_geometry
            or self._expanded_geometry
        )
        if current is None:
            return False
        target = self._geometry_for_outer_position(x, y, current)
        if target is None:
            return False

        # A negative Tk coordinate is not an absolute screen coordinate: Tk
        # treats ``-810`` as a bottom/right offset.  The collapsed drawer can
        # legitimately have a negative absolute outer y, so move the native
        # top-level HWND directly on Windows.  Still publish the corresponding
        # Tk geometry and acknowledgement token so Configure/save handling
        # remains owned by the existing animation contract.
        if os.name == "nt" and (x < 0 or y < 0):
            try:
                hwnd = int(self.winfo_id())
            except Exception:
                hwnd = 0
            # Install the acknowledgement before SetWindowPos can emit its
            # Configure event; otherwise the native move can be mistaken for
            # a title-bar drag by the existing quiet-timer path.
            self._set_window_geometry(
                target,
                expected_outer_position=(x, y),
                write_geometry=False,
            )
            if _set_native_window_position(hwnd, x, y):
                return True

            # A negative coordinate is an absolute screen coordinate only for
            # SetWindowPos.  Passing it to Tk after a native failure would
            # reinterpret it as a right/bottom offset and move the window to
            # an unrelated position.  Leave this frame untouched instead.
            self._clear_expected_geometry()
            logger.warning(
                "negative outer position was not applied; retaining current position at (%d, %d)",
                x,
                y,
            )
            return False

        self._set_window_geometry(target, expected_outer_position=(x, y))
        return True

    def _set_window_geometry(
        self,
        geometry: WindowGeometry,
        *,
        expected_outer_position: tuple[int, int] | None = None,
        write_geometry: bool = True,
    ) -> None:
        """Write geometry while fencing the Configure event it will produce.

        Tk delivers root Configure events asynchronously.  Consequently a
        geometry write made by the drawer animation can otherwise look exactly
        like a title-bar drag by the time ``_schedule_geometry_save`` sees it.
        Keep both the Tk geometry and (where available) the outer screen
        position as an acknowledgement token for that one write.
        """

        self._cancel_native_titlebar_interaction()
        self._dock_expected_geometry = geometry
        self._dock_expected_outer_position = expected_outer_position
        if write_geometry:
            self.geometry(self._geometry_to_string(geometry))

    def _clear_expected_geometry(self) -> None:
        self._dock_expected_geometry = None
        self._dock_expected_outer_position = None

    def _configure_matches_expected_geometry(
        self,
        geometry: WindowGeometry,
        outer_rect: tuple[int, int, int, int] | None = None,
    ) -> bool:
        expected = self._dock_expected_geometry
        if expected is None:
            return False
        if geometry == expected:
            return True

        expected_outer = self._dock_expected_outer_position
        return (
            expected_outer is not None
            and outer_rect is not None
            and (outer_rect[0], outer_rect[1]) == expected_outer
            and geometry.width == expected.width
            and geometry.height == expected.height
        )

    def _set_window_y(self, y: int) -> None:
        rect = self._window_outer_rect()
        current = (
            self._current_window_geometry()
            or self._dock_expected_geometry
            or self._last_observed_geometry
            or self._expanded_geometry
        )
        if current is None:
            return
        x = rect[0] if rect is not None else current.x
        self._set_window_outer_position(x, y)

    def _cancel_geometry_save_job(self) -> None:
        if self._geometry_save_job is None:
            return
        try:
            self.after_cancel(self._geometry_save_job)
        except Exception:
            pass
        self._geometry_save_job = None

    def _dock_area_for_geometry(self, geometry: WindowGeometry | None = None) -> WorkArea | None:
        candidate = geometry or self._current_window_geometry() or self._expanded_geometry
        if candidate is None or not getattr(self, "_work_areas", None):
            return None
        try:
            return select_work_area(candidate, self._work_areas, primary_index=self._primary_work_area_index)
        except (IndexError, TypeError, ValueError):
            return None

    def _is_pointer_inside_window(self) -> bool:
        # ``winfo_rootx/y`` describe the Tk client widget, but a native
        # title-bar drag can leave the Tk coordinate model out of sync for a
        # short time.  Query the visible top-level HWND first so the native
        # caption is never mistaken for usable drawer content.
        if os.name == "nt":
            try:
                class _Rect(ctypes.Structure):
                    _fields_ = [
                        ("left", wintypes.LONG),
                        ("top", wintypes.LONG),
                        ("right", wintypes.LONG),
                        ("bottom", wintypes.LONG),
                    ]

                class _Point(ctypes.Structure):
                    _fields_ = [
                        ("x", wintypes.LONG),
                        ("y", wintypes.LONG),
                    ]

                user32 = ctypes.windll.user32
                get_client_rect = user32.GetClientRect
                client_to_screen = user32.ClientToScreen
                get_cursor_pos = user32.GetCursorPos
                get_client_rect.argtypes = [
                    wintypes.HWND,
                    ctypes.POINTER(_Rect),
                ]
                get_client_rect.restype = wintypes.BOOL
                client_to_screen.argtypes = [
                    wintypes.HWND,
                    ctypes.POINTER(_Point),
                ]
                client_to_screen.restype = wintypes.BOOL
                get_cursor_pos.argtypes = [ctypes.POINTER(_Point)]
                get_cursor_pos.restype = wintypes.BOOL

                native_hwnd = _resolve_native_window_hwnd(int(self.winfo_id()))
                if native_hwnd:
                    hwnd = wintypes.HWND(native_hwnd)
                    client_rect = _Rect()
                    client_origin = _Point()
                    cursor = _Point()
                    if (
                        get_client_rect(hwnd, ctypes.byref(client_rect))
                        and client_to_screen(hwnd, ctypes.byref(client_origin))
                        and get_cursor_pos(ctypes.byref(cursor))
                    ):
                        client_left = client_origin.x + client_rect.left
                        client_top = client_origin.y + client_rect.top
                        client_right = client_origin.x + client_rect.right
                        client_bottom = client_origin.y + client_rect.bottom
                        return (
                            client_left <= cursor.x < client_right
                            and client_top <= cursor.y < client_bottom
                        )
            except Exception:
                # Tk/headless sessions and restricted Windows APIs retain the
                # established Tk-coordinate fallback below.
                pass

        try:
            pointer_x = int(self.winfo_pointerx())
            pointer_y = int(self.winfo_pointery())
        except Exception:
            return False

        # Prefer the Tk client area.  The native title bar is not part of the
        # content that should keep the drawer expanded after a drag to the
        # top edge, while a pointer over the client area should still do so.
        try:
            client_x = int(self.winfo_rootx())
            client_y = int(self.winfo_rooty())
            client_width = int(self.winfo_width())
            client_height = int(self.winfo_height())
            if client_width > 0 and client_height > 0:
                return (
                    client_x <= pointer_x < client_x + client_width
                    and client_y <= pointer_y < client_y + client_height
                )
        except Exception:
            pass

        # Keep the existing screen-space fallback for environments where the
        # Tk client rectangle cannot be queried.
        try:
            rect = self._window_outer_rect()
            if rect is None:
                return False
            return (
                rect[0] <= pointer_x < rect[2]
                and rect[1] <= pointer_y < rect[3]
            )
        except Exception:
            return False

    def _observe_window_position(self) -> None:
        """Use Configure as the native-titlebar move signal, never global Motion."""

        if (
            self._geometry_restoring
            or self._dock_restore_blocked
            or self._dock_dragging
            or getattr(self, "_height_resizing", False)
        ):
            return
        geometry = self._current_window_geometry()
        if geometry is None:
            return
        outer_rect = self._window_outer_rect()
        if outer_rect is None:
            outer_top = geometry.y
            docking_geometry = geometry
        else:
            outer_top = outer_rect[1]
            docking_geometry = WindowGeometry(
                outer_rect[0],
                outer_rect[1],
                max(1, outer_rect[2] - outer_rect[0]),
                max(1, outer_rect[3] - outer_rect[1]),
            )

        if self._window_is_maximized():
            self._dock_resize_blocked = True
            self._cancel_dock_jobs()
            if self._dock_state != "free":
                self._release_dock()
            return

        if self._dock_native_interaction:
            baseline = self._dock_native_baseline
            if baseline is not None and (
                abs(geometry.width - baseline.width) >= self._DOCK_SIZE_CHANGE_THRESHOLD
                or abs(geometry.height - baseline.height) >= self._DOCK_SIZE_CHANGE_THRESHOLD
            ):
                self._dock_native_size_changed = True
                self._dock_resize_blocked = True
                self._cancel_dock_jobs()
                if self._dock_state != "free":
                    self._release_dock()
            self._last_observed_geometry = geometry
            return

        if self._dock_resize_blocked:
            area = self._dock_area_for_geometry(docking_geometry)
            if area is None or outer_top > area.top + self._DOCK_EDGE_THRESHOLD:
                self._dock_resize_blocked = False
            elif (
                not self._native_resize_capability_available()
                and abs(outer_top - area.top) <= self._DOCK_EDGE_THRESHOLD
            ):
                # A verified non-resizable normal frame has no native resize
                # owner left after the quiet timer.  Do not let a size-change
                # fence permanently suppress a top-edge observation.  The
                # maximized case returned above and a move away from the edge
                # retain their existing protection semantics.
                self._dock_resize_blocked = False
            else:
                self._cancel_dock_job("_dock_debounce_job")
                self._last_observed_geometry = geometry
                return

        if self._dock_undock_blocked:
            area = self._dock_work_area or self._dock_area_for_geometry(docking_geometry)
            if area is None or outer_top <= area.top + self._DOCK_EDGE_THRESHOLD:
                return
            self._dock_undock_blocked = False

        if self._dock_state == "docked_expanded":
            area = self._dock_work_area
            if area is not None and abs(outer_top - area.top) > self._DOCK_EDGE_THRESHOLD:
                # A native title-bar drag away from the edge always releases
                # docking.  From this point on ordinary Configure saves are
                # allowed and no automatic collapse can follow the drag.
                undock_near_edge = outer_top <= area.top + self._DOCK_EDGE_THRESHOLD
                self._release_dock()
                self._dock_undock_blocked = undock_near_edge
            elif area is not None:
                # Horizontal title-bar moves are still part of the docked
                # expanded geometry and must survive a later tray restore.
                self._remember_expanded_geometry(geometry)
            return

        if self._dock_state in ("collapsing", "expanding", "collapsed"):
            return

        area = self._dock_area_for_geometry(docking_geometry)
        near_top = area is not None and abs(outer_top - area.top) <= self._DOCK_EDGE_THRESHOLD
        if near_top and not self._dock_pause_count:
            self._cancel_dock_job("_dock_debounce_job")
            self._dock_debounce_job = self.after(self._DOCK_DEBOUNCE_MS, self._on_top_debounce)
        else:
            self._cancel_dock_job("_dock_debounce_job")
        self._last_observed_geometry = geometry

    def _on_top_debounce(self) -> None:
        self._dock_debounce_job = None
        if (
            self._geometry_restoring
            or self._dock_pause_count
            or self._dock_native_interaction
            or self._dock_resize_blocked
            or getattr(self, "_height_resizing", False)
            or self._window_is_maximized()
            or self._dock_state != "free"
        ):
            return
        geometry = self._current_window_geometry()
        if geometry is None:
            return
        outer_rect = self._window_outer_rect()
        if outer_rect is None:
            outer_top = geometry.y
            docking_geometry = geometry
        else:
            outer_top = outer_rect[1]
            docking_geometry = WindowGeometry(
                outer_rect[0],
                outer_rect[1],
                max(1, outer_rect[2] - outer_rect[0]),
                max(1, outer_rect[3] - outer_rect[1]),
            )
        area = self._dock_area_for_geometry(docking_geometry)
        if area is None or abs(outer_top - area.top) > self._DOCK_EDGE_THRESHOLD:
            return
        self._dock_work_area = area
        self._remember_expanded_geometry(geometry)
        self._start_dock_animation(area.top, "docked_expanded")

    def _release_dock(self) -> None:
        self._cancel_dock_jobs()
        self._dock_state = "free"
        self._dock_work_area = None
        self._dock_dragging = False
        self._dock_undock_blocked = False
        self._hide_dock_handle()
        self._remember_expanded_geometry()

    def _start_dock_animation(self, target_y: int, final_state: str) -> None:
        if self._dock_native_interaction or self._window_is_maximized():
            return
        current = self._current_window_geometry()
        if current is None:
            return
        current_rect = self._window_outer_rect()

        # Cancelling first makes a fast reverse start from the current
        # interpolated y instead of stacking callbacks from both directions.
        self._cancel_dock_animation()
        self._cancel_dock_job("_dock_debounce_job")
        self._cancel_dock_job("_dock_autohide_job")
        self._cancel_geometry_save_job()
        start_y = current_rect[1] if current_rect is not None else current.y
        if start_y == target_y:
            self._set_window_y(target_y)
            self._dock_state = final_state
            if final_state == "collapsed":
                self._show_dock_handle()
            else:
                self._hide_dock_handle()
                self._remember_expanded_geometry(self._current_window_geometry())
                if final_state == "docked_expanded":
                    self._schedule_dock_autohide()
            return

        self._dock_state = "collapsing" if final_state == "collapsed" else "expanding"
        # Keep the handle over the moving statusbar during expansion.  A
        # press that arrives immediately after Enter can therefore cancel the
        # reverse animation and start a deliberate drag instead of losing the
        # only visible drag target.
        serial = self._dock_animation_serial
        step = 0

        def _tick() -> None:
            nonlocal step
            if serial != self._dock_animation_serial:
                return
            step += 1
            ratio = min(1.0, step / self._DOCK_ANIMATION_STEPS)
            y = round(start_y + (target_y - start_y) * ratio)
            self._set_window_y(y)
            if ratio >= 1.0:
                self._dock_animation_job = None
                self._dock_state = final_state
                if final_state == "collapsed":
                    self._show_dock_handle()
                else:
                    self._hide_dock_handle()
                    self._remember_expanded_geometry(self._current_window_geometry())
                    if final_state == "docked_expanded":
                        self._schedule_dock_autohide()
                return
            self._dock_animation_job = self.after(self._DOCK_ANIMATION_STEP_MS, _tick)

        self._dock_animation_job = self.after(self._DOCK_ANIMATION_STEP_MS, _tick)

    def _request_dock_collapse(self) -> None:
        if (
            self._dock_state != "docked_expanded"
            or self._dock_pause_count
            or self._dock_native_interaction
            or self._dock_resize_blocked
            or self._window_is_maximized()
        ):
            return
        area = self._dock_work_area
        geometry = self._current_window_geometry()
        if area is None or geometry is None:
            return
        self._start_dock_animation(
            area.top - self._window_outer_height() + self._dock_handle_height,
            "collapsed",
        )

    def _request_dock_expand(self) -> None:
        if self._dock_state not in ("collapsed", "collapsing", "expanding"):
            return
        area = self._dock_work_area or self._dock_area_for_geometry(self._expanded_geometry)
        if area is None:
            return
        self._dock_work_area = area
        self._start_dock_animation(area.top, "docked_expanded")

    def _schedule_dock_autohide(self) -> None:
        self._cancel_dock_job("_dock_autohide_job")
        if (
            self._dock_state != "docked_expanded"
            or self._dock_modal_present()
            or self._dock_native_interaction
            or self._window_is_maximized()
        ):
            return
        delay = 250 if self._dock_resize_blocked else self._DOCK_AUTOHIDE_MS
        self._dock_autohide_job = self.after(delay, self._autohide_if_pointer_left)

    def _autohide_if_pointer_left(self) -> None:
        self._dock_autohide_job = None
        if self._dock_state != "docked_expanded" or self._window_is_maximized():
            return

        # Native Configure events temporarily own geometry.  Do not collapse
        # against that owner, but do keep polling; otherwise the one-shot timer
        # is lost while a native interaction is settling.
        if self._dock_native_interaction:
            self._dock_autohide_job = self.after(250, self._autohide_if_pointer_left)
            return

        # Once the quiet period has ended, a verified non-resizable normal
        # frame cannot still have a real native resize owner.  Clear only this
        # stale fence while the drawer is already docked and expanded; the
        # maximized case returned above and native interaction case above keep
        # their protection semantics.
        if self._dock_resize_blocked:
            resize_capability = getattr(self, "_native_resize_capability_available", None)
            native_resize_available = (
                resize_capability() if resize_capability is not None else True
            )
            if not native_resize_available:
                self._dock_resize_blocked = False
            else:
                self._dock_autohide_job = self.after(250, self._autohide_if_pointer_left)
                return

        if self._dock_modal_present():
            self._dock_autohide_job = self.after(250, self._autohide_if_pointer_left)
            return

        # The native title bar is outside the Tk root's Enter/Leave stream;
        # polling the Tk client area keeps the window open while the pointer
        # is over usable content without requiring a title-bar Leave event.
        if self._is_pointer_inside_window():
            self._dock_autohide_job = self.after(250, self._autohide_if_pointer_left)
            return
        self._request_dock_collapse()

    def _on_dock_enter(self, _event=None) -> None:
        if self._dock_state == "docked_expanded":
            self._schedule_dock_autohide()

    def _on_dock_leave(self, _event=None) -> None:
        if self._dock_state == "docked_expanded":
            self._schedule_dock_autohide()

    def _show_dock_handle(self) -> None:
        if not hasattr(self, "_dock_handle"):
            return
        self._register_dock_handle_dnd()
        self.status_dot.grid_remove()
        self.status_label.grid_remove()
        self._dock_handle.place(
            x=0,
            y=0,
            relwidth=1.0,
            relheight=1.0,
        )
        self._dock_handle.lift()

    def _hide_dock_handle(self) -> None:
        if not hasattr(self, "_dock_handle"):
            return
        self._dock_handle.place_forget()
        self.status_dot.grid()
        self.status_label.grid()

    def _register_dock_handle_dnd(self) -> None:
        """Register the visible handle as a full DND_FILES/DND_TEXT target."""

        if self._dock_handle_dnd_registered or not hasattr(self, "_dock_handle"):
            return
        # DND events do not bubble through Tk.  Register the handle and its
        # child labels explicitly so a drop anywhere on the narrow bar works.
        _DND_DIAGNOSTICS["generation"] += 1
        self._register_dnd_target(self._dock_handle)
        for child in self._dock_handle.winfo_children():
            self._register_dnd_recursive(child, _generation_started=True)
        self._dock_handle_dnd_registered = True

    def _on_dock_handle_enter(self, _event=None) -> None:
        self._on_dock_enter()
        if not self._dock_dragging and not self._dock_drop_active:
            self._request_dock_expand()

    def _on_dock_handle_motion(self, event) -> None:
        """Keep the handle interactive while an expansion animation is running."""

        if self._dock_dragging:
            self._on_dock_handle_drag_motion(event)

    def _on_dock_handle_leave(self, _event=None) -> None:
        # Do not schedule an autohide while the bar is being dragged or while
        # its pointer is causing the expand animation to reverse.
        if not self._dock_dragging:
            self._on_dock_leave()

    def _on_dock_handle_press(self, event) -> None:
        self._cancel_dock_animation()
        self._cancel_dock_job("_dock_autohide_job")
        geometry = self._current_window_geometry()
        if geometry is None:
            return
        rect = self._window_outer_rect()
        start_x = rect[0] if rect is not None else geometry.x
        start_y = rect[1] if rect is not None else geometry.y
        self._dock_dragging = True
        self._dock_drag_moved = False
        self._dock_drag_expanded = False
        self._dock_drag_origin = (event.x_root, event.y_root, start_x, start_y)
        self._dock_state = "collapsed"

    def _on_dock_handle_drag_motion(self, event) -> None:
        if not self._dock_dragging or self._dock_drag_origin is None:
            return
        origin_x, origin_y, start_x, start_y = self._dock_drag_origin
        geometry = self._current_window_geometry()
        if geometry is None:
            return
        rect = self._window_outer_rect()
        outer_width = rect[2] - rect[0] if rect is not None else geometry.width
        outer_height = rect[3] - rect[1] if rect is not None else geometry.height
        new_x = start_x + int(event.x_root - origin_x)
        new_y = start_y + int(event.y_root - origin_y)
        self._dock_drag_moved = self._dock_drag_moved or abs(new_x - start_x) > 2 or abs(new_y - start_y) > 2
        area = self._dock_work_area
        collapsed_y = area.top - outer_height + self._dock_handle_height if area is not None else start_y
        if area is not None and new_y > collapsed_y + 12:
            # Pulling the bar down far enough is an intentional vertical
            # undock.  Keep the native title bar and all normal drag behavior.
            self._dock_state = "free"
            self._dock_work_area = None
            self._dock_drag_expanded = True
            self._dock_undock_blocked = True
            # Release the handle at a safe offset below the edge.  This keeps
            # the intentional undock from immediately re-triggering debounce.
            new_y = area.top + self._DOCK_EDGE_THRESHOLD + 4
            self._hide_dock_handle()
        if area is not None:
            new_x = min(max(new_x, area.left), area.right - outer_width)
        self._set_window_outer_position(new_x, new_y)
        current = self._current_window_geometry() or geometry
        if self._dock_state == "collapsed":
            expanded = self._geometry_for_outer_position(new_x, area.top if area else new_y, current)
            self._remember_expanded_geometry(expanded)
        else:
            self._remember_expanded_geometry(current)

    def _on_dock_handle_release(self, _event=None) -> None:
        self._dock_dragging = False
        self._dock_drag_origin = None
        self._clear_expected_geometry()
        was_moved = self._dock_drag_moved
        self._dock_drag_moved = False
        if self._dock_state == "free":
            self._hide_dock_handle()
        elif self._dock_state == "collapsed" and not was_moved:
            self._request_dock_expand()
        if self._dock_state == "collapsed":
            self._schedule_geometry_save()
        elif self._dock_state == "free":
            self._schedule_geometry_save()

    def _on_mousewheel(self, event):
        self._scroll_canvas(self._actions_canvas, event)

    @staticmethod
    def _scroll_canvas(canvas, event) -> None:
        bbox = canvas.bbox("all")
        if not bbox:
            return
        canvas_height = canvas.winfo_height()
        content_height = bbox[3] - bbox[1]
        if content_height > canvas_height:
            delta = int(-1 * (event.delta / 120)) or (-1 if event.delta > 0 else 1)
            canvas.yview_scroll(delta, "units")

    def _on_station_mousewheel(self, event):
        self._scroll_canvas(self._station_canvas, event)

    @staticmethod
    def _bind_mousewheel_recursive(widget, callback) -> None:
        """让动态条目的外层和内部控件都把滚轮交给对应滚动区。"""
        widget.bind("<MouseWheel>", callback, add="+")
        for child in widget.winfo_children():
            DesktopToolApp._bind_mousewheel_recursive(child, callback)

    def _configure_disabled_textbox(self, textbox) -> None:
        """为 CTkTextbox 设置主题化 disabled 状态颜色。"""
        textbox.configure(
            text_color=self._t("disabled_foreground"),
            fg_color=self._t("disabled_background"),
        )

    def _init_storage(self) -> None:
        self._ensure_default_config()
        self.station_storage = StationStorage(STATE_PATH)
        self.module_storage = ModuleStorage(MODULE_STATE_PATH)
        self.entries: list[StationEntry] = self.station_storage.load()
        self.custom_modules: list[CustomModule] = self.module_storage.load()
        self.quick_actions = self._load_quick_actions()

    def _ensure_default_config(self) -> None:
        """首次运行时，从打包内置的 data 目录复制默认配置到用户持久化目录 (APPDATA)。"""
        if DATA_DIR.exists() and any(DATA_DIR.iterdir()):
            return
        builtin_data = REPO_ROOT / "data"
        if not builtin_data.exists():
            return
        import shutil
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        for src in builtin_data.iterdir():
            dst = DATA_DIR / src.name
            if not dst.exists():
                shutil.copy2(src, dst)

    def _load_quick_actions(self) -> list[dict]:
        data = _load_json(QUICK_ACTIONS_PATH, {})
        actions = data.get("actions", []) if isinstance(data, dict) else []
        if actions:
            return actions
        return [dict(a) for a in QUICK_ACTION_DEFS]

    def _save_quick_actions(self) -> None:
        _save_json(QUICK_ACTIONS_PATH, {"actions": self.quick_actions})

    # ============================================================
    # 窗口
    # ============================================================

    def _create_app_icon(self):
        """生成并返回一个统一的高颜值科技感图标 (PIL.Image 格式)"""
        from PIL import Image, ImageDraw
        # 1. 采用与软件左上角、任务栏一致的高颜值科技感蓝紫色圆角双层方框
        img = Image.new("RGB", (64, 64), self._t("background"))
        draw = ImageDraw.Draw(img)
        
        # 外层方框 (深邃科技靛蓝色)
        draw.rounded_rectangle([4, 4, 60, 60], radius=16,
                               fill=self._t("elevated"), outline=self._t("border"), width=2)
        # 内层方框 (炫酷的渐变科技紫蓝色)
        draw.rounded_rectangle([12, 12, 52, 52], radius=10, fill=self._t("primary"))
        return img

    def _save_window_geometry_now(self) -> None:
        if getattr(self, "_geometry_restoring", False):
            return
        try:
            candidate = self._expanded_geometry if self._dock_state in {
                "collapsing", "collapsed", "expanding", "docked_expanded",
            } else self._current_window_geometry()
            if candidate is None:
                return
            # The native frame is intentionally non-resizable horizontally.
            # Keep persisted geometry compatible with that contract even if a
            # stale or foreign geometry object reaches this path.
            candidate = WindowGeometry(
                candidate.x,
                candidate.y,
                DEFAULT_WINDOW_WIDTH,
                candidate.height,
            )
            save_window_geometry(WINDOW_GEOMETRY_PATH, candidate)
        except Exception as exc:
            logger.debug("window geometry save skipped: %s", exc)

    def _apply_native_window_style_once(self) -> bool:
        """Apply the non-resizable native-frame contract once per visible HWND."""

        if self._native_window_style_applied:
            return True
        try:
            tk_hwnd = int(self.winfo_id())
        except Exception as exc:
            logger.debug("native window HWND unavailable: %s", exc)
            return False
        verified = _disable_native_resize_and_maximize(tk_hwnd)
        if verified:
            self._native_window_style_applied = True
        return verified

    def _reapply_native_window_style_after_map(self, _event=None) -> None:
        """Verify the frame after Tk has displayed or remapped the toplevel.

        Tk may recreate or adjust native frame styles while mapping a window.
        The idle callback catches the initial startup race, while the Map
        binding below also protects the same visible HWND after a tray
        withdraw/deiconify cycle.  This remains independent of Configure
        handling: it never rewrites the style on every geometry event.
        """

        try:
            self.update_idletasks()
            hwnd = int(self.winfo_id())
            verified = _disable_native_resize_and_maximize(hwnd)
            if verified:
                self._native_window_style_applied = True
        except Exception as exc:
            logger.debug("post-map native window style verification skipped: %s", exc)

    def _schedule_native_window_style_reapply(self) -> None:
        """Schedule exactly one post-map style verification."""

        if self._native_window_style_reapply_scheduled:
            return
        self._native_window_style_reapply_scheduled = True
        try:
            self.bind("<Map>", self._reapply_native_window_style_after_map, add="+")
            self.after_idle(self._reapply_native_window_style_after_map)
        except Exception as exc:
            logger.debug("post-map native window style scheduling skipped: %s", exc)

    def _schedule_geometry_save(self, _event=None) -> None:
        if (
            _event is not None
            and not self._dock_dragging
            and self._dock_state not in ("collapsing", "expanding")
            and not self._dock_restore_blocked
        ):
            geometry = self._current_window_geometry()
            if geometry is not None:
                expected_event = self._configure_matches_expected_geometry(
                    geometry,
                    self._window_outer_rect(),
                )
                # Always consume the acknowledgement token.  Leaving a
                # mismatching token behind after a native move makes every
                # later Configure event look like the same old move and can
                # keep the native quiet timer alive forever.
                self._clear_expected_geometry()
                if not expected_event:
                    if not self._dock_native_interaction:
                        self._begin_native_titlebar_interaction(
                            self._last_observed_geometry or geometry,
                        )
                    else:
                        # A drag emits a stream of Configure events.  The
                        # quiet timer must follow the last one, not the first,
                        # or a still-moving native window can start docking.
                        self._arm_native_titlebar_quiet_timer(self._DOCK_NATIVE_QUIET_MS)
                self._last_observed_geometry = geometry
        self._observe_window_position()
        if self._geometry_restoring:
            return
        if (
            self._dock_state in ("collapsing", "expanding")
            or self._dock_dragging
            or self._dock_native_interaction
        ):
            return
        if self._geometry_save_job is not None:
            try:
                self.after_cancel(self._geometry_save_job)
            except Exception:
                pass
        self._geometry_save_job = self.after(350, self._save_window_geometry_now)

    def _init_window(self) -> None:
        self.title("AiTool")
        work_areas, primary_index = _get_windows_work_areas(self)
        self._work_areas = work_areas
        self._primary_work_area_index = primary_index
        restored = load_and_place_window_geometry(
            WINDOW_GEOMETRY_PATH,
            work_areas,
            primary_index=primary_index,
        )
        work_area = select_work_area(restored, work_areas, primary_index=primary_index)
        fixed_width = min(DEFAULT_WINDOW_WIDTH, work_area.width)
        restored = WindowGeometry(
            min(max(restored.x, work_area.left), work_area.right - fixed_width),
            restored.y,
            fixed_width,
            restored.height,
        )
        self.minsize(
            min(MIN_WINDOW_WIDTH, work_area.width),
            min(MIN_WINDOW_HEIGHT, work_area.height),
        )
        x_geometry = f"+{restored.x}" if restored.x >= 0 else str(restored.x)
        y_geometry = f"+{restored.y}" if restored.y >= 0 else str(restored.y)
        self.geometry(f"{restored.width}x{restored.height}{x_geometry}{y_geometry}")
        self.resizable(False, False)
        self._expanded_geometry = restored
        self.configure(fg_color=self._t("background"))
        self.attributes("-topmost", True)
        self._pinned = True
        self.overrideredirect(False)
        # ``super().__init__`` has created the Tk toplevel by this point.  Flush
        # pending window-manager work before querying its HWND, then update the
        # native style before binding Configure so FRAMECHANGED cannot look like
        # a user title-bar drag.
        try:
            self.update_idletasks()
        except Exception:
            pass
        self._apply_native_window_style_once()
        self._schedule_native_window_style_reapply()

        # 设置 Windows 任务栏和左上角的应用程序窗口图标，与托盘图标完美保持一致！
        try:
            from PIL import ImageTk
            app_icon_img = self._create_app_icon()
            self._app_icon_photo = ImageTk.PhotoImage(app_icon_img)
            self.iconphoto(True, self._app_icon_photo)
        except Exception:
            pass

        # 拦截关闭按钮：改为最小化到系统托盘
        self.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
        self.bind("<Configure>", self._schedule_geometry_save, add="+")
        self._tray_icon = None

        # 1. 默认并强力开启 Windows 开机自启动，确保出厂即常驻！
        self._setup_default_startup()

        # 2. 绑定全局系统热键 Alt + A 来显示/隐藏窗口 (默认开启，优雅常驻)
        self._setup_global_hotkey()

    def _setup_default_startup(self) -> None:
        """初次运行时自动将 AiTool 写入 Windows 开机自启动注册表，实现默认开启。"""
        try:
            import winreg
            import sys
            if getattr(sys, "frozen", False):
                app_path = sys.executable
            else:
                app_path = str(Path(__file__).resolve().parents[2] / "run_desktop_tool.py")

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
            )
            try:
                winreg.QueryValueEx(key, "AiTool")
            except FileNotFoundError:
                # 若检测不到自启动项，自动写入，默认开启
                winreg.SetValueEx(key, "AiTool", 0, winreg.REG_SZ, f'"{app_path}"')
            finally:
                winreg.CloseKey(key)
        except Exception:
            pass

    def _setup_global_hotkey(self) -> None:
        """在后台守护线程中注册全局系统热键 Alt + A，实现任何状态下一键呼出/隐藏主界面。"""
        try:
            import keyboard
            
            def _toggle_gui():
                # 收起只是顶部停靠状态，不等同于托盘隐藏。
                if self._tray_hidden or not self.winfo_viewable():
                    self.after(0, self._restore_from_tray)
                elif self._dock_state in ("collapsed", "collapsing", "expanding"):
                    self.after(0, self._request_dock_expand)
                else:
                    # 保留原有契约：正常可见时 Alt+A 进入托盘。
                    self.after(0, self._minimize_to_tray)

            # 在后台注册全局热键 Alt + A / alt+a (忽略大小写)
            keyboard.add_hotkey("alt+a", _toggle_gui, suppress=True)
        except Exception:
            pass

    def _get_startup_status(self) -> bool:
        """检查 Windows 注册表判定开机自启动是否已开启。"""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ
            )
            try:
                # 检查是否存在名为 AiTool 的项
                winreg.QueryValueEx(key, "AiTool")
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False

    def _toggle_startup(self, icon=None, item=None) -> None:
        """开启或关闭 Windows 开机自启动注册表项。"""
        import sys
        import winreg
        
        # 探测最合适的可执行文件路径：如果是打包后的 exe 运行，使用 sys.executable，否则用启动 py 脚本
        if getattr(sys, "frozen", False):
            app_path = sys.executable
        else:
            app_path = str(Path(__file__).resolve().parents[2] / "run_desktop_tool.py")

        current_status = self._get_startup_status()
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
            )
            if current_status:
                # 已经开启，现在点击则是关闭
                winreg.DeleteValue(key, "AiTool")
                self.after(0, lambda: self._toast("已关闭开机自启动", "warning"))
            else:
                # 未开启，现在开启
                winreg.SetValueEx(key, "AiTool", 0, winreg.REG_SZ, f'"{app_path}"')
                self.after(0, lambda: self._toast("已成功开启开机自启动！", "success"))
            winreg.CloseKey(key)
        except Exception as exc:
            self.after(0, lambda: self._toast(f"设置失败: {exc}", "danger"))

    def _show_settings_dialog(self, icon=None, item=None) -> None:
        """显示设置弹窗。为了保证在主窗口被隐藏（withdraw）时也能正常设置，在主线程中唤起设置弹窗。"""
        def _build_dialog():
            self._cancel_dock_jobs()
            self._tray_hidden = False
            self.deiconify()
            restored = self._expanded_geometry or self._current_window_geometry()
            if restored is not None:
                self._set_window_geometry(restored)
            self._dock_state = "free"
            self.attributes("-topmost", self._pinned)
            self.focus_force()

            dialog = ctk.CTkToplevel(self)
            dialog.title("设置中心")
            dialog.geometry("320x260") # 微调增高高度，为全局快捷键 Alt+A 标识提供排版空间
            dialog.resizable(False, False)
            dialog.configure(fg_color=self._t("background"))
            dialog.transient(self)
            dialog.grab_set()
            self._bind_dock_modal(dialog)

            ctk.CTkLabel(dialog, text="⚙️ AiTool 桌面工具 设置中心",
                         font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
                         text_color=self._t("focus")).pack(pady=(20, 16))

            # 开机自启动复选开关
            is_auto = self._get_startup_status()
            startup_var = ctk.BooleanVar(value=is_auto)

            def _on_switch_toggle():
                self._toggle_startup()
                # 刷新状态
                startup_var.set(self._get_startup_status())

            switch = ctk.CTkSwitch(dialog, text="开机自启动", variable=startup_var,
                                   command=_on_switch_toggle,
                                   font=ctk.CTkFont(family=FONT, size=11, weight="bold"),
                                   progress_color=self._t("primary"), text_color=self._t("secondary"))
            switch.pack(pady=8)

            ctk.CTkLabel(dialog, text="开启后，电脑开机时将自动运行 AiTool",
                         font=ctk.CTkFont(family=FONT, size=9),
                         text_color=self._t("muted")).pack(pady=(0, 12))

            # 增加全局快捷键的可视化展示
            hotkey_lbl = ctk.CTkLabel(dialog, text="全局唤醒/隐藏快捷键：Alt + A",
                                      font=ctk.CTkFont(family=FONT, size=11, weight="bold"),
                                      text_color=self._t("focus"))
            hotkey_lbl.pack(pady=4)

            ctk.CTkLabel(dialog, text="Alt + A：展开 AiTool；已展开时再次按下可最小化到托盘",
                         font=ctk.CTkFont(family=FONT, size=9),
                         text_color=self._t("muted")).pack(pady=(0, 16))

            ctk.CTkButton(dialog, text="关闭设置", corner_radius=6,
                          fg_color=self._t("hover"), hover_color=self._t("elevated"),
                          text_color=self._t("text"), font=ctk.CTkFont(family=FONT, size=11),
                          command=dialog.destroy).pack(fill="x", padx=40)

        self.after(0, _build_dialog)

    def _quit_from_tray(self) -> None:
        """在 Tk 主线程中完成托盘退出，避免从 pystray 线程触碰 Tk。"""
        self._cancel_dock_jobs()
        if self._dock_state == "free":
            self._remember_expanded_geometry(self._current_window_geometry())
        else:
            self._remember_expanded_geometry(self._expanded_geometry)
        self._save_window_geometry_now()

        tray_icon = self._tray_icon
        self._tray_icon = None
        if tray_icon is not None:
            try:
                tray_icon.stop()
            except Exception as exc:
                logger.debug("tray stop skipped during quit: %s", exc)

        self.quit()

    def _minimize_to_tray(self) -> None:
        """隐藏窗口并在系统托盘中生成一个精美的托盘图标。"""
        self._tray_hidden = True
        self._tray_restore_was_docked = self._dock_state in {
            "docked_expanded", "collapsing", "collapsed", "expanding",
        }
        self._cancel_dock_jobs()
        if self._tray_restore_was_docked:
            self._remember_expanded_geometry(self._expanded_geometry)
        else:
            self._remember_expanded_geometry(self._current_window_geometry())
        self._save_window_geometry_now()
        self.withdraw() # 隐藏主窗口
        self._ensure_tray_icon()

        self._toast("AiTool 已最小化到托盘常驻后台", "success")

    def _ensure_tray_icon(self) -> None:
        """创建并启动托盘图标；隐藏和恢复之间始终复用同一个图标。"""
        if self._tray_icon is not None:
            return

        # 如果托盘图标尚未启动，则在后台守护线程中初始化并启动它
        import pystray

        # 使用统一绘制的高颜值科技图标
        img = self._create_app_icon()

        def _show_app(icon, item):
            """从托盘菜单调度主窗口恢复，保留托盘图标。"""
            self.after(0, self._restore_from_tray)

        def _quit_app(icon, item):
            """彻底安全退出应用，清除托盘"""
            self.after(0, self._quit_from_tray)

        def _get_startup_menu_label(item):
            return "✓ 开机自启动" if self._get_startup_status() else "开机自启动"

        menu = pystray.Menu(
            pystray.MenuItem("打开 AiTool", _show_app, default=True), # 设为双击默认动作
            pystray.MenuItem("设置中心", self._show_settings_dialog),
            pystray.MenuItem(_get_startup_menu_label, self._toggle_startup),
            pystray.MenuItem("彻底退出", _quit_app)
        )

        self._tray_icon = pystray.Icon("AiTool", img, "AiTool 桌面工具", menu)

        # 使用 threading 启动托盘图标轮询监听，防止阻塞 Tkinter 的 mainloop 主线程！
        threading.Thread(target=self._tray_icon.run, daemon=True).start()


    def _restore_from_tray(self) -> None:
        """从托盘恢复窗口显示"""
        self._cancel_dock_jobs()
        self._dock_restore_blocked = True
        self._tray_hidden = False
        self.deiconify()
        self.attributes("-topmost", self._pinned)
        self.focus_force()
        restored = self._expanded_geometry or self._current_window_geometry()
        if restored is not None:
            self._set_window_geometry(restored)
        if self._tray_restore_was_docked:
            area = self._dock_area_for_geometry(restored)
            if area is not None:
                self._dock_work_area = area
                self._dock_state = "docked_expanded"
                self._hide_dock_handle()
                self._schedule_dock_autohide()
        else:
            self._dock_state = "free"
        self._tray_restore_was_docked = False
        self.after_idle(self._finish_tray_restore)

    def _finish_tray_restore(self) -> None:
        self._dock_restore_blocked = False
        if self._dock_state == "docked_expanded":
            self._schedule_dock_autohide()

    # ============================================================
    # UI 构建
    # ============================================================

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        import tkinter as tk
        self.content = ctk.CTkFrame(self, fg_color=self._t("background"), corner_radius=0)
        self.content.grid(row=0, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=0)
        self.content.grid_rowconfigure(1, weight=1)
        self.content.grid_rowconfigure(2, weight=0)
        self._register_dnd_target(self.content)

        self._build_station_area()
        self._build_card_area()
        self._build_height_resize_grip()
        self._build_statusbar()

        self.bind_all("<Control-v>", self._on_paste)
        self.bind("<Enter>", self._on_dock_enter, add="+")
        self.bind("<Leave>", self._on_dock_leave, add="+")

    def _build_height_resize_grip(self) -> None:
        """Build the internal, vertical-only height resize target."""

        self._height_resize_grip = ctk.CTkFrame(
            self.content,
            height=6,
            fg_color=self._t("surface"),
            border_width=1,
            border_color=self._t("border"),
            corner_radius=0,
            cursor="sb_v_double_arrow",
        )
        self._height_resize_grip.grid(row=2, column=0, sticky="ew")
        self._height_resize_grip.grid_propagate(False)
        self._height_resize_grip.bind("<Button-1>", self._on_height_grip_press, add="+")
        self._height_resize_grip.bind("<B1-Motion>", self._on_height_grip_motion, add="+")
        self._height_resize_grip.bind("<ButtonRelease-1>", self._on_height_grip_release, add="+")

    def _on_height_grip_press(self, event) -> None:
        """Start a height-only drag when normal free geometry owns the window."""

        if (
            self._dock_state != "free"
            or self._geometry_restoring
            or getattr(self, "_tray_hidden", False)
        ):
            return

        try:
            geometry = self._current_window_geometry()
            if geometry is None:
                return
            work_area = self._dock_area_for_geometry(geometry)
            if work_area is None:
                return
            self._cancel_dock_job("_dock_debounce_job")
            self._cancel_dock_job("_dock_autohide_job")
            self._cancel_geometry_save_job()
            self._height_resizing = True
            self._height_resize_origin = (
                int(event.x_root),
                int(event.y_root),
                geometry.x,
                geometry.y,
                geometry.height,
                work_area.height,
            )
        except Exception:
            # Tk can destroy or remap the grip between the button event and
            # this callback.  A failed press must never leave resize mode set.
            self._height_resizing = False
            self._height_resize_origin = None

    def _on_height_grip_motion(self, event) -> None:
        """Apply the pointer delta to height without persisting each frame."""

        if not self._height_resizing or self._height_resize_origin is None:
            return
        if (
            self._dock_state != "free"
            or self._geometry_restoring
            or getattr(self, "_tray_hidden", False)
        ):
            return

        try:
            _origin_x, origin_y, _start_x, _start_y, start_height, max_height = self._height_resize_origin
            geometry = self._current_window_geometry()
            if geometry is None:
                return
            work_area = self._dock_area_for_geometry(geometry)
            if work_area is None:
                return
            max_height = min(max_height, work_area.height)
            min_height = min(MIN_WINDOW_HEIGHT, max_height)
            height = min(
                max(start_height + int(event.y_root) - origin_y, min_height),
                max_height,
            )
            width = min(DEFAULT_WINDOW_WIDTH, work_area.width)
            target = WindowGeometry(geometry.x, geometry.y, width, height)
            # Keep Configure/save handling behind the existing acknowledgement
            # fence; only release schedules the disk write.
            self._set_window_geometry(target, write_geometry=False)
            self.geometry(self._geometry_to_string(target))
        except Exception:
            # Ignore Tkinter.TclError when the window is withdrawn or destroyed
            # while the pointer is still held.
            return

    def _on_height_grip_release(self, _event=None) -> None:
        """End a height drag and reuse the normal debounced geometry save."""

        if not self._height_resizing:
            return
        self._height_resizing = False
        self._height_resize_origin = None
        self._clear_expected_geometry()
        if (
            self._dock_state == "free"
            and not self._geometry_restoring
            and not getattr(self, "_tray_hidden", False)
        ):
            self._schedule_geometry_save()

    def _build_station_area(self) -> None:
        import tkinter as tk

        self.station_section = ctk.CTkFrame(self.content, fg_color=self._t("surface"), corner_radius=0)
        self.station_section.grid(row=0, column=0, sticky="nsew")
        self.station_section.configure(height=188)
        self.station_section.grid_propagate(False)
        self.station_section.grid_columnconfigure(0, weight=1)
        self.station_section.grid_rowconfigure(1, weight=1)

        self._register_dnd_target(self.station_section)

        header = ctk.CTkFrame(self.station_section, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=SPACING["md"], pady=(SPACING["sm"] + 2, SPACING["xs"]))
        header.grid_columnconfigure(1, weight=1)
        self._register_dnd_target(header)
        ctk.CTkLabel(header, text="中转站", font=ctk.CTkFont(family=FONT, size=FS["section_title"], weight="bold"),
                     text_color=self._t("secondary")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="拖入收藏 · 拖出复制 · 双击打开",
                     font=ctk.CTkFont(family=FONT, size=FS["status"] - 1), text_color=self._t("muted")).grid(row=0, column=1, sticky="e")

        self.btn_theme = ctk.CTkButton(
            header,
            text="☀ 亮色" if self.effective_theme == "dark" else "☾ 暗色",
            width=52,
            height=24,
            corner_radius=12,
            fg_color=self._t("hover"),
            hover_color=self._t("elevated"),
            text_color=self._t("secondary"),
            font=ctk.CTkFont(family=FONT, size=9),
            command=self._toggle_theme,
        )
        self.btn_theme.grid(row=0, column=2, padx=(SPACING["xs"], 0))

        self.btn_pin = ctk.CTkButton(header, text="📌", width=24, height=24, corner_radius=12,
                                     fg_color=self._t("hover"), hover_color=self._t("elevated"),
                                     text_color=self._t("pin_text"),
                                     font=ctk.CTkFont(family=FONT, size=11),
                                     command=self._toggle_pin)
        self.btn_pin.grid(row=0, column=3, padx=(SPACING["xs"] + 2, 0))
        self._register_dnd_recursive(header)

        self.station_scroll = ctk.CTkFrame(self.station_section, fg_color=self._t("surface"), corner_radius=0)
        self.station_scroll.grid(row=1, column=0, sticky="nsew", padx=(SPACING["sm"], 0), pady=(0, SPACING["sm"]))
        self.station_scroll.grid_columnconfigure(0, weight=1)
        self.station_scroll.grid_rowconfigure(0, weight=1)
        self._register_dnd_target(self.station_scroll)
        self._station_canvas = tk.Canvas(self.station_scroll, bg=self._t("surface"), highlightthickness=0, bd=0)
        self.station_scrollbar = ctk.CTkScrollbar(
            self.station_scroll, command=self._station_canvas.yview,
            fg_color=self._t("surface"), button_color=self._t("scrollbar"),
            button_hover_color=self._t("pressed"),
        )
        self._station_canvas.grid(row=0, column=0, sticky="nsew")
        self.station_scrollbar.grid(row=0, column=1, sticky="ns")
        self.station_scrollbar.grid_remove()
        self._station_item_host = ctk.CTkFrame(self._station_canvas, fg_color=self._t("surface"), corner_radius=0)
        self._station_item_host.grid_columnconfigure(0, weight=1)
        self._station_canvas_window = self._station_canvas.create_window((0, 0), window=self._station_item_host, anchor="nw")
        self._station_canvas.configure(yscrollcommand=self.station_scrollbar.set)
        self._station_item_host.bind(
            "<Configure>",
            lambda e: (
                self._station_canvas.configure(scrollregion=self._station_canvas.bbox("all")),
                self.after_idle(lambda: self._sync_scrollbar_visibility(self._station_canvas, self.station_scrollbar)),
            ),
        )
        self._station_canvas.bind(
            "<Configure>",
            lambda e: (
                self._station_canvas.itemconfigure(self._station_canvas_window, width=e.width),
                self.after_idle(lambda: self._sync_scrollbar_visibility(self._station_canvas, self.station_scrollbar)),
            ),
        )
        self._station_canvas.bind("<MouseWheel>", self._on_station_mousewheel)
        self._station_item_host.bind("<MouseWheel>", self._on_station_mousewheel)
        self.station_frame = self._station_item_host

        self.station_empty_label = ctk.CTkLabel(
            self._station_item_host, text="拖入文件或文件夹",
            font=ctk.CTkFont(family=FONT, size=FS["station_name"]), text_color=self._t("muted"))
        self.station_empty_label.pack(expand=True, pady=SPACING["sm"])

        self._register_dnd_target(self._station_canvas)
        self._register_dnd_target(self._station_item_host)
        self._register_dnd_recursive(self.station_scroll)
        self.after_idle(lambda: self._sync_scrollbar_visibility(self._station_canvas, self.station_scrollbar))

    def _build_card_area(self) -> None:
        import tkinter as tk

        self.actions_scroll = ctk.CTkFrame(self.content, fg_color=self._t("background"), corner_radius=0)
        self.actions_scroll.grid(row=1, column=0, sticky="nsew")
        self.actions_scroll.grid_columnconfigure(0, weight=1)
        self.actions_scroll.grid_rowconfigure(0, weight=1)
        self._register_dnd_target(self.actions_scroll)
        self._actions_canvas = tk.Canvas(self.actions_scroll, bg=self._t("canvas"), highlightthickness=0, bd=0)
        self.actions_scrollbar = ctk.CTkScrollbar(
            self.actions_scroll, command=self._actions_canvas.yview,
            fg_color=self._t("background"), button_color=self._t("scrollbar"),
            button_hover_color=self._t("pressed"),
        )
        self._actions_canvas.grid(row=0, column=0, sticky="nsew")
        self.actions_scrollbar.grid(row=0, column=1, sticky="ns")
        self.actions_scrollbar.grid_remove()
        self._action_item_host = ctk.CTkFrame(self._actions_canvas, fg_color=self._t("background"), corner_radius=0)
        self._action_item_host.grid_columnconfigure(0, weight=1)
        self._actions_canvas_window = self._actions_canvas.create_window((0, 0), window=self._action_item_host, anchor="nw")
        self._actions_canvas.configure(yscrollcommand=self.actions_scrollbar.set)
        self._action_item_host.bind(
            "<Configure>",
            lambda e: (
                self._actions_canvas.configure(scrollregion=self._actions_canvas.bbox("all")),
                self.after_idle(lambda: self._sync_scrollbar_visibility(self._actions_canvas, self.actions_scrollbar)),
            ),
        )
        self._actions_canvas.bind(
            "<Configure>",
            lambda e: (
                self._actions_canvas.itemconfigure(self._actions_canvas_window, width=e.width),
                self.after_idle(lambda: self._sync_scrollbar_visibility(self._actions_canvas, self.actions_scrollbar)),
            ),
        )
        self._actions_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._action_item_host.bind("<MouseWheel>", self._on_mousewheel)
        self.card_scroll = self.actions_scroll

        self._register_dnd_target(self._actions_canvas)
        self._register_dnd_target(self._action_item_host)
        self._register_dnd_recursive(self.actions_scroll)
        self.after_idle(lambda: self._sync_scrollbar_visibility(self._actions_canvas, self.actions_scrollbar))

    def _sync_scrollbar_visibility(self, canvas, scrollbar) -> None:
        """Show a scrollbar only when its content exceeds the canvas viewport."""

        import tkinter as tk

        try:
            viewport_height = canvas.winfo_height()
            if viewport_height <= 1:
                return

            bounds = canvas.bbox("all")
            content_height = 0 if bounds is None else bounds[3] - bounds[1]
            if content_height <= viewport_height:
                canvas.yview_moveto(0)
                scrollbar.grid_remove()
            else:
                scrollbar.grid(row=0, column=1, sticky="ns")
        except tk.TclError:
            # Tk may destroy a just-refreshed item while an idle callback runs.
            return

    def _build_statusbar(self) -> None:
        import tkinter as tk

        self.statusbar = ctk.CTkFrame(self, fg_color=self._t("surface"), height=30, corner_radius=0)
        self.statusbar.grid(row=1, column=0, sticky="ew")
        self.statusbar.grid_propagate(False)
        self._register_dnd_target(self.statusbar)

        self.status_dot = ctk.CTkLabel(self.statusbar, text="●", width=20,
                                       text_color=self._t("success"),
                                       font=ctk.CTkFont(family=FONT, size=9))
        self.status_dot.grid(row=0, column=0, padx=(SPACING["md"], SPACING["xs"]))

        self.status_label = ctk.CTkLabel(self.statusbar, text="就绪，拖动至桌面上边缘可隐藏", font=ctk.CTkFont(family=FONT, size=FS["status"]),
                                         text_color=self._t("secondary"))
        self.status_label.grid(row=0, column=1, sticky="w")
        self._register_dnd_recursive(self.statusbar)

        # The handle remains in the fixed statusbar and outside both scrolling
        # hosts.  It is only placed over the statusbar while the window is
        # collapsed, so the root -> content/statusbar contract stays intact.
        self._dock_handle = ctk.CTkFrame(
            self.statusbar,
            fg_color=self._t("surface"),
            border_width=1,
            border_color=self._t("border"),
            corner_radius=0,
        )
        self._dock_handle.grid_columnconfigure(0, weight=1)
        self._dock_handle.grid_rowconfigure(0, weight=1)
        self._dock_handle_label = tk.Canvas(
            self._dock_handle,
            bg=self._t("surface"),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._dock_handle_label.grid(row=0, column=0, sticky="nsew")
        self._dock_handle_label.bind("<Configure>", self._draw_dock_handle_icon, add="+")
        self._draw_dock_handle_icon()

        for widget in (self._dock_handle, self._dock_handle_label):
            widget.bind("<Enter>", self._on_dock_handle_enter, add="+")
            widget.bind("<Leave>", self._on_dock_handle_leave, add="+")
            widget.bind("<ButtonPress-1>", self._on_dock_handle_press, add="+")
            widget.bind("<B1-Motion>", self._on_dock_handle_motion, add="+")
            widget.bind("<ButtonRelease-1>", self._on_dock_handle_release, add="+")

    def _draw_dock_handle_icon(self, _event=None) -> None:
        """Draw the centered three-line grip on the collapsed dock handle."""

        canvas = getattr(self, "_dock_handle_label", None)
        if canvas is None:
            return

        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        center_x = width / 2
        center_y = height / 2
        icon_center_y = center_y + 2
        left_x = center_x - 14
        right_x = center_x + 14

        canvas.delete("dock_handle_icon")
        canvas.create_line(
            left_x,
            icon_center_y - 3,
            right_x,
            icon_center_y - 3,
            fill=self._t("secondary"),
            width=1,
            capstyle="round",
            tags="dock_handle_icon",
        )
        canvas.create_line(
            left_x,
            icon_center_y,
            right_x,
            icon_center_y,
            fill=self._t("secondary"),
            width=1,
            capstyle="round",
            tags="dock_handle_icon",
        )
        canvas.create_line(
            left_x,
            icon_center_y + 3,
            right_x,
            icon_center_y + 3,
            fill=self._t("secondary"),
            width=1,
            capstyle="round",
            tags="dock_handle_icon",
        )

    # ============================================================
    # 数据刷新
    # ============================================================

    def _refresh_all(self) -> None:
        self._refresh_station()
        self._refresh_cards()
        # 第一次启动时自动静默检测，并弹出使用说明
        self.after(500, self._show_user_guide)

    def _refresh_station(self) -> None:
        for w in tuple(self._station_item_host.winfo_children()):
            w.destroy()

        if not self.entries:
            self.station_empty_label = ctk.CTkLabel(
                self.station_frame, text="拖入文件或文件夹",
                font=ctk.CTkFont(family=FONT, size=FS["status"]), text_color=self._t("muted"))
            self.station_empty_label.pack(expand=True, pady=SPACING["sm"])
            self._register_dnd_recursive(self.station_frame)
            self.after_idle(lambda: self._sync_scrollbar_visibility(self._station_canvas, self.station_scrollbar))
            return

        for entry in self.entries:
            self._create_station_item(entry)
        self._register_dnd_recursive(self.station_frame)
        self.after_idle(lambda: self._sync_scrollbar_visibility(self._station_canvas, self.station_scrollbar))

    def _create_station_item(self, entry: StationEntry) -> None:
        import tkinter as tk
        p = Path(entry.path)
        exists = p.exists()

        # 仿 Windows 经典资源管理器：极简无框容器
        item = ctk.CTkFrame(self.station_frame, fg_color="transparent",
                             corner_radius=4, border_width=0)
        item.pack(fill="x", padx=SPACING["xs"], pady=1)
        
        item.grid_columnconfigure(0, minsize=SPACING["icon_col"], weight=0)
        item.grid_columnconfigure(1, weight=1)
        item.grid_columnconfigure(2, minsize=32, weight=0) # 预留删除按钮绝对物理列

        icon_img = WindowsIconCache.get_system_icon_image(entry.path, entry.kind == "folder")
        
        icon_label = tk.Label(item, bg=self._t("surface"))
        if isinstance(icon_img, ImageTk.PhotoImage):
            icon_label.configure(image=icon_img)
            icon_label.image = icon_img
        else:
            icon_label.configure(text=str(icon_img), font=(FONT, 14), fg=self._t("text"))
            
        icon_label.grid(row=0, column=0, sticky="", pady=3)

        name_text = entry.display_name
        if not exists:
            name_text += " (失效)"
        name_fg = self._t("text") if exists else self._t("muted")
        
        name_label = tk.Label(item, text=name_text,
                              font=(FONT, FS["station_name"]),
                              bg=self._t("surface"), fg=name_fg, anchor="w")
        name_label.grid(row=0, column=1, sticky="ew", padx=2, pady=3)

        # 1. 【中转站删除闪烁与点击痛点完美解决！】
        # - 痛点：以前用 grid_forget + grid 动态显隐，会造成剧烈的闪烁位移。
        # - 解决方案：固定使用 column=2 绝对物理预留列，并且通过配置文字前景色（text_color）和卡片背景完美咬合。
        # - 默认状态下：将前景色 text_color 设为和行背景一模一样的卡片色（self._t("surface")），从而达到无形显隐的效果，绝不抖动闪变！
        # - 鼠标移入行时：立刻将 text_color 变为明显的红色/灰色前景色！
        btn = ctk.CTkButton(item, text="✕", width=22, height=22, corner_radius=11,
                            fg_color="transparent", hover_color=self._t("danger"),
                            text_color=self._t("surface"), # 改用底板背景色替代 "transparent" 关键字，彻底消除 CTk 内部 ValueError
                            font=ctk.CTkFont(family=FONT, size=9, weight="bold"),
                            command=lambda e=entry: self._remove_entry(e))
        # 物理位置固定，拒绝抖动，符合 Tkinter 标准 grid 属性
        btn.grid(row=0, column=2, padx=(2, SPACING["xs"]), pady=2, sticky="")

        def on_enter(e):
            item.configure(fg_color=self._t("hover"))
            for w in (icon_label, name_label):
                w.configure(bg=self._t("hover"))
            btn.configure(text_color=self._t("secondary"), fg_color="transparent") # hover 时醒目亮起
            # 用不显眼的暗灰色字体在下方状态栏显示该文件的完整物理路径
            self._set_status(entry.path, "muted")

        def on_leave(e):
            # 获取鼠标当前坐标，防止因鼠标落在子 Label 上产生的虚假 leave 触发闪烁
            # 只有鼠标真正完全离开 item 的物理矩形范围时才熄灭按钮
            x, y = item.winfo_pointerxy()
            rx0 = item.winfo_rootx()
            ry0 = item.winfo_rooty()
            rx1 = rx0 + item.winfo_width()
            ry1 = ry0 + item.winfo_height()
            if not (rx0 <= x <= rx1 and ry0 <= y <= ry1):
                item.configure(fg_color="transparent")
                for w in (icon_label, name_label):
                    w.configure(bg=self._t("surface"))
                btn.configure(text_color=self._t("surface"), fg_color="transparent") # 完美熄灭且绝不位移抖动
                # 恢复经典“就绪”状态
                self._set_status("就绪", "ready")

        item.bind("<Enter>", on_enter)
        item.bind("<Leave>", on_leave)
        for w in (name_label, icon_label):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

        # 确保鼠标经过删除按钮本身时，行的高亮依然能够完美保留不闪烁
        btn.bind("<Enter>", lambda e: on_enter(None))
        btn.bind("<Leave>", lambda e: on_leave(None))

        for w in (item, name_label, icon_label):
            w.bind("<Double-Button-1>", lambda e, ent=entry: self._open_entry(ent))
            w.bind("<Button-3>", lambda e, ent=entry: self._open_entry_folder(ent)) # 鼠标右键（Button-3）点击时自动打开所在文件夹并选中

        self._bind_mousewheel_recursive(item, self._on_station_mousewheel)

        for w in (name_label, icon_label):
            try:
                w.drag_source_register(1, DND_FILES)
                w.dnd_bind("<<DragInitCmd>>", lambda e, ent=entry: self._on_station_drag_out(ent))
                w.dnd_bind("<<DragEndCmd>>", lambda e: self._on_station_drag_end())
                _record_dnd_registration("source", w, True)
            except Exception as exc:
                _record_dnd_registration("source", w, False, exc)

    def _refresh_cards(self) -> None:
        for w in tuple(self._action_item_host.winfo_children()):
            w.destroy()

        header = ctk.CTkFrame(self._action_item_host, fg_color="transparent")
        header.pack(fill="x", padx=SPACING["md"], pady=(SPACING["sm"], SPACING["xs"]))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text="快捷动作", font=ctk.CTkFont(family=FONT, size=FS["section_title"], weight="bold"),
                     text_color=self._t("secondary")).grid(row=0, column=0, sticky="w")

        self.btn_add = ctk.CTkButton(header, text="➕", width=24, height=24, corner_radius=12,
                                     fg_color=self._t("add_button"), hover_color=self._t("add_button_hover"),
                                     text_color=self._t("add_button_text"), font=ctk.CTkFont(family=FONT, size=9),
                                     command=self._show_add_menu)
        self.btn_add.grid(row=0, column=2, padx=(SPACING["xs"], 0))

        cards = self._get_all_cards()

        if not cards:
            ctk.CTkLabel(self._action_item_host, text="暂无动作",
                          font=ctk.CTkFont(family=FONT, size=FS["status"]),
                          text_color=self._t("muted")).pack(pady=20)
        else:
            for card in cards:
                self._create_card(card)

        # 4. 在界面最下面加一行温馨高逼格小字：“一切都可以拖进来！”
        # - 它会作为卡片容器的收尾元素，优雅居中悬浮在最下方，文字配色选用温柔的 muted 暗灰色
        footer = ctk.CTkFrame(self._action_item_host, fg_color="transparent")
        footer.pack(fill="x", side="bottom", pady=(24, 16))
        
        lbl_tip = ctk.CTkLabel(footer, text="✨ 一切都可以拖进来！",
                              font=ctk.CTkFont(family=FONT, size=FS["card_desc"] + 1, slant="italic"),
                              text_color=self._t("muted"), cursor="hand2")
        lbl_tip.pack(anchor="center")
        lbl_tip.bind("<MouseWheel>", self._on_mousewheel)

        # 绑定手动点击触发“使用说明”弹窗，提供详细极客教程
        lbl_tip.bind("<Button-1>", lambda event: self._show_user_guide(manual=True))

        self._register_dnd_recursive(self._action_item_host)
        self.after_idle(lambda: self._sync_scrollbar_visibility(self._actions_canvas, self.actions_scrollbar))

    def _get_all_cards(self) -> list[dict]:
        cards = []
        for qa in self.quick_actions:
            action_type = qa.get("module_type", qa["type"])
            cards.append({
                "id": qa["id"],
                "type": qa["type"],
                "group": "quick",
                "title": qa["title"],
                "desc": qa["desc"],
                "params": dict(qa.get("params", {})),
                "need_confirm": action_type == "folder-copy",
                "action_type": action_type,
            })
        for m in self.custom_modules:
            type_label = MODULE_TYPE_LABELS.get(m.module_type, m.module_type)
            params_str = "; ".join(f"{k}={v}" for k, v in m.params.items())
            cards.append({
                "id": m.module_id,
                "type": m.module_type,
                "group": "module",
                "title": m.name,
                "desc": f"{type_label} · {params_str}" if params_str else type_label,
                "params": dict(m.params),
                "need_confirm": m.module_type == "folder-copy",
                "action_type": m.module_type,
            })
        return cards

    def _create_card(self, card: dict) -> None:
        # 重构：精巧的极简无背景板悬浮卡片式设计
        frame = ctk.CTkFrame(self._action_item_host, fg_color=self._t("card"), bg_color="transparent", corner_radius=10,
                             border_width=1, border_color=self._t("border"))
        frame.pack(fill="x", padx=SPACING["sm"], pady=SPACING["xs"])
        
        frame.grid_columnconfigure(0, minsize=SPACING["icon_col"], weight=0)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(2, minsize=40, weight=0) # 稍微拓宽编辑区列宽，预留编辑箭头呼吸位
        frame.grid_rowconfigure(0, weight=1)

        import tkinter as tk
        icon_text = ACTION_ICON_GLYPHS.get(card["type"], "🧩")
        action_colors = self._tokens["action_icon_by_kind"]
        icon_color = action_colors.get(card.get("action_type", card["type"]), self._t("action_icon"))
        
        # 2 & 3. 【彻底消除突兀的背景板，并解决卡片图标垂直偏斜问题】
        # - 痛点：以前有一个突兀的深灰色 elevated 背景板，视觉被生硬地割裂了，且 Emoji 在框里无法完美上下居中。
        # - 解决方案：我们废除生硬的 elevated 图标框！将图标背景色直接和卡片底板 `self._t("card")` 设为 100% 相同！
        # - 图标直接作为精美独立的气氛组件，在 `52px` 绝对对齐格中完全居中对齐，浑然一体，绝不突兀！
        icon_label = tk.Label(frame, text=icon_text,
                               bg=self._t("card"), fg=icon_color,
                               font=(FONT, 18), anchor="center") # 放大动作图标字号到 18pt
        icon_label.grid(row=0, column=0, sticky="nsew", pady=SPACING["card_pady"])

        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.grid(row=0, column=1, sticky="ew", padx=(4, 4), pady=SPACING["card_pady"])
        body.grid_columnconfigure(0, weight=1)

        title_lbl = tk.Label(body, text=card["title"],
                             font=(FONT, FS["card_title"], "bold"),
                             bg=self._t("card"), fg=self._t("text"), anchor="w")
        title_lbl.grid(row=0, column=0, sticky="w")
        
        desc_lbl = tk.Label(body, text=card.get("desc", ""),
                             font=(FONT, FS["card_desc"]),
                             bg=self._t("card"), fg=self._t("muted"), anchor="w")
        desc_lbl.grid(row=1, column=0, sticky="w")

        # 2. 【编辑箭头重构：消除突兀背景，箭头放大，极度精致】
        # - 痛点：以前的箭头非常渺小，且带一个有色差的背景按钮框，极其难看。
        # - 重构方案：我们使用 ctk.CTkButton，但将其背景、前景色彻底设为透明。
        # - 通过将 text 改为极具指向感的经典 Windows 右方向箭头 `">"`，字号直接拉到 `16pt bold`。
        # - 将其 `hover_color` 修改为比底板稍微亮一点的高级 hover 色，只有在鼠标放上去时，才呈现出微弱、高级的圆圈气泡效果！
        edit_btn = ctk.CTkButton(frame, text=">", width=24, height=24, corner_radius=12, # 完美的 24x24 正圆形按钮
                                 fg_color="transparent", hover_color=self._t("hover"),
                                 bg_color=self._t("card"),
                                 text_color=self._t("secondary"),
                                 font=ctk.CTkFont(family=FONT_MONO, size=15, weight="bold"), # 采用等宽 Consolas 完美对齐
                                 command=lambda c=card: self._edit_card(c))

        # 为卡片中所有的 Widget 递归绑定滚轮事件
        def _propagate_mousewheel(widget):
            widget.bind("<MouseWheel>", self._on_mousewheel)
            for child in widget.winfo_children():
                _propagate_mousewheel(child)

        _propagate_mousewheel(frame)
        edit_btn.grid(row=0, column=2, padx=(0, SPACING["sm"]), sticky="") # 严格垂直绝对居中

        # 点击卡片执行
        def on_click(e, c=card):
            self._execute_card(c)

        frame.bind("<Button-1>", on_click)
        for child in (title_lbl, desc_lbl):
            child.bind("<Button-1>", on_click)
        body.bind("<Button-1>", on_click)
        icon_label.bind("<Button-1>", on_click)

    # ============================================================
    # 全局拖放
    # ============================================================

    def _register_dnd_target(self, widget) -> None:
        """显式注册一个稳定 DND 容器，并把结果写入诊断快照。"""
        try:
            if widget in self._dnd_target_widgets:
                return
        except TypeError:
            # Tk widgets are weak-referenceable in normal operation.  Keep a
            # direct registration path for a minimal/headless sentinel.
            pass
        try:
            widget.drop_target_register(DND_FILES, DND_TEXT)
            widget.dnd_bind("<<Drop>>", self._on_global_drop)
            widget.dnd_bind("<<DragEnter>>", self._on_global_drag_enter)
            widget.dnd_bind("<<DragLeave>>", self._on_global_drag_leave)
            try:
                self._dnd_target_widgets.add(widget)
            except TypeError:
                pass
            _record_dnd_registration("target", widget, True)
        except Exception as exc:
            _record_dnd_registration("target", widget, False, exc)

    def _register_dnd_recursive(self, widget, _generation_started: bool = False) -> None:
        """递归给 widget 及其所有子组件注册 DND_FILES + DND_TEXT 拖放事件。

        TkinterDnD 的事件不会向父容器冒泡，只有鼠标直接悬停的 widget 才能接收 drop。
        所以每次动态创建/销毁子 widget 后，必须重新注册才能保证全界面都能接收网址拖拽。
        """
        if not _generation_started:
            _DND_DIAGNOSTICS["generation"] += 1
        self._register_dnd_target(widget)
        for child in widget.winfo_children():
            self._register_dnd_recursive(child, _generation_started=True)

    def _on_global_drag_enter(self, event) -> None:
        if not self._dock_drop_active:
            self._dock_drop_active = True
            self._dock_pause()
        self._set_status("拖入文件...", "warning")

    def _on_global_drag_leave(self, event) -> None:
        if self._dock_drop_active:
            self._dock_drop_active = False
            self._dock_resume()
        self._set_status("就绪", "ready")

    def _on_paste(self, event=None) -> None:
        """Ctrl+V 粘贴：读取剪贴板内容，智能识别网址或文件路径并添加模块。"""
        try:
            raw_data = self.clipboard_get().strip()
        except Exception:
            return
        if not raw_data:
            return
        if self._dock_state in ("collapsed", "collapsing"):
            self._request_dock_expand()
        self._set_status("粘贴添加...", "warning")
        self._process_input_data(raw_data, paths_source=None)

    def _on_global_drop(self, event) -> None:
        try:
            raw_data = str(event.data).strip()
            paths_source = event.data
            self._process_input_data(raw_data, paths_source)
        except Exception:
            logger.exception("_on_global_drop failed")
        finally:
            if self._dock_drop_active:
                self._dock_drop_active = False
                self._dock_resume()
            if self._dock_state in ("collapsed", "collapsing"):
                self._request_dock_expand()

    def _process_input_data(self, raw_data: str, paths_source=None) -> None:
        """智能识别并添加模块/收藏。拖拽和粘贴共用此逻辑。

        raw_data: 原始文本数据
        paths_source: 拖拽时的 event.data（用于 tk.splitlist 解析文件路径），粘贴时为 None
        """
        splitlist = self.tk.splitlist if paths_source is not None else None
        result = parse_input(raw_data, paths_source, splitlist=splitlist)
        if result is None:
            return

        if result.modules:
            self.custom_modules.extend(result.modules)
            self.module_storage.save(self.custom_modules)
            self._refresh_cards()
            names = [m.name for m in result.modules]
            self._toast(f"已自动生成模块: {', '.join(names)}", "success")

        if result.station_paths:
            station_state = self.station_storage.current_state
            sort_mode = station_state.sort_mode
            custom_order = list(station_state.custom_order)
            next_entries, added_s, skipped = collect_station_entries(
                result.station_paths,
                self.entries,
                sort_mode=sort_mode,
                custom_order=custom_order,
            )
            if sort_mode == "custom":
                # collect_station_entries already places unlisted entries at
                # the end. Persist their keys there too, so later refreshes
                # retain that position (including after remove and re-add).
                # Keep an intentionally empty order empty; an established
                # custom order is updated to the displayed sequence so a new
                # entry is persisted at its end.
                if custom_order:
                    custom_order = [normalize_path_key(entry.path) for entry in next_entries]
            self.station_storage.save_state(
                next_entries,
                sort_mode=sort_mode,
                custom_order=custom_order,
            )
            self.entries = next_entries
            self._refresh_station()
            if added_s:
                self._toast(f"已收藏到中转站: {', '.join(added_s)}", "success")

        self._set_status("就绪", "ready")

    def _on_station_drag_out(self, entry: StationEntry):
        """从中转站拖出文件到系统资源管理器。"""
        self._dock_drop_active = True
        self._dock_pause()
        from tkinterdnd2 import COPY
        tcl_path = "{" + entry.path + "}"
        return (COPY, DND_FILES, tcl_path)

    def _on_station_drag_end(self) -> None:
        if not self._dock_drop_active:
            return
        self._dock_drop_active = False
        self._dock_resume()

    # ============================================================
    # 中转站操作
    # ============================================================

    def _open_entry_folder(self, entry: StationEntry) -> None:
        """右键点击中转站文件项时，自动打开其所在文件夹，并定位/选中该文件。"""
        p = Path(entry.path)
        if not p.exists():
            # 即使文件本身不存在了，但如果父目录存在，也可以尝试打开父目录
            if p.parent.exists():
                folder_path = p.parent
            else:
                self._dock_pause()
                try:
                    messagebox.showwarning("入口失效", "所选路径及其所在文件夹均已不存在。", parent=self)
                finally:
                    self._dock_resume()
                return
        else:
            folder_path = p.parent

        import subprocess
        if os.name == "nt":
            # Windows 特有方式：在文件资源管理器中打开文件夹并选中该文件
            try:
                if p.exists():
                    subprocess.run(["explorer", "/select,", str(p.resolve())], check=False)
                else:
                    subprocess.run(["explorer", str(folder_path.resolve())], check=False)
                self._set_status(f"已打开文件夹: {folder_path.name}", "ready")
            except Exception as e:
                self._toast(f"打开文件夹失败: {e}", "danger")
        else:
            # 兼容其他系统
            if hasattr(os, "startfile"):
                os.startfile(str(folder_path))
            else:
                subprocess.run(["open", str(folder_path)])

    def _open_entry(self, entry: StationEntry) -> None:
        p = Path(entry.path)
        if not p.exists():
            self._dock_pause()
            try:
                messagebox.showwarning("入口失效", "所选入口已不存在。", parent=self)
            finally:
                self._dock_resume()
            return
        if hasattr(os, "startfile"):
            os.startfile(str(p))
            self._set_status(f"已打开: {p.name}", "ready")

    def _remove_entry(self, entry: StationEntry) -> None:
        station_state = self.station_storage.current_state
        next_entries, custom_order = remove_station_entry(
            self.entries,
            entry.path,
            station_state.custom_order,
        )
        self.station_storage.save_state(
            next_entries,
            sort_mode=station_state.sort_mode,
            custom_order=custom_order,
        )
        self.entries = next_entries
        self._refresh_station()
        self._toast("已移除", "success")

    def _copy_entry_to(self, entry: StationEntry) -> None:
        self._dock_pause()
        try:
            target = filedialog.askdirectory(title="选择导出目录", parent=self)
        finally:
            self._dock_resume()
        if not target:
            return
        ok, message = copy_station_entry_to_directory(entry, Path(target))
        if ok:
            self._toast(message, "success")
        else:
            self._toast(message, "warning")

    # ============================================================
    # 动作执行
    # ============================================================

    def _execute_card(self, card: dict) -> None:
        if card.get("need_confirm"):
            self._dock_pause()
            try:
                confirmed = messagebox.askyesno("确认执行", f"{card['title']}\n\n确认执行？", parent=self)
            finally:
                self._dock_resume()
            if not confirmed:
                self._set_status("已取消", "ready")
                return

        action_type = card["action_type"]
        params = card.get("params", {})

        # 5. 对于高频重度的“文件夹覆盖复制 (folder-copy)”，采用无缝的 进度条+动态状态文本 混合弹窗提示！
        # - 痛点：文件拷贝属于重度磁盘 I/O 阻塞任务，如果静默在后台跑，用户会觉得“卡死”或“根本没反应”。
        # - 解决方案：我们弹出一个非阻塞的、带有动态旋转进度条和执行状态文本的现代 HUD 面板。
        if action_type == "folder-copy":
            self._dock_pause()
            hud = ctk.CTkToplevel(self)
            hud.title("正在同步复制")
            hud.geometry("320x150")
            hud.resizable(False, False)
            hud.configure(fg_color=self._t("background"))
            hud.transient(self)
            hud.grab_set()
            self._bind_dock_modal(hud)

            # 居中子标签
            ctk.CTkLabel(hud, text="📂 正在同步覆盖目标文件...",
                         font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
                         text_color=self._t("text")).pack(pady=(16, 8))

            # 循环进度条
            progress = ctk.CTkProgressBar(hud, width=260, height=8,
                                          fg_color=self._t("surface"), progress_color=self._t("primary"))
            progress.pack(pady=8)
            progress.configure(mode="indetermined")
            progress.start()

            status_lbl = ctk.CTkLabel(hud, text="准备执行 I/O 通道同步...",
                                      font=ctk.CTkFont(family=FONT, size=11),
                                      text_color=self._t("muted"))
            status_lbl.pack(pady=(4, 16))

            def _run_with_hud():
                # 模拟/轮询进度文字变动
                def _update_status(txt):
                    hud.after(0, lambda: status_lbl.configure(text=txt))

                _update_status("开始验证路径可用性...")
                # 执行
                review = self._do_execute(action_type, params)
                _update_status("磁盘写入成功，正在校验完整性...")
                
                # 销毁 HUD 并弹出令人放心的原生 Success/Error 弹窗
                def _done():
                    progress.stop()
                    hud.destroy()
                    self._dock_pause()
                    try:
                        if review["status"] == "ready":
                            messagebox.showinfo("同步成功", f"🎉 {card['title']} 执行成功！\n\n- 状态: 已完成\n- 详情: {review['summary']}", parent=self)
                        else:
                            messagebox.showerror("同步失败", f"❌ {card['title']} 执行失败！\n\n- 失败原因: {review['summary']}", parent=self)
                    finally:
                        self._dock_resume()
                    self._on_execute_done(card["title"], review)

                hud.after(1000, _done)

            threading.Thread(target=_run_with_hud, daemon=True).start()
            return

        self._set_status(f"正在执行: {card['title']}...", "warning")
        self._dock_pause()
        self.update_idletasks()

        def _run():
            review = self._do_execute(action_type, params)
            self.after(0, lambda: self._on_execute_done(card["title"], review))

        threading.Thread(target=_run, daemon=True).start()

    def _do_execute(self, action_type: str, params: dict) -> dict:
        if action_type == "folder-copy":
            source = params.get("source", "")
            target = params.get("target", "")
            source2 = params.get("source2", "")
            target2 = params.get("target2", "")
            review = execute_folder_copy(
                Path(source) if source else None,
                Path(target) if target else None,
                Path(source2) if source2 else None,
                Path(target2) if target2 else None,
            )
        elif action_type == "launch-bat":
            script = params.get("script", "")
            review = launch_bat_script(Path(script) if script else None)
        elif action_type == "update-svn":
            workspace = params.get("workspace", "")
            review = execute_svn_update(Path(workspace) if workspace else None)
        elif action_type == "commit-svn":
            workspace = params.get("workspace", "")
            message = params.get("message", "")
            review = execute_svn_commit(Path(workspace) if workspace else None, message)
        elif action_type == "open-web":
            url = params.get("url", "")
            review = execute_open_web(url)
        elif action_type == "app-launch":
            app_path = params.get("app_path", "")
            work_dir = params.get("work_dir", "")
            args = params.get("args", "")
            review = execute_app_launch(Path(app_path) if app_path else None, work_dir, args)
        else:
            review = ActionReview("unknown", "blocked", "execute", f"未知动作: {action_type}", [])
        return _review_to_dict(review)

    def _on_execute_done(self, title: str, review: dict) -> None:
        level = "success" if review["status"] == "ready" else "danger"
        self._toast(review["summary"], level)
        self._set_status(review["summary"], review["status"])
        self._dock_resume()

    # ============================================================
    # 动作配置对话框核心渲染函数（抽离出的公用组件）
    # ============================================================
    def _render_config_fields(self, container: ctk.CTkFrame, module_type: str, initial_params: dict) -> dict[str, ctk.StringVar]:
        """根据模块类型生成完全直观、带独立“选择”文件/目录按钮的动态表单，废除原文本框。"""
        for w in container.winfo_children():
            w.destroy()

        container.grid_columnconfigure(0, weight=1)
        param_vars = {}

        if module_type == "folder-copy":
            fields = [
                {"key": "source", "label": "源路径 1", "desc": "配置文件的 autocode", "browse": "folder"},
                {"key": "target", "label": "目标路径 1", "desc": "共享文件夹", "browse": "folder"},
                {"key": "source2", "label": "源路径 2 (可选)", "desc": "配置文件的 LuaFile", "browse": "folder"},
                {"key": "target2", "label": "目标路径 2 (可选)", "desc": "Unity 的 Data 路径", "browse": "folder"}
            ]
        elif module_type == "launch-bat":
            fields = [
                {"key": "script", "label": "脚本路径", "browse": "file"}
            ]
        elif module_type == "update-svn":
            fields = [
                {"key": "workspace", "label": "SVN 工作副本目录", "browse": "folder"}
            ]
        elif module_type == "commit-svn":
            fields = [
                {"key": "workspace", "label": "SVN 提交目录", "browse": "folder"},
                {"key": "message", "label": "提交说明 (可选)", "browse": "text"}
            ]
        elif module_type == "open-web":
            fields = [
                {"key": "url", "label": "网页 URL 地址", "browse": "text"}
            ]
        elif module_type == "app-launch":
            fields = [
                {"key": "app_path", "label": "程序或快捷方式路径 (.exe/.lnk)", "browse": "exe_lnk"},
                {"key": "work_dir", "label": "工作副本目录 (可选，为空时用程序父级)", "browse": "folder"},
                {"key": "args", "label": "启动参数 (可选)", "browse": "text"}
            ]
        else:
            fields = []

        for idx, f in enumerate(fields):
            lbl_text = f["label"]
            if "desc" in f:
                lbl_text += f" ({f['desc']})"
                
            ctk.CTkLabel(container, text=lbl_text, font=ctk.CTkFont(family=FONT, size=12),
                         text_color=self._t("secondary")).pack(anchor="w", pady=(8, 4))
            
            var = ctk.StringVar(value=initial_params.get(f["key"], ""))
            param_vars[f["key"]] = var
            
            row = ctk.CTkFrame(container, fg_color="transparent")
            row.pack(fill="x", pady=(0, 8))
            row.grid_columnconfigure(0, weight=1)
            
            entry = ctk.CTkEntry(row, textvariable=var, fg_color=self._t("surface"),
                                 text_color=self._t("text"), border_color=self._t("border"),
                                 font=ctk.CTkFont(family=FONT, size=12))
            entry.grid(row=0, column=0, sticky="ew")

            if f["browse"] != "text":
                def _browse(k=f["key"], kind=f["browse"]):
                    self._dock_pause()
                    try:
                        if kind == "folder":
                            p = filedialog.askdirectory(parent=container.winfo_toplevel())
                        elif kind == "exe_lnk":
                            p = filedialog.askopenfilename(parent=container.winfo_toplevel(),
                                                            filetypes=[("可执行程序与快捷方式", "*.exe;*.lnk"), ("所有文件", "*.*")])
                        else:
                            p = filedialog.askopenfilename(parent=container.winfo_toplevel(),
                                                            filetypes=[("批处理", "*.bat;*.cmd"), ("所有文件", "*.*")])
                    finally:
                        self._dock_resume()
                    if p:
                        param_vars[k].set(p)

                ctk.CTkButton(row, text="选择", width=50, corner_radius=6,
                              fg_color=self._t("hover"), hover_color=self._t("elevated"),
                              text_color=self._t("text"), font=ctk.CTkFont(family=FONT, size=11),
                              command=_browse).grid(row=0, column=1, padx=(4, 0))

        return param_vars

    # ============================================================
    # 卡片编辑 (重构：完全抛弃手打 key=value 文本框)
    # ============================================================

    def _edit_card(self, card: dict) -> None:
        if card["group"] == "quick":
            self._edit_quick_action(card)
        elif card["group"] == "module":
            self._edit_module(card)

    def _edit_quick_action(self, card: dict) -> None:
        qa = next((a for a in self.quick_actions if a["id"] == card["id"]), None)
        if not qa:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("编辑快捷动作")
        dialog.geometry("360x480")
        dialog.configure(fg_color=self._t("background"))
        dialog.transient(self)
        dialog.grab_set()
        self._bind_dock_modal(dialog)

        ctk.CTkLabel(dialog, text="名称", font=ctk.CTkFont(family=FONT, size=12),
                     text_color=self._t("secondary")).pack(anchor="w", padx=16, pady=(16, 4))
        name_var = ctk.StringVar(value=qa["title"])
        ctk.CTkEntry(dialog, textvariable=name_var, fg_color=self._t("surface"),
                     text_color=self._t("text"), border_color=self._t("border"),
                     font=ctk.CTkFont(family=FONT, size=12)).pack(fill="x", padx=16)

        fields_container = ctk.CTkFrame(dialog, fg_color="transparent")
        fields_container.pack(fill="x", padx=16, pady=4)
        
        param_vars = self._render_config_fields(fields_container, qa.get("module_type", qa["type"]), qa.get("params", {}))

        ctk.CTkLabel(dialog, text="校验结果", font=ctk.CTkFont(family=FONT, size=12),
                     text_color=self._t("secondary")).pack(anchor="w", padx=16, pady=(12, 4))
        review_text = ctk.CTkTextbox(dialog, height=80, fg_color=self._t("surface"),
                                     text_color=self._t("secondary"), border_width=1,
                                     border_color=self._t("border"), corner_radius=6,
                                     font=ctk.CTkFont(family=FONT, size=11))
        review_text.pack(fill="x", padx=16)
        review_text.insert("1.0", "点击「校验」检查参数")
        self._configure_disabled_textbox(review_text)
        review_text.configure(state="disabled")

        def _do_review():
            params = {k: v.get().strip() for k, v in param_vars.items()}
            action_type = qa.get("module_type", qa["type"])
            review = self._do_review_action(action_type, params)
            review_text.configure(state="normal")
            review_text.delete("1.0", "end")
            review_text.insert("1.0", f"状态：{review['status']}\n结论：{review['summary']}")
            for d in review.get("details", []):
                review_text.insert("end", f"\n- {d}")
            review_text.configure(state="disabled")

        def _do_delete():
            self._dock_pause()
            try:
                confirmed = messagebox.askyesno("确认删除", f"删除「{qa['title']}」？", parent=dialog)
            finally:
                self._dock_resume()
            if not confirmed:
                return
            self.quick_actions = [a for a in self.quick_actions if a["id"] != qa["id"]]
            self._save_quick_actions()
            self._refresh_cards()
            self._toast("已删除", "success")
            dialog.destroy()

        def _do_save():
            params = {k: v.get().strip() for k, v in param_vars.items()}
            name = name_var.get().strip() or qa["title"]
            qa["title"] = name
            qa["params"] = params
            self._save_quick_actions()
            self._refresh_cards()
            self._toast("已保存", "success")
            dialog.destroy()

        def _do_execute():
            params = {k: v.get().strip() for k, v in param_vars.items()}
            dialog.destroy()
            card2 = dict(card)
            card2["params"] = params
            self._execute_card(card2)

        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=12)
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=1)
        btns.grid_columnconfigure(2, weight=1)
        btns.grid_columnconfigure(3, weight=1)
        ctk.CTkButton(btns, text="删除", corner_radius=6,
                      fg_color=self._t("danger"), hover_color=self._t("danger"),
                      text_color=self._t("text"), font=ctk.CTkFont(family=FONT, size=12),
                      command=_do_delete).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(btns, text="校验", corner_radius=6,
                      fg_color=self._t("hover"), hover_color=self._t("elevated"),
                      text_color=self._t("text"), font=ctk.CTkFont(family=FONT, size=12),
                      command=_do_review).grid(row=0, column=1, sticky="ew", padx=4)
        ctk.CTkButton(btns, text="保存", corner_radius=6,
                      fg_color=self._t("primary"), hover_color=self._t("focus"),
                      text_color=self._t("text"), font=ctk.CTkFont(family=FONT, size=12),
                      command=_do_save).grid(row=0, column=2, sticky="ew", padx=4)
        ctk.CTkButton(btns, text="执行", corner_radius=6,
                      fg_color=self._t("elevated"), hover_color=self._t("hover"),
                      text_color=self._t("text"), font=ctk.CTkFont(family=FONT, size=12),
                      command=_do_execute).grid(row=0, column=3, sticky="ew", padx=(4, 0))

    def _edit_module(self, card: dict) -> None:
        module = next((m for m in self.custom_modules if m.module_id == card["id"]), None)
        if not module:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("编辑模块")
        dialog.geometry("360x520") # 统一高度，避免 4 行配置溢出窗口边界
        dialog.configure(fg_color=self._t("background"))
        dialog.transient(self)
        dialog.grab_set()
        self._bind_dock_modal(dialog)

        ctk.CTkLabel(dialog, text="名称", font=ctk.CTkFont(family=FONT, size=12),
                     text_color=self._t("secondary")).pack(anchor="w", padx=16, pady=(16, 4))
        name_var = ctk.StringVar(value=module.name)
        ctk.CTkEntry(dialog, textvariable=name_var, fg_color=self._t("surface"),
                     text_color=self._t("text"), border_color=self._t("border"),
                     font=ctk.CTkFont(family=FONT, size=12)).pack(fill="x", padx=16)

        fields_container = ctk.CTkFrame(dialog, fg_color="transparent")
        fields_container.pack(fill="both", expand=True, padx=16, pady=4)
        
        param_vars = self._render_config_fields(fields_container, module.module_type, module.params)

        def _delete():
            self._dock_pause()
            try:
                confirmed = messagebox.askyesno("确认删除", f"删除「{module.name}」？", parent=dialog)
            finally:
                self._dock_resume()
            if not confirmed:
                return
            self.custom_modules = [m for m in self.custom_modules if m.module_id != module.module_id]
            self.module_storage.save(self.custom_modules)
            self._refresh_cards()
            self._toast("已删除", "success")
            dialog.destroy()

        def _save():
            module.name = name_var.get().strip() or module.name
            module.params = {k: v.get().strip() for k, v in param_vars.items()}
            self.module_storage.save(self.custom_modules)
            self._refresh_cards()
            self._toast("已保存", "success")
            dialog.destroy()

        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=12)
        btns.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(btns, text="删除", corner_radius=6,
                      fg_color=self._t("danger"), hover_color=self._t("danger"),
                      text_color=self._t("text"), font=ctk.CTkFont(family=FONT, size=12),
                      command=_delete).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkButton(btns, text="保存", corner_radius=6,
                      fg_color=self._t("primary"), hover_color=self._t("focus"),
                      text_color=self._t("text"), font=ctk.CTkFont(family=FONT, size=12),
                      command=_save).grid(row=0, column=1, sticky="ew")

    # ============================================================
    # 添加菜单
    # ============================================================

    def _show_add_menu(self) -> None:
        self._add_module_dialog()

    def _add_module_dialog(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("添加模块")
        dialog.geometry("360x520") # 微增高窗体，确保新增提示行后不会出现溢出或被按钮遮挡
        dialog.configure(fg_color=self._t("background"))
        dialog.transient(self)
        dialog.grab_set()
        self._bind_dock_modal(dialog)

        ctk.CTkLabel(dialog, text="名称", font=ctk.CTkFont(family=FONT, size=12),
                     text_color=self._t("secondary")).pack(anchor="w", padx=16, pady=(16, 4))
        name_var = ctk.StringVar()
        ctk.CTkEntry(dialog, textvariable=name_var, fg_color=self._t("surface"),
                     text_color=self._t("text"), border_color=self._t("border"),
                     font=ctk.CTkFont(family=FONT, size=12)).pack(fill="x", padx=16)

        ctk.CTkLabel(dialog, text="类型", font=ctk.CTkFont(family=FONT, size=12),
                     text_color=self._t("secondary")).pack(anchor="w", padx=16, pady=(12, 4))
        type_var = ctk.CTkOptionMenu(dialog, values=list(MODULE_TYPE_LABELS.values()),
                                     fg_color=self._t("surface"), button_color=self._t("hover"),
                                     text_color=self._t("text"),
                                     font=ctk.CTkFont(family=FONT, size=12))
        type_var.set(MODULE_TYPE_LABELS["folder-copy"])
        type_var.pack(fill="x", padx=16)

        fields_container = ctk.CTkFrame(dialog, fg_color="transparent")
        fields_container.pack(fill="both", expand=True, padx=16, pady=4)

        param_vars_ref = {}

        def _on_type_change(choice):
            nonlocal param_vars_ref
            label_to_type = {v: k for k, v in MODULE_TYPE_LABELS.items()}
            module_type = label_to_type.get(choice, "folder-copy")
            
            hints = {}
            if module_type == "folder-copy":
                hints = {"source": "", "target": "", "source2": "", "target2": ""}
            elif module_type == "launch-bat":
                hints = {"script": str(DEFAULT_EXPORT_BAT)}
            elif module_type == "update-svn":
                hints = {"workspace": str(DEFAULT_SVN_ROOT)}
            elif module_type == "commit-svn":
                hints = {"workspace": str(DEFAULT_SVN_ROOT), "message": "AiTool auto commit"}
            elif module_type == "open-web":
                hints = {"url": "https://"}
            elif module_type == "app-launch":
                hints = {"app_path": "", "work_dir": "", "args": ""}
                
            param_vars_ref.clear()
            param_vars_ref.update(self._render_config_fields(fields_container, module_type, hints))

        type_var.configure(command=_on_type_change)
        _on_type_change(type_var.get())

        def _save():
            name = name_var.get().strip()
            if not name:
                self._toast("名称不能为空", "warning")
                return
            label_to_type = {v: k for k, v in MODULE_TYPE_LABELS.items()}
            module_type = label_to_type.get(type_var.get(), "folder-copy")
            
            params = {k: v.get().strip() for k, v in param_vars_ref.items()}
            
            module = CustomModule(
                module_id=ModuleStorage.generate_id(),
                name=name, module_type=module_type, params=params,
            )
            self.custom_modules.append(module)
            self.module_storage.save(self.custom_modules)
            self._refresh_cards()
            self._toast(f"已添加: {name}", "success")
            dialog.destroy()

        ctk.CTkButton(dialog, text="保存", corner_radius=6,
                      fg_color=self._t("primary"), hover_color=self._t("focus"),
                      text_color=self._t("text"), font=ctk.CTkFont(family=FONT, size=12),
                      command=_save).pack(fill="x", padx=16, pady=12)

    # ============================================================
    # 窗口控制
    # ============================================================

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        # 修复置顶功能：在 CustomTkinter 中属性设置需要配合 update_idletasks 和强力 topmost 属性重绘刷新，
        # 从而完美在各种复杂的多窗口、甚至全屏游戏前台状态下保持稳定的最高层置顶！
        self.attributes("-topmost", self._pinned)
        self.btn_pin.configure(text="📌" if self._pinned else "📍")
        
        # 强力置顶保障：让 Windows 系统底层立刻对 topmost 状态进行高亮冲刷
        self.lift()
        self.update_idletasks()
        
        self._toast("已开启窗口置顶" if self._pinned else "已取消窗口置顶", "success")

    # ============================================================
    # 状态 & Toast
    # ============================================================

    def _set_status(self, text: str, level: str = "ready") -> None:
        self.status_label.configure(text=text)
        colors = {"ready": self._t("success"), "warning": self._t("warning"),
                  "blocked": self._t("danger"), "muted": self._t("muted")}
        self.status_dot.configure(text_color=colors.get(level, self._t("success")))

    _toast_label = None

    def _toast(self, message: str, level: str = "") -> None:
        colors = {"success": self._t("success"), "warning": self._t("warning"),
                  "danger": self._t("danger")}
        color = colors.get(level, self._t("secondary"))

        if DesktopToolApp._toast_label:
            DesktopToolApp._toast_label.destroy()

        toast = ctk.CTkLabel(self, text=message, font=ctk.CTkFont(family=FONT, size=12),
                             text_color=color, fg_color=self._t("elevated"),
                             corner_radius=20, padx=16, pady=6)
        toast.place(relx=0.5, rely=0.08, anchor="n")
        DesktopToolApp._toast_label = toast

        self.after(3000, lambda: toast.destroy() if toast.winfo_exists() else None)

    # ============================================================
    # 使用说明
    # ============================================================
    def _show_user_guide(self, manual: bool = False) -> None:
        """弹出精致的极客用户使用说明。支持检测‘首次启动文件标志’，如果是首次启动，则静默自动弹窗。"""
        flag_file = DATA_DIR / ".user_guide_seen"
        if not manual and flag_file.exists():
            # 自动检测时：如果已经看过，则不打扰用户
            return

        # 写入标记文件
        try:
            flag_file.parent.mkdir(parents=True, exist_ok=True)
            with open(flag_file, "w", encoding="utf-8") as f:
                f.write("seen")
        except Exception:
            pass

        guide = ctk.CTkToplevel(self)
        guide.title("AiTool 使用说明")
        guide.geometry("380x480")
        guide.resizable(False, False)
        guide.configure(fg_color=self._t("background"))
        guide.transient(self)
        guide.grab_set()
        self._bind_dock_modal(guide)

        ctk.CTkLabel(guide, text="✨ 欢迎使用 AiTool 生产力助手 ✨",
                     font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
                     text_color=self._t("focus")).pack(pady=(20, 12))

        textbox = ctk.CTkTextbox(guide, width=340, height=340, fg_color=self._t("surface"),
                                  text_color=self._t("secondary"), border_width=1,
                                  border_color=self._t("border"), corner_radius=10,
                                  font=ctk.CTkFont(family=FONT, size=11, weight="bold"))
        textbox.pack(padx=20, pady=4)

        instructions = (
            "🚀 AiTool 使用说明\n"
            "========================================\n"
            "📐 窗口与停靠\n"
            "========================================\n"
            "  - 默认大小为 320 × 640，位置在当前主显示器工作区左上角。\n"
            "  - 已保存的有效窗口位置和高度会优先恢复。窗口宽度固定为 320px。\n"
            "  - 底部状态栏上方的纵向拖拽区域可以调整高度，调整结果会保存。\n"
            "  - 将窗口拖到屏幕顶部并停留即可停靠；鼠标离开后会自动收起，\n"
            "    只露出约 30px 的横条。鼠标移入横条即可展开。\n"
            "  - 顶部收起与隐藏到系统托盘是两种独立方式。\n\n"
            "⌨️ 快捷键与托盘\n"
            "========================================\n"
            "  - Alt+A：正常显示时隐藏到 Windows 右下角系统托盘；\n"
            "    托盘隐藏时恢复窗口；顶部横条收起时展开顶部窗口。\n"
            "  - 关闭按钮会隐藏到系统托盘，不会直接退出程序。托盘菜单提供：\n"
            "    打开 AiTool、设置中心、开机自启动切换、彻底退出。\n\n"
            "📥 拖放、粘贴与中转站\n"
            "========================================\n"
            "  - 窗口显示时，可拖放网址、脚本、应用、普通文件或文件夹。\n"
            "  - Ctrl+V 可粘贴网址或路径；托盘隐藏时主窗口不接收拖放。\n"
            "  - 中转站条目支持双击打开、右键定位，以及拖出复制。\n"
            "  - 快捷动作支持添加、编辑、删除和执行。\n\n"
            "🎨 其他设置\n"
            "========================================\n"
            "  - 主题按钮可切换亮色/暗色，置顶按钮可切换窗口置顶。\n"
            "  - 配置保存在 %APPDATA%\\AiTool\\；源码运行时保存在项目 data 目录。\n"
            "  - 更新 EXE 不会覆盖已有的用户配置。\n"
            "========================================\n"
            "      祝您使用愉快！"
        )
        
        textbox.insert("1.0", instructions)
        self._configure_disabled_textbox(textbox)
        textbox.configure(state="disabled")

        ctk.CTkButton(guide, text="我知道了", corner_radius=6,
                      fg_color=self._t("primary"), hover_color=self._t("focus"),
                      text_color=self._t("text"), font=ctk.CTkFont(family=FONT, size=12),
                      command=guide.destroy).pack(fill="x", padx=20, pady=(12, 16))

def main() -> int:
    app = DesktopToolApp()
    app.mainloop()
    return 0
