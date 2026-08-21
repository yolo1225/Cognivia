# Agent Contract V3

本文档与 `backend/app/agents/contracts.py`、`backend/app/agents/state.py`、`docs/contracts/v3/` 共同构成正式契约来源。所有生产节点、消息、任务事件和新测试统一使用 `agent-contract-v3`，不提供旧版本 Python 导入兼容层。

## 运行模型

`build_learning_graph()` 是唯一顶层图构建器。首次生成与反馈更新共用同一图，`generation_tasks.public_id` 同时作为公开 `task_id` 和 LangGraph `thread_id`。State 只保存结构化契约对象，各节点只能写入自己拥有的输出字段。

生成前必须满足证据前置条件：`GenerationRequirements.required_knowledge_ids` 必须全部存在于紧邻的 `RetrieveKnowledgeOutput.covered_knowledge_ids`，并且每个目标至少对应一个检索片段。适配器不得静默删除无证据目标，也不得让生成模型补写无来源内容。检索预算必须覆盖最多 10 个生成目标，并保持在既有 12 个片段上限内。

主链为：

```text
prepare_task -> analyze_profile -> retrieve_knowledge
-> generate_resource -> review_resource -> finalize_task
```

自然语言反馈先经过 `interpret_feedback`；人工审批经过 `human_review`。修订沿原任务线程回到检索节点，最多自动修订两轮。

## Agent 边界

- Orchestrator：准备任务、路由、修订与最终决策，不生成专业内容。
- Profile Analysis：根据诊断与有效反馈证据形成画像判断和检索计划。
- Knowledge Retrieval：只返回知识库内可追溯的知识块和来源。
- Content Generation：仅根据画像、检索结果和资源目标生成结构化资源。
- Review and Validation：独立检查事实、来源、难度和覆盖率，并执行双模型仲裁。
- Tutoring：解释自然语言反馈，给出证据与推荐动作，不直接覆盖画像。

节点输入输出模型、枚举、必填规则和消息结构以生成的 JSON Schema 为准。Agent 消息包含 sender、receiver、message type、payload、timestamp 和 task/session ID。

## 覆盖职责

- `lecture`：概念、原理和常见误区。
- `practice_guide`：操作、配置、验证和排错。
- `graded_quiz`：覆盖任务全部核心知识，并包含基础、提升、挑战三个层级。

检索完成后，适配器只分配一次 `resource_knowledge_targets`。单份资源以自己的责任集合为分母，覆盖率阈值为 90%；学习包以所有资源有效覆盖的并集为分子、任务目标集合为分母，阈值同为 90%。

## 可验证声明与修订

生成资源通过 `knowledge_coverage` 声明“知识点 -> 来源引用”，但该声明本身不构成覆盖。审核前从 `structured_content` 确定性拆分原子事实，并按 `resource_type + field_path + normalized_claim` 生成稳定 `claim_id`。两个审核通道必须接收顺序和 `claim_set_hash` 完全相同的事实集合；遗漏、新增或重复 claim 时只允许一次定向结构修复。

`FactCheck.verdict` 使用 `supported`、`contradicted`、`unable_to_determine` 三态。历史 `supported/determinable` 字段仍可读取并归一化，但新输出必须写 `verdict`。`unable_to_determine` 表示证据未提及、被裁剪或不足，不计为事实错误，但来源追溯不通过；明确相反证据才允许判为 `contradicted`。

审核报告输出每份资源的 target/covered/missing 集合和三类 claim ID 清单；学习包继续按各资源实质覆盖并集计算。知识点只有在目标范围内、存在非模板教学内容、内容绑定同知识点证据且至少一个对应 claim 最终为 `supported` 时才算覆盖。修订计划携带失败的资源类型、claim ID、字段路径以及 missing/preserve 集合，已通过资源不得重做。

事实和来源由 primary/secondary 两个独立模型通道审核，分数由系统根据三态结果计算，模型自报分数仅供解释。两路一致的 `unable_to_determine` 直接进入定向修订；只有同一 claim 的 verdict 不一致时，审核节点才发出 `source_verification`，由知识检索智能体补充证据并只复审争议 claim。补充来源可判断真假，但资源未引用该来源前仍不能通过追溯。复审后仍冲突才进入人工复核。

`content_md` 只由 `structured_content` 确定性渲染，用于展示、导出和持久化；生成模型不生成第二份正文，审核载荷也不包含 `content_md`。`RetrievedChunk.content_checksum` 与 `source_locator` 为种子、手动新增和未来导入提供统一的内容及来源定位。

## 持久化与发布

- `generation_tasks.package_coverage_json`
- `learning_resources.knowledge_coverage_json`
- `review_reports.target_knowledge_ids_json`
- `review_reports.covered_knowledge_ids_json`
- `review_reports.missing_knowledge_ids_json`

只有全部资源审核通过且学习包覆盖率通过时，自动模式才能完成并发布。拒绝或等待人工复核的资源不得进入学习者默认可见列表。既有数据库历史记录不回写，新任务和新 Agent Run 必须记录 V3 版本。

## Schema 与示例

执行 `python -m app.scripts.export_agent_contract_v3` 生成并校验：

- `agent-contract-v3.schema.json`
- Agent 消息示例
- 首次生成与反馈无变化示例
- 人工复核示例
- 三类资源示例
