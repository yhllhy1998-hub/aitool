# AGENTS.md

AiTool 是一个 Windows 桌面效率工具，解决日常文件中转、文件夹覆盖复制、脚本启动和 SVN 操作的效率问题。

## 1. 项目结构

- 代码：`src/aitool_desktop/`（app / operations / models / storage）
- 入口：`run_desktop_tool.py`
- 默认配置：`data/`（quick_actions.json / custom_modules.json / document_station_entries.json）
- 打包配置：`AiTool桌面工具.spec`（**唯一打包入口，不要用其他 spec**）
- 治理：`.agent/`（轻量，单主控模式）
- 文档：`docs/`

## 2. 打包规则（重要！踩坑总结）

### 2.1 打包命令

```powershell
py -m PyInstaller "AiTool桌面工具.spec" --noconfirm --upx-dir "C:\Users\Administrator\AppData\Local\Programs\Python\Python312"
```

### 2.2 spec 文件规则（禁止擅自修改）

`AiTool桌面工具.spec` 是经过多次验证的稳定配置，**不要修改以下内容**：

- **hiddenimports 必须包含**：`_tkinter`, `json`, `uuid`, `datetime`, `shutil`, `subprocess`, `re`, `ctypes`, `webbrowser`
- **必须调用**：`collect_submodules('tkinter')`, `collect_submodules('tkinterdnd2')`, `collect_data_files('tkinterdnd2')`
- **datas 必须包含**：`('data', 'data')` + `collect_data_files('tkinterdnd2')`
- **pathex 必须是** `['src']`
- **optimize = 2**
- **excludes 只能排除**：`numpy`, `matplotlib`, `multiprocessing`, `IPython`, `scipy`, `test`, `unittest`, `pydoc`, `sqlite3`, `tkinter.test`, `tkinter.tix`, `distutils`, `lib2to3`, `turtle`, `turtledemo`, `pydoc_data`
- **绝对不能排除**：`ctypes`, `inspect`, `dis`, `urllib`, `http`, `xml`, `email`, `ast`, `re`, `webbrowser`（标准库间接依赖，排除会导致运行时 ModuleNotFoundError）

### 2.3 UPX

- UPX 安装路径：`C:\Users\Administrator\AppData\Local\Programs\Python\Python312\upx.exe`
- 如果系统没有 UPX，从 https://github.com/upx/upx/releases 下载 win64 版（约 660KB），放到 Python 目录下
- UPX 会自动压缩 DLL/PYD，exe 从 18.88MB 降到 14.94MB

### 2.4 打包前必做

1. 清理 PyInstaller 缓存：`Remove-Item "C:\Users\Administrator\AppData\Local\pyinstaller\bincache01py31264bit" -Recurse -Force`
2. 清理 build 目录：`Remove-Item "D:\LHYsAuto\AiTool\build" -Recurse -Force`
3. 清理 APPDATA（模拟首次运行）：`Remove-Item "$env:APPDATA\AiTool" -Recurse -Force`

### 2.5 打包后验证

1. 启动 exe，确认窗口标题是 "AiTool"（不是 "Unhandled exception"）
2. 拖拽网址到窗口，确认自动生成网页模块
3. Ctrl+V 粘贴网址，确认自动生成网页模块
4. 确认 APPDATA 配置目录自动创建且包含默认配置文件

## 3. 代码规则（踩坑总结）

### 3.1 frozen 环境路径

```python
if getattr(sys, "frozen", False):
    REPO_ROOT = Path(sys._MEIPASS)          # 打包内置资源
    DATA_DIR = Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "AiTool"  # 用户持久化
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    DATA_DIR = REPO_ROOT / "data"
```

- **REPO_ROOT**：打包后指向 `_MEIPASS`（只读临时目录），用于找内置 data/
- **DATA_DIR**：打包后指向 `%APPDATA%/AiTool/`，用于读写用户配置
- **绝对不要用 `Path(__file__).resolve().parents[2]` 在 frozen 环境下定位 data/**

### 3.2 默认配置初始化

- `_ensure_default_config()` 在 `_init_storage` 开头调用
- 首次运行时从 `REPO_ROOT/data/` 复制默认配置到 `DATA_DIR`
- 之后用户修改的配置保存在 `DATA_DIR`，重启不丢失

### 3.3 tkinterdnd2 拖拽

- **顶层 import 必须是**：`from tkinterdnd2 import DND_FILES, DND_TEXT, TkinterDnD`
- **不能只 import DND_FILES**，`_register_dnd_recursive` 会用到 `DND_TEXT`，缺少会触发 `NameError`，被 `except` 静默吞掉，导致拖拽注册全部失败
- `_register_dnd_recursive` 在每次 `_refresh_station` 和 `_refresh_cards` 后调用，因为动态创建的子 widget 需要重新注册 DND 事件
- TkinterDnD 事件不冒泡，只有鼠标直接悬停的 widget 才能接收 drop

### 3.4 拖拽和粘贴共用逻辑

- `_process_input_data(raw_data, paths_source)` 是核心识别方法
- `_on_global_drop(event)` → `str(event.data).strip()` + `event.data` 作为 paths_source
- `_on_paste(event)` → `self.clipboard_get().strip()` + `paths_source=None`
- 识别优先级：http/https 网址 → www. 网址 → 分号多路径 → 文件路径（.url/.exe/.lnk/.bat/.cmd/.py/其他）

### 3.5 Ctrl+V 粘贴

- `self.bind_all("<Control-v>", self._on_paste)` 在 `_build_ui` 末尾绑定
- `bind_all` 确保窗口内所有 widget 都能响应，不需要逐个绑定

## 4. 主控

单主控模式。主控职责见 `docs/master-controller-handbook.md`。

主控负责：对齐意图、定义边界、证据验收、反熵收束。
主控不是默认执行者。

## 5. 任务分型

- `exploratory`：探路、验证假设。不要求证据。
- `deliverable`：边界明确、要 claim done/fixed。走验证出口。

## 6. 护栏

- 危险命令拦截：`.agent/hooks/dangerous_cmd.py`
- 路径写入门控：`.agent/hooks/write_scope_gate.py`
- 受控执行：`.agent/scripts/safe_run.py`

## 7. 验证

交付验证入口：`.agent/scripts/verify_outputs.py`
治理体检入口：`.agent/scripts/check_governance.py`

验收基于真实证据，不接受表层成功信号。

## 8. 不做

- 多 session 协作
- 自动编排系统
- 完整 owner/subagent 编排
- mode engine / 多模型 verifier

## 9. 相关文档

- 架构：`docs/project-architecture.md`
- 验收标准：`docs/delivery-acceptance.md`
- 版本规划：`docs/version-plan.md`
- 主控手册：`docs/master-controller-handbook.md`

## 10. 常用命令

- 安装依赖：`pip install customtkinter pillow pystray tkinterdnd2 pyinstaller`
- 运行源码：`python run_desktop_tool.py`
- 运行测试：`python -m pytest tests/ -v`
- 打包：见第 2 节
