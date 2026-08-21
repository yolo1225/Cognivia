# Agent Contract V6

V6 是当前唯一活动契约。V5 Schema 与文档仅用于读取历史运行记录，不得与 V6
指标或局部刷新结果混合计算。

## 质量语义

- 声明状态：`supported`、`contradicted`、`evidence_insufficient`、`unresolved`。
- 幻觉分子：`contradicted + unresolved`；证据不足单独报告，不计入幻觉分子。
- `evaluated_claim_count` 包含四种声明状态，幻觉率以全部已审核声明为分母。
- 证据不足、明确矛盾或仲裁后未解决均阻止受影响资源发布。
- 单份资源只对分配给自己的知识目标负责，并记录缺失目标；资源发布硬门禁只包括明确矛盾、证据不足和仲裁未解决。
- 包级 `primary_owner` 按实操指南、讲义、测验的确定性优先级保存；测验可重复评测目标，但不能替代主教学资源补齐覆盖。
- 难度匹配和90%覆盖阈值在学习包及正式评测层面执行；包级不足时只修订贡献缺口的资源。

## 刷新和修订

- 首次生成保存 `resource_knowledge_targets`；局部刷新必须继承，不得重新分配。
- V5学习包必须完整重新生成后才能进入V6局部刷新。
- 自动修订使用类型化字段补丁，只能修改审核点名的路径；列表顺序、ID、来源及未点名字段保持不变。
- 最多自动修订两轮；未通过资源不发布。

可执行事实来源为 `backend/app/agents/contracts.py`、`backend/app/agents/state.py`、
`backend/app/agents/contract_adapters.py` 以及 `docs/contracts/v6/` 生成物。
