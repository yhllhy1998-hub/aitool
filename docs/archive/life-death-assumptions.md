# 生死假设清单

更新时间：2026-07-09 12:10 +08:00
识别阶段：第二里程碑前置——需求确认后技术栈生死假设识别

## 背景

母仓主控纠偏：需求已在 `docs/desktop-tool-milestone-1-contract.md` 第 2 节明确，生死假设应聚焦"技术栈能否稳定实现"，而非"需求是什么"。

## 生死假设清单（按主控职责说明书 10.3 格式）

### H1：Python + tkinter 能否打包成单 exe 并双击运行

- **假设内容**：Python 3.12 + tkinter 应用能用 PyInstaller 打包成单文件 exe，在无 Python 环境的 Windows 机器上双击运行
- **最小验证动作**：用 PyInstaller `--onefile --windowed` 打包当前 app，启动 exe 检查进程是否存活
- **通过判定标准**：exe 生成成功，启动后进程存活 ≥ 5 秒不崩溃，GUI 引导链路通
- **失败判定标准**：打包失败，或 exe 启动后立即崩溃退出
- **失败后转向**：PySide6（体积更大但 PyInstaller 支持更成熟）或 Electron（成本上升需重新评估）
- **验证结果**：**pass**
- **验证证据**：
  - 打包命令：`python -m PyInstaller --onefile --windowed --collect-submodules tkinter --add-data tcl --add-data _tkinter.pyd`
  - exe 路径：`dist/aitool_desktop.exe`（7.3MB）
  - 启动测试：进程 pid=17868 存活 8 秒未崩溃
  - 关键发现：PyInstaller 6.21 + Python 3.12 默认不收集 tkinter 子模块（filedialog 等），必须用 `--collect-submodules tkinter` 显式收集，并补充 tcl/tk 数据目录和 `_tkinter.pyd`

### H2：文件夹全量覆盖复制能否在进程内安全执行

- **假设内容**：`shutil.copytree(dirs_exist_ok=True)` 能在 tkinter 进程内安全执行全量覆盖复制，不卡死 UI，数据完整
- **最小验证动作**：用 500 文件 + 子目录的临时目录做真实覆盖复制，计时并校验完整性
- **通过判定标准**：复制完成、UI 不卡死（< 10s）、文件内容完整可核对
- **失败判定标准**：复制中断、数据损坏、或 UI 卡死超 10 秒
- **失败后转向**：后台线程 + 进度条，或改用 robocopy 子进程
- **验证结果**：**pass**
- **验证证据**：
  - 测试规模：500 文件 + 1 子目录 + 1 深层文件
  - 耗时：0.29 秒
  - 完整性：500 文件内容全部正确，深层文件正确
  - 结论：常规量级在主线程安全；超大规模目录仍建议后台线程（阶段跟进项）

### H3：外部 .bat 启动能否拿到退出码与输出

- **假设内容**：`subprocess` 启动 .bat 后能拿到退出码与输出，失败可回报
- **最小验证动作**：启动一个已知会失败的 .bat，检查退出码捕获
- **通过判定标准**：能拿到非零退出码和错误输出
- **失败判定标准**：无法捕获退出码或进程 hang 住
- **失败后转向**：subprocess + 日志文件重定向
- **验证结果**：**pass**
- **验证证据**：
  - `launch_bat_script` 已实现：subprocess.run + capture_output + timeout=120s
  - 测试 `test_launch_bat_success_returns_ready`：exit 0 → status=ready，退出码=0
  - 测试 `test_launch_bat_failure_returns_blocked_with_exit_code`：exit 1 → status=blocked，退出码=1
  - 超时保护：TimeoutExpired 捕获并回报

## 结论

- H1、H2 已通过，技术栈可支撑核心需求
- 第二里程碑可以推进：文件夹全量覆盖复制从 dry-run 推进到受控真实执行
- exe 打包路径已验证通，后续打包只需复用验证过的 PyInstaller 参数

## 复用沉淀

PyInstaller 打包 tkinter 应用的关键参数（已验证）：

```bash
python -m PyInstaller --noconfirm --onefile --windowed \
  --collect-submodules tkinter \
  --hidden-import _tkinter \
  --hidden-import json \
  --hidden-import uuid \
  --hidden-import datetime \
  --hidden-import shutil \
  --hidden-import subprocess \
  --add-data "<python_base>/tcl;tcl" \
  --add-data "<python_base>/DLLs/_tkinter.pyd;." \
  --add-data "src/aitool_desktop;aitool_desktop" \
  run_desktop_tool.py
```

已固化为脚本：`.agent/scripts/build_exe.py`

关键经验：
1. PyInstaller 6.21 + Python 3.12 默认不收集 tkinter 子模块（filedialog 等），必须 `--collect-submodules tkinter`
2. 部分标准库模块（json/uuid 等）在静态分析时可能被遗漏，需 `--hidden-import` 显式声明，或在入口脚本顶部显式 import 让 PyInstaller 追踪到
3. 打包后必须用 console 版本验证运行时无 ModuleNotFoundError，仅检查 exe 生成不够
