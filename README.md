# 🚀 AiTool — 极速文件资产中转站与多功能效率启动器

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-orange.svg)]()
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)]()

`AiTool` 是一款专为 Windows 桌面效率而生的极客、绿色的**资产中转站、脚本运行器、应用快捷方式执行器与网页快捷通道**。
它采用 **CustomTkinter** 打造现代化暗黑毛玻璃感 UI，并集成 **tkinterdnd2** 实现了全界面无缝的全局拖放流操作。

体积轻量（编译后仅 **14.94MB**），支持系统托盘、全局快捷键隐藏/唤醒、开机自启动设置。

---

## ✨ 核心特性

- **📂 全局万物皆可拖放 (`Unified Drag-and-Drop`)**
  - **`.exe / .lnk`** ➔ 自动创建“启动应用”快捷模块。
  - **`.bat / .cmd / .py`** ➔ 自动创建“运行脚本”极速模块。
  - **网页链接 / `.url`** ➔ 自动提取或解包，创建“一键打开网页”模块。
  - **其他任意格式文件/文件夹** ➔ 智能暂存至“中转站”中。

- **📦 极客文件资产中转站 (`Asset Staging Station`)**
  - **拖入暂存，拖出提取**：拖入任意文件收藏，长按可直接将文件跨程序拖出到 Windows 资源管理器或聊天软件中进行复制。
  - **🔍 低调路径悬停显示**：鼠标悬停在暂存文件上时，下方状态栏会以不显眼的暗灰色字体低调呈现其绝对路径，有效防混淆。
  - **🎯 右键快速定位**：在暂存文件上点击**鼠标右键**，自动打开其所在文件夹并在 Windows 文件资源管理器中**精准高亮选中**该文件。
  - **双击打开**：双击直接调用系统关联程序打开该文件。

- **⚡ 多通道高频动作（快捷卡片）**
  - **多路径覆盖复制 (Folder Copy)**：独家支持配置**双通道路径覆盖**（最多 4 个源-目的对应路径），一键静默多路同步，并配备炫酷的 HUD 进度条弹窗反馈。
  - **SVN 自动提交 (SVN Commit)**：一键唤起 SVN 提交面板，自动关联，提高版本控制流效率。
  - **动作快速自定义**：卡片右侧内置精美 `>` 按钮，可随时自定义、删除和编辑卡片。

- **🛸 极致优雅的后台常驻**
  - **全局热键（Alt + A）**：在任意界面随时按下 `Alt + A` 即可闪现/退避隐藏工具窗口。
  - **精致系统托盘**：关闭窗口时自动隐藏至右下角系统托盘（搭载科技感微光火箭图标），支持开机自启动。
  - **始终置顶 (Always on Top)**：一键锁定置顶，成为随时待命的屏幕侧边效率助手。

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
2. 安装依赖依赖项：
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
