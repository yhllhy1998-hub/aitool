# AiTool 桌面工具

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-orange.svg)]()
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)]()

AiTool 是一个 Windows 桌面效率工具，用于临时收纳文件和文件夹、快速打开或定位资源，以及通过快捷动作执行常用脚本、应用和网页操作。它支持拖放和剪贴板输入，并可收起到屏幕顶部或隐藏到系统托盘。

---

## 使用说明

### 输入与资源管理

- 窗口显示时，可以把网址、脚本、应用、普通文件或文件夹拖入窗口。
- `Ctrl+V` 可以粘贴网址或路径。托盘隐藏时主窗口不接收拖放，恢复窗口后即可继续使用。
- 中转站条目支持双击打开、右键定位，以及拖出复制。
- 快捷动作支持添加、编辑、删除和执行。

### 窗口行为

- 默认窗口大小为 `320 × 640`，默认位置是当前主显示器工作区左上角；已有有效窗口几何会优先恢复。
- 窗口宽度固定为 `320px`，不能调整宽度。窗口底部、状态栏上方的纵向拖拽区域可以调整高度，调整后的高度会保存，关闭再打开时恢复。
- 将窗口拖到屏幕顶部并停留会停靠。鼠标离开后窗口自动收起，只露出约 `30px` 的横条；鼠标移入横条即可展开。
- 顶部收起和隐藏到系统托盘是两种独立方式。
- `Alt+A` 的行为取决于当前状态：正常显示窗口时隐藏到 Windows 右下角系统托盘；托盘隐藏时恢复窗口；顶部横条收起时展开顶部窗口。

### 系统托盘、主题与配置

- 点击关闭按钮会隐藏到系统托盘，不是彻底退出。托盘菜单提供“打开 AiTool”“设置中心”“开机自启动”切换和“彻底退出”。
- 主题按钮可以切换亮色/暗色，置顶按钮可以切换窗口置顶。
- 配置保存在 `%APPDATA%\AiTool\`；源码运行时保存在项目 `data` 目录。更新 EXE 不会覆盖已有用户配置。

---

## 核心功能

- **📂 拖放与粘贴**
  - 支持网址、脚本、应用、普通文件和文件夹，也可以使用 `Ctrl+V` 粘贴网址或路径。

- **📦 文件中转站**
  - 支持双击打开、右键定位和拖出复制。

- **⚡ 快捷动作**
  - 支持添加、编辑、删除和执行常用动作。

---

## 🛠️ 项目架构

```text
AiTool/
├── src/
│   └── aitool_desktop/
│       ├── app.py           # 核心桌面端 UI 控制、事件监听与托盘管理
│       ├── models.py        # 动作卡片与中转站核心数据模型定义
│       ├── operations.py    # 双通道复制、SVN 触发等后台核心物理操作
│       └── storage.py       # JSON 存储层（记录您的个性化卡片和暂存文件）
├── run_desktop_tool.py      # 项目程序运行入口
├── tests/                   # 自动化测试用例
└── .gitignore               # 精简的开源过滤规则
```

---

## 🚀 快速开始

### 方式一：源码运行

1. 确保安装了 Python 3.10+ 环境。
2. 安装依赖项：
   ```bash
   pip install customtkinter tkinterdnd2 pystray Pillow keyboard
   ```
3. 运行程序：
   ```bash
   python run_desktop_tool.py
   ```

### 方式二：编译打包 (PyInstaller + UPX)

如果您想将其编译打包为精简、绿色的单文件 `AiTool.exe`，我们已经完成了极致的体积优化过滤（排除 numpy, scipy 等大体积包），您可以直接运行：

```bash
pyinstaller --clean --noconfirm --onefile --windowed --add-data "src/aitool_desktop;src/aitool_desktop" --exclude-module numpy --exclude-module matplotlib --exclude-module scipy --exclude-module xml --exclude-module multiprocessing --name "AiTool" run_desktop_tool.py
```

---

## 📝 开源协议

本项目采用 [MIT License](LICENSE) 开源协议。欢迎提交 Issue 与 Pull Request！
