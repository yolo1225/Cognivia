# V2 Candidate RAG Evaluation

- 状态：evaluated
- 数据集：development（30 条）
- Embedding：qwen3.7-text-embedding
- 算法版本：v2-candidate-1.0.0
- 知识数据版本：`sha256:837441b02400435bf83fc802d79b69a473b591fdd9062529e16154c22560c608`
- 冻结验收哈希：`sha256:25ce6ac9c25158a88cb7eb92d0068bec769331714bfd53a87d39c9900157d589`
- 评测时间：2026-07-25T06:01:08.563778+00:00
- Candidate 索引版本：`sha256:d704d3cf95e5cb11b8219d0fc1b767b84c669fb56cf162a70a3499a330c398c8`

| 指标 | 分子 | 分母 | 比率 | 目标 |
|---|---:|---:|---:|---:|
| recall_at_12 | 58 | 64 | 0.90625 | >= 90% |
| priority_top_12_coverage | 18 | 21 | 0.857143 | >= 95% |
| prerequisite_coverage | 15 | 17 | 0.882353 | >= 90% |
| source_completeness | 360 | 360 | 1.0 | = 100% |

- 跨领域错误：0
- 延迟：P50 244.672 ms，P95 288.409 ms
- V2 契约非法输出：0

| 验收检查 | 结果 |
|---|---|
| recall_at_12 | passed |
| priority_top_12_coverage | failed |
| prerequisite_coverage | failed |
| source_completeness | passed |
| cross_domain_errors | passed |
| p95_latency_ms | passed |
| v2_contract_illegal_outputs | passed |

| 失败归因 | Case ID |
|---|---|
| ranking | RAG-DEV-002, RAG-DEV-014, RAG-DEV-018, RAG-DEV-026 |
| relation | RAG-DEV-010, RAG-DEV-029 |
- 失败 Case：RAG-DEV-002, RAG-DEV-010, RAG-DEV-014, RAG-DEV-018, RAG-DEV-026, RAG-DEV-029
