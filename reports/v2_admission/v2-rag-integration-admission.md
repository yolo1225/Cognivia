# V2 RAG Integration Admission

- RAG 准入：`rag_admitted`
- 统一 V2 运行链切换：`runtime_cutover_blocked`
- 生成时间：2026-07-25T09:44:22.511267+00:00

| 检查 | 结果 | 说明 |
|---|---|---|
| report_development | passed | requires V2 candidate, full mode, expected split, and expected case count |
| report_acceptance | passed | requires V2 candidate, full mode, expected split, and expected case count |
| report_all | passed | requires V2 candidate, full mode, expected split, and expected case count |
| acceptance_targets | passed | all frozen-acceptance V2 target checks must be true |
| report_identity | passed | consistent fields: all |
| all_report_aggregate | passed | all report must be the offline aggregate of development and frozen acceptance |
| candidate_manifest | passed | active collection manifest must match report index, model, data version, and domain |
| active_collection_metadata | passed | active collection metadata matches manifest and report |
| v1_non_live_regression | passed | recorded V1 regression must be passed and use the required non-live command |
| contract_baseline | passed | contract maintainer approval or an independently verified baseline is required |

## 阻塞项

- `v2_agent_chain_incomplete`：Profile, Generation, Review, Orchestrator, and Tutoring have no approved V2 runtime chain.
- `v2_graph_e2e_not_approved`：V2 graph, run-summary, SSE-summary, and human-recovery end-to-end tests are not approved.

## Candidate Evidence

- Active collection：`knowledge_ai_app_dev_candidate_20260725094109875892_ecba13ae`
- Index version：`sha256:d704d3cf95e5cb11b8219d0fc1b767b84c669fb56cf162a70a3499a330c398c8`
