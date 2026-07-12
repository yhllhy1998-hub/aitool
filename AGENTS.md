# AGENTS.md

AiTool 是一个 Windows 桌面效率工具，解决日常文件中转、文件夹覆盖复制、脚本启动和 SVN 操作的效率问题。

## 1. 项目结构

- 代码：`src/aitool_desktop/`（app / operations / models / storage）
- 入口：`run_desktop_tool.py`
- 治理：`.agent/`（轻量，单主控模式）
- 文档：`docs/`

## 2. 主控

单主控模式。主控职责见 `docs/master-controller-handbook.md`。

主控负责：对齐意图、定义边界、证据验收、反熵收束。
主控不是默认执行者。

## 3. 任务分型

- `exploratory`：探路、验证假设。不要求证据。
- `deliverable`：边界明确、要 claim done/fixed。走验证出口。

## 4. 护栏

- 危险命令拦截：`.agent/hooks/dangerous_cmd.py`
- 路径写入门控：`.agent/hooks/write_scope_gate.py`
- 受控执行：`.agent/scripts/safe_run.py`

## 5. 验证

交付验证入口：`.agent/scripts/verify_outputs.py`
治理体检入口：`.agent/scripts/check_governance.py`

验收基于真实证据，不接受表层成功信号。

## 6. 不做

- 多 session 协作
- 自动编排系统
- 完整 owner/subagent 编排
- mode engine / 多模型 verifier

## 7. 相关文档

- 架构：`docs/project-architecture.md`
- 验收标准：`docs/delivery-acceptance.md`
- 版本规划：`docs/version-plan.md`
- 主控手册：`docs/master-controller-handbook.md`
- 试错日志：`.agent/logs/trial-status.md`
- 活动任务：`.agent/state/active-task.yaml`
- 运行时状态：`.agent/state/runtime-state.json`
- 最近验证：`.agent/state/last-verification.json`

## 8. 常用命令

- 安装依赖：`pip install PyQt5 pyinstaller`
- 运行测试：`python -m pytest tests/ -v`
- 构建可执行：`pyinstaller --noconfirm --onefile --windowed --name "AiTool桌面工具" run_desktop_tool.py`
