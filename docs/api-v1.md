# API v1 契约

所有 JSON 响应统一包含 `schema_version`、`request_id`、`data` 或 `error`、`timestamp`。生成任务的 `task_id` 同时作为 LangGraph `thread_id`，首次生成和反馈触发不更换 ID。

## 核心接口

| Method | Path | 说明 |
| --- | --- | --- |
| POST | `/api/v1/generation-tasks` | 创建任务，接收 `trigger_type`、`execution_mode`、`learning_goal` |
| GET | `/api/v1/generation-tasks/{task_id}` | 获取状态、进度、决策和资源 |
| GET | `/api/v1/generation-tasks/{task_id}/events` | SSE 联合事件流 |
| GET | `/api/v1/generation-tasks/{task_id}/agent-runs` | 脱敏的结构化 Agent 运行摘要 |
| POST | `/api/v1/tutoring/sessions` | 为当前已审核资源创建导学会话 |
| POST | `/api/v1/tutoring/sessions/{id}/messages` | 自然语言反馈入口 |
| GET | `/api/v1/tutoring/sessions/{id}` | 获取连续导学消息 |
| POST | `/api/v1/resources/{id}/feedback` | 快捷标签、评分或选中文本反馈 |
| GET | `/api/v1/resources/{id}/versions` | 获取资源系列版本链 |
| POST | `/api/v1/resources/{id}/export` | 生成 Markdown/PDF 导出并返回哈希和审核信息 |
| GET | `/api/v1/evaluations/summary?mode=live\|baseline` | 读取 live 或 baseline 评测结果，默认 live |
| GET | `/api/v1/health/dependencies` | 数据库、Chroma、模型通道和真实演示就绪状态 |
| PATCH | `/api/v1/knowledge/items/{id}` | 修改知识点、关系并标记局部影响范围 |
| POST | `/api/v1/knowledge/rebuild-index` | 同步增量重建待处理知识向量 |
| POST | `/api/v1/diagnostics/sessions/{id}/submit` | 提交诊断；简答题返回 AI 分项评分、评语和不确定标记 |
| POST | `/api/v1/learning-paths/{path_id}/nodes/{node_id}/verify` | 从服务端已确认答题记录验证当前路径节点 |
| POST | `/api/v1/learning-paths/{path_id}/nodes/{node_id}/complete` | 使用已验证证据完成节点并解锁后继节点 |

学习者资源列表默认仅返回 `is_current=true && review_status=passed`；管理员使用 `include_unpublished=true` 查看未发布版本。

健康接口只返回模型名称和是否配置，不返回 API 密钥。正式验收必须满足 `ready_for_live_demo=true`。

## M4B 诊断与路径约定

- 简答题未完成模型评分时返回 HTTP 503，`error.code=DIAGNOSTIC_SCORING_PENDING`，`details.retryable=true`；不生成新画像或路径。
- 诊断成功响应的 `answer_results` 包含 `scoring_method`、`criteria`、`ai_comment`、`confidence`、`scoring_uncertain`、缺失点和事实错误。
- 路径节点状态为 `locked | current | completed | skipped`；学习者本阶段不能主动跳过节点。
- `verify` 不接受客户端分数；`complete` 必须提交 `evidence_ids`，服务端会重新验证学习者、领域、知识点和分数阈值。

## SSE 事件

显式事件类型包括：

```text
trigger_routed
agent_status
feedback_classified
profile_update_decided
profile_updated | profile_unchanged
review_disagreement
review_retrieval_started
path_refresh_started
path_refresh_completed
resource_created
task_completed | task_failed
```

所有事件携带同一个 `task_id`。前端对未知事件或枚举显示“未知状态”，不因新值崩溃。

## 其他 MVP 接口

健康检查、演示账号、学习者画像、诊断、知识库、报告和领域配置继续使用原 `/api/v1` 路由，不引入 JWT、Redis、Neo4j、WebSocket 或 `/api/v2`。
# M1 结构化知识导入

- `GET /api/v1/knowledge/imports/{import_id}`：查看导入状态与候选统计。
- `GET/PATCH /api/v1/knowledge/imports/{import_id}/candidates`：查看或修改知识、关系和诊断题候选。
- `POST /api/v1/knowledge/imports/{import_id}/validate`：运行来源、字段、重复和关系环校验。
- `POST /api/v1/knowledge/imports/{import_id}/approve`：批准候选并事务性写入正式知识库。
- `POST /api/v1/knowledge/imports/{import_id}/build-index`：启动 Candidate 索引构建。
- `POST /api/v1/knowledge/imports/{import_id}/smoke-test`：检查活动索引与数据版本。
- `POST /api/v1/knowledge/imports/{import_id}/publish`：冒烟通过后发布导入。
- `GET /api/v1/knowledge/imports/{import_id}/events`：读取导入状态 SSE 事件。
