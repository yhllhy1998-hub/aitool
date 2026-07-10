# 自我治理架构

## 1. 为什么需要这一层

AiTool 是正式项目，但它同时承担 harness 实践沉淀的职责。
这意味着项目一边要交付真实需求，一边要防止规则、文档和状态逐渐漂移。

如果没有明确的治理层，最常见的失控方式有三种：

1. 外部技能越过本地规则，直接替代项目判断
2. 文档与状态落后于真实代码和交付结论
3. 反复出现的风险只停留在对话里，没有变成结构

## 2. 治理层负责什么

治理层的职责是：
- 识别文档、状态和实现之间的偏差
- 决定问题应该落在文档、状态、脚本还是测试
- 约束外部技能只做辅助，不替代项目治理
- 把稳定结论写回项目结构

## 3. 技能治理

`.agent/state/skill-governance.json` 用来回答三件事：

1. 本地哪些治理文件优先级最高
2. 外部技能的默认角色是什么
3. 哪些技能在什么情况下可以使用，哪些情况下不该介入

例如 `agent-workflow` 只能作为流程设计辅助，不能替代主控手册，也不能接管普通项目推进。

## 4. 项目实践登记

`.agent/state/practice-registry.json` 用来记录：

1. 项目当前的正式定位
2. 适用阶段与主要用途
3. 哪些文档承担定位说明
4. 当前治理约束是什么

这让项目定位不再只存在于口头说明里。

## 5. 治理检查

`.agent/scripts/check_governance.py` 负责校验：
- 必需治理文件是否存在
- 治理 JSON 是否结构有效
- 定位文档是否仍然可达
- 登记路径是否仍然存在

这样一来，治理层就不是“写了几段话”，而是可以被脚本验证的结构。

## 6. 纠偏闭环

本项目建议把每一轮真实推进都走成下面这个闭环：

1. 观察偏差
2. 判断偏差属于规则、实现还是状态问题
3. 把修正落到最小有效结构
4. 跑检查与测试
5. 把结论写回项目文档与跟踪记录

## 7. 当前已落地的抓手

当前已经落地：
- `docs/project-positioning.md`
- `docs/self-evolution-architecture.md`
- `docs/delivery-acceptance.md`
- `.agent/state/skill-governance.json`
- `.agent/state/practice-registry.json`
- `.agent/scripts/check_governance.py`
- `tests/test_governance_contracts.py`
- `tests/test_governance_runtime.py`

## 8. 一句话总结

> 自我治理不是“事后多写一份复盘”，而是把反复出现的偏差收成以后默认生效的项目结构。
