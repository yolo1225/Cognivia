# Agent 执行规范

> 更新日期：2026-07-06  
> 目标读者：开发代理、代码生成代理、协作智能体。  
> 用途：约束后续实现行为，避免偏离当前 MVP 交付路线。

## 1. 总原则

项目定位是比赛 MVP 原型，不是完整 SaaS 平台。

开发优先级固定为：

```text
可演示闭环 > 可复现指标 > 架构完整性 > 企业级扩展
```

开发代理新增功能前必须先自检三个问题：

1. 是否支撑 `learner profile -> diagnosis -> retrieval -> generation -> review -> decision -> feedback -> update`？
2. 是否能提升比赛评分中的完整性、创新性、用户体验或指标证明？
3. 是否能在演示路线中被看见、被解释、被复现？

如果答案不明确，放入后续扩展，不进入当前 MVP。

## 2. 前端规范

技术栈固定：

- Vue 3
- TypeScript
- Vite
- Element Plus
- ECharts
- Vue Flow
- Pinia
- Axios

页面建设规则：

- 优先建设真实工具界面，不做营销落地页。
- 首页是演示工作台，必须引导完整流程。
- 核心页面固定包括：诊断测评、Agent 协作、学习资源、学习报告、知识库管理、领域配置、评测指标。
- 前端可以先用 demo 数据跑顺体验，但 API 类型、字段和状态必须按真实后端契约设计。
- 页面中文必须可读，禁止提交乱码。
- 所有核心操作必须有加载、成功、失败、空状态。
- 不新增大型 UI 框架，不引入与 Element Plus 冲突的组件系统。

### 2.1 目录职责与依赖方向

前端目录职责固定如下：

- `pages/`：路由级页面，负责编排页面用例和组合组件，不沉淀通用请求实现。
- `components/`：可复用展示与交互组件，不直接创建 Axios 实例，不持有跨页面业务状态。
- `stores/`：Pinia 跨页面共享状态和需要跨路由保留的业务状态。
- `api/`：Axios 实例、请求函数、响应解包和接口 DTO；后端字段变化时优先在此处统一适配。
- `types/`：非接口专属的共享领域类型；不得与 `api/` 中的后端 DTO 重复定义同一结构。
- `utils/`：无状态、可复用的纯工具函数，不依赖页面和 Store。

依赖方向应保持为：

```text
pages/components -> stores/composables -> api
pages/components -> types/utils
```

页面局部状态保留在页面或可复用 composable 中；只有需要跨组件、跨页面共享或跨路由保留的状态才进入 Pinia。组件和页面必须复用 `api/` 中的请求封装，不得各自创建 Axios 实例或重复实现统一响应解包。

### 2.2 命名与 TypeScript 规则

- Vue 组件文件和组件名使用 `PascalCase`，普通 TypeScript 文件、函数和变量使用 `camelCase`，常量使用语义清晰的命名；现有第三方约定或已稳定的 API 文件名不为统一外观而批量重命名。
- 新增 Vue 组件统一使用 Composition API 和 `<script setup lang="ts">`；修改旧组件时在不扩大任务范围的前提下逐步收敛。
- 保持 TypeScript `strict=true`。禁止无说明地使用 `any`；确需兼容不稳定外部数据时，优先使用 `unknown`、运行时校验和局部类型收窄，并在代码中说明边界。
- Props、Emits、API 响应和 Store 公共状态必须有明确类型。不得复制一份字段略有差异的后端 DTO 供页面临时使用。
- 异常不得通过空 `catch` 或只打印控制台后继续执行的方式静默吞掉；必须转化为用户可理解的失败状态，或继续抛给统一错误处理层。

交互约定：

- 知识库新增或修改后，前端必须提示“需要重建向量索引”。
- 生成资源必须展示资源类型、难度、审核状态和知识来源。
- 资源反馈必须展示触发的动作，例如补救解释、挑战任务、资源修订。
- Agent 页面必须展示每个节点的职责和运行状态，不能只显示一个“生成中”。
- 指标页展示评测目标时，必须说明离线 `test_script` 是最终来源。

### 2.3 生命周期、安全与异常状态

- 所有核心操作必须覆盖加载、成功、失败和空状态；可能重复提交的按钮在请求期间禁用或使用幂等机制，避免重复创建任务和资源。
- 路由离开、组件卸载、任务终止或请求失败时，必须清理定时器、事件监听和长连接；SSE 必须显式关闭，ECharts 实例必须执行 `dispose`。
- 页面不得直接渲染不可信 HTML。模型生成的 Markdown 必须经过安全渲染或清理，禁止通过 `v-html` 绕过内容安全边界。
- API 错误分支依据 HTTP 状态码和稳定错误码处理，不得通过匹配中文错误消息决定业务行为。
- Demo、baseline、live 数据必须显示或保留明确的运行模式，不得在同一页面中无标识地混用。

### 2.4 前端最低检查

前端改动提交前必须在 `frontend/` 下依次通过：

```bash
npm run lint
npm run test
npm run build
```

`npm run build` 已包含 `vue-tsc` 类型检查。`npm run format` 只用于主动修复格式，不作为只读检查命令；执行格式化时不得顺带改写与当前任务无关的文件。

## 3. 后端规范

技术栈固定：

- FastAPI
- Python 3.12
- SQLAlchemy
- Alembic
- MySQL 8
- ChromaDB
- LangGraph `StateGraph`
- OpenAI-compatible API
- SSE

API 规则：

- 基础路径固定 `/api/v1`。
- 所有响应必须使用统一结构：`schema_version`、`request_id`、`data` 或 `error`。
- MVP 认证使用演示账号和角色，不阻塞核心闭环。
- 新增接口必须优先服务演示路线。
- 修改 API 字段时要同步更新 `frontend/src/api` 类型。

### 3.1 分层与依赖方向

后端按以下职责组织，允许 MVP 中省略没有实际价值的空壳层，但不得混淆职责：

```text
router -> service -> agent/domain -> repository/integration
```

- Router 负责 HTTP/SSE 适配、输入校验、身份上下文和统一响应，不直接堆积复杂业务流程或跨多表事务。
- Service 负责业务用例、事务边界、幂等控制和多个 Agent/数据能力的编排。
- Agent/domain 负责独立 Agent 节点和领域决策，不自行管理跨步骤事务，也不得绕过冻结契约输出临时结构。
- Repository 负责可复用的数据访问；integration 负责模型、ChromaDB、文件解析等外部系统适配。
- Pydantic Schema、SQLAlchemy Model、Service 和 Repository 各自承担接口校验、持久化、业务编排和数据访问职责，禁止互相替代。

公共函数、跨模块接口、Service 方法和 Agent 节点必须提供参数与返回值类型注解。循环导入或反向依赖不得通过移动导入位置长期掩盖，应调整职责边界。

服务实现规则：

- 允许保留 demo/rule-based 实现作为过渡，但必须在代码或文档中标明边界。
- 生成任务应逐步从 `demo_flow_service` 迁移到正式 service 和 Agent 节点。
- 每个 Agent 必须有独立职责、结构化输入输出、运行记录和消息记录。
- SSE 事件应来自真实任务状态或 `agent_runs`，不长期依赖硬编码步骤。

### 3.2 异常、事务与外部调用

- 业务异常在 Service 或领域层使用稳定错误类型表达，由统一异常处理层转换为 HTTP 状态码和标准错误响应；Router 不重复拼装不同格式的错误对象。
- 一个业务用例的数据库事务由 Service 控制。数据库写入失败必须回滚，不得保留任务已完成但资源未落库等互相矛盾的状态。
- 模型和其他可重试外部调用最多重试 3 次，等待 1 秒、3 秒和 5 秒；仅对超时、限流和明确的临时错误重试，参数错误、权限错误和结构化输出持续不合法不得无限重试。
- 模型结构化输出校验失败时允许按统一重试策略修复；耗尽重试后记录失败摘要并将任务转入明确失败或人工处理状态。
- ChromaDB 暂时不可用时，检索型生成任务不得伪造来源。已有可靠关系或关系型数据可满足明确降级策略时才允许降级，并记录 `provider_mode` 和降级原因；否则任务失败且对用户可见。
- API Key、模型密钥和其他敏感配置只能通过环境变量或受控配置注入，不得写入源码、普通日志、前端构建产物或提交到仓库的环境文件。

### 3.3 API、时间与标识规范

成功响应保持统一结构：

```json
{
  "schema_version": "v1",
  "request_id": "request-public-id",
  "data": {}
}
```

失败响应保持统一结构，`error` 至少包含稳定错误码和可读消息：

```json
{
  "schema_version": "v1",
  "request_id": "request-public-id",
  "error": {
    "code": "KNOWLEDGE_ITEM_NOT_FOUND",
    "message": "知识点不存在",
    "details": {}
  }
}
```

- 使用与错误语义匹配的 HTTP 状态码；`message` 可优化中文文案，前端业务判断只能依赖 HTTP 状态码和稳定 `code`。
- 时间通过 ISO 8601 传输，持久化统一按 UTC 处理，前端按 `Asia/Shanghai` 展示；不得传递无时区含义的模糊时间字符串。
- 对外接口、任务引用和日志关联优先使用稳定的 `public_id`，不得暴露可推断数据量或内部关系的自增主键。
- 当前接口类型继续维护在 `frontend/src/api` 并通过契约测试防止漂移；从 FastAPI OpenAPI 自动生成 TypeScript 类型属于推荐演进项，完成生成链路前不得宣称已自动同步。

### 3.4 数据库与迁移规范

- 数据模型变化必须新增 Alembic migration；已经进入共享历史或演示环境的 migration 不得改写，只能通过后续 migration 修正。
- `public_id`、唯一业务键必须有唯一约束；外键、状态筛选、任务查询和其他高频条件按实际查询建立索引。
- Service 明确事务边界和提交时机，初始化与演示数据脚本必须可重复执行，不得因重复运行生成冲突数据。
- JSON 字段只存放不需要独立筛选、排序、唯一约束或关系查询的扩展数据；关键状态、公开标识、关联关系和评测字段不得隐藏在 JSON 中。
- 外键删除、软删除或保留策略必须按业务含义显式决定，不依赖数据库默认行为造成级联数据丢失。

### 3.5 异步任务、SSE 与幂等规范

- 任务状态只能按定义的状态机合法迁移；`completed`、`no_change`、`failed`、`rejected` 等终态不得被普通重试回退。人工复核恢复和修订必须走已有 LangGraph 分支并保留记录。
- 创建任务、生成资源、提交反馈和人工复核操作必须使用业务唯一键、任务 ID 或等价机制保证幂等；网络重试不得重复创建正式资源或重复应用画像更新。
- SSE 事件至少包含任务 ID、事件类型、任务或节点状态、发生时间和可排序的事件标识。事件内容来自任务状态或 `agent_runs`，不得长期使用前端计时器伪造进度。
- 当前未实现完整断线补发时，客户端重连后必须先读取任务快照，再继续订阅后续事件。基于 `Last-Event-ID` 的精确补发属于后续增强项，在实现和测试完成前不列为当前已具备能力。
- 等待人工复核不是调用失败；任务进入明确的 `waiting_human` 状态并停止自动推进。数据库失败、模型重试耗尽和无法安全降级的检索失败进入失败状态，保存摘要、错误码和可追踪运行记录。

### 3.6 后端最低检查

后端改动提交前必须在 `backend/` 下通过：

```bash
python -m ruff check app tests
python -m compileall app tests
python -m pytest
```

如果测试明确依赖未启动的 MySQL、ChromaDB 或真实模型服务，应先执行不依赖外部服务的单元、契约和 API 测试，并在交付说明中列出未执行项及原因；不得把缺少外部环境描述为测试通过。Agent 契约、审核仲裁、任务状态机、知识更新和画像证据判断属于评分关键逻辑，修改时必须有针对性测试。

## 4. 知识库规范

知识点至少包含：

- `name`
- `category`
- `difficulty`
- `tags`
- `content`
- `source_title`
- `source_url`（可选）
- `license_note`
- `needs_reembedding`

知识更新规则：

1. 新增、修改或导入知识点后，必须设置 `needs_reembedding=true`。
2. 使用 `knowledge_relations` 找出前置、后继、相关知识点。
3. 影响到的学习路径必须设置 `needs_refresh=true`。
4. 向量索引重建完成后，才可清除 `needs_reembedding`。
5. 如果来源或审核规则变化，相关资源应标记为 `review_stale`（字段可后续补充）。

当前 MVP 允许先支持单条手动导入；批量 Excel/JSON 导入作为下一阶段能力。开发代理不得因为批量导入未完成而阻塞演示闭环。

## 5. Agent 规范

系统不能退化为单次模型调用。

核心 Agent：

- Orchestrator Agent
- Profile Analysis Agent
- Knowledge Retrieval Agent
- Content Generation Agent
- Review and Validation Agent
- Tutoring Agent

每个 Agent 必须满足：

- 有独立系统提示词。
- 有结构化输入输出。
- 写入 `agent_runs`。
- 关键消息写入 `agent_messages`。
- 输出中不能包含完整敏感学习者画像或完整资源内容，普通日志只存摘要、ID、状态和分数。

主流程：

```text
START -> prepare_task
prepare_task -> analyze_profile       when trigger_type = initial_generation
prepare_task -> interpret_feedback    when trigger_type = resource_feedback
interpret_feedback -> analyze_profile
analyze_profile -> finalize_task      when no generation, review or regeneration is required
analyze_profile -> retrieve_knowledge when generation, review or regeneration is required
retrieve_knowledge -> generate_resource -> review_resource -> finalize_task
finalize_task -> END                  when completed, no_change, failed or rejected
finalize_task -> retrieve_knowledge   when revision_required and revision_count < 2
finalize_task -> human_review         when manual_review_required or assisted approval is pending
human_review -> retrieve_knowledge    when request_revision
human_review -> finalize_task         when approve or reject
```

约束：

- `build_learning_graph()` 是唯一顶层图构建函数，worker 不得复制一套图定义。
- 首次生成和反馈调优都使用 `generation_tasks.public_id` 作为 `task_id/thread_id`。
- 自然语言反馈进入导学会话；快捷标签、评分和选中文本只作为辅助证据。
- 单次 `too_hard/too_easy` 不得直接修改画像；证据不足时保存 `no_change` 和理由。
- 临时材料上传属于紧随 P0 的 P1；未来实现时必须任务级隔离，不得自动入库或直接更新画像。

### 5.1 Agent 契约修改规范

`docs/agent-contract-v2.md`、`backend/app/agents/contracts.py`、`backend/app/agents/state.py` 和对应 Schema 是已冻结契约。契约由一名指定负责人统一维护，其他成员及开发代理在实现具体 Agent 时必须将以下文件视为只读：

- `backend/app/agents/contracts.py`
- `backend/app/agents/state.py`
- `backend/app/agents/contract_adapters.py`
- `backend/tests/contracts/`
- `docs/agent-contract-v2.md`
- `docs/contracts/v2/`

具体 Agent 实现者不得为了让代码、Prompt 或测试通过，擅自修改字段名、类型、枚举、必填性、默认值、State 字段所有权、Schema 或顶层图。实现与契约不一致时，先在 Agent 内按已有契约适配；确实无法表达时，停止修改共享文件并提交契约变更申请。

变更申请必须说明申请字段或规则、所属输入/输出、生产与消费节点、使用原因、是否可空、默认值和兼容性影响。只有契约负责人可以决定是否修改，并统一更新模型、State、适配器、示例、Schema、测试和文档。破坏性变更必须升级契约版本。

契约负责人统一称为“项目指定契约维护者”。项目未明确具体人员时，开发者只能提交变更申请，不得自行视为维护者。申请应落在团队可追踪的任务、Issue 或评审记录中，并包含受影响节点、兼容性判断和验收方式；批准后由契约维护者一次性更新模型、State、适配器、示例、Schema、测试和文档，避免多人分别修改造成漂移。

当前运行链和所有独立服务入口统一使用正式 `contracts` 与 `state`。V1 契约、State 和 Agent 实现已经退役，禁止重新引入。

## 6. 审核与反幻觉规范

Review and Validation Agent 是评分关键组件。

生成资源必须检查：

- factual accuracy
- source traceability
- difficulty match
- core knowledge coverage

双模型审核规则：

- `primary_review_model` 和 `secondary_review_model` 都要检查事实和来源。
- 分差超过 10 分，或一方通过一方失败，必须触发仲裁。
- 仲裁流程：重新检索来源 -> 重新审核 -> 仍不一致则 `manual_review_required`。
- 未通过或人工复核资源不得默认展示给学习者。

## 7. 评测规范

离线 `test_script` 是 MVP 指标的事实来源。开发代理不得用前端展示值替代离线评测结果。

必须可复现：

- hallucination rate `< 5%`
- difficulty match accuracy `>= 85%`
- core knowledge coverage `>= 90%`
- learning path order accuracy（如实现）

前端指标页只能展示或解释结果，不能替代离线评测。

## 8. 本地运行规范

Docker Compose 是默认演示环境。

推荐访问：

- Frontend: `http://localhost:5173/`
- Backend Docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/v1/health`

如果同时存在 Docker 前端和本地 Node/Vite，优先保留 Docker 前端，避免 `localhost` 与 `127.0.0.1` 指向不同服务。

前端最低检查以第 2.4 节为准，至少执行：

```bash
cd frontend
npm run lint
npm run test
npm run build
```

后端最低检查以第 3.6 节为准，至少执行：

```bash
cd backend
python -m ruff check app tests
python -m compileall app tests
python -m pytest
```

依赖真实模型或外部服务的 live 测试必须显式启用，不得进入默认离线测试。缺少外部环境时，按第 3.6 节记录未执行项，不能用 `compileall` 代替测试结果。

## 9. 文档规范

文档分工：

- 根目录需求文档：产品目标、评分优先级。
- 根目录设计文档：技术边界、架构设计。
- `docs/current-iteration-plan.md`：当前实际迭代计划。
- `docs/project-conventions.md`：当前工程规范。
- `AGENTS.md`：开发代理必须遵守的简版规则入口。

当实现路线与原设计文档发生偏移时，开发代理先更新 `docs/current-iteration-plan.md`，再决定是否回写根目录设计文档。

## 10. 完成定义与状态治理

### 10.1 Definition of Done

一个功能只有同时满足以下条件，才可标记为代码完成：

- 支持 MVP 主闭环或明确的评分、演示目标，没有引入未批准的范围扩张。
- 有明确的数据落点、稳定 API 契约和前端可见入口；纯后端基础能力需有可复现调用或测试证据。
- 前端覆盖加载、成功、失败和空状态，并处理重复提交与资源清理。
- API 变更已同步 `frontend/src/api` 类型；数据库变更已有新 Alembic migration；Agent 实现未修改冻结契约。
- 新增或修改的关键逻辑有成功、失败和相关边界测试，前后端最低检查已经通过。
- 普通日志不包含真实姓名、完整回答、完整画像、完整资源或密钥。
- Demo、baseline、live 模式和数据来源标记清晰，演示结果可按文档复现。

代码完成不等于真实环境验收完成。因外部服务缺失而未执行的测试、真实模型回归或 Docker 验收必须在交付说明中明确列出。

### 10.2 统一状态

迭代计划、任务记录和交付说明统一使用以下状态，中文说明可以附加，但不得混用含义：

| 状态 | 含义 |
|------|------|
| `planned` | 已进入计划，尚未开始实现 |
| `in_development` | 正在实现，接口或行为仍可能变化 |
| `code_complete` | 代码、文档和本地最低检查完成，尚未代表真实环境通过 |
| `locally_verified` | 已在约定的本地或 Docker 环境完成可复现验证 |
| `live_verified` | 已使用真实模型或真实外部服务完成指定回归 |
| `demo_accepted` | 已按比赛演示路线验收，可进入录像或提交材料 |

### 10.3 运行模式与指标证据

- Demo、baseline 和 live 运行必须保存或展示明确的 `provider_mode` 或等价标识。
- Demo/rule-based 结果用于演示稳定性，baseline 用于可复现对照，live 用于真实模型能力验证；三者不得互相冒充。
- 前端指标、文档截图和演示口径必须能追溯到对应 `test_script` 报告、运行模式、知识库版本和评测时间。
- 未完成真实环境验证时只能标记到 `code_complete` 或 `locally_verified`，不得标记为 `live_verified` 或对外宣称真实指标已达成。
