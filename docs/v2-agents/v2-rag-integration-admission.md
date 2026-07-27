# V2 RAG 检索集成准入

## 结论边界

阶段五只提供统一 V2 运行链的准入证据和接线清单。它不修改 `build_learning_graph()`、V1 retrieval node、worker、SSE 或冻结 V2 契约。

准入结果固定分成两个状态：

- `rag_admitted`：候选 V2 检索索引和阶段四证据可进入后续 V2 图接线工作。
- `runtime_cutover_blocked`：现有运行链仍是 legacy State/contract，且 Profile、Generation、Review、Orchestrator、Tutoring 尚未形成经端到端验证的 V2 图；不得切换生产任务。

若 candidate manifest、V1 非 live 回归记录或契约负责人基线签字缺失，结果必须是 `rag_admission_blocked / runtime_cutover_blocked`。阶段四指标全绿本身不代表系统已经切换。

## 只读校验

运行：

```powershell
cd backend
python -m app.scripts.validate_v2_rag_admission --json
```

校验器读取以下证据，输出 `reports/v2_admission/v2-rag-integration-admission.json` 和 `.md`。它不会调用 embedding、写数据库或切换 collection；只会读取 manifest 指向 collection 的元数据以验证 index/model/data version。

| 证据 | 默认位置 | 必须满足 |
|---|---|---|
| full development | `reports/rag_evaluation/v2-candidate-full-development.json` | `v2-candidate`、`full`、30 例 |
| full acceptance | `reports/rag_evaluation/v2-candidate-full-acceptance.json` | `v2-candidate`、`full`、20 例且所有目标通过 |
| full all | `reports/rag_evaluation/v2-candidate-full-all.json` | 50 例，且为前两者离线汇总 |
| candidate manifest | `storage/candidate-index/ai_app_dev/manifest.json` | active collection 元数据与报告的 index/model/data version 一致 |
| V1 回归记录 | `reports/v2_admission/v1-non-live-regression.json` | 记录 `pytest tests/contracts tests/unit tests/integration -m "not live"` 的通过结果 |
| 契约基线签字 | `reports/v2_admission/contract-baseline.json` | 契约负责人批准，或提供独立核验基线 |

三份报告的 `embedding_model`、`algorithm_version`、`index_version`、`source_data_version` 与 `acceptance_cases_sha256` 必须完全相同。验收报告必须通过 Recall@12、priority Top-12、prerequisite、来源完整率、跨领域错误、P95 和 V2 契约非法输出全部检查。

V1 回归记录格式：

```json
{
  "schema_version": "v1-non-live-regression-v1",
  "status": "passed",
  "failed": 0,
  "command": "pytest tests/contracts tests/unit tests/integration -m \"not live\"",
  "recorded_at": "2026-07-25T00:00:00+00:00"
}
```

契约基线签字格式：

```json
{
  "schema_version": "v2-contract-baseline-attestation-v1",
  "status": "approved",
  "approved_by": "contract-maintainer",
  "baseline_ref": "<verified-commit-or-review-record>",
  "approved_at": "2026-07-25T00:00:00+00:00"
}
```

当前工作区的冻结契约文件存在待契约负责人处理的改动。未提供上述签字或独立基线前，校验结果必须保留 `contract_baseline` 阻塞项。

## 未来接线映射

未来统一 V2 graph 由新的 V2 runtime adapter 负责，不能由现有 `app.agents.nodes` 或 V1 worker 导入 V2 retrieval。下表是接线设计，不是当前运行路径。

| 方向 | V1 数据 | V2 契约字段 | 未来适配责任 | 调用时机 | 失败行为 |
|---|---|---|---|---|---|
| V1 task scope | `task_id` | `RetrieveKnowledgeInput.task_id`、`context.task_id` | V2 orchestrator adapter | V2 `analyze_profile` 后 | 标记任务失败，不复用旧 task 内半成品 |
| V1 request context | `session_id`、`learner_id`、`profile_id`、`domain_code`、`resource_types`、`learning_goal`、反馈引用 | `RetrieveKnowledgeInput.context` | V2 task-context adapter | 构造 V2 retrieval input | 缺少必填字段即受控失败 |
| V1 profile | `profile`、`profile_result` | `RetrieveKnowledgeInput.profile: ProfileSnapshot` | V2 profile adapter | 在 retrieval 前完成结构化画像转换 | 不以字典默认值替代；失败即停止 |
| V1 plan | `retrieval_plan` | `RetrieveKnowledgeInput.retrieval_plan: RetrievalPlan` | V2 profile/orchestrator adapter | 画像输出后 | 校验 ID、枚举、Top-12 上限；失败即停止 |
| V1 revision | `revision_plan` | `RetrieveKnowledgeInput.revision_plan` | V2 orchestrator adapter | 修订循环才传入 | 无有效修订计划时传 `null` |
| V1 action | `recommended_action`、`trigger_type` | `RetrieveKnowledgeInput.purpose` | V2 orchestrator adapter | 构造 request 时 | 映射不确定即停止，不猜测 purpose |
| V2 evidence | `RetrieveKnowledgeOutput.chunks` | `GenerateResourceInput.retrieved_chunks` | V2 generation adapter | V2 retrieval 成功后 | 空 chunks 或 required ID 缺失时停止生成 |
| V2 source control | chunk `source.source_ref_id` | `GenerationRequirements.source_whitelist` | V2 generation adapter | 构造 generation input | 只允许已检索来源；校验失败即停止 |
| V2 coverage | `covered_knowledge_ids`、`missing_knowledge_ids`、`warnings` | generation requirements 与运行摘要 | V2 orchestrator adapter | 检索后、生成前 | 缺失必需知识或 index warning 时任务失败并等待管理员决定 |

`RetrieveKnowledgeOutput` 的 `query_text`、chunk 正文和相似度只在受控节点输入中使用；它们不进入普通运行摘要或 SSE。

## 运行依赖和隐私边界

V2 节点启用前，每个任务开始时必须锁定 candidate active collection、index version、manifest、embedding model，并检查：

- `OPENAI_API_BASE`
- `OPENAI_API_KEY`
- `EMBEDDING_MODEL`
- Chroma 与 MySQL 可用性
- candidate manifest 与 active collection 元数据

任一检查失败时，V2 节点受控失败，保留 V1 演示链可供管理员另行选择。不得静默回退、不得在同一个任务中混用 V1 mock 索引和 V2 candidate 索引。

接线后，`agent_runs`、`agent_messages` 与 SSE 摘要仅记录：`task_id`、节点、collection/index version、模型名、chunk 数、covered/missing ID、warning 类别、耗时和决定。禁止写入完整查询、chunk 正文、向量、完整画像或完整资源。

## 切换和回退责任

只有阶段五 RAG 准入通过，且 Profile、Generation、Review、Orchestrator、Tutoring 的独立 V2 实现、契约测试、V2 图端到端适配、运行摘要、SSE 摘要和人工复核恢复测试全部通过后，才可由负责人启用统一 V2 graph feature flag。

每个任务开始后固定 retrieval engine、index version 与 manifest。V2 retrieval 失败时任务标记为失败；管理员决定重试或在新的任务中切回 V1。禁止单任务内自动回退或混链。
