# 项目架构（AiTool）

## 1. 定位

AiTool 是一个 Windows 桌面工具，解决日常文件中转、文件夹覆盖复制、脚本启动和 SVN 操作的效率问题。

## 2. 代码结构

```text
src/aitool_desktop/
  app.py           # GUI 层：CustomTkinter + 拖放 + 托盘 + 热键
  operations.py    # 业务逻辑：文件夹复制、bat 启动、svn 操作
  models.py        # 数据模型：StationEntry、ActionReview、CustomModule
  storage.py       # 持久化：JSON 读写
run_desktop_tool.py  # PyInstaller 入口
```

## 3. 治理结构

```text
.agent/
  hooks/
    dangerous_cmd.py       # 危险命令拦截
    write_scope_gate.py    # 路径写入门控
  scripts/
    safe_run.py            # 受控执行入口
    verify_outputs.py      # 交付验证
    check_governance.py    # 治理体检
  state/
    active-task.yaml       # 当前任务
    runtime-state.json     # 运行时状态
    last-verification.json # 最近验证结果
  logs/
    trial-status.md        # 试跑状态
docs/
  master-controller-handbook.md  # 主控手册（轻量版）
  project-architecture.md        # 本文档
  windows-docking-lessons.md      # Windows Snap 隔离与顶部停靠经验
  version-plan.md                # 版本计划
  delivery-acceptance.md         # 交付验收标准
```

Windows 原生窗口样式、Snap 隔离和顶部停靠的实现判断见[专项经验文档](windows-docking-lessons.md)。

## 4. 入口

- 任务牌：`.agent/state/active-task.yaml`
- 执行入口：`.agent/scripts/safe_run.py`
- 验证入口：`.agent/scripts/verify_outputs.py`
- 治理体检：`.agent/scripts/check_governance.py`

## 5. 当前不做

- 多 session 协作（单主控模式）
- 自动编排系统
- 母仓级完整治理体系
