# 项目架构说明

## 1. 项目类型

AiTool 是一个正式项目，也是一个 harness 实践项目。
它不是纯粹的模板仓，也不是临时试验目录。
本项目的结构设计，直接服务于真实需求承接、执行控制、验证与收口。

项目 owner：`Codex`
指定主控线程：`019f3a9b-9dfd-74a0-97eb-820fb8f94ac5`

## 2. 架构目标

AiTool 当前维护五层结构：

1. 主控层
2. 执行层
3. 证据层
4. 治理层
5. 项目推进层

前四层是运行骨架，第五层用于承接正式项目的阶段计划、验收口径与状态收口。

## 3. 主控层

职责：
- 定义当前任务与阶段
- 定义任务类型
- 定义写入边界
- 识别高风险动作
- 决定是否下放执行
- 定义验收口径

主要文件：
- `.agent/state/active-task.yaml`
- `.agent/state/controller-registry.json`
- `docs/master-controller-handbook.md`

## 4. 执行层

职责：
- 跑命令
- 改文件
- 生成产物

主要文件：
- `.agent/scripts/safe_run.py`
- `.agent/hooks/dangerous_cmd.py`
- `.agent/hooks/write_scope_gate.py`
- `.agent/common/task_state.py`

其中 `.agent/common/task_state.py` 是当前本地低依赖实现，用于保证状态文件读取不被外部依赖卡住。

## 5. 证据层

证据层只服务 `deliverable` 任务。

职责：
- 记录交付级验证结果
- 把最近一次 claim 级结论写回项目状态

主要文件：
- `.agent/scripts/verify_outputs.py`
- `.agent/state/last-verification.json`
- `.agent/state/runtime-state.json`

## 6. 治理层

职责：
- 保持本地治理文件优先级清晰
- 约束外部技能的使用边界
- 记录本项目的实践定位与适用阶段
- 把反复出现的偏差收束成结构

主要文件：
- `.agent/state/skill-governance.json`
- `.agent/state/practice-registry.json`
- `.agent/scripts/check_governance.py`
- `docs/self-evolution-architecture.md`
- `docs/project-positioning.md`

## 7. 项目推进层

职责：
- 维护版本路线与阶段目标
- 定义交付与落地验收口径
- 记录当前轮次状态与阻塞

主要文件：
- `docs/version-plan.md`
- `docs/delivery-acceptance.md`
- `.agent/logs/trial-status.md`

## 8. 仓库结构

```text
AGENTS.md
.gitignore
docs/
  project-positioning.md
  master-controller-handbook.md
  project-architecture.md
  self-evolution-architecture.md
  version-plan.md
  delivery-acceptance.md
.agent/
  common/
    task_state.py
  hooks/
    dangerous_cmd.py
    write_scope_gate.py
  logs/
    trial-status.md
  scripts/
    check_governance.py
    safe_run.py
    verify_outputs.py
  state/
    active-task.yaml
    controller-registry.json
    runtime-state.json
    last-verification.json
    skill-governance.json
    practice-registry.json
tests/
```

`.agent/scripts/` 下可能还会有项目临时脚本，但它们不属于当前最小稳定骨架。

## 9. 状态文件职责

### `.agent/state/active-task.yaml`

主控任务卡。
当前至少表达：
- `task_id`
- `current_table`
- `stage`
- `status`
- `task_type`
- `actor`
- `controller_thread_id`
- `allow_write`
- `next_step`
- `override`

### `.agent/state/controller-registry.json`

记录：
- 项目 owner
- 项目定位
- 指定主控线程
- 当前目标

### `.agent/state/runtime-state.json`

记录：
- 最近执行命令
- 失败次数
- 最近一次验证结果

### `.agent/state/last-verification.json`

记录最近一次 `deliverable` 级验证结果。

### `.agent/state/skill-governance.json`

定义：
- 本地治理文件优先级
- 外部技能的默认角色
- 技能何时可用、何时不该介入

### `.agent/state/practice-registry.json`

记录：
- 项目实践定位
- 适用阶段
- 关键定位文档
- 当前治理约束

## 10. 护栏设计

### 危险命令 gate

优先拦截：
- `rm -rf`
- `Remove-Item -Recurse -Force`
- `del /s /q`
- `rmdir /s /q`
- `git reset --hard`
- `git clean -fd`
- `git push --force`

### 路径 gate

默认重点保护：
- `assets/`
- `baseline/`
- `fixtures/`
- `samples/`
- `input/`
- `inputs/`
- `templates/`
- `source-of-truth/`

主控保留边界定义权，不受普通路径 gate 直接限制。
灾难性命令仍然被全局拦截。

## 11. 当前原则

1. 真实需求优先
2. 结构为交付服务
3. 只有 `deliverable` 任务进入证据出口
4. 治理结论必须写回项目
5. 依赖保持尽量轻量

## 12. 当前不做

以下内容明确后置：
- 自动 handoff
- retro 或路径结案系统
- mode engine
- 多模型 verifier
- 完整 owner / subagent 自动编排
