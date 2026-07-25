# V2 Candidate RAG Evaluation

- 状态：evaluated
- 数据集：acceptance（20 条）
- Embedding：qwen3.7-text-embedding
- 算法版本：v2-candidate-1.0.0
- 知识数据版本：`sha256:837441b02400435bf83fc802d79b69a473b591fdd9062529e16154c22560c608`
- 冻结验收哈希：`sha256:25ce6ac9c25158a88cb7eb92d0068bec769331714bfd53a87d39c9900157d589`
- 评测时间：2026-07-25T06:18:30.287167+00:00
- Candidate 索引版本：`sha256:d704d3cf95e5cb11b8219d0fc1b767b84c669fb56cf162a70a3499a330c398c8`

| 指标 | 分子 | 分母 | 比率 | 目标 |
|---|---:|---:|---:|---:|
| recall_at_12 | 45 | 47 | 0.957447 | >= 90% |
| priority_top_12_coverage | 16 | 16 | 1.0 | >= 95% |
| prerequisite_coverage | 13 | 13 | 1.0 | >= 90% |
| source_completeness | 240 | 240 | 1.0 | = 100% |

- 跨领域错误：0
- 延迟：P50 257.582 ms，P95 335.103 ms
- V2 契约非法输出：0

| 验收检查 | 结果 |
|---|---|
| recall_at_12 | passed |
| priority_top_12_coverage | passed |
| prerequisite_coverage | passed |
| source_completeness | passed |
| cross_domain_errors | passed |
| p95_latency_ms | passed |
| v2_contract_illegal_outputs | passed |

| 失败归因 | Case ID |
|---|---|
| ranking | RAG-ACC-009, RAG-ACC-017 |
- 失败 Case：RAG-ACC-009, RAG-ACC-017
