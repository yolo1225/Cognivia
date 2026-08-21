# V3 RAG Integration Admission

- RAG 准入：`rag_admission_blocked`
- 统一 V3 运行链切换：`runtime_cutover_blocked`
- 生成时间：2026-08-15T05:12:14.254549+00:00

| 检查 | 结果 | 说明 |
|---|---|---|
| report_development | blocked | report is unavailable |
| report_acceptance | blocked | report is unavailable |
| report_all | blocked | report is unavailable |
| acceptance_targets | blocked | all frozen-acceptance V3 target checks must be true |
| report_identity | blocked | development, acceptance, and all reports are required |
| all_report_aggregate | blocked | all three reports are required |
| candidate_manifest | blocked | acceptance report is unavailable |
| v1_non_live_regression | blocked | recorded V1 regression must be passed and use the required non-live command |
| contract_baseline | blocked | contract maintainer approval or an independently verified baseline is required |

## 阻塞项

- `report_development`：report is unavailable
- `report_acceptance`：report is unavailable
- `report_all`：report is unavailable
- `acceptance_targets`：all frozen-acceptance V3 target checks must be true
- `report_identity`：development, acceptance, and all reports are required
- `all_report_aggregate`：all three reports are required
- `candidate_manifest`：acceptance report is unavailable
- `v1_non_live_regression`：recorded V1 regression must be passed and use the required non-live command
- `contract_baseline`：contract maintainer approval or an independently verified baseline is required
- `missing_development_report`：missing_development_report:/app/reports/rag_evaluation/v3-candidate-full-development.json
- `missing_acceptance_report`：missing_acceptance_report:/app/reports/rag_evaluation/v3-candidate-full-acceptance.json
- `missing_all_report`：missing_all_report:/app/reports/rag_evaluation/v3-candidate-full-all.json
- `missing_v1_regression`：missing_v1_regression:/app/reports/v3_admission/v1-non-live-regression.json
- `missing_contract_baseline`：missing_contract_baseline:/app/reports/v3_admission/contract-baseline.json
- `v3_agent_chain_incomplete`：Profile, Generation, Review, Orchestrator, and Tutoring have no approved V3 runtime chain.
- `v3_graph_e2e_not_approved`：V3 graph, run-summary, SSE-summary, and human-recovery end-to-end tests are not approved.
