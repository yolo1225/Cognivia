# V2 Candidate RAG Development Ablation

- 算法版本：v2-candidate-1.0.0
- Embedding：qwen3.7-text-embedding
- Candidate 索引版本：`sha256:d704d3cf95e5cb11b8219d0fc1b767b84c669fb56cf162a70a3499a330c398c8``
- 知识数据版本：`sha256:837441b02400435bf83fc802d79b69a473b591fdd9062529e16154c22560c608``

| 模式 | Recall@12 | priority Top-12 | prerequisite | 来源完整率 | P95 |
|---|---:|---:|---:|---:|---:|
| semantic-only | 0.90625 | 0.857143 | 0.882353 | 1 | 288.409 ms |
| explicit-only | 0.4375 | 1 | 0.411765 | 1 | 279.275 ms |
| semantic+relation | 0.9375 | 0.857143 | 1 | 1 | 322.587 ms |
| full | 0.984375 | 1 | 1 | 1 | 310.809 ms |

- full 相对 semantic-only 的 Recall@12 提升：0.078125
