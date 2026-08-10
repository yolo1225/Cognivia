# V2 Candidate RAG Evaluation

- 状态：evaluated
- 数据集：development（30 条）
- Embedding：qwen3.7-text-embedding
- 算法版本：v2-candidate-1.0.0
- 知识数据版本：`sha256:837441b02400435bf83fc802d79b69a473b591fdd9062529e16154c22560c608`
- 冻结验收哈希：`sha256:25ce6ac9c25158a88cb7eb92d0068bec769331714bfd53a87d39c9900157d589`
- 评测时间：2026-07-25T06:03:58.999970+00:00
- Candidate 索引版本：`sha256:d704d3cf95e5cb11b8219d0fc1b767b84c669fb56cf162a70a3499a330c398c8`

| 指标 | 分子 | 分母 | 比率 | 目标 |
|---|---:|---:|---:|---:|
| recall_at_12 | 28 | 64 | 0.4375 | >= 90% |
| priority_top_12_coverage | 21 | 21 | 1.0 | >= 95% |
| prerequisite_coverage | 7 | 17 | 0.411765 | >= 90% |
| source_completeness | 28 | 28 | 1.0 | = 100% |

- 跨领域错误：0
- 延迟：P50 218.402 ms，P95 279.275 ms
- V2 契约非法输出：0

| 验收检查 | 结果 |
|---|---|
| recall_at_12 | failed |
| priority_top_12_coverage | passed |
| prerequisite_coverage | failed |
| source_completeness | passed |
| cross_domain_errors | passed |
| p95_latency_ms | passed |
| v2_contract_illegal_outputs | passed |

| 失败归因 | Case ID |
|---|---|
| ranking | RAG-DEV-001, RAG-DEV-003, RAG-DEV-008, RAG-DEV-011, RAG-DEV-013, RAG-DEV-015, RAG-DEV-016, RAG-DEV-018, RAG-DEV-030 |
| relation | RAG-DEV-002, RAG-DEV-005, RAG-DEV-006, RAG-DEV-007, RAG-DEV-009, RAG-DEV-010, RAG-DEV-012, RAG-DEV-014, RAG-DEV-017, RAG-DEV-019, RAG-DEV-020, RAG-DEV-021, RAG-DEV-022, RAG-DEV-023, RAG-DEV-024, RAG-DEV-025, RAG-DEV-026, RAG-DEV-027, RAG-DEV-028, RAG-DEV-029 |
- 失败 Case：RAG-DEV-001, RAG-DEV-002, RAG-DEV-003, RAG-DEV-005, RAG-DEV-006, RAG-DEV-007, RAG-DEV-008, RAG-DEV-009, RAG-DEV-010, RAG-DEV-011, RAG-DEV-012, RAG-DEV-013, RAG-DEV-014, RAG-DEV-015, RAG-DEV-016, RAG-DEV-017, RAG-DEV-018, RAG-DEV-019, RAG-DEV-020, RAG-DEV-021, RAG-DEV-022, RAG-DEV-023, RAG-DEV-024, RAG-DEV-025, RAG-DEV-026, RAG-DEV-027, RAG-DEV-028, RAG-DEV-029, RAG-DEV-030
