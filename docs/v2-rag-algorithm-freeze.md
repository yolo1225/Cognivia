# V2 RAG 算法冻结记录

- 冻结时间：2026-07-25T10:14:43.2609405Z
- 算法版本：`v2-candidate-1.0.0`
- 实现基线：`04fac55` (`freeze v2 rag evaluation and admission`)
- Embedding 模型：`qwen3.7-text-embedding`
- Candidate active collection：`knowledge_ai_app_dev_candidate_20260725094109875892_ecba13ae`
- Candidate index version：`sha256:d704d3cf95e5cb11b8219d0fc1b767b84c669fb56cf162a70a3499a330c398c8`
- 知识数据版本：`sha256:837441b02400435bf83fc802d79b69a473b591fdd9062529e16154c22560c608`
- 冻结 acceptance 集哈希：`sha256:25ce6ac9c25158a88cb7eb92d0068bec769331714bfd53a87d39c9900157d589`

## 证据

| 报告 | SHA-256 |
|---|---|
| `v2-candidate-full-development.json` | `1822de85caa26a0a320b2a32454a18c273a9193902e073c2d4fb59537b5238fb` |
| `v2-candidate-full-acceptance.json` | `a0c5c10f10a5f0c2ccd0ed2af287a980861d274665383fe920947535b610e9aa` |
| `v2-candidate-full-all.json` | `124c44ab47826f92091881792ccf7c4634f99afd38c2dd7c7ff8d2bf0ae281f4` |

- development、acceptance 与 all 报告的模型、算法、索引、数据和冻结验收哈希一致。
- acceptance 满足 Recall@12、priority Top-12、prerequisite、来源完整率、跨领域错误、P95 和 V2 契约非法输出全部门槛。
- 非 live 回归：`pytest tests/contracts tests/unit tests/integration -m "not live" -q`，结果为 `139 passed, 3 deselected`。
- [阶段五准入报告](v2-rag-integration-admission.md) 的结论为 `rag_admitted / runtime_cutover_blocked`。

## 冻结规则

后续调优只能从 development 集开始，任何算法、知识数据、embedding 模型或 candidate index version 变化都必须递增算法版本并重新执行开发评测。不得对本冻结版本重复查询 acceptance 集；全量结果只能由已生成的 development 与 acceptance 报告离线汇总。
