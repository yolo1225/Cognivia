# V2 学情分析阶段四：评测冻结与集成交接

> 冻结日期：2026-07-27
> 领域配置版本：`ai_app_dev_profile_v1`
> 算法版本：`profile_analysis_service_v2`

## 冻结结论

阶段四不调整阈值、权重、领域配置、50 个案例或冻结验收 manifest。开发集与冻结验收集均已达到既定门禁，因此当前算法行为进入冻结状态。

| 冻结对象 | 值 |
| --- | --- |
| 配置版本 | `ai_app_dev_profile_v1` |
| 种子知识指纹 | `983bb0404433259345eafe17b0f24a8ea743379b4010174e46bcf3fd649ab7ab` |
| 验收基线版本 | `ai_app_dev_profile_v1_acceptance_2` |
| 规范化哈希算法 | `canonical-json-sha256-v1` |
| 验收 fixture 规范化哈希 | `8be120d56e21c89a4819466c5e4bc78b561623044bd4b07131082f3249264929` |
| 正式命令 | `python -m app.scripts.evaluate_profile_v2` |

评测门禁报告使用 `profile-v2-evaluation-v2`。它会校验 manifest，并输出开发/验收分集、所有质量指标、失败 case ID、五类归因、100 次确定性检查和 P50/P95；任何完整性、契约、预期、指标或延迟门禁失败均以非零状态退出。

## 固定验收标准

- V2 契约合法输出率：100%。
- 单次主观反馈误更新率：0%。
- 强证据更新决策准确率：至少 95%。
- 薄弱知识识别准确率：至少 90%。
- 检索策略准确率：至少 95%；目标难度准确率：至少 90%。
- 重点/前置知识完整率：至少 95%。
- 相同输入重复执行一致率：100%；P95 小于等于 500ms。

失败只记录 case ID 与以下归因：输入准备、证据政策、画像计算、影响范围、检索计划；报告不得输出完整画像、反馈正文或资源内容。

如需调整阈值或权重，必须创建新的配置版本，在开发集重新收敛，并由契约维护流程评审对冻结验收基线的影响。不得通过修改已冻结的验收案例或 manifest 来掩盖回归。

## 阶段五集成交接清单

本清单只分配后续责任，不构成生产接线授权。

| 集成组件 | 输入与输出责任 | 进入接线前必须完成的确认 |
| --- | --- | --- |
| 诊断评分服务 | 将逐题评分转换为 `knowledge_assessments` 与 `diagnostic_summary`，并关联脱敏 `EvidenceRef`。 | 明确题目-知识点映射、确认状态和证据 ID 去重来源。 |
| V2 导学适配层 | 将 `InterpretFeedbackOutput` 转换为 `feedback_evidence` 与 `recommended_action`。 | 快捷反馈、未确认自然语言和资源错误不得直接覆盖画像。 |
| 画像持久化层 | 分配新画像 ID，原子写入版本、前一版本关联与变更证据。 | 定义乐观并发控制、重放幂等性和失败回滚。 |
| 关系解析服务 | 以正式知识关系补全 dependent/related、路径节点和资源影响范围。 | 不允许 Profile Agent 根据命名规则虚构路径或资源 ID。 |
| Profile→Retrieval 适配层 | 以同一 `task_id` 与 `TaskContext` 把 `profile`、`retrieval_plan` 转为 `RetrieveKnowledgeInput`。 | 固定 `remedial/consolidation/challenge` 的 purpose 映射，`review` 使用 `source_verification`。 |
| 运行记录与 SSE 层 | 记录 Agent 运行、消息和进度摘要。 | 仅记录 ID、状态、计数、分数和脱敏原因；不得记录完整画像、答案或资源。 |
| V1 回退责任 | 在 V2 统一运行链切换后保留 V1 演示恢复路径。 | V2 合同、画像验收、Retrieval 直接消费和端到端回归任一失败时回退。 |

阶段五开始前仍必须保持 V1 `nodes.py`、`graphs.py`、数据库、worker 与 SSE 不变。只有所有 V2 Agent 完成且该清单经评审后，才允许统一切换。