# 版本计划（AiTool）

## 1. 当前状态

5 条需求已全部实现，EXE 已打包。当前处于交付验收阶段。

## 2. 已知问题

1. **嵌套路径复制 bug**：`execute_folder_copy` 不检查 target 是否为 source 子目录，可能导致递归复制
2. **2 个测试 failure**：嵌套路径测试 + svn 测试文本过时
3. **状态文件与实际脱节**：测试计数、task_id、路径均过时

## 3. 下一步

1. 修复嵌套路径 bug
2. 修复过时测试
3. 刷新状态文件
4. 用户验收
5. EXE 打包固化

## 4. 不做

- 不启用 oh-my-opencode-slim（项目规模不需要多智能体编排）
- 不引入母仓完整治理体系（当前轻量结构已够用）
- 不做自动 handoff / mode engine / 多模型 verifier
