# BASELINE 可复现评测报告

- 状态：passed
- 案例：50/50
- 知识库版本：ai_app_dev-kb-2026.07-v3
- 脚本版本：live-evaluator-2.0
- 评测时间：2026-08-14T07:25:33.949493+00:00
- 运行模式：baseline
- 运行编号：baseline

| 指标 | 分子 | 分母 | 比率 |
|---|---:|---:|---:|
| 幻觉率 | 0 | 200 | 0.0 |
| 难度匹配准确率 | 50 | 50 | 1.0 |
| 核心知识覆盖率 | 100 | 100 | 1.0 |
| 审核结论准确率 | 50 | 50 | 1.0 |
| 画像结论准确率 | 50 | 50 | 1.0 |

性能：P50 1590 ms，P95 1920 ms。

## 失败案例

- hallucination: 无
- difficulty: 无
- coverage: 无
- review_decision: 无
- profile_decision: 无

无法判定：Cases without a determinable observed result are excluded from metric denominators.

## Agent 性能

| Agent | P50 ms | P95 ms |
|---|---:|---:|
| content_generation_agent | 572 | 616 |
| knowledge_retrieval_agent | 146 | 168 |
| review_validation_agent | 482 | 526 |
