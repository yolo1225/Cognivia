# API v1 契约

> 最近同步：2026-08-27。此页描述当前 `develop` 运行接口的稳定入口；请求/响应字段以
> FastAPI OpenAPI（`/api/v1/openapi.json`）和 `frontend/src/api/` 类型为准。

## 通用约定与认证

- 基础路径为 `/api/v1`。JSON 响应使用 `schema_version`、`request_id`、`data` 或 `error`
  的统一外壳；部分响应还带 `timestamp`。
- 当前身份机制为 learner/admin 角色、bcrypt 密码、JWT HttpOnly Cookie、CSRF header 与 Redis
  refresh session。除登录、注册、刷新和健康检查外，写接口需要 Cookie 中的 `csrf_token` 与
  `X-CSRF-Token` 一致。
- 所有学习者侧接口执行对象归属和领域就绪校验。管理员路由由后端 `require_admin` 保护。
- `generation_tasks.public_id` 同时是单次生成事件的外部 `task_id` 与 LangGraph `thread_id`。
  反馈、学习调整和知识刷新会创建新的事件任务，并以 `source_task_id`、`source_feedback_id` 关联来源；
  每个任务失败后可从自身的持久化检查点恢复。

| Method | Path | 说明 |
| --- | --- | --- |
| POST | `/auth/register` | 注册 learner 并建立 Cookie 会话 |
| POST | `/auth/login` / `/auth/refresh` / `/auth/logout` | 登录、刷新与注销会话 |
| GET | `/auth/me` | 读取当前身份与关联 learner |
| GET | `/health` / `/health/dependencies` | 服务与依赖健康、Candidate RAG/模型就绪状态 |

## 学习者建档、诊断与路径

| Method | Path | 说明 |
| --- | --- | --- |
| GET/POST | `/learners` | 查询或创建 learner |
| PUT | `/learners/{learner_id}/target-domain` | 切换到已发布的目标领域 |
| PUT | `/learners/{learner_id}/initial-context` | 保存首次建档背景与学习方向 |
| GET | `/learners/{learner_id}/profile` | 读取当前画像、首诊门禁和版本信息 |
| POST | `/diagnostics/sessions` | 创建确定性抽题的异步诊断会话 |
| POST | `/diagnostics/sessions/{session_id}/submit` | 提交诊断；简答题按独立评分任务完成 |
| GET | `/diagnostics/sessions/current`、`/{session_id}`、`/{session_id}/events` | 恢复会话、轮询状态或订阅 SSE |
| POST | `/diagnostics/sessions/{session_id}/retry` | 重试可恢复的评分会话 |
| POST | `/learning-paths/{path_id}/nodes/{node_id}/verify` | 用服务端已确认答题记录验证节点 |
| POST | `/learning-paths/{path_id}/nodes/{node_id}/complete` | 以已验证证据完成节点并解锁后继 |

诊断、分阶测试、错题巩固与导学掌握检查只使用 `active + certified` 正式题库。题目不足不会跨领域或用临时题静默补齐；节点推进只接受这些服务端已确认的正式证据。

## 生成、资源、导学与调整

| Method | Path | 说明 |
| --- | --- | --- |
| POST | `/generation-tasks` | 创建初始、节点或局部刷新生成任务 |
| GET | `/generation-tasks`、`/active`、`/{task_id}` | 查询任务列表、活动任务或详情 |
| POST | `/generation-tasks/{task_id}/retry` | 重试失败任务或恢复检查点 |
| GET | `/generation-tasks/{task_id}/events` | 订阅任务、Agent 状态、审核仲裁和发布 SSE |
| GET | `/generation-tasks/{task_id}/agent-runs` | 读取脱敏 Agent 运行摘要 |
| POST | `/generation-tasks/feedback/{feedback_id}/confirm` | 确认需要生成的反馈调整 |
| GET | `/resources` | 读取当前已审核通过资源；可按 learner/task 过滤 |
| POST | `/resources/{resource_id}/quiz-attempts` | 创建资源内分阶测试尝试 |
| GET/PUT/POST | `/resources/{resource_id}/quiz-attempts/...` | 恢复、保存和完成资源内测试 |
| POST | `/resources/{resource_id}/feedback` | 提交快捷标签、评分或选中文本反馈 |
| GET | `/resources/{resource_id}/versions` | 查看资源系列版本链 |
| POST/GET | `/resources/{resource_id}/export`、`/resources/exports/{file_name}` | 创建与下载资源导出文件 |
| POST/GET | `/tutoring/sessions`、`/tutoring/sessions/{session_id}/messages` | 创建导学会话并提交自然语言消息 |
| POST | `/tutoring/sessions/{session_id}/messages/stream` | 订阅单次导学回复 SSE |
| POST | `/tutoring/sessions/{session_id}/assessments/{assessment_id}/answers` | 提交导学评估答案 |
| POST | `/tutoring/sessions/{session_id}/mastery-check` | 请求当前节点掌握度验证 |
| POST | `/learning-adjustments/{proposal_id}/resource-decision` | 对生成/跳过学习调整资源作出选择 |

资源只有在三个资源类型齐全、双模型审核通过且包级质量门槛通过时才原子发布。反馈、自然语言导学和
服务端答题证据共同决定是否创建画像新版本；单次主观反馈只会形成证据或即时导学，不直接改写画像。

## 学习包、报告与错题巩固

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/learning-packages/current`、`/{task_id}` | 查询当前学习包或历史任务学习包 |
| POST | `/learning-packages/{task_id}/export` | 导出完整学习包 |
| POST | `/learning-packages/{task_id}/knowledge-impact/dismiss` | 暂不处理当前知识影响提示 |
| POST | `/learning-packages/{task_id}/knowledge-refresh` | 创建受影响资源的局部刷新 |
| GET | `/reports/learners/{learner_id}` | 学习报告：画像、知识状态、路径、调整提案与效果对比 |
| GET | `/reports/learners/{learner_id}/learning-journey` | 学习历程与学习包继承关系 |
| GET | `/mistake-review/summary`、`/items`、`/items/{item_id}` | 查询错题巩固摘要与项目 |
| POST | `/mistake-review/items/{item_id}/start` | 基于正式题库开启同知识点巩固 |
| POST | `/mistake-review/items/{item_id}/attempts/{attempt_id}/answer` | 服务端评分巩固题并保存来源证据 |

## 领域与知识管理（管理员）

| Method | Path | 说明 |
| --- | --- | --- |
| GET/POST | `/domains` | 查询或创建领域 |
| GET/PATCH | `/domains/{domain_code}` | 查看或编辑领域基本配置 |
| GET | `/domains/{domain_code}/stats`、`/validate`、`/readiness` | 领域统计、配置检查和发布门禁 |
| POST | `/domains/{domain_code}/publish`、`/disable` | 发布或停用领域 |
| GET/POST | `/knowledge/documents` | 查询或上传 Markdown/PDF/TXT 等来源文档 |
| GET/POST/DELETE | `/knowledge/documents/{document_id}`、`/{document_id}/retry` | 查看、重试或删除文档 |
| GET/PATCH | `/knowledge/imports/{import_id}`、`/candidates/...` | 读取导入运行或修订候选 |
| GET | `/knowledge/imports/{import_id}/summary`、`/graph-preview`、`/events` | 查看导入汇总、图谱预览或订阅进度 |
| POST | `/knowledge/imports/{import_id}/validate`、`/approve`、`/build-index`、`/smoke-test`、`/publish`、`/confirm-publish` | 执行候选校验、批准、索引、冒烟与确认发布 |
| GET/POST/PATCH | `/knowledge/items`、`/knowledge/items/{knowledge_id}` | 管理已发布知识条目 |
| GET | `/knowledge/relations`、`/questions`、`/search` | 查询关系、认证题库或知识检索 |
| POST | `/knowledge/rebuild-index` | 启动待处理知识的 Candidate 索引重建 |
| GET | `/knowledge/rebuild-index/status` | 查询索引构建状态 |

领域发布依赖 Candidate manifest、数据/模型版本一致性、检索冒烟、知识关系、题库密度与来源认证等
readiness 门禁。正式题目生命周期为 `pending | certified | rejected | stale`，诊断和运行时测验仅使用
`active + certified` 题目。

## 运维与评测接口

- `GET /evaluations/summary` 为管理员读取已保存评测汇总；离线 `test_script` 仍是竞赛指标的事实来源。
- `/admin/users` 与 `/admin/model-settings` 路由仅允许管理员，用于账号状态、会话处置与模型运行配置。
- SSE 的常见事件包括 `trigger_routed`、`agent_status`、`feedback_classified`、
  `profile_update_decided`、`profile_updated`、`profile_unchanged`、`review_disagreement`、
  `review_retrieval_started`、`path_refresh_started`、`path_refresh_completed`、`resource_created`、
  `task_completed` 与 `task_failed`。前端必须容忍未知事件类型。
