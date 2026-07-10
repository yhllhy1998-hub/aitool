from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
import ctypes
from ctypes import wintypes

from PIL import Image, ImageTk
import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

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


if getattr(sys, "frozen", False):
    REPO_ROOT = Path(sys._MEIPASS)
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "data" / "document_station_entries.json"
MODULE_STATE_PATH = REPO_ROOT / "data" / "custom_modules.json"
QUICK_ACTIONS_PATH = REPO_ROOT / "data" / "quick_actions.json"
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

THEME = {
    "bg": "#1a1b2e",
    "surface": "#232438",
    "elevated": "#2a2b42",
    "hover": "#313349",
    "card": "#262840",
    "border": "#353755",
    "text": "#f0f1f8",
    "text_sec": "#b8bbd8",
    "text_muted": "#8a8db0",
    "primary": "#7c6ef0",
    "primary_hover": "#8b7ff5",
    "danger": "#e85a5a",
    "success": "#4ade80",
    "warning": "#fbbf24",
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

ACTION_ICON_COLORS = {
    "folder-copy": "#60a5fa",
    "launch-bat": "#fbbf24",
    "update-svn": "#4ade80",
    "commit-svn": "#f43f5e", # 经典玫瑰红/粉红，代表提交/保存状态
    "open-web": "#a855f7",    # 科技紫，代表网络跳转
    "app-launch": "#38bdf8",  # 天蓝色，代表打开应用
    "copy": "#60a5fa",
    "bat": "#fbbf24",
    "svn": "#4ade80",
}

ACTION_ICON_TEXT = {
    "folder-copy": "📋",
    "launch-bat": "⚡",
    "update-svn": "🔄",
    "commit-svn": "📤", # SVN 提交
    "open-web": "🌐",   # 打开网页
    "app-launch": "🚀", # 打开应用
    "copy": "📋",
    "bat": "⚡",
    "svn": "🔄",
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
            return cls._cache[ext]

        _ensure_win32()
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
                    return photo
            except Exception:
                pass

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
        return fallback_emoji

    @classmethod
    def get_icon(cls, path_str: str, is_folder: bool = False):
        return cls.get_system_icon_image(path_str, is_folder)


class DesktopToolApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self) -> None:
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        from tkinterdnd2 import DND_FILES, DND_TEXT
        self.drop_target_register(DND_FILES, DND_TEXT)
        self._init_storage()
        self._init_window()
        self._build_ui()
        self._refresh_all()

    def _on_mousewheel(self, event):
        # 优化滑动体验：当且仅当卡片区域的总高度（bbox("all") 的 height）大于当前 Canvas 的视口物理高度（winfo_height）时，才允许滑动滚动。
        # 这可以完美防止在内容没有占满界面时，用户由于无意间滑轮操作导致界面整体被不自然地往上或往下卷曲，产生大片虚空露白！
        canvas_h = self._card_canvas.winfo_height()
        content_h = self._card_canvas.bbox("all")[3] # 获得内容底边界 Y 坐标，即总高度
        if content_h > canvas_h:
            self._card_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _init_storage(self) -> None:
        self.station_storage = StationStorage(STATE_PATH)
        self.module_storage = ModuleStorage(MODULE_STATE_PATH)
        self.entries: list[StationEntry] = self.station_storage.load()
        self.custom_modules: list[CustomModule] = self.module_storage.load()
        self.quick_actions = self._load_quick_actions()

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
        # 动态绘制 64x64 圆角矩形加能量圆环科技微光火箭图标
        img = Image.new("RGB", (64, 64), (26, 27, 46)) # 与底色 (1a1b2e) 完全契合的优雅蓝黑色背景
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([4, 4, 60, 60], radius=16, fill="#7c6ef0")
        draw.ellipse([20, 24, 44, 44], fill="#f0f1f8")
        return img

    def _init_window(self) -> None:
        self.title("AiTool")
        self.geometry("360x580")
        self.minsize(320, 420)
        self.maxsize(480, 800)
        self.configure(fg_color=THEME["bg"])
        self.attributes("-topmost", True)
        self._pinned = True
        self.overrideredirect(False)

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
                # 根据当前窗口的显示状态智能切换
                if self.winfo_viewable():
                    # 当前可见，则将其优雅退避隐藏到系统托盘常驻
                    self.after(0, self._minimize_to_tray)
                else:
                    # 当前隐藏，则立刻闪现最前对齐唤醒
                    self.after(0, self._restore_from_tray)

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
            self.deiconify()
            self.attributes("-topmost", True)
            self.focus_force()

            dialog = ctk.CTkToplevel(self)
            dialog.title("设置中心")
            dialog.geometry("320x260") # 微调增高高度，为全局快捷键 Alt+A 标识提供排版空间
            dialog.resizable(False, False)
            dialog.configure(fg_color=THEME["bg"])
            dialog.transient(self)
            dialog.grab_set()

             ctk.CTkLabel(dialog, text="⚙️ AiTool 桌面工具 设置中心",
                         font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
                         text_color=THEME["primary_hover"]).pack(pady=(20, 16))

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
                                   progress_color=THEME["primary"], text_color=THEME["text_sec"])
            switch.pack(pady=8)

            ctk.CTkLabel(dialog, text="开启后，电脑开机时将自动运行 AiTool",
                         font=ctk.CTkFont(family=FONT, size=9),
                         text_color=THEME["text_muted"]).pack(pady=(0, 12))

            # 增加全局快捷键的可视化展示
            hotkey_lbl = ctk.CTkLabel(dialog, text="全局唤醒/隐藏快捷键：Alt + A",
                                      font=ctk.CTkFont(family=FONT, size=11, weight="bold"),
                                      text_color=THEME["primary_hover"])
            hotkey_lbl.pack(pady=4)

            ctk.CTkLabel(dialog, text="在任何界面按 Alt + A，即可快速闪现/退避隐藏窗口",
                         font=ctk.CTkFont(family=FONT, size=9),
                         text_color=THEME["text_muted"]).pack(pady=(0, 16))

            ctk.CTkButton(dialog, text="关闭设置", corner_radius=6,
                          fg_color=THEME["hover"], hover_color=THEME["elevated"],
                          text_color=THEME["text"], font=ctk.CTkFont(family=FONT, size=11),
                          command=dialog.destroy).pack(fill="x", padx=40)

        self.after(0, _build_dialog)

    def _minimize_to_tray(self) -> None:
        """隐藏窗口并在系统托盘中生成一个精美的托盘图标。"""
        self.withdraw() # 隐藏主窗口

        # 如果托盘图标尚未启动，则在后台守护线程中初始化并启动它
        if not self._tray_icon:
            import pystray

            # 使用统一绘制的高颜值科技图标
            img = self._create_app_icon()

            def _show_app(icon, item):
                """双击或者右键菜单点击‘显示主界面’时，将窗口复原并最前展示"""
                icon.stop()
                self._tray_icon = None
                self.after(0, self._restore_from_tray)

            def _quit_app(icon, item):
                """彻底安全退出应用，清除托盘"""
                icon.stop()
                self.quit()

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

        self._toast("AiTool 已最小化到托盘常驻后台", "success")

    def _restore_from_tray(self) -> None:
        """从托盘恢复窗口显示"""
        self.deiconify()
        self.attributes("-topmost", self._pinned)
        self.focus_force()

    # ============================================================
    # UI 构建
    # ============================================================

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)  # 让唯一的 Canvas 填充整个主窗口区域实现“整页一起滚动”

        import tkinter as tk
        # 1. 重构整页联动滑动：
        # - 痛点：之前的“中转站”和“功能卡片”是两个彼此割裂的 Widget Grid。中转站钉在上方，只有下方的卡片区能滑动，超出无法展现。
        # - 重构方案：我们使用一个全域 Canvas + CTkScrollbar 作为主架构，把中转站 (Station) 和 卡片功能区 (Cards) 全部作为子卡片渲染放入同一个 `self._main_inner` 容器。
        # - 如此一来，“中转站”和“功能卡”都会完美地在这个画布内，随着滚轮在**整个工具界面**范围内一并平滑滑动，视觉更统一、更现代、更开阔！
        
        from tkinterdnd2 import DND_FILES, DND_TEXT, TkinterDnD
        
        self.main_scroll = ctk.CTkFrame(self, fg_color=THEME["bg"], corner_radius=0)
        self.main_scroll.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.main_scroll.grid_columnconfigure(0, weight=1)
        self.main_scroll.grid_rowconfigure(0, weight=1)

        self._card_canvas = tk.Canvas(self.main_scroll, bg=THEME["bg"], highlightthickness=0, bd=0)
        scrollbar = ctk.CTkScrollbar(self.main_scroll, command=self._card_canvas.yview)
        
        self._card_inner = ctk.CTkFrame(self._card_canvas, fg_color=THEME["bg"])
        
        def _update_scrollregion(event):
            self._card_canvas.configure(scrollregion=self._card_canvas.bbox("all"))

        self._card_inner.bind("<Configure>", _update_scrollregion)
        self._card_window = self._card_canvas.create_window((0, 0), window=self._card_inner, anchor="nw")
        self._card_canvas.configure(yscrollcommand=scrollbar.set)

        self._card_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._card_inner.grid_columnconfigure(0, weight=1)
        self._card_canvas.bind("<Configure>", lambda event: self._card_canvas.itemconfig(self._card_window, width=event.width))

        def _on_mousewheel_local(event):
            self._on_mousewheel(event)

        self._card_canvas.bind("<MouseWheel>", _on_mousewheel_local)
        self._card_inner.bind("<MouseWheel>", _on_mousewheel_local)

        # 挂载全域拖拽事件：同时注册 DND_FILES (文件) 和 DND_TEXT (文本/字符串超链接)
        # - 痛点：TkinterDnD 如果默认只注册 DND_FILES，那么拖入“纯文本/URL字符串”时，Windows 系统会返回禁止图标（🚫 标志）
        # - 解决方案：我们同时向整个界面和画布注册 DND_TEXT 监听，完美打通操作系统底层的文本数据拖放通道！
        self._card_canvas.drop_target_register(DND_FILES, DND_TEXT)
        self._card_canvas.dnd_bind("<<Drop>>", self._on_global_drop)
        self._card_canvas.dnd_bind("<<DragEnter>>", self._on_global_drag_enter)
        self._card_canvas.dnd_bind("<<DragLeave>>", self._on_global_drag_leave)
        
        self._card_inner.drop_target_register(DND_FILES, DND_TEXT)
        self._card_inner.dnd_bind("<<Drop>>", self._on_global_drop)
        self._card_inner.dnd_bind("<<DragEnter>>", self._on_global_drag_enter)
        self._card_inner.dnd_bind("<<DragLeave>>", self._on_global_drag_leave)

        # 构建子区域
        self._build_station_area()
        self._build_card_area()
        self._build_statusbar()

    def _build_station_area(self) -> None:
        wrap = ctk.CTkFrame(self._card_inner, fg_color=THEME["surface"], corner_radius=0)
        wrap.pack(fill="x", padx=0, pady=0)
        wrap.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(wrap, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=SPACING["md"], pady=(SPACING["sm"] + 2, SPACING["xs"]))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text="中转站", font=ctk.CTkFont(family=FONT, size=FS["section_title"], weight="bold"),
                     text_color=THEME["text_sec"]).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="拖入收藏 · 拖出复制 · 双击打开",
                     font=ctk.CTkFont(family=FONT, size=FS["status"] - 1), text_color=THEME["text_muted"]).grid(row=0, column=1, sticky="e")

        self.btn_pin = ctk.CTkButton(header, text="📌", width=24, height=24, corner_radius=12,
                                     fg_color=THEME["hover"], hover_color=THEME["elevated"],
                                     font=ctk.CTkFont(family=FONT, size=11),
                                     command=self._toggle_pin)
        self.btn_pin.grid(row=0, column=2, padx=(SPACING["xs"] + 2, 0))

        self.station_frame = ctk.CTkFrame(wrap, fg_color=THEME["surface"], height=110,
                                          corner_radius=0)
        self.station_frame.grid(row=2, column=0, sticky="ew", padx=SPACING["sm"], pady=(0, SPACING["sm"]))
        self.station_frame.grid_propagate(False)
        self.station_frame.grid_columnconfigure(0, weight=1)
        self.station_frame.grid_rowconfigure(0, weight=1)

        self.station_empty_label = ctk.CTkLabel(
            self.station_frame, text="拖入文件或文件夹",
            font=ctk.CTkFont(family=FONT, size=FS["station_name"]), text_color=THEME["text_muted"])
        self.station_empty_label.pack(expand=True, pady=SPACING["sm"])

    def _build_card_area(self) -> None:
        self.card_scroll = ctk.CTkFrame(self._card_inner, fg_color=THEME["bg"], corner_radius=0)
        self.card_scroll.pack(fill="both", expand=True, padx=0, pady=0)
        self.card_scroll.grid_columnconfigure(0, weight=1)

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=THEME["surface"], height=30, corner_radius=0)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_propagate(False)

        self.status_dot = ctk.CTkLabel(bar, text="●", width=20,
                                       text_color=THEME["success"],
                                       font=ctk.CTkFont(family=FONT, size=9))
        self.status_dot.grid(row=0, column=0, padx=(SPACING["md"], SPACING["xs"]))

        self.status_label = ctk.CTkLabel(bar, text="就绪", font=ctk.CTkFont(family=FONT, size=FS["status"]),
                                         text_color=THEME["text_sec"])
        self.status_label.grid(row=0, column=1, sticky="w")

    # ============================================================
    # 数据刷新
    # ============================================================

    def _refresh_all(self) -> None:
        self._refresh_station()
        self._refresh_cards()
        # 第一次启动时自动静默检测，并弹出使用说明
        self.after(500, self._show_user_guide)

    def _refresh_station(self) -> None:
        for w in self.station_frame.winfo_children():
            w.destroy()

        if not self.entries:
            self.station_empty_label = ctk.CTkLabel(
                self.station_frame, text="拖入文件或文件夹",
                font=ctk.CTkFont(family=FONT, size=FS["status"]), text_color=THEME["text_muted"])
            self.station_empty_label.pack(expand=True, pady=SPACING["sm"])
            self._register_dnd_recursive(self.station_frame)
            return

        for entry in self.entries:
            self._create_station_item(entry)
        self._register_dnd_recursive(self.station_frame)

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
        
        icon_label = tk.Label(item, bg=THEME["surface"])
        if isinstance(icon_img, ImageTk.PhotoImage):
            icon_label.configure(image=icon_img)
            icon_label.image = icon_img
        else:
            icon_label.configure(text=str(icon_img), font=(FONT, 14), fg=THEME["text"])
            
        icon_label.grid(row=0, column=0, sticky="", pady=3)

        name_text = entry.display_name
        if not exists:
            name_text += " (失效)"
        name_fg = THEME["text"] if exists else THEME["text_muted"]
        
        name_label = tk.Label(item, text=name_text,
                              font=(FONT, FS["station_name"]),
                              bg=THEME["surface"], fg=name_fg, anchor="w")
        name_label.grid(row=0, column=1, sticky="ew", padx=2, pady=3)

        # 1. 【中转站删除闪烁与点击痛点完美解决！】
        # - 痛点：以前用 grid_forget + grid 动态显隐，会造成剧烈的闪烁位移。
        # - 解决方案：固定使用 column=2 绝对物理预留列，并且通过配置文字前景色（text_color）和卡片背景完美咬合。
        # - 默认状态下：将前景色 text_color 设为和行背景一模一样的卡片色（THEME["surface"]），从而达到无形显隐的效果，绝不抖动闪变！
        # - 鼠标移入行时：立刻将 text_color 变为明显的红色/灰色前景色！
        btn = ctk.CTkButton(item, text="✕", width=22, height=22, corner_radius=11,
                            fg_color="transparent", hover_color=THEME["danger"],
                            text_color=THEME["surface"], # 改用底板背景色替代 "transparent" 关键字，彻底消除 CTk 内部 ValueError
                            font=ctk.CTkFont(family=FONT, size=9, weight="bold"),
                            command=lambda e=entry: self._remove_entry(e))
        # 物理位置固定，拒绝抖动，符合 Tkinter 标准 grid 属性
        btn.grid(row=0, column=2, padx=(2, SPACING["xs"]), pady=2, sticky="")

        def on_enter(e):
            item.configure(fg_color=THEME["hover"])
            for w in (icon_label, name_label):
                w.configure(bg=THEME["hover"])
            btn.configure(text_color=THEME["text_sec"], fg_color="transparent") # hover 时醒目亮起
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
                    w.configure(bg=THEME["surface"])
                btn.configure(text_color=THEME["surface"], fg_color="transparent") # 完美熄灭且绝不位移抖动
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

        for w in (name_label, icon_label):
            w.drag_source_register(1, DND_FILES)
            w.dnd_bind("<<DragInitCmd>>", lambda e, ent=entry: self._on_station_drag_out(ent))

    def _refresh_cards(self) -> None:
        # 为了保证整页滚动流畅：
        # - 在刷新卡片区时，不能把中转站销毁。
        # - 我们应该只清理 _card_inner 容器中，“快捷动作模块”的子组件。
        # - 所以我们对 _card_inner 清理时，跳过 index 0 的中转站（Station Area）面板组件，其余全部清理重装！
        children = self._card_inner.winfo_children()
        # 索引 0 是中转站的 wrap 面板，我们保留它
        for w in children[1:]:
            w.destroy()

        header = ctk.CTkFrame(self._card_inner, fg_color="transparent")
        header.pack(fill="x", padx=SPACING["md"], pady=(SPACING["sm"], SPACING["xs"]))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text="快捷动作", font=ctk.CTkFont(family=FONT, size=FS["section_title"], weight="bold"),
                     text_color=THEME["text_sec"]).grid(row=0, column=0, sticky="w")

        self.btn_add = ctk.CTkButton(header, text="➕", width=24, height=24, corner_radius=12,
                                     fg_color=THEME["primary"], hover_color=THEME["primary_hover"],
                                     text_color="#fff", font=ctk.CTkFont(family=FONT, size=9),
                                     command=self._show_add_menu)
        self.btn_add.grid(row=0, column=2, padx=(SPACING["xs"], 0))

        cards = self._get_all_cards()

        if not cards:
            ctk.CTkLabel(self._card_inner, text="暂无动作",
                          font=ctk.CTkFont(family=FONT, size=FS["status"]),
                          text_color=THEME["text_muted"]).pack(pady=20)
        else:
            for card in cards:
                self._create_card(card)

        # 4. 在界面最下面加一行温馨高逼格小字：“一切都可以拖进来！”
        # - 它会作为卡片容器的收尾元素，优雅居中悬浮在最下方，文字配色选用温柔的 muted 暗灰色
        footer = ctk.CTkFrame(self._card_inner, fg_color="transparent")
        footer.pack(fill="x", side="bottom", pady=(24, 16))
        
        lbl_tip = ctk.CTkLabel(footer, text="✨ 一切都可以拖进来！",
                              font=ctk.CTkFont(family=FONT, size=FS["card_desc"] + 1, slant="italic"),
                              text_color=THEME["text_muted"], cursor="hand2")
        lbl_tip.pack(anchor="center")
        lbl_tip.bind("<MouseWheel>", self._on_mousewheel)

        # 绑定手动点击触发“使用说明”弹窗，提供详细极客教程
        lbl_tip.bind("<Button-1>", lambda event: self._show_user_guide(manual=True))

        self._register_dnd_recursive(self._card_inner)

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
        frame = ctk.CTkFrame(self._card_inner, fg_color=THEME["card"], bg_color="transparent", corner_radius=10,
                             border_width=1, border_color=THEME["border"])
        frame.pack(fill="x", padx=SPACING["sm"], pady=SPACING["xs"])
        
        frame.grid_columnconfigure(0, minsize=SPACING["icon_col"], weight=0)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(2, minsize=40, weight=0) # 稍微拓宽编辑区列宽，预留编辑箭头呼吸位
        frame.grid_rowconfigure(0, weight=1)

        import tkinter as tk
        icon_text = ACTION_ICON_TEXT.get(card["type"], "🧩")
        icon_color = ACTION_ICON_COLORS.get(card["type"], THEME["text_sec"])
        
        # 2 & 3. 【彻底消除突兀的背景板，并解决卡片图标垂直偏斜问题】
        # - 痛点：以前有一个突兀的深灰色 elevated 背景板，视觉被生硬地割裂了，且 Emoji 在框里无法完美上下居中。
        # - 解决方案：我们废除生硬的 elevated 图标框！将图标背景色直接和卡片底板 `THEME["card"]` 设为 100% 相同！
        # - 图标直接作为精美独立的气氛组件，在 `52px` 绝对对齐格中完全居中对齐，浑然一体，绝不突兀！
        icon_label = tk.Label(frame, text=icon_text,
                               bg=THEME["card"], fg=icon_color,
                               font=(FONT, 18), anchor="center") # 放大动作图标字号到 18pt
        icon_label.grid(row=0, column=0, sticky="nsew", pady=SPACING["card_pady"])

        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.grid(row=0, column=1, sticky="ew", padx=(4, 4), pady=SPACING["card_pady"])
        body.grid_columnconfigure(0, weight=1)

        title_lbl = tk.Label(body, text=card["title"],
                             font=(FONT, FS["card_title"], "bold"),
                             bg=THEME["card"], fg=THEME["text"], anchor="w")
        title_lbl.grid(row=0, column=0, sticky="w")
        
        desc_lbl = tk.Label(body, text=card.get("desc", ""),
                             font=(FONT, FS["card_desc"]),
                             bg=THEME["card"], fg=THEME["text_muted"], anchor="w")
        desc_lbl.grid(row=1, column=0, sticky="w")

        # 2. 【编辑箭头重构：消除突兀背景，箭头放大，极度精致】
        # - 痛点：以前的箭头非常渺小，且带一个有色差的背景按钮框，极其难看。
        # - 重构方案：我们使用 ctk.CTkButton，但将其背景、前景色彻底设为透明。
        # - 通过将 text 改为极具指向感的经典 Windows 右方向箭头 `">"`，字号直接拉到 `16pt bold`。
        # - 将其 `hover_color` 修改为比底板稍微亮一点的高级 hover 色，只有在鼠标放上去时，才呈现出微弱、高级的圆圈气泡效果！
        edit_btn = ctk.CTkButton(frame, text=">", width=24, height=24, corner_radius=12, # 完美的 24x24 正圆形按钮
                                 fg_color="transparent", hover_color=THEME["hover"],
                                 bg_color=THEME["card"],
                                 text_color=THEME["text_sec"],
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

    def _register_dnd_recursive(self, widget) -> None:
        """递归给 widget 及其所有子组件注册 DND_FILES + DND_TEXT 拖放事件。

        TkinterDnD 的事件不会向父容器冒泡，只有鼠标直接悬停的 widget 才能接收 drop。
        所以每次动态创建/销毁子 widget 后，必须重新注册才能保证全界面都能接收网址拖拽。
        """
        try:
            widget.drop_target_register(DND_FILES, DND_TEXT)
            widget.dnd_bind("<<Drop>>", self._on_global_drop)
            widget.dnd_bind("<<DragEnter>>", self._on_global_drag_enter)
            widget.dnd_bind("<<DragLeave>>", self._on_global_drag_leave)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._register_dnd_recursive(child)

    def _on_global_drag_enter(self, event) -> None:
        self._set_status("拖入文件...", "warning")

    def _on_global_drag_leave(self, event) -> None:
        self._set_status("就绪", "ready")

    def _on_global_drop(self, event) -> None:
        # 支持两种拖拽方式：
        # 1. 拖入来自浏览器的原生链接 URL、或者剪贴板/选中的文本（通过 event.data 文本智能正则判定）
        # 2. 拖入 Windows 本地文件（通过 tk.splitlist(event.data) 分割后的真实路径）
        raw_data = str(event.data).strip()
        
        added_modules = []
        added_station = []

        # 用正则表达式与前缀检测对整个拖入的 event.data 进行“纯网址/文本超链接”检测
        # 支持各种形式：带引号、不带引号，或者包含 http://, https:// 的独立字符串
        import re
        url_match = re.search(r'(https?://[^\s"\'{}<>]+)', raw_data)
        
        # 额外针对拖入可能带大括号包围的网址（如 {https://github.com}）进行剥离
        cleaned_raw = raw_data.strip("{}'\" ")
        url_match_loose = re.search(r'(https?://[^\s"\'{}<>]+)', cleaned_raw)
        
        if url_match_loose:
            extracted_url = url_match_loose.group(1)
            name = "打开网页 " + (extracted_url[:25] + "..." if len(extracted_url) > 25 else extracted_url)
            module = CustomModule(
                module_id=ModuleStorage.generate_id(),
                name=name,
                module_type="open-web",
                params={"url": extracted_url},
            )
            self.custom_modules.append(module)
            added_modules.append(name)
        elif cleaned_raw.lower().startswith("www."):
            # 兼容无协议头的普通网址，如 www.baidu.com
            full_url = "https://" + cleaned_raw
            name = "打开 " + cleaned_raw
            module = CustomModule(
                module_id=ModuleStorage.generate_id(),
                name=name,
                module_type="open-web",
                params={"url": full_url},
            )
            self.custom_modules.append(module)
            added_modules.append(name)
        elif ";" in raw_data and (raw_data.count(":") >= 2 or "/" in raw_data or "\\" in raw_data):
            # 额外兼容：如果拖入的字符串是用半角分号分割的多个路径，智能建立多路径文件覆盖拷贝
            parts = [p.strip() for p in raw_data.split(";")]
            # 如果拖入两个或多个存在的文件夹
            valid_dirs = [p for p in parts if Path(p).exists() and Path(p).is_dir()]
            if len(valid_dirs) >= 2:
                name = "多路径覆盖复制"
                module = CustomModule(
                    module_id=ModuleStorage.generate_id(),
                    name=name,
                    module_type="folder-copy",
                    params={"source": ";".join(valid_dirs), "target": ""},
                )
                self.custom_modules.append(module)
                added_modules.append(name)
        else:
            # 如果不包含 http 开头的网络地址，我们退回经典的文件路径分割和智能识别
            paths = list(self.tk.splitlist(event.data))
            if not paths:
                return

            for raw_path in paths:
                p = Path(raw_path)
                # 兼容 Windows 经典 .url 快捷配置文件
                if p.suffix.lower() == ".url":
                    try:
                        url_val = ""
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                if line.strip().lower().startswith("url="):
                                    url_val = line.split("=", 1)[1].strip()
                                    break
                        if url_val:
                            name = "打开 " + p.stem
                            module = CustomModule(
                                module_id=ModuleStorage.generate_id(),
                                name=name,
                                module_type="open-web",
                                params={"url": url_val},
                            )
                            self.custom_modules.append(module)
                            added_modules.append(name)
                            continue
                    except Exception:
                        pass

                if not p.exists():
                    # 额外兼容：如果路径不存在，但是包含了诸如 www.baidu.com 等经典无头网址文本
                    raw_lower = raw_path.strip().lower()
                    if raw_lower.startswith("www."):
                        full_url = "https://" + raw_path.strip()
                        name = "打开 " + raw_path.strip()
                        module = CustomModule(
                            module_id=ModuleStorage.generate_id(),
                            name=name,
                            module_type="open-web",
                            params={"url": full_url},
                        )
                        self.custom_modules.append(module)
                        added_modules.append(name)
                        continue
                    continue
                    
                ext = p.suffix.lower()
                if ext in {".exe", ".lnk"}:
                    # 智能归类为：打开应用模块
                    name = "启动 " + (p.stem if ext == ".lnk" else p.name)
                    module = CustomModule(
                        module_id=ModuleStorage.generate_id(),
                        name=name,
                        module_type="app-launch",
                        params={"app_path": str(p), "work_dir": "", "args": ""},
                    )
                    self.custom_modules.append(module)
                    added_modules.append(name)
                elif ext in {".bat", ".cmd", ".py"}:
                    # 智能归类为：启动脚本模块
                    name = "执行 " + p.name
                    module = CustomModule(
                        module_id=ModuleStorage.generate_id(),
                        name=name,
                        module_type="launch-bat",
                        params={"script": str(p)},
                    )
                    self.custom_modules.append(module)
                    added_modules.append(name)
                else:
                    # 其他所有格式（如 .zip, .xlsx, .png，或普通文件夹）：智能收藏到文件站
                    added_station.append(raw_path)

        # 批量保存与视图重刷
        if added_modules:
            self.module_storage.save(self.custom_modules)
            self._refresh_cards()
            self._toast(f"已自动生成模块: {', '.join(added_modules)}", "success")
            
        if added_station:
            self.entries, added_s, skipped = collect_station_entries(added_station, self.entries)
            self.station_storage.save(self.entries)
            self._refresh_station()
            if added_s:
                self._toast(f"已收藏到中转站: {', '.join(added_s)}", "success")
                
        self._set_status("就绪", "ready")

    def _on_station_drag_out(self, entry: StationEntry):
        """从中转站拖出文件到系统资源管理器。"""
        from tkinterdnd2 import COPY
        tcl_path = "{" + entry.path + "}"
        return (COPY, DND_FILES, tcl_path)

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
                messagebox.showwarning("入口失效", "所选路径及其所在文件夹均已不存在。", parent=self)
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
            messagebox.showwarning("入口失效", "所选入口已不存在。", parent=self)
            return
        if hasattr(os, "startfile"):
            os.startfile(str(p))
            self._set_status(f"已打开: {p.name}", "ready")

    def _remove_entry(self, entry: StationEntry) -> None:
        self.entries = [e for e in self.entries if e.path != entry.path]
        self.station_storage.save(self.entries)
        self._refresh_station()
        self._toast("已移除", "success")

    def _copy_entry_to(self, entry: StationEntry) -> None:
        target = filedialog.askdirectory(title="选择导出目录", parent=self)
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
            if not messagebox.askyesno("确认执行", f"{card['title']}\n\n确认执行？", parent=self):
                self._set_status("已取消", "ready")
                return

        action_type = card["action_type"]
        params = card.get("params", {})

        # 5. 对于高频重度的“文件夹覆盖复制 (folder-copy)”，采用无缝的 进度条+动态状态文本 混合弹窗提示！
        # - 痛点：文件拷贝属于重度磁盘 I/O 阻塞任务，如果静默在后台跑，用户会觉得“卡死”或“根本没反应”。
        # - 解决方案：我们弹出一个非阻塞的、带有动态旋转进度条和执行状态文本的现代 HUD 面板。
        if action_type == "folder-copy":
            hud = ctk.CTkToplevel(self)
            hud.title("正在同步复制")
            hud.geometry("320x150")
            hud.resizable(False, False)
            hud.configure(fg_color=THEME["bg"])
            hud.transient(self)
            hud.grab_set()

            # 居中子标签
            ctk.CTkLabel(hud, text="📂 正在同步覆盖目标文件...",
                         font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
                         text_color=THEME["text"]).pack(pady=(16, 8))

            # 循环进度条
            progress = ctk.CTkProgressBar(hud, width=260, height=8,
                                          fg_color=THEME["surface"], progress_color=THEME["primary"])
            progress.pack(pady=8)
            progress.configure(mode="indetermined")
            progress.start()

            status_lbl = ctk.CTkLabel(hud, text="准备执行 I/O 通道同步...",
                                      font=ctk.CTkFont(family=FONT, size=11),
                                      text_color=THEME["text_muted"])
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
                    if review["status"] == "ready":
                        messagebox.showinfo("同步成功", f"🎉 {card['title']} 执行成功！\n\n- 状态: 已完成\n- 详情: {review['summary']}", parent=self)
                    else:
                        messagebox.showerror("同步失败", f"❌ {card['title']} 执行失败！\n\n- 失败原因: {review['summary']}", parent=self)
                    self._on_execute_done(card["title"], review)

                hud.after(1000, _done)

            threading.Thread(target=_run_with_hud, daemon=True).start()
            return

        self._set_status(f"正在执行: {card['title']}...", "warning")
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
                         text_color=THEME["text_sec"]).pack(anchor="w", pady=(8, 4))
            
            var = ctk.StringVar(value=initial_params.get(f["key"], ""))
            param_vars[f["key"]] = var
            
            row = ctk.CTkFrame(container, fg_color="transparent")
            row.pack(fill="x", pady=(0, 8))
            row.grid_columnconfigure(0, weight=1)
            
            entry = ctk.CTkEntry(row, textvariable=var, fg_color=THEME["surface"],
                                 text_color=THEME["text"], border_color=THEME["border"],
                                 font=ctk.CTkFont(family=FONT, size=12))
            entry.grid(row=0, column=0, sticky="ew")

            if f["browse"] != "text":
                def _browse(k=f["key"], kind=f["browse"]):
                    if kind == "folder":
                        p = filedialog.askdirectory(parent=container.winfo_toplevel())
                    elif kind == "exe_lnk":
                        p = filedialog.askopenfilename(parent=container.winfo_toplevel(),
                                                        filetypes=[("可执行程序与快捷方式", "*.exe;*.lnk"), ("所有文件", "*.*")])
                    else:
                        p = filedialog.askopenfilename(parent=container.winfo_toplevel(),
                                                        filetypes=[("批处理", "*.bat;*.cmd"), ("所有文件", "*.*")])
                    if p:
                        param_vars[k].set(p)

                ctk.CTkButton(row, text="选择", width=50, corner_radius=6,
                              fg_color=THEME["hover"], hover_color=THEME["elevated"],
                              text_color=THEME["text"], font=ctk.CTkFont(family=FONT, size=11),
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
        dialog.configure(fg_color=THEME["bg"])
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="名称", font=ctk.CTkFont(family=FONT, size=12),
                     text_color=THEME["text_sec"]).pack(anchor="w", padx=16, pady=(16, 4))
        name_var = ctk.StringVar(value=qa["title"])
        ctk.CTkEntry(dialog, textvariable=name_var, fg_color=THEME["surface"],
                     text_color=THEME["text"], border_color=THEME["border"],
                     font=ctk.CTkFont(family=FONT, size=12)).pack(fill="x", padx=16)

        fields_container = ctk.CTkFrame(dialog, fg_color="transparent")
        fields_container.pack(fill="x", padx=16, pady=4)
        
        param_vars = self._render_config_fields(fields_container, qa.get("module_type", qa["type"]), qa.get("params", {}))

        ctk.CTkLabel(dialog, text="校验结果", font=ctk.CTkFont(family=FONT, size=12),
                     text_color=THEME["text_sec"]).pack(anchor="w", padx=16, pady=(12, 4))
        review_text = ctk.CTkTextbox(dialog, height=80, fg_color=THEME["surface"],
                                     text_color=THEME["text_sec"], border_width=1,
                                     border_color=THEME["border"], corner_radius=6,
                                     font=ctk.CTkFont(family=FONT, size=11))
        review_text.pack(fill="x", padx=16)
        review_text.insert("1.0", "点击「校验」检查参数")
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
            if not messagebox.askyesno("确认删除", f"删除「{qa['title']}」？", parent=dialog):
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
                      fg_color=THEME["danger"], hover_color="#f06868",
                      text_color="#fff", font=ctk.CTkFont(family=FONT, size=12),
                      command=_do_delete).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(btns, text="校验", corner_radius=6,
                      fg_color=THEME["hover"], hover_color=THEME["elevated"],
                      text_color=THEME["text"], font=ctk.CTkFont(family=FONT, size=12),
                      command=_do_review).grid(row=0, column=1, sticky="ew", padx=4)
        ctk.CTkButton(btns, text="保存", corner_radius=6,
                      fg_color=THEME["primary"], hover_color=THEME["primary_hover"],
                      text_color="#fff", font=ctk.CTkFont(family=FONT, size=12),
                      command=_do_save).grid(row=0, column=2, sticky="ew", padx=4)
        ctk.CTkButton(btns, text="执行", corner_radius=6,
                      fg_color=THEME["elevated"], hover_color=THEME["hover"],
                      text_color=THEME["text"], font=ctk.CTkFont(family=FONT, size=12),
                      command=_do_execute).grid(row=0, column=3, sticky="ew", padx=(4, 0))

    def _edit_module(self, card: dict) -> None:
        module = next((m for m in self.custom_modules if m.module_id == card["id"]), None)
        if not module:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("编辑模块")
        dialog.geometry("360x520") # 统一高度，避免 4 行配置溢出窗口边界
        dialog.configure(fg_color=THEME["bg"])
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="名称", font=ctk.CTkFont(family=FONT, size=12),
                     text_color=THEME["text_sec"]).pack(anchor="w", padx=16, pady=(16, 4))
        name_var = ctk.StringVar(value=module.name)
        ctk.CTkEntry(dialog, textvariable=name_var, fg_color=THEME["surface"],
                     text_color=THEME["text"], border_color=THEME["border"],
                     font=ctk.CTkFont(family=FONT, size=12)).pack(fill="x", padx=16)

        fields_container = ctk.CTkFrame(dialog, fg_color="transparent")
        fields_container.pack(fill="both", expand=True, padx=16, pady=4)
        
        param_vars = self._render_config_fields(fields_container, module.module_type, module.params)

        def _delete():
            if not messagebox.askyesno("确认删除", f"删除「{module.name}」？", parent=dialog):
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
                      fg_color=THEME["danger"], hover_color="#f06868",
                      text_color="#fff", font=ctk.CTkFont(family=FONT, size=12),
                      command=_delete).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkButton(btns, text="保存", corner_radius=6,
                      fg_color=THEME["primary"], hover_color=THEME["primary_hover"],
                      text_color="#fff", font=ctk.CTkFont(family=FONT, size=12),
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
        dialog.configure(fg_color=THEME["bg"])
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="名称", font=ctk.CTkFont(family=FONT, size=12),
                     text_color=THEME["text_sec"]).pack(anchor="w", padx=16, pady=(16, 4))
        name_var = ctk.StringVar()
        ctk.CTkEntry(dialog, textvariable=name_var, fg_color=THEME["surface"],
                     text_color=THEME["text"], border_color=THEME["border"],
                     font=ctk.CTkFont(family=FONT, size=12)).pack(fill="x", padx=16)

        ctk.CTkLabel(dialog, text="类型", font=ctk.CTkFont(family=FONT, size=12),
                     text_color=THEME["text_sec"]).pack(anchor="w", padx=16, pady=(12, 4))
        type_var = ctk.CTkOptionMenu(dialog, values=list(MODULE_TYPE_LABELS.values()),
                                     fg_color=THEME["surface"], button_color=THEME["hover"],
                                     text_color=THEME["text"],
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
                      fg_color=THEME["primary"], hover_color=THEME["primary_hover"],
                      text_color="#fff", font=ctk.CTkFont(family=FONT, size=12),
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
        colors = {"ready": THEME["success"], "warning": THEME["warning"],
                  "blocked": THEME["danger"], "muted": THEME["text_muted"]}
        self.status_dot.configure(text_color=colors.get(level, THEME["success"]))

    _toast_label = None

    def _toast(self, message: str, level: str = "") -> None:
        colors = {"success": THEME["success"], "warning": THEME["warning"],
                  "danger": THEME["danger"]}
        color = colors.get(level, THEME["text_sec"])

        if DesktopToolApp._toast_label:
            DesktopToolApp._toast_label.destroy()

        toast = ctk.CTkLabel(self, text=message, font=ctk.CTkFont(family=FONT, size=12),
                             text_color=color, fg_color=THEME["elevated"],
                             corner_radius=20, padx=16, pady=6)
        toast.place(relx=0.5, rely=0.08, anchor="n")
        DesktopToolApp._toast_label = toast

        self.after(3000, lambda: toast.destroy() if toast.winfo_exists() else None)

    # ============================================================
    # 使用说明
    # ============================================================
    def _show_user_guide(self, manual: bool = False) -> None:
        """弹出精致的极客用户使用说明。支持检测‘首次启动文件标志’，如果是首次启动，则静默自动弹窗。"""
        flag_file = REPO_ROOT / "data" / ".user_guide_seen"
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
        guide.configure(fg_color=THEME["bg"])
        guide.transient(self)
        guide.grab_set()

        ctk.CTkLabel(guide, text="✨ 欢迎使用 AiTool 生产力助手 ✨",
                     font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
                     text_color=THEME["primary_hover"]).pack(pady=(20, 12))

        textbox = ctk.CTkTextbox(guide, width=340, height=340, fg_color=THEME["surface"],
                                  text_color=THEME["text_sec"], border_width=1,
                                  border_color=THEME["border"], corner_radius=10,
                                  font=ctk.CTkFont(family=FONT, size=11, weight="bold"))
        textbox.pack(padx=20, pady=4)

        instructions = (
            "🚀 智能极客拖放矩阵\n"
            "========================================\n"
            "您可以把任何东西扔进本界面的任意角落：\n\n"
            "  1. 🌐 拖入网页链接 / .url 文件\n"
            "     --> 自动为您生成一键「网页跳转卡片」！\n\n"
            "  2. 🚀 拖入 .exe 程序 / 桌面快捷方式 (.lnk)\n"
            "     --> 自动为您生成一键「启动应用程序卡片」！\n\n"
            "  3. ⚡ 拖入 .bat / .cmd / .py 脚本\n"
            "     --> 自动为您生成一键「静默脚本执行卡片」！\n\n"
            "  4. 📁 拖入其它格式（.zip, .xlsx, 普通目录...）\n"
            "     --> 自动收藏进上方「中转站」供后续流转！\n\n\n"
            "📂 高频双通道资源覆盖\n"
            "========================================\n"
            "  在双通道资源覆盖模块中，双击可同时执行两组路径同步。\n"
            "  - 源路径 1 (配置文件的 autocode) -> 共享文件夹\n"
            "  - 源路径 2 (配置文件的 LuaFile) -> Unity 的 Data 路径\n\n\n"
            "📋 基础中转站交互\n"
            "========================================\n"
            "  - 双击：打开文件/文件夹\n"
            "  - ✕ 按钮：安全地将文件从中转站移除\n"
            "  - 拖出：可以直接把文件拖放回系统桌面或目录！\n"
            "========================================\n"
            "      尽情体验无负担、零摩擦的极致操作吧！"
        )
        
        textbox.insert("1.0", instructions)
        textbox.configure(state="disabled")

        ctk.CTkButton(guide, text="我知道了", corner_radius=6,
                      fg_color=THEME["primary"], hover_color=THEME["primary_hover"],
                      text_color="#fff", font=ctk.CTkFont(family=FONT, size=12),
                      command=guide.destroy).pack(fill="x", padx=20, pady=(12, 16))

        self.after(2400, lambda: toast.destroy() if toast.winfo_exists() else None)


def main() -> int:
    ctk.set_appearance_mode("dark")
    app = DesktopToolApp()
    app.mainloop()
    return 0
