# AGENTS.md

AiTool 是一个**正式项目**，同时也是一个 **harness 实践项目**。

它的首要任务不是充当模板试验场，而是以真实需求为牵引，沉淀一套能稳定承接、推进、验证和收口交付的工程结构。

项目 owner：`Codex`
指定主控线程：`019f3a9b-9dfd-74a0-97eb-820fb8f94ac5`

## 1. 项目目标

当前目标是：

> 以正式项目方式承接真实需求，并在交付过程中沉淀可复用的 harness 实践。

真正的成功标准不是“文档看起来完整”，而是：
- 用户目标被正确收束
- 高风险动作被提前识别
- 执行过程受护栏约束
- 交付结果可验证、可继续接手

未来如果要把稳定实践收束成文件包、skill 或插件，那是后续沉淀方向，不是当前项目主身份。

## 2. 当前范围

AiTool 当前聚焦五件事：

1. 主控任务卡
2. 执行层护栏
3. 交付证据出口
4. 项目治理与规则收口
5. 面向真实需求的阶段推进

当前明确**不做**：
- 自动 handoff
- retro 系统
- mode engine
- 多模型 verifier
- 完整 owner / subagent 自动编排

## 3. 主控层

主控负责：
- 识别当前任务与阶段
- 对齐真实用户目标
- 定义任务类型与写入边界
- 识别高风险动作
- 决定哪些动作下放执行
- 定义验收口径
- 做最小而明确的收口

主控不是默认执行者。

## 4. 执行层

执行层负责：
- 跑命令
- 改文件
- 生成产物
- 回报验证结果

执行层受 `.agent/` 约束。
AiTool 目前保留 `.agent/common/task_state.py` 这层低依赖读取实现，用来保证状态文件在缺少额外依赖时仍可被稳定读取。

## 5. 任务分型

### exploratory

用于：
- 需求澄清
- 路径比较
- 风险验证
- 边界探查

这类任务默认不要求 pass/fail 级证据。

### deliverable

用于：
- 范围明确的里程碑交付
- 需要 claim `done`、`fixed` 或 `passed` 的任务
- 需要明确验收与验证结果的实现工作

只有这类任务进入验证出口。

## 6. 项目原则

- 真实需求优先
- 结构为交付服务
- 高风险动作先列清单再推进
- 变更保持最小且明确
- 稳定经验可以沉淀，但不反客为主

## 7. 当前结构

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
  state/
  hooks/
  scripts/
  logs/
tests/
```

## 8. 主入口

- 任务卡：`.agent/state/active-task.yaml`
- 主控登记：`.agent/state/controller-registry.json`
- 技能治理：`.agent/state/skill-governance.json`
- 项目实践登记：`.agent/state/practice-registry.json`
- 安全执行入口：`.agent/scripts/safe_run.py`
- 验证入口：`.agent/scripts/verify_outputs.py`
- 治理检查：`.agent/scripts/check_governance.py`

一句话记住：

> AiTool 用正式项目标准推进真实交付，同时把稳定做法沉淀为可复用的 harness 实践。
