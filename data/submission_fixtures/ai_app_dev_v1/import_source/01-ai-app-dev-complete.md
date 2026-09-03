# 人工智能应用开发实训完整知识包 (ai_app_dev)

本文件用于空库导入演示，包含 75 条正式主领域知识点。请与启动夹具二选一使用。

## 多智能体角色划分
- **knowledge_id:** `agent_role_design`
- **category:** 多智能体
- **difficulty:** 2
- **tags:** agent, role
- **source:** [OpenAI Agents SDK - Agents](https://openai.github.io/openai-agents-python/agents/)
- **license:** MIT License; OpenAI Agents SDK official documentation summary
- **ability_weights:** `{"theory":0.35,"practice":0.25,"learning_speed":0.0,"problem_solving":0.3,"knowledge_breadth":0.1}`

多智能体设计应依据任务边界、工具权限和可验证输出拆分角色，而不是为同一次调用添加多个名称。一个 Agent 可以负责明确领域任务，使用受限工具并把结构化结果交给下游；需要协调时，可由管理 Agent 选择下一角色，或通过 handoff 把控制权交给专门 Agent。角色说明要清楚描述职责、输入、输出和不能执行的动作，工具参数仍由应用校验。拆分只有在能减少上下文混杂、隔离权限或提高评测可解释性时才有价值；简单任务应避免不必要的 Agent 数量和额外延迟。

**应用任务**
按任务边界、工具权限和结构化输出拆分角色，为每个角色填写职责、输入、输出、禁止动作和工具并检查拆分价值。

**预期结果**
形成职责不重叠的 Agent 表与交接关系，简单任务不为数量增加角色，工具参数仍由应用校验。

## AI 应用开发全流程
- **knowledge_id:** `ai_app_dev_overview`
- **category:** 领域概览
- **difficulty:** 1
- **tags:** overview, workflow
- **source:** [NIST AI Risk Management Framework Playbook](https://airc.nist.gov/AI_RMF_Knowledge_Base/Playbook)
- **license:** NIST public resource; official guidance summary
- **ability_weights:** `{"theory":0.5,"practice":0.1,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.2}`

AI 应用开发不是一次模型调用，而是从任务定义、数据与知识准备、模型接入、工具和检索编排、输出校验、离线评测到运行监控的完整工程过程。开发者应先明确用户目标、允许使用的证据、失败边界和可量化指标，再选择模型与组件。实现阶段要把不确定的模型输出放入可验证、可重试和可观测的应用流程，并通过风险识别、测试和人工监督控制影响。上线后继续根据真实失败样例更新数据、提示、检索和评测集，使能力改进能够复现而不是依赖单次演示。

**操作目标**
把一个 AI 应用需求拆成可验证的工程环节，并记录每个环节的输入、输出、失败边界和指标。

**操作步骤**
1. 创建一份流程清单，依次列出任务定义、知识准备、模型接入、编排、输出校验、离线评测和运行监控。
2. 为每个环节标注允许使用的证据、可观察输出和失败处理方式。
3. 检查清单是否包含可量化指标，以及真实失败样例如何进入数据、提示、检索或评测集的更新。

**预期结果**
形成一份覆盖完整工程过程的风险与验证清单；清单不把单次模型输出视为最终业务结果。

**常见错误**
只记录正常路径、没有定义失败边界，或只展示一次成功调用而没有固定评测输入。

**验收标准**
清单能够把每个环节映射到明确证据、可观察结果、失败处理和至少一项可量化指标。

## Alembic 数据库迁移
- **knowledge_id:** `alembic_migrations`
- **category:** 后端开发
- **difficulty:** 3
- **tags:** alembic, migration
- **source:** [Alembic Documentation - Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- **license:** MIT License; Alembic official documentation summary
- **ability_weights:** `{"theory":0.2,"practice":0.5,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

Alembic 使用有序 revision 脚本记录数据库 schema 变化，并在 alembic_version 中保存当前版本。自动生成迁移只能作为初稿，开发者仍需检查列类型、默认值、约束、索引和数据迁移逻辑。迁移应小步、可审查，并在空数据库升级和已有数据升级两种路径上测试；生产或演示数据变更前应具备备份与回退策略。SQLAlchemy 模型修改与迁移脚本必须一起提交，不能只改 ORM 后依赖 create_all 修补正式数据库。

**应用任务**
为字段变更编写小步 Alembic revision，检查类型、默认值、约束、索引和回填，并验证空库与已有数据升级。

**预期结果**
ORM 与迁移同步，升级顺序可审查，正式数据变更具备备份和回退路径。

## 模型 API 限流、重试与故障处理
- **knowledge_id:** `api_resilience_retry`
- **category:** 模型调用
- **difficulty:** 3
- **tags:** api, retry, resilience
- **source:** [OpenAI Cookbook - How to Handle Rate Limits](https://cookbook.openai.com/examples/how_to_handle_rate_limits)
- **license:** MIT License; OpenAI Cookbook summary
- **ability_weights:** `{"theory":0.2,"practice":0.4,"learning_speed":0.0,"problem_solving":0.3,"knowledge_breadth":0.1}`

模型 API 调用必须设置连接与读取超时，并区分限流、临时服务不可用、网络中断、认证失败和请求参数错误。只有可能恢复且操作可安全重复的失败适合重试；认证或校验错误应立即返回。重试采用有上限的指数退避并加入随机抖动，遵守服务端 Retry-After 等提示，避免多个客户端同时再次冲击服务。并发调用使用信号量或队列限制在服务配额内。连续失败后应进入明确降级或失败状态，保留 request_id、尝试次数、错误类型和耗时，不把空响应伪装成成功结果。

**应用任务**
构造限流、临时不可用、网络中断、认证失败和参数错误记录，逐项判断恢复性、安全重复性以及重试或立即返回。

**预期结果**
形成故障决策表，仅可恢复且可安全重复的失败有限重试，并记录 request_id、尝试次数、错误类型和耗时。

## 自动化测试与测试分层
- **knowledge_id:** `automated_testing`
- **category:** 质量保障
- **difficulty:** 2
- **tags:** testing, pytest, quality
- **source:** [pytest Documentation - Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
- **license:** MIT License; pytest official documentation summary
- **ability_weights:** `{"theory":0.25,"practice":0.4,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

自动化测试把可重复的行为验证写成代码，使重构和依赖升级后能够快速发现回归。单元测试聚焦纯函数、校验和排序等小范围逻辑，使用替身隔离网络和数据库；集成测试检查数据库、向量库或模型适配器之间的真实边界；端到端测试只覆盖少量关键用户流程。测试应采用确定输入和明确断言，失败信息指出哪个行为偏离预期。外部模型调用默认使用可控替身，真实网络测试必须显式标记，不能把缺少密钥后的 mock 结果报告为 live 验收。

**应用任务**
为一个功能分别设计纯函数单元测试、数据库或向量库集成测试和关键流程端到端测试，标注替身与 live 边界。

**预期结果**
形成分层测试清单，普通测试不依赖真实网络，live 测试显式标记且不会把 mock 结果报告为真实通过。

## ChromaDB Collection 管理
- **knowledge_id:** `chromadb_collections`
- **category:** 向量数据库
- **difficulty:** 2
- **tags:** chromadb, collection
- **source:** [Chroma Documentation - Collections](https://docs.trychroma.com/docs/collections/manage-collections)
- **license:** Apache-2.0 project documentation; official Chroma summary
- **ability_weights:** `{"theory":0.25,"practice":0.45,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

Chroma collection 将 ID、embedding、文档和 metadata 组织为可查询集合。创建 collection 时应固定名称、embedding 模型、向量维度和距离度量，并在后续写入与查询中保持一致；同一集合混入不同模型的向量会导致维度错误或无意义距离。upsert 适合按稳定 chunk ID 更新，知识删除或重新切片时还要清理旧 ID。开发候选索引应与 V1 演示索引隔离，通过 manifest 指向已完成条数、维度、来源和 smoke query 校验的活动 collection，构建失败不能覆盖上一有效版本。

**应用任务**
定义 collection 的名称、embedding 模型、维度、度量和稳定 chunk ID，执行 upsert、更新、重切片和旧 ID 清理。

**预期结果**
集合配置一致，失败构建不覆盖有效索引，活动 collection 的条数、维度、来源和 smoke query 可核对。

## 引用与来源可追溯
- **knowledge_id:** `citation_traceability`
- **category:** RAG
- **difficulty:** 3
- **tags:** citation, traceability
- **source:** [W3C PROV-O: The PROV Ontology](https://www.w3.org/TR/prov-o/)
- **license:** W3C Document License; official recommendation summary
- **ability_weights:** `{"theory":0.25,"practice":0.25,"learning_speed":0.0,"problem_solving":0.4,"knowledge_breadth":0.1}`

引用与来源追溯要求生成内容中的关键事实能够定位到实际使用的证据，而不是只在文末附上一组无对应关系的链接。证据记录应包含稳定标识、来源标题、位置或片段、URL、获取时间以及必要的许可信息，生成结果再声明哪些结论使用了哪些证据。审核时要检查来源是否真实存在、引用范围是否支持对应结论、版本是否过期，以及转换和切片过程是否改变原意。采用统一的来源实体和派生关系，可以从结果反查检索片段与原始文档，也能在来源更新时识别需要复核的内容。

**应用任务**
为生成结论建立到证据片段、来源标题、位置、URL、获取时间和许可的映射，并模拟来源更新后的影响查询。

**预期结果**
每条关键事实能定位到支持范围，既能从结果反查原文，也能从来源变化找到待复核内容。

## 内容生成智能体
- **knowledge_id:** `content_generation_agent`
- **category:** 多智能体
- **difficulty:** 3
- **tags:** agent, generation
- **source:** [OpenAI Documentation - Prompt Engineering](https://platform.openai.com/docs/guides/prompt-engineering)
- **license:** OpenAI official documentation; summarized for training
- **ability_weights:** `{"theory":0.25,"practice":0.35,"learning_speed":0.0,"problem_solving":0.3,"knowledge_breadth":0.1}`

内容生成智能体接收明确任务、目标受众、允许使用的证据和输出结构，再生成讲解、操作步骤、摘要或测验等内容。系统提示应划定职责和禁止事项，用户输入提供本次目标，检索材料以可区分的数据块传入。关键事实只能来自给定证据；资料不足时应缩小回答范围、提出需要补充的信息或明确无法判断。输出采用稳定结构并保留证据标识，便于程序校验和后续审核。生成模型不应自行调用未授权工具，内容即使格式正确，也必须在发布前进行事实和安全检查。

**应用任务**
给生成 Agent 明确任务、受众、白名单证据和输出结构，要求关键事实绑定证据 ID，并设计资料不足与格式失败处理。

**预期结果**
生成结果结构稳定可追溯，个性化不增加证据外事实，资料不足时缩小范围或明确失败。

## 应用数据结构设计
- **knowledge_id:** `data_schema_design`
- **category:** 数据建模
- **difficulty:** 2
- **tags:** schema, database
- **source:** [SQLAlchemy Documentation - Declarative Table Configuration](https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html)
- **license:** MIT License; SQLAlchemy official documentation summary
- **ability_weights:** `{"theory":0.3,"practice":0.35,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

应用数据结构应把需要稳定查询和关联的对象建模为具有明确主键、字段类型、约束和关系的实体。经常参与筛选、排序、唯一性判断或外键连接的数据应使用可索引字段，变化较快且通常整体读取的附加属性才适合放入 JSON。模型还要明确空值、默认值、级联行为和时间字段，避免同一业务状态出现多种表示。AI 应用额外需要保存模型、数据和评测版本等可追踪元数据，但运行时契约与持久化模型应通过显式转换隔离，不能把 ORM 对象直接作为跨组件协议。

**应用任务**
为任务、资源和审核结果列出实体，逐项标注主键、字段类型、空值、默认值、唯一约束、外键和时间字段，并区分稳定查询字段与附加 JSON 属性。

**预期结果**
形成可关联查询的数据结构表，版本追踪字段明确，运行时契约与 ORM 模型通过显式转换隔离。

## Docker 容器化部署
- **knowledge_id:** `docker_containerization`
- **category:** 工程基础
- **difficulty:** 2
- **tags:** docker, container, deployment
- **source:** [Docker Documentation - Build and Run Your Image](https://docs.docker.com/get-started/introduction/build-and-push-first-image/)
- **license:** Apache-2.0 repository license; Docker official documentation summary
- **ability_weights:** `{"theory":0.2,"practice":0.5,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

Docker 镜像把应用代码、运行时和依赖打包成可重复分发的只读层，容器则是镜像的运行实例。Dockerfile 应固定合适的基础镜像、先复制依赖清单以利用缓存，再复制应用代码，并使用非 root 用户和明确启动命令。配置和密钥在运行时注入，不写入镜像层。多服务开发环境可用 Compose 描述应用、数据库和向量库的网络、端口、健康检查与持久卷。镜像构建成功不代表服务可用，启动后仍需检查迁移、健康端点和依赖服务状态。

**应用任务**
设计镜像与 Compose，固定基础镜像和依赖层，使用非 root、运行时配置、健康检查、服务网络和持久卷。

**预期结果**
构建可重复且密钥不进入镜像，多服务启动后通过迁移、健康端点和依赖状态确认真实可用。

## 文档解析与清洗
- **knowledge_id:** `document_parsing`
- **category:** 知识管理
- **difficulty:** 2
- **tags:** document, parsing
- **source:** [pypdf Documentation - Text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)
- **license:** BSD-3-Clause License; pypdf official documentation summary
- **ability_weights:** `{"theory":0.2,"practice":0.5,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

文档解析要尽可能保留标题层级、段落、列表、表格、代码块和页码等结构，并移除重复页眉页脚、导航、乱码和不可见控制字符。扫描 PDF 可能需要 OCR，表格或多栏版式不能简单按阅读流拼接，否则字段和值会错位。清洗后应保留原文定位信息和来源元数据，便于引用回查。解析结果为空、字符异常或重复率过高时应拒绝入库并报告原因；错误清洗会同时污染 embedding、召回和最终事实审核。

**应用任务**
对包含标题、列表、表格、代码块或页码的文档执行解析清洗，检查层级、阅读顺序、定位、乱码和重复内容。

**预期结果**
得到结构与来源位置可回查的规范文本，空文本、字符异常、表格错位或重复率过高会被拒绝。

## Embedding 基础
- **knowledge_id:** `embedding_basics`
- **category:** RAG
- **difficulty:** 2
- **tags:** embedding, vector
- **source:** [OpenAI Documentation - Embeddings](https://platform.openai.com/docs/guides/embeddings)
- **license:** OpenAI official documentation; summarized for training
- **ability_weights:** `{"theory":0.45,"practice":0.25,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

Embedding 模型把文本映射为固定维度的数值向量，相关文本通常在该向量空间中距离更近。建库向量和查询向量必须来自同一模型与兼容预处理流程，否则维度可能不一致，或即使维度相同也失去可比性。应用应记录模型名、维度和索引版本，并对空文本、批处理数量、限流和异常响应进行校验。Embedding 只提供相似性信号，不证明事实正确；检索结果还要经过领域过滤、来源校验和任务策略排序。

**应用任务**
记录建库和查询的 embedding 模型、维度、预处理与索引版本，检查空文本、批量数量、限流和异常响应。

**预期结果**
形成向量兼容性检查表，建库与查询向量可比较，异常输入被阻断，相似性不被表述为事实正确性。

## 离线评测指标
- **knowledge_id:** `evaluation_metrics`
- **category:** 质量保障
- **difficulty:** 3
- **tags:** evaluation, metrics
- **source:** [OpenAI Documentation - Evaluation Best Practices](https://platform.openai.com/docs/guides/evaluation-best-practices)
- **license:** OpenAI official documentation; summarized for training
- **ability_weights:** `{"theory":0.3,"practice":0.25,"learning_speed":0.0,"problem_solving":0.35,"knowledge_breadth":0.1}`

离线评测先固定任务定义、代表性案例、参考答案或评分 rubric、数据版本和模型配置，再批量运行被测系统。指标必须对应实际失败风险，例如任务完成率、事实正确率、检索召回、引用支持率、格式合法率、延迟和成本，并同时报告分子、分母、不可判定样例和失败 case ID。开发集用于分析错误和调整实现，独立验收集只用于判断版本是否达到门槛，不能针对验收样例逐条调参。模型输出存在随机性时要固定可控参数或重复运行，并把提示、检索、生成、工具和评分器分别归因。

**应用任务**
固定任务、案例、rubric、数据和模型版本，为任务、事实、检索、引用、格式、延迟和成本定义分子分母并运行两套数据。

**预期结果**
形成包含不可判定、失败 case ID 和分阶段归因的可复现报告，随机性通过固定参数或重复运行处理。

## FastAPI 接口设计
- **knowledge_id:** `fastapi_endpoint_design`
- **category:** 后端开发
- **difficulty:** 2
- **tags:** fastapi, backend
- **source:** [FastAPI Documentation - Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- **license:** MIT License; FastAPI official documentation summary
- **ability_weights:** `{"theory":0.2,"practice":0.5,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

FastAPI 接口应按业务资源组织 APIRouter 和路径，使用类型标注与 Pydantic 模型描述请求参数、请求体和响应。依赖注入适合提供数据库会话、认证上下文和共享服务，业务逻辑则放在 service 层，避免路由函数承担完整流程。公共响应可以包含 schema_version、request_id，以及 data 或 error；HTTP 状态码与错误对象应保持一致。修改端点字段时必须同步客户端类型，并为成功、空结果、校验失败和服务异常添加聚焦测试。

**应用任务**
为业务资源设计路由、Pydantic 请求响应、认证与数据库依赖，把业务处理放入 service 并列出四类接口测试。

**预期结果**
端点返回一致 envelope，HTTP 状态与错误对象一致，字段变化能够同步到客户端类型。

## 前端 API 客户端封装
- **knowledge_id:** `frontend_api_client`
- **category:** 前端开发
- **difficulty:** 2
- **tags:** axios, frontend
- **source:** [Axios Documentation - The Axios Instance](https://axios-http.com/docs/instance)
- **license:** MIT License; Axios official documentation summary
- **ability_weights:** `{"theory":0.15,"practice":0.55,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

前端 API 客户端应集中配置 baseURL、超时和必要请求头，并使用 TypeScript 类型描述服务端响应。响应拦截器可以提取 request_id、规范化网络错误与服务端 error，但不能吞掉原始状态码或把失败转换成空成功。每个业务模块封装清晰方法，页面负责加载、空、失败和成功展示。取消过期请求或比较 task_id 可以避免快速切换页面时发生竞态；SSE 连接与普通 Axios 请求分开管理，并在组件卸载或任务结束时释放。

**应用任务**
为业务模块封装带 TypeScript 类型的 Axios 方法，统一超时、请求头和错误规范化，并设计取消旧请求与 SSE 生命周期。

**预期结果**
页面区分加载、空、失败和成功，request_id 与状态码可追踪，组件卸载或任务终止时释放连接。

## Vue 前端状态管理
- **knowledge_id:** `frontend_vue_state`
- **category:** 前端开发
- **difficulty:** 2
- **tags:** vue, pinia
- **source:** [Pinia Documentation - Core concepts](https://pinia.vuejs.org/core-concepts/)
- **license:** MIT License; Pinia official documentation summary
- **ability_weights:** `{"theory":0.15,"practice":0.55,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

Vue 3 使用响应式状态驱动组件渲染，跨页面共享的用户、任务、资源和 Agent 状态可集中到 Pinia store。store 应按业务边界划分 state、getters 和 actions，组件只消费所需状态，避免把临时表单值和所有服务端数据堆进单一全局对象。异步 action 要显式维护 loading、error 和 empty 状态，并以 task_id 合并轮询或 SSE 更新，防止旧请求覆盖新任务。需要持久化的最小导航状态与敏感业务载荷应分开，刷新后优先从后端重新获取真实状态。

**应用任务**
把用户、任务和资源按业务边界组织为 Pinia state、getters 和 actions，为异步 action 设计 loading、error、empty 与竞态保护。

**预期结果**
组件只消费所需状态，旧请求不覆盖新任务，刷新后从后端恢复真实状态且敏感载荷不被多余持久化。

## 函数调用与工具使用
- **knowledge_id:** `function_calling_tools`
- **category:** 模型调用
- **difficulty:** 3
- **tags:** tools, function-calling
- **source:** [OpenAI Documentation - Function calling](https://platform.openai.com/docs/guides/function-calling)
- **license:** OpenAI official documentation; summarized for training
- **ability_weights:** `{"theory":0.2,"practice":0.4,"learning_speed":0.0,"problem_solving":0.3,"knowledge_breadth":0.1}`

函数调用让模型输出工具名称和结构化参数，由应用决定是否执行检索、计算、数据库查询等外部能力。每个工具应使用窄而清晰的 schema，描述参数类型、必填条件和作用范围；服务端必须再次验证参数、权限和资源归属，不能因为参数来自模型就直接信任。工具结果以明确角色和调用 ID 回传，使模型能够继续推理。执行失败、超时或返回空结果时，应提供受控错误并限制循环次数，避免 Agent 无限重复调用或越权访问。

**应用任务**
为外部工具定义窄参数 Schema、权限范围、资源归属校验、超时和最大循环次数，并设计成功、失败与空结果回传。

**预期结果**
形成工具调用契约，模型只提出名称与参数，服务端完成验证授权，调用 ID 能关联执行结果。

## Git 协作与变更管理
- **knowledge_id:** `git_collaboration`
- **category:** 工程基础
- **difficulty:** 1
- **tags:** git, collaboration
- **source:** [Pro Git - Distributed Git and Contributing to a Project](https://git-scm.com/book/en/v3/Distributed-Git-Contributing-to-a-Project)
- **license:** CC BY-NC-SA 3.0; official Git book summary
- **ability_weights:** `{"theory":0.15,"practice":0.55,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

Git 通过提交保存项目在某一时刻的可追溯快照。协作时应让每个提交聚焦一个可解释变化，提交说明描述意图，功能分支与主分支保持清晰边界，并在合并前完成差异检查和自动化测试。处理冲突时需要理解双方修改，不能用覆盖方式丢弃未知工作。数据集、评测脚本和算法版本也应随代码记录，使实验结果能映射到确定提交。敏感密钥、大型运行产物和本地数据库不应进入版本库。

**前置环境**
在一个已初始化且不含敏感密钥的 Git 仓库中进行练习。

**操作步骤**
1. 运行 git status 确认当前分支和工作区变化。
2. 运行 git diff 检查尚未暂存的实际差异。
3. 使用 git add <file1> <file2> 只暂存属于同一意图的文件，运行 git diff --cached 检查已暂存差异，再使用 git commit -m "<intent-based message>" 创建说明意图的提交。
4. 运行 git log --oneline 检查提交是否能够映射到该次变化。

```bash
git status
git diff
git add <file1> <file2>
git diff --cached
git commit -m "<intent-based message>"
git log --oneline
```

**预期结果**
git status 显示当前工作区状态，git diff 显示未暂存差异，git diff --cached 显示已暂存差异，git log --oneline 显示提交历史摘要。

**常见错误**
把敏感密钥或大型运行产物加入版本库，或在不了解双方修改时用覆盖方式解决冲突。

**验收标准**
提交只包含一个可解释变化，提交说明描述意图，并且变更前已检查实际差异和测试结果。

## 幻觉防护策略
- **knowledge_id:** `hallucination_guardrails`
- **category:** 质量保障
- **difficulty:** 3
- **tags:** hallucination, guardrails
- **source:** [NIST AI 600-1 - Artificial Intelligence Risk Management Framework: Generative AI Profile](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)
- **license:** NIST publication; official guidance summary
- **ability_weights:** `{"theory":0.25,"practice":0.25,"learning_speed":0.0,"problem_solving":0.4,"knowledge_breadth":0.1}`

生成式 AI 的事实错误不能只靠一条禁止编造的提示消除。有效防护要覆盖数据、检索、生成、验证和发布：限定可信来源并保留引用；要求模型在证据不足时说明不确定性；对结构、权限和高风险结论执行确定性校验；使用代表性案例测量事实错误；对高影响或争议结果保留人工监督。评审模型本身也可能出错，因此不能把模型评分当作绝对真值，应使用人工标注样例校准规则并持续抽查。风险措施还应与使用场景和后果相匹配，避免用同一阈值处理所有任务。

**应用任务**
针对生成场景分别设计数据、检索、生成、确定性校验、模型审核、发布门槛和人工监督措施并标注风险。

**预期结果**
形成分层防护表，证据不足、结构错误、高风险结论和评审分歧有不同且可测量的处置。

## HTTP 与 REST 基础
- **knowledge_id:** `http_rest_basics`
- **category:** 工程基础
- **difficulty:** 1
- **tags:** http, rest
- **source:** [RFC 9110 - HTTP Semantics](https://datatracker.ietf.org/doc/html/rfc9110)
- **license:** IETF Trust legal provisions; official standards summary
- **ability_weights:** `{"theory":0.25,"practice":0.45,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

**请求与响应**
HTTP 请求由方法、目标 URI、头字段和可选消息内容组成，响应使用状态码表达处理结果。

**方法语义**
面向资源的 API 通常让 GET 获取表示且保持安全语义，让 POST 提交处理或创建资源，让 PUT 替换已知资源，让 PATCH 表达部分修改，让 DELETE 请求删除资源。幂等性决定客户端在连接中断后能否安全重试，但具体接口仍需说明业务副作用，不能仅根据方法名推断特定服务的实际行为。

**错误边界**
服务端应使用合适的 2xx、4xx、5xx 状态码，并用稳定 JSON 错误结构提供 request_id 和可处理的错误信息。通用 HTTP 语义不能证明某个兼容服务一定返回某个具体错误码或错误体。

**操作步骤**
1. 选择一份真实 API 文档，记录一个请求的方法、目标 URI、头字段和可选消息内容。
2. 对照文档标注该方法的安全性、幂等性和可能的业务副作用，不仅凭方法名推断。
3. 检查成功与失败响应如何使用 2xx、4xx、5xx，并记录错误结构中的 request_id 和可处理信息。
4. 模拟连接中断场景，根据幂等性和业务副作用判断是否允许重试。

**预期结果**
形成一份请求与响应检查表，能够区分通用 HTTP 语义和目标服务明确声明的行为。

**常见错误**
把 HTTP 成功等同于业务成功，或仅根据 GET、POST 等方法名推断某个服务的实际副作用和错误体。

**验收标准**
检查表包含方法、URI、头字段、消息内容、状态类别、错误结构、幂等性和重试判断。

## 神经网络与感知机
- **knowledge_id:** `ki_0e673b8eec42b320`
- **category:** 深度学习
- **difficulty:** 2
- **tags:** neural-network, perceptron, activation, mlp, source_record:ai_深度学习_001
- **source:** [Goodfellow, Bengio & Courville《深度学习》(花书, 2016)](https://www.deeplearningbook.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

人工神经网络由大量相互连接的神经元组成，每个神经元对输入加权求和后经激活函数输出。感知机是最简单的单层神经网络，能实现线性分类，但无法解决线性不可分问题（如异或）；多层感知机（MLP）通过引入隐藏层与非线性激活函数，使网络能够逼近任意复杂函数。常用激活函数包括 ReLU、Sigmoid、Tanh 等，非线性激活是神经网络具备强大表达能力的必要条件。神经网络的深度与宽度共同决定其容量，是深度学习的基础结构。

## GPT 与生成式预训练
- **knowledge_id:** `ki_185eac93556247a0`
- **category:** 自然语言处理
- **difficulty:** 3
- **tags:** gpt, decoder, generative, autoregressive, source_record:ai_自然语言处理_004
- **source:** [Brown et al.《Language Models are Few-Shot Learners》(GPT-3, 2020)](https://arxiv.org/abs/2005.14165)
- **license:** 学术论文; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

GPT 系列是基于 Transformer 解码器的生成式预训练语言模型，采用自回归方式逐词预测下一词，因而具有强大的文本生成能力。GPT 的演进体现了规模化的威力：GPT-1 验证预训练有效性，GPT-2 展示多任务泛化潜力，GPT-3 以千亿参数展现少样本学习（few-shot）能力，证明了模型与数据规模增大带来的能力涌现。GPT 代表解码器架构，与 BERT 的编码器架构形成理解与生成的互补，是 ChatGPT 等对话模型的技术基础。

## 子词嵌入与字节对编码
- **knowledge_id:** `ki_23ed31d7af0f95d0`
- **category:** 预训练
- **difficulty:** 2
- **tags:** subword, fasttext, bpe, source_record:ml_大语言模型_llm_006
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_natural-language-processing-pretraining/subword-embedding.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

子词嵌入通过利用词的内部形态结构来改进词向量表示，fastText是典型代表，它将每个中心词表示为字符n-gram向量的和，从而共享相似结构词的参数，使罕见词和词表外词也能获得较好向量。提取子词时需要在词首尾添加特殊字符以区分前缀后缀，并指定n-gram长度范围。字节对编码（BPE）是一种压缩算法，通过迭代合并最频繁的连续符号对来生成任意长度的子词，能适应固定词表大小，已用于GPT-2和RoBERTa等预训练模型的输入表示。实现BPE时应初始化符号词表为所有字符和特殊符号，统计词频时不考虑跨词边界，并在每个词尾附加特殊符号以便恢复原词序列。

## 反向传播算法
- **knowledge_id:** `ki_307d4cd9dc09951f`
- **category:** 深度学习
- **difficulty:** 3
- **tags:** backpropagation, chain-rule, gradient, training, source_record:ai_深度学习_002
- **source:** [Goodfellow, Bengio & Courville《深度学习》(花书, 2016)](https://www.deeplearningbook.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

反向传播是训练神经网络的核心算法，利用链式法则高效计算损失函数对网络中每个参数的梯度。训练过程包括前向传播（由输入计算输出与损失）与反向传播（由输出层向输入层逐层回传误差梯度）两个阶段，再利用梯度下降等优化算法更新参数。反向传播使深层网络的参数能够被有效训练，是现代深度学习的基石。其关键是计算图与链式法则，实践中还需处理梯度消失、梯度爆炸与数值稳定性等问题。

## BERT 与双向编码
- **knowledge_id:** `ki_3e3229243be11058`
- **category:** 自然语言处理
- **difficulty:** 3
- **tags:** bert, encoder, bidirectional, understanding, source_record:ai_自然语言处理_003
- **source:** [Devlin et al.《BERT: Pre-training of Deep Bidirectional Transformers》(2018)](https://arxiv.org/abs/1810.04805)
- **license:** 学术论文; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

BERT（2018）是基于 Transformer 编码器的预训练语言模型，采用双向编码，即同时利用上下文两侧信息理解每个词的语义，因此同一词在不同语境中具有不同的向量表示。BERT 通过遮罩语言建模与下一句预测两个自监督任务在大规模语料上预训练，再针对下游任务微调，显著提升了情感分类、命名实体识别、问答等自然语言理解任务的性能。BERT 代表编码器架构模型，擅长理解类任务，与擅长生成的 GPT 解码器架构形成互补。

## 语言模型与数据集
- **knowledge_id:** `ki_46d9d4de4c4835d2`
- **category:** 基础概念
- **difficulty:** 2
- **tags:** language-model, probability, n-gram, smoothing, source_record:ml_自然语言处理_nlp_003
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_recurrent-neural-networks/language-models-and-dataset.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

语言模型的目标是估计文本序列的联合概率，通过逐词元采样可生成自然文本，但理想模型需理解语义而非仅语法。训练时，单词概率可由语料库词频估计，但罕见词组合因数据稀疏难以准确，需使用拉普拉斯平滑添加小常量以避免零计数。然而，基于计数的模型存储开销大、忽略词义，且长序列罕见，效果有限。马尔可夫假设可简化建模，如一阶假设当前词仅依赖前一词，对应一元、二元和三元语法模型。实际应用中，应优先考虑高频词统计，但需意识到简单频率方法对长依赖和语义理解不足，需结合更高级模型。

## 语言模型与预训练
- **knowledge_id:** `ki_63bef1cdb46b2948`
- **category:** 自然语言处理
- **difficulty:** 3
- **tags:** language-model, pretraining, transfer-learning, self-supervised, source_record:ai_自然语言处理_002
- **source:** [Devlin et al.《BERT: Pre-training of Deep Bidirectional Transformers》(2018)](https://arxiv.org/abs/1810.04805)
- **license:** 学术论文; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

语言模型是估计词序列概率分布的模型，本质是根据上文预测下一个词（补全续写）。预训练指在大规模语料上先训练模型获得通用语言知识，再迁移到下游任务。预训练的演进从静态词向量（Word2Vec）到上下文相关表示（ELMo、BERT），技术手段包括遮罩语言建模（MLM，完形填空）与下一句预测（NSP）等自监督任务。预训练—微调范式大幅提升了下游任务性能并降低了标注需求，是当代大语言模型能力的基础。

## 张量数据操作基础
- **knowledge_id:** `ki_65f1659af27d4984`
- **category:** 基础概念
- **difficulty:** 1
- **tags:** tensor, ndarray, reshape, deep-learning, source_record:ml_深度学习基础_001
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_preliminaries/ndarray.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

深度学习中的数据以张量（tensor）形式存储，张量是多维数值数组，一维对应向量，二维对应矩阵，更高维没有特殊名称。深度学习框架的张量类（如PyTorch的Tensor、TensorFlow的Tensor）与NumPy的ndarray类似，但额外支持GPU加速和自动微分，因此更适合深度学习。创建张量时，可以用arange生成连续整数序列，默认创建为整数或浮点数，且除非指定，张量存储在CPU内存中。访问张量的形状用shape属性，元素总数用numel或size。改变形状而不改变元素数量和值时，使用reshape函数，可以指定目标维度，其中-1表示自动计算该维度大小。初始化张量时，可以用zeros、ones创建全0或全1张量，或从特定分布随机采样。理解张量的基本操作是进行深度学习计算的前提，后续章节会通过实例巩固这些概念。

## 自注意力与位置编码
- **knowledge_id:** `ki_6613d44b56deaa3e`
- **category:** 注意力机制
- **difficulty:** 2
- **tags:** self-attention, positional-encoding, sequence-modeling, source_record:ml_自然语言处理_nlp_021
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_attention-mechanisms/self-attention-and-positional-encoding.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

自注意力让同一序列的词元同时充当查询、键和值，每个查询关注所有键值对并输出等长序列，因此能直接建模任意位置间的依赖。相比卷积和循环网络，自注意力计算复杂度为O(n²d)，但顺序操作仅O(1)，最大路径长度为O(1)，更适合并行和捕捉远距离关系。然而自注意力本身不感知顺序，必须添加位置编码来注入序列位置信息。使用时应根据序列长度权衡计算开销，并确保位置编码与输入维度匹配。

## 智能体与环境
- **knowledge_id:** `ki_68375283ac5ca527`
- **category:** AI概论
- **difficulty:** 2
- **tags:** agent, environment, perception, action, source_record:ai_AI概论_003
- **source:** [Russell & Norvig《人工智能：现代方法》(AIMA, 第4版, 2020)](http://aima.cs.berkeley.edu)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

智能体（Agent）是能够通过传感器感知环境、通过执行器对环境施加影响的系统。智能体的核心是感知—决策—行动的循环，其行为由感知序列到行动的映射（智能体函数）描述。根据环境特性，智能体所处的环境可分为完全可观测与部分可观测、确定性与随机性、静态与动态、离散与连续等类型，不同环境特性决定智能体需要采用不同的设计策略。理性智能体的目标是在给定感知与先验知识下，选择使期望效用最大化的行动。智能体框架是贯穿现代 AI（从专家系统到 LLM Agent）的统一视角。

## 控制流
- **knowledge_id:** `ki_747302beb84cdbdf`
- **category:** Python基础
- **difficulty:** 1
- **tags:** control-flow, if, for, while, comprehension, source_record:pyda_Python基础_003
- **source:** [Python 官方文档（Python 3 教程）](https://docs.python.org/zh-cn/3/)
- **license:** 官方文档; 内容总结
- **ability_weights:** `{"theory":0.25,"practice":0.4,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

Python 控制流包括条件判断（if-elif-else）与循环（for、while）。for 循环遍历序列或可迭代对象，是数据处理中最常用的循环结构；while 循环在条件满足时重复执行。Python 的列表推导式（comprehension）提供简洁的序列生成与变换方式，如 [x*2 for x in data]。在数据分析中，控制流用于数据的逐条处理、条件筛选与批量变换，但应优先使用向量化的 NumPy/Pandas 操作替代显式循环以提升性能。

## 模型评估与交叉验证
- **knowledge_id:** `ki_747c6d2d0ed6ba38`
- **category:** 机器学习
- **difficulty:** 2
- **tags:** cross-validation, evaluation, metric, holdout, source_record:ai_机器学习_004
- **source:** [Goodfellow, Bengio & Courville《深度学习》(花书, 2016)](https://www.deeplearningbook.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

模型评估用于客观衡量模型的泛化能力。基本做法是把数据划分为训练集与测试集，在训练集上训练、在测试集上评估；当数据量较小或需要更稳定的估计时，采用 k 折交叉验证，将数据分成 k 份，轮流以其中一份为验证集、其余为训练集，取 k 次结果的平均。评估指标因任务而异：分类常用准确率、精确率、召回率、F1 与 ROC-AUC，回归常用均方误差等。评估需注意数据泄露、类别不平衡与评估集与训练集分布一致等问题，避免用测试集调参导致评估失真。

## 数据预处理基础
- **knowledge_id:** `ki_8107173e3737a444`
- **category:** 基础概念
- **difficulty:** 1
- **tags:** pandas, preprocessing, data, source_record:ml_深度学习基础_002
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_preliminaries/pandas.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

深度学习通常从预处理原始数据开始，而非直接使用张量。应使用pandas读取CSV等格式的数据，并注意缺失值以NaN表示。处理缺失值时，可以采用插值法（如用均值填充数值列）或删除法，但插值法更常用。对于类别值，应将NaN视为独立类别，并使用独热编码（如get_dummies）转换为数值列，避免模型误解类别含义。预处理后，需将pandas数据转换为张量格式以供模型使用。整个过程应确保数据清洗和特征工程合理，以提升模型训练效果。

## 函数与模块
- **knowledge_id:** `ki_884cca8ccb2c9f0c`
- **category:** Python基础
- **difficulty:** 1
- **tags:** function, module, import, def, source_record:pyda_Python基础_004
- **source:** [Python 官方文档（Python 3 教程）](https://docs.python.org/zh-cn/3/)
- **license:** 官方文档; 内容总结
- **ability_weights:** `{"theory":0.25,"practice":0.4,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

函数用 def 定义，通过参数接收输入、return 返回结果，是代码复用与逻辑封装的基础。模块是 Python 代码的组织单元，通过 import 导入其他模块或包的功能。数据分析中大量使用 import numpy as np、import pandas as pd 等方式导入第三方库，并使用其中的函数与类。理解函数的参数传递、默认参数与返回值，以及模块的导入与使用，是编写可维护数据分析代码的基础。

## 自动微分与反向传播
- **knowledge_id:** `ki_8ba31f93fb9f7bcd`
- **category:** 基础概念
- **difficulty:** 1
- **tags:** autograd, backpropagation, computational-graph, source_record:ml_深度学习基础_005
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_preliminaries/autograd.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

自动微分是深度学习优化的核心，通过构建计算图跟踪数据与操作，系统能自动反向传播梯度，避免手工求导。使用框架时，需要为参数分配梯度存储空间，并注意默认行为：PyTorch和Paddle会累积梯度，每次反向传播前应清零；MXNet和TensorFlow则自动覆盖。梯度计算应验证正确性，例如对标量函数求导后检查结果是否符合解析解。当输出非标量时，梯度是矩阵或更高维张量，需明确求导目标。自动微分简化了复杂模型训练，但开发者需理解计算图机制和梯度管理，避免内存耗尽或梯度错误。

## 大语言模型的能力与局限
- **knowledge_id:** `ki_8fcfe12783a7baea`
- **category:** 自然语言处理
- **difficulty:** 2
- **tags:** emergence, few-shot, hallucination, limitation, source_record:ai_自然语言处理_006
- **source:** [Brown et al.《Language Models are Few-Shot Learners》(GPT-3, 2020)](https://arxiv.org/abs/2005.14165)
- **license:** 学术论文; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

大语言模型展现出涌现能力，即当规模超过一定阈值后出现小模型不具备的能力，如少样本学习、上下文学习、多任务与初步推理。这些能力使其成为通用任务的基础设施。但大语言模型也存在明显局限：可能生成看似合理但事实错误的内容（幻觉），缺乏真正的逻辑与因果推理，对训练数据中的偏差与有害信息可能继承与放大，且存在可解释性危机与较高的推理成本。理解其能力边界是负责任地使用大模型的前提，通常需通过检索增强、外部工具与人工审核等手段缓解其局限。

## Transformer架构核心
- **knowledge_id:** `ki_947e73313a12fc88`
- **category:** 注意力机制
- **difficulty:** 2
- **tags:** transformer, self-attention, encoder-decoder, source_record:ml_自然语言处理_nlp_022
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_attention-mechanisms/transformer.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

Transformer完全基于注意力机制，摒弃了卷积和循环层，凭借自注意力的并行计算和最短路径优势成为现代深度学习的基础。其编码器由多个相同层叠加，每层包含多头自注意力和基于位置的前馈网络两个子层，均采用残差连接和层规范化，输入需加位置编码以保留序列顺序。解码器在编码器结构基础上，额外插入编码器-解码器注意力层，其中查询来自解码器前层，键和值来自编码器输出；解码器自注意力需使用掩蔽机制，确保每个位置仅能关注之前位置，维持自回归属性。基于位置的前馈网络对序列各位置应用同一MLP，实现逐位置的非线性变换。

## 多头注意力机制
- **knowledge_id:** `ki_96709f9830593e5c`
- **category:** 注意力机制
- **difficulty:** 3
- **tags:** multihead, attention, transformer, source_record:ml_自然语言处理_nlp_020
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_attention-mechanisms/multihead-attention.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

多头注意力通过并行学习多组独立的线性投影，将查询、键和值变换到不同子空间，并分别执行注意力汇聚，最后拼接各头输出并经线性投影得到最终结果。这种设计允许模型同时捕获序列内不同范围的依赖关系，如短距离和长距离依赖，从而表达比简单加权平均更复杂的函数。实现时通常选用缩放点积注意力作为每个头的基础，并设定各投影维度相等且等于输出维度除以头数，以控制计算和参数开销。若将线性变换输出维度设为头数与隐藏维度的乘积，则可并行计算所有头，提升效率。每个头可能关注输入的不同部分，组合后增强模型的表示能力。

## 基本数据类型
- **knowledge_id:** `ki_a23b92994c49c639`
- **category:** Python基础
- **difficulty:** 1
- **tags:** data-type, list, dict, tuple, set, source_record:pyda_Python基础_002
- **source:** [Python 官方文档（Python 3 教程）](https://docs.python.org/zh-cn/3/)
- **license:** 官方文档; 内容总结
- **ability_weights:** `{"theory":0.25,"practice":0.4,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

Python 的基本数据类型包括数值（整数 int、浮点数 float、复数 complex）、布尔 bool、字符串 str，以及容器类型：列表 list（有序可变）、元组 tuple（有序不可变）、字典 dict（键值对）、集合 set（无序不重复）。列表适合存放同质数据序列，字典适合键值查找与结构化数据，元组用于不可变的数据组合。掌握这些数据类型的特性与适用场景，是数据处理的基础，尤其是列表与字典在数据分析中的频繁使用。

## 词嵌入与word2vec
- **knowledge_id:** `ki_d122c91269e87257`
- **category:** 词嵌入
- **difficulty:** 2
- **tags:** word2vec, skip-gram, CBOW, embedding, source_record:ml_大语言模型_llm_001
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_natural-language-processing-pretraining/word2vec.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

词嵌入是将词映射为实向量的技术，用于表示词义和特征，解决独热向量无法编码词间相似度的问题。word2vec包含跳元模型和连续词袋模型，均为自监督模型，通过条件概率训练。跳元模型假设中心词生成周围上下文词，每个词有中心词和上下文词两个向量，用softmax建模条件概率，训练时最大化似然函数，通常用中心词向量作为词表示。连续词袋模型假设上下文词生成中心词，对上下文词向量取平均，训练类似，通常用上下文词向量作为词表示。训练需注意词表大时梯度计算复杂度高，可考虑近似训练方法。

## Jupyter Notebook
- **knowledge_id:** `ki_e669ac1d0bc95972`
- **category:** Python基础
- **difficulty:** 1
- **tags:** jupyter, notebook, repl, interactive, source_record:pyda_Python基础_005
- **source:** [Wes McKinney《利用Python进行数据分析》(第3版, 2022)](https://www.oreilly.com.cn)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.25,"practice":0.4,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

Jupyter Notebook 是交互式的计算环境，以单元格为单位组织代码、文本与可视化输出，支持逐段执行与结果即时展示，是数据分析与探索的理想工具。Notebook 把代码、图表与说明文档整合在一起，便于复现分析过程与分享结果，广泛用于数据清洗、探索性分析与报告生成。其交互式特性适合数据探索时的反复试算，是数据分析工作流的重要组成部分。

## 文本预处理流程
- **knowledge_id:** `ki_e82e51e944744bdb`
- **category:** 基础概念
- **difficulty:** 1
- **tags:** text-preprocessing, tokenization, vocabulary, source_record:ml_自然语言处理_nlp_002
- **source:** [动手学深度学习 (Dive into Deep Learning, d2l.ai 中文版)](https://zh.d2l.ai/chapter_recurrent-neural-networks/text-preprocessing.html)
- **license:** CC BY-SA 4.0; d2l.ai textbook summary
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

文本预处理是将原始文本转换为模型可操作的数字序列的核心步骤，通常包括四个环节：首先将文本作为字符串加载到内存中，并可以按需清洗，例如忽略标点符号和统一字母大小写；其次将字符串拆分为词元，词元可以是单词或字符，单词级拆分常用空格分割，字符级则直接列出每个字符；然后需要建立词表，将每个词元映射到唯一的数字索引，词表应覆盖训练数据中的所有词元；最后将文本转换为数字索引序列，以便模型直接读取。预处理时需要注意语料库规模，小语料库适合演示，但真实应用可能包含数十亿单词，因此处理流程应高效且可扩展。词元类型的选择会影响后续模型设计，字符级适合处理未知词或形态变化，单词级则保留更多语义信息，开发者应根据任务需求决定。

## 大语言模型的缩放法则
- **knowledge_id:** `ki_eb61025d0c6deea3`
- **category:** 自然语言处理
- **difficulty:** 3
- **tags:** scaling-law, llm, parameters, compute, source_record:ai_自然语言处理_005
- **source:** [Kaplan et al.《Scaling Laws for Neural Language Models》(2020)](https://arxiv.org/abs/2001.08361)
- **license:** 学术论文; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

缩放法则（Scaling Laws）揭示了大语言模型性能与资源投入之间的规律：在参数规模、数据规模与算力三者中任一项指数增长，都会带来模型性能（如损失）的线性提升，其贡献排序大致为参数规模、数据规模、算力。这意味着扩大模型与数据规模是提升性能的可靠路径，也解释了大模型的性能优势来源。但规模化带来巨大的训练成本与能耗，且性能提升存在边际递减，因此大模型的发展需要在规模、成本与能力之间权衡，也催生了高效训练、蒸馏与压缩等研究方向。

## 过拟合与正则化
- **knowledge_id:** `ki_f183dd3f6c58b215`
- **category:** 机器学习
- **difficulty:** 3
- **tags:** overfitting, regularization, bias-variance, generalization, source_record:ai_机器学习_003
- **source:** [Goodfellow, Bengio & Courville《深度学习》(花书, 2016)](https://www.deeplearningbook.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

过拟合指模型在训练数据上表现很好、但在新数据上泛化能力差的现象，源于模型过度拟合训练样本中的噪声。过拟合与欠拟合、偏差-方差权衡密切相关：模型过于简单导致欠拟合（高偏差），过于复杂导致过拟合（高方差）。正则化是抑制过拟合的主要手段，通过在损失函数中加入对模型复杂度的惩罚（如 L1、L2 正则）约束参数，此外还有早停、数据增强、Dropout、增加训练数据等方法。控制模型复杂度以获得良好泛化，是机器学习的核心课题。

## 监督、无监督与强化学习
- **knowledge_id:** `ki_fc9bb9f9de5913e5`
- **category:** 机器学习
- **difficulty:** 2
- **tags:** supervised, unsupervised, reinforcement, paradigms, source_record:ai_机器学习_001
- **source:** [Goodfellow, Bengio & Courville《深度学习》(花书, 2016)](https://www.deeplearningbook.org)
- **license:** 公开出版教材; 内容总结
- **ability_weights:** `{"theory":0.4,"practice":0.2,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.15}`

机器学习按训练信号分为三大范式。监督学习从带标签的样本中学习输入到输出的映射，用于分类与回归任务；无监督学习在无标签数据中发现内在结构，用于聚类、降维与密度估计；强化学习通过智能体与环境交互获得的奖励信号学习策略，目标是最大化长期累积回报。此外还有介于监督与无监督之间的半监督学习与自监督学习（如大模型的预训练）。选择何种范式取决于标签的可得性与任务目标，是机器学习建模的首要判断。

## 知识库导入流程
- **knowledge_id:** `knowledge_base_ingestion`
- **category:** 知识管理
- **difficulty:** 2
- **tags:** knowledge-base, ingestion
- **source:** [Chroma Documentation - Adding Data to Chroma Collections](https://docs.trychroma.com/docs/collections/add-data)
- **license:** Apache-2.0 project documentation; official Chroma summary
- **ability_weights:** `{"theory":0.2,"practice":0.45,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

知识库导入应先解析并规范化文本，再校验稳定文档标识、正文、元数据和来源，拒绝重复标识、空内容以及无法解释的字段。写入向量库时，文档、元数据、ID 和 embedding 必须保持一一对应；更新已有内容要同步替换受影响片段和向量，删除内容则清理孤立记录。批量操作需要检查输入数组长度和模型维度，成功后再记录索引版本与条目数量。导入流程应具备幂等性和机器可读摘要，使同一数据版本重复执行不会产生重复 chunk，并能通过条数核对和代表性查询验证索引可用。

**应用任务**
对知识文档执行解析规范化、稳定 ID、正文元数据和来源校验，核对写入数组与向量维度并测试重复、更新和删除。

**预期结果**
导入具有幂等摘要，文档、metadata、ID 和向量一一对应，更新删除不留下重复或孤立片段。

## 知识检索智能体
- **knowledge_id:** `knowledge_retrieval_agent`
- **category:** 多智能体
- **difficulty:** 3
- **tags:** agent, retrieval
- **source:** [OpenAI Documentation - Retrieval](https://platform.openai.com/docs/guides/retrieval)
- **license:** OpenAI official documentation; summarized for training
- **ability_weights:** `{"theory":0.25,"practice":0.35,"learning_speed":0.0,"problem_solving":0.3,"knowledge_breadth":0.1}`

**知识检索智能体设计**

**职责边界**

检索智能体把用户问题和任务上下文转换为查询，从受控知识源中找出证据并返回带来源的片段。它负责查询构造、调用检索工具、过滤和整理结果，不负责凭模型记忆补写资料，也不应在没有证据时生成确定事实。应用应把向量库、文件搜索或数据库查询封装成权限明确的工具，并限制可访问的知识域。

**查询与召回**

查询可以包含用户目标、关键实体、时间或产品范围等约束。语义检索使用 embedding 找到含义相近的片段，元数据过滤用于限制文件、类别、日期或权限；当任务已经给出明确文档标识时，应优先在该范围内检索。候选数量要为后续过滤保留余量，但不能无限扩大。空查询、跨域结果、过期材料和来源字段不完整的候选应明确排除或标记，不允许静默伪造成有效证据。

**结果组织**

候选片段需要按稳定标识去重，避免相同正文或同一文档的相邻片段占满上下文。排序可以综合语义相关性、元数据约束、任务优先级和来源质量，但每个分数的含义必须统一，不能混用不同距离度量。对于多主题问题，应优先覆盖不同子问题，再用剩余预算补充细节。长文档片段应保留标题、章节或相邻上下文，使定义、条件和例外不会在切片后分离。

**来源与安全**

返回结果至少应包含片段标识、文档标识、正文、相关度、来源标题和可定位原文的位置。检索内容属于数据而不是系统指令，应用要防止文档中的恶意文字覆盖工具权限或运行规则。涉及私有文件时，权限校验必须发生在服务端检索边界，不能只依赖模型拒绝。普通日志只记录查询摘要、命中 ID、数量、耗时和错误类型，不记录完整私有正文或向量。

**验证**

检索质量应通过固定问题和相关文档标注评估，分别观察召回覆盖、排序、来源完整率和延迟。失败样例要区分查询表达不充分、数据未入库、切片不合理、过滤条件错误和向量模型不一致。只有开发集可用于调整查询与排序规则，独立验收集用于判断修改是否真正泛化。

**应用任务**
为多主题问题构造查询与元数据约束，从受控知识域召回、去重并覆盖各子问题，再输出正文、相关度、来源和定位。

**预期结果**
得到权限合规的带来源结果，空查询、跨域、过期和来源不完整候选被排除或明确标记。

## LangGraph StateGraph
- **knowledge_id:** `langgraph_stategraph`
- **category:** 多智能体
- **difficulty:** 3
- **tags:** langgraph, stategraph
- **source:** [LangGraph Documentation - Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- **license:** MIT License; LangGraph official documentation summary
- **ability_weights:** `{"theory":0.25,"practice":0.4,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

LangGraph StateGraph 以共享状态 schema、节点函数和边描述有状态工作流。节点接收当前状态并返回受控更新，普通边表达固定顺序，条件边根据状态选择下一节点；编译后的图可以使用 thread_id 和 checkpointer 保存可恢复执行。状态字段应有明确所有者和合并语义，数据库会话、客户端和不可序列化对象不能进入 State。项目只保留一个 build_learning_graph() 顶层构建函数，首次生成与反馈调整复用相同 task_id/thread_id；进程中断时通过 checkpoint 沿原任务自动恢复一次，审核未通过时沿同一线程进入有限局部修订。

**应用任务**
列出共享状态、图节点、固定边、条件边和有限循环，标注字段所有者、合并语义、thread_id 和恢复条件。

**预期结果**
形成可解释的 StateGraph，状态只含必要可序列化数据，循环有终止条件且失败可从检查点恢复。

## 大模型 API 调用
- **knowledge_id:** `llm_api_calling`
- **category:** 模型调用
- **difficulty:** 2
- **tags:** llm, api
- **source:** [OpenAI API Reference - Responses](https://developers.openai.com/api/reference/resources/responses)
- **license:** OpenAI official documentation; summarized for training
- **ability_weights:** `{"theory":0.2,"practice":0.5,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

**调用输入**
大模型 API 调用需要显式配置服务地址、模型、消息或输入、最大输出长度以及超时策略。调用前应限制输入大小并移除不必要的隐私数据。

**结果验证**
调用后校验结束原因、结构化字段和业务约束。这些要求不构成某个具体 SDK、端点、模型名或响应字段的代码示例；实际实现必须依据目标服务当前文档。

**失败分类**
对限流、服务不可用和网络超时可进行有上限的退避重试，对认证失败、无效参数等确定性错误应立即失败。不得在来源未指定时补充具体错误码。

**可观测边界**
普通运行记录只保存 task_id、模型名、耗时、token 用量、状态和内容摘要，不能记录完整画像、知识正文或生成资源。

**操作步骤**
1. 对照目标服务当前文档，列出服务地址、模型、输入、最大输出长度和超时等必需配置。
2. 使用已配置参数向目标服务发起一次不含真实隐私数据的最小真实调用，并记录实际结束原因和响应结构。
3. 使用本地结构化契约校验实际响应字段和业务约束，不推断文档未声明的字段。
4. 分别记录可重试的瞬时故障和应立即失败的确定性错误，并限制重试次数。
5. 检查普通日志只包含 task_id、模型名、耗时、token 用量、状态和内容摘要。

**预期结果**
形成一份基于目标服务当前文档和实际响应的调用验证记录，不包含自行补充的端点、模型名、错误码或响应字段。

**常见错误**
常见错误包括：把兼容接口当作行为完全一致，记录完整输入输出，或对认证失败和无效参数继续重试。

**验收标准**
验证记录包含输入边界、结构校验、失败分类、有限重试和日志隐私检查。

## 模型评审的可靠性与校准
- **knowledge_id:** `llm_judge_reliability`
- **category:** 质量保障
- **difficulty:** 4
- **tags:** evaluation, llm-judge, calibration
- **source:** [OpenAI Cookbook - Evaluating Model Performance](https://cookbook.openai.com/examples/evaluation/getting_started_with_openai_evals)
- **license:** MIT License; OpenAI Cookbook summary
- **ability_weights:** `{"theory":0.3,"practice":0.25,"learning_speed":0.0,"problem_solving":0.35,"knowledge_breadth":0.1}`

使用大模型评分时，评审提示必须提供清晰 rubric、待评内容和必要参考资料，要求输出结构化分数与理由。评分器可能受答案顺序、长度、措辞和自身知识偏差影响，因此需要用人工标注样例校准，并分别测量误通过和误拒绝。能够通过代码判断的格式、数值和引用存在性不应交给模型。评审失败时先检查输入和 rubric，再进行有限重试；多个评分器不一致也不能简单多数表决。高风险或持续分歧样例应进入人工复核，并把人工推翻结果加入后续评测集。

**应用任务**
用人工标注的正确、错误、来源不支持和边界样例校准评审 rubric，测量误通过、误拒绝与顺序敏感性。

**预期结果**
形成评分器校准报告，可确定项由代码判断，多模型冲突进入输入复核与独立仲裁。

## 检索元数据过滤
- **knowledge_id:** `metadata_filtering`
- **category:** RAG
- **difficulty:** 3
- **tags:** metadata, retrieval
- **source:** [Chroma Documentation - Metadata filtering](https://docs.trychroma.com/docs/querying-collections/metadata-filtering)
- **license:** Apache-2.0 project documentation; official Chroma summary
- **ability_weights:** `{"theory":0.2,"practice":0.45,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

元数据过滤在向量相似度之外限定候选范围，例如按 domain_code、知识 ID、分类、难度或标签筛选。过滤条件应使用建库时已保存且类型稳定的 metadata 字段，并在查询前确认 collection 支持对应操作。领域过滤属于正确性边界，不能仅依赖查询文本暗示领域；个性化难度则既可以先过滤，也可以保留更宽候选后参与排序。过滤过严会造成空结果，因此系统应返回明确 warning 和缺失知识 ID，而不是自动移除关键条件或跨领域补齐。

**应用任务**
为检索定义 domain_code、知识 ID、分类、难度和标签过滤，验证字段类型并测试过滤过严的空结果分支。

**预期结果**
形成明确过滤条件和空结果 warning，领域边界始终保留，系统不会跨领域静默补齐。

## MySQL 索引与查询
- **knowledge_id:** `mysql_indexing`
- **category:** 后端开发
- **difficulty:** 3
- **tags:** mysql, index
- **source:** [MySQL 8.0 Reference Manual - Optimization and Indexes](https://dev.mysql.com/doc/refman/8.0/en/optimization-indexes.html)
- **license:** Oracle official documentation; reference summary
- **ability_weights:** `{"theory":0.2,"practice":0.4,"learning_speed":0.0,"problem_solving":0.3,"knowledge_breadth":0.1}`

MySQL 索引通过有序结构减少扫描范围，适用于 public_id、domain_code、状态、时间戳和外键等高频过滤或连接字段。联合索引的列顺序应匹配实际查询的等值条件、范围条件和排序需求，不能因为字段经常出现就盲目建立多个重叠索引。唯一索引还能表达业务唯一性，但索引会增加写入和存储成本。优化前应使用 EXPLAIN 查看访问类型、候选索引和估算行数，并用代表性数据验证，而不是仅凭小型开发库的响应时间判断。

**应用任务**
选择包含等值过滤、范围、连接和排序的查询，用 EXPLAIN 比较无索引、单列索引与联合索引并记录写入代价。

**预期结果**
得到匹配真实查询顺序的最小索引方案，访问类型和估算扫描行数由代表性数据验证。

## 日志、指标与链路追踪
- **knowledge_id:** `observability_tracing`
- **category:** 质量保障
- **difficulty:** 3
- **tags:** observability, logging, tracing
- **source:** [OpenTelemetry Documentation - Observability Primer](https://opentelemetry.io/docs/concepts/observability-primer/)
- **license:** Apache-2.0; OpenTelemetry official documentation summary
- **ability_weights:** `{"theory":0.2,"practice":0.45,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

可观测性通过日志、指标和链路追踪解释系统正在发生什么。日志记录离散事件和错误类别，指标聚合请求量、延迟、失败率、token 用量等时间序列，trace 则使用统一上下文连接一次请求经过的 API、检索、模型和工具调用。每个任务应传播稳定 request_id 或 trace_id，并让 span 标注组件、状态和耗时，而不是保存完整敏感输入。监控要同时覆盖成功率和质量信号，设置可行动的告警，并通过采样控制成本。排障时从异常指标定位 trace，再查看经过脱敏的相关日志。

**应用任务**
设计 request_id 或 trace_id 在 API、检索、模型和工具间传播，定义日志、指标、span 的状态、耗时与脱敏字段。

**预期结果**
能够关联一次任务各组件的状态与延迟，普通日志不含敏感正文，告警可定位到具体 trace。

## OpenAI 兼容接口
- **knowledge_id:** `openai_compatible_api`
- **category:** 模型调用
- **difficulty:** 2
- **tags:** openai-compatible, api
- **source:** [OpenAI API Reference](https://developers.openai.com/api/reference/overview)
- **license:** OpenAI official documentation; summarized for training
- **ability_weights:** `{"theory":0.2,"practice":0.5,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

**兼容范围**
OpenAI 兼容接口通常复用模型列表、聊天生成、Responses 或 Embeddings 等请求形态，让应用通过配置切换兼容服务。兼容不意味着行为完全一致：服务商可能只实现部分端点，对工具调用、结构化输出、流式事件和错误码的支持也可能不同。

**配置边界**
应用应集中管理 base_url、api_key、chat model、review model 与 embedding model，启动时验证必需配置。这些通用字段不能用来推断固定的模型名、端点路径、SDK 调用方式或响应字段。

**运行验证**
真实调用后应使用本地 Pydantic 契约检查响应。具体字段必须以目标服务的当前文档和实际响应为准。缺少 live 配置时必须明确失败或进入标记清楚的测试模式，不能静默把 mock 结果当成真实模型结果。

**操作步骤**
1. 从目标服务当前文档记录其明确支持的端点形态、模型和鉴权配置。
2. 集中配置 base_url、api_key、chat model、review model 与 embedding model，并在启动时检查必需项。
3. 发起标记清楚的最小真实调用，保存状态、结束原因和响应结构摘要。
4. 使用本地 Pydantic 契约校验实际响应，并逐项检查工具调用、结构化输出、流式事件和错误处理能力。
5. 缺少 live 配置时明确失败或进入标记清楚的测试模式。

**预期结果**
形成一份当前服务的兼容能力矩阵；矩阵只记录文档和实际调用能够确认的能力。

**常见错误**
根据兼容名称推断固定端点、模型名、SDK 用法或响应字段，或把 mock 结果静默当成真实调用。

**验收标准**
配置检查、真实调用标记、本地契约校验和兼容能力矩阵均可追溯到目标服务当前文档或实际响应。

## 编排智能体工作流
- **knowledge_id:** `orchestrator_workflow`
- **category:** 多智能体
- **difficulty:** 3
- **tags:** orchestrator, workflow
- **source:** [LangGraph Documentation - Workflows and Agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- **license:** MIT License; LangGraph official documentation summary
- **ability_weights:** `{"theory":0.2,"practice":0.35,"learning_speed":0.0,"problem_solving":0.35,"knowledge_breadth":0.1}`

编排工作流把复杂任务分成可观察节点，并根据共享状态和节点结果选择下一步。顺序流程适合固定阶段，条件边适合按结构化判断分支，并行节点适合彼此独立的工作；需要循环时必须设置终止条件和最大次数。编排层负责路由、状态推进、错误边界和恢复，不应代替专业节点生成其业务结果。状态只保存后续节点确实需要的数据，外部客户端和数据库会话留在执行边界。关键路由、失败和人工暂停点应能够从状态快照解释，使任务重试不会丢失已有进度或无限循环。

**应用任务**
把生成任务拆成可观察阶段，为顺序、条件、并行和循环定义路由条件、最大次数、失败边界与恢复点。

**预期结果**
形成能从状态快照解释路由的编排图，协调层只推进状态和选择节点，不替代专业节点。

## 隐私与日志策略
- **knowledge_id:** `privacy_log_policy`
- **category:** 质量保障
- **difficulty:** 2
- **tags:** privacy, logging
- **source:** [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- **license:** CC BY-SA 4.0; OWASP official guidance summary
- **ability_weights:** `{"theory":0.3,"practice":0.3,"learning_speed":0.0,"problem_solving":0.3,"knowledge_breadth":0.1}`

日志遵循数据最小化原则，只记录排障和审计必需的信息。普通日志可以保存 request_id、task_id、模型名、状态、耗时、重试次数、分数和非敏感 warning 摘要，不应保存真实姓名、完整答题文本、完整学习者画像、知识正文、生成资源、API 密钥或 embedding 向量。错误处理要避免把请求对象和响应正文自动格式化进日志。需要完整载荷的调试模式必须显式开启、限制环境和访问权限，并设置清理期限；展示或导出前还要脱敏。

**应用任务**
审查任务日志字段，把 ID、状态、耗时、重试和分数列为允许项，把姓名、答题、画像、正文、密钥和向量列为禁止项。

**预期结果**
形成日志字段白名单和受控调试策略，完整载荷仅在显式受限环境启用并具有清理期限。

## Prompt 工程基础
- **knowledge_id:** `prompt_basic`
- **category:** Prompt 工程
- **difficulty:** 2
- **tags:** prompt, llm
- **source:** [OpenAI Documentation - Prompt engineering](https://platform.openai.com/docs/guides/prompt-engineering)
- **license:** OpenAI official documentation; summarized for training
- **ability_weights:** `{"theory":0.4,"practice":0.3,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

Prompt 工程通过明确任务、上下文、约束、示例和输出格式，提高模型结果的相关性与可检验性。系统提示应说明角色职责和禁止事项，用户输入提供本次目标与材料，开发侧再用结构化校验落实字段和枚举约束。重要要求应写成可判断条件，例如必须引用给定来源、证据不足时返回无法判定，而不是只说提高质量。提示词版本应与评测案例一同保存，并使用固定输入集比较修改前后的正确性、覆盖率和格式遵循率；提示词不能替代权限检查、数据验证或事实核验。

**操作目标**
把一个模糊生成要求改写成可判断、可复现的提示与评测条件。

**操作步骤**
1. 写明角色职责、输入材料、允许使用的事实范围和禁止事项。
2. 把提高质量等模糊要求改成可判断条件，例如来源引用、证据不足处理、字段和枚举约束。
3. 固定一组输入案例，保存提示词版本并比较正确性、覆盖率和格式遵循率。
4. 检查权限、数据验证和事实核验是否由应用逻辑落实，而不是只写在提示词中。

**预期结果**
形成一份包含任务、上下文、约束、示例、输出格式和评测条件的提示词版本。

**常见错误**
只要求模型提高质量，没有可判断条件；或把权限检查、数据验证和事实核验完全交给提示词。

**验收标准**
固定案例能够重复执行，并可比较提示修改前后的正确性、覆盖率和格式遵循率。

## Prompt 上下文设计
- **knowledge_id:** `prompt_context_design`
- **category:** Prompt 工程
- **difficulty:** 2
- **tags:** prompt, context
- **source:** [OpenAI Documentation - Prompt engineering](https://platform.openai.com/docs/guides/prompt-engineering)
- **license:** OpenAI official documentation; summarized for training
- **ability_weights:** `{"theory":0.3,"practice":0.35,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

上下文设计决定模型在一次任务中能够使用哪些事实、约束、工具结果和示例。材料应按任务相关性筛选，标出来源与边界，并让指令和引用文本在结构上可区分，防止检索内容中的文字被误当成系统指令。长上下文需要为任务说明、必要用户上下文、证据片段和输出预留明确预算；重复、过期或互相冲突的片段应在送入模型前处理。对多轮任务，应传递必要摘要和稳定 ID，而不是无限累积完整历史。

**操作步骤**
1. 收集任务说明、必要用户上下文、证据片段和输出约束，并为每类材料标记来源与边界。
2. 删除与任务无关、重复或过期的片段，单独标记互相冲突的证据。
3. 在结构上分隔系统指令、用户目标和引用文本，避免把引用内容当成系统指令。
4. 为任务说明、用户上下文、证据和输出分别预留预算；多轮任务只传递必要摘要和稳定 ID。

**预期结果**
形成一份去重、带来源边界且结构分区清晰的上下文包。

**常见错误**
无限累积完整历史、重复发送相同片段，或没有区分指令和引用文本。

**验收标准**
上下文包中的每个事实片段都有来源，冲突证据被标记，并且各部分未超出预留预算。

## Prompt 效果评估
- **knowledge_id:** `prompt_evaluation`
- **category:** Prompt 工程
- **difficulty:** 3
- **tags:** prompt, evaluation
- **source:** [OpenAI Documentation - Evaluation best practices](https://platform.openai.com/docs/guides/evals)
- **license:** OpenAI official documentation; summarized for training
- **ability_weights:** `{"theory":0.25,"practice":0.25,"learning_speed":0.0,"problem_solving":0.4,"knowledge_breadth":0.1}`

Prompt 评估需要先固定代表性输入、期望行为、评分规则和数据版本，再批量运行候选提示词。指标可以覆盖事实正确性、任务完成度、知识覆盖、格式合法率、拒答行为和延迟，并应同时报告分子、分母与失败 case ID。开发集用于调试，冻结验收集用于验证泛化，不能在看到验收答案后逐例修补同一版本。模型输出具有随机性时应重复采样或固定可控参数，并对失败案例按提示、数据、检索、模型和评审规则归因。

**应用任务**
固定开发集与独立验收集，为候选 Prompt 定义事实、完成度、覆盖、格式、拒答和延迟指标并批量对比。

**预期结果**
形成包含分子、分母和失败 case ID 的可复现报告，失败能够按提示、数据、检索、模型和评审规则归因。

## Prompt Injection 防护
- **knowledge_id:** `prompt_injection_defense`
- **category:** 质量保障
- **difficulty:** 3
- **tags:** security, prompt-injection, agents
- **source:** [OWASP Cheat Sheet - LLM Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
- **license:** CC BY-SA 4.0; OWASP official guidance summary
- **ability_weights:** `{"theory":0.25,"practice":0.25,"learning_speed":0.0,"problem_solving":0.4,"knowledge_breadth":0.1}`

**Prompt Injection 防护**

**风险来源**

Prompt Injection 是攻击者把恶意指令放入用户消息、网页、文件、邮件或工具结果，诱导模型忽略原始任务、泄漏数据或执行越权操作。直接注入出现在用户输入中，间接注入则隐藏在系统检索或浏览的外部材料里。编码、拼写变形、多语言转换和分段传递都可能绕过简单关键词规则，因此不能把字符串黑名单当作完整安全边界。

**指令与数据隔离**

应用应把系统和开发者指令与不可信内容放入结构清晰的不同区域，并明确外部材料只能作为数据引用。模型看到某条文字不等于获得执行权限。检索结果、网页正文和工具返回值进入上下文前应保留来源和信任级别，必要时只抽取任务所需字段。对要求泄漏系统提示、密钥、其他用户数据或改变安全规则的内容，应用应拒绝并记录非敏感风险类型。

**工具和权限**

工具采用最小权限、窄参数和服务端校验。身份、资源归属、金额、收件人以及写入、发送、删除等高影响动作必须由确定性代码验证，不能因为参数来自模型就直接执行。敏感操作可要求用户确认或人工审批，并设置调用次数、时间和数据范围限制。密钥只在工具执行边界使用，不放入模型上下文。

**检测与响应**

输入输出过滤、危险模式检测和内容分类可以降低已知攻击风险，但都可能误报或漏报。检测到可疑材料时，应缩小工具权限、隔离该来源、请求人工确认或终止任务，而不是让模型自行判断是否继续。日志只保存事件 ID、来源和风险类别，不复制潜在敏感全文。

**安全测试**

测试集应覆盖直接注入、间接文档注入、编码混淆、角色冒充、数据外泄、跨用户访问和工具滥用，并检查系统是否在证据不足时安全失败。每次修改提示、工具、检索源或权限策略后都要重复运行这些样例，同时验证正常请求仍可完成，避免防护只靠过度拒绝取得表面成功。测试报告要记录攻击类别、预期安全行为、实际工具调用和失败原因，并把新发现的绕过方式加入固定回归集。

**应用任务**
为读取外部材料并调用写入工具的 Agent 标注指令区、非可信数据区、信任级别、最小权限、服务端校验与确认点。

**预期结果**
恶意材料不能获得执行权限；可疑内容触发缩权、隔离、确认或安全失败，同时正常请求仍可完成。

## Prompt 输出格式约束
- **knowledge_id:** `prompt_output_format`
- **category:** Prompt 工程
- **difficulty:** 2
- **tags:** prompt, json
- **source:** [OpenAI Documentation - Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)
- **license:** OpenAI official documentation; summarized for training
- **ability_weights:** `{"theory":0.25,"practice":0.45,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

输出格式约束要求模型按照 JSON Schema、固定字段或约定的 Markdown 结构返回结果，使下游程序能够可靠解析。字段应明确类型、是否必填、枚举范围和嵌套边界，并避免让同一个字段承担多种语义。支持 Structured Outputs 的模型可以按 schema 约束生成，但应用仍要执行 Pydantic 等运行时校验，处理拒答、截断、缺字段和业务规则不满足等情况。格式正确不代表事实正确，来源和内容质量仍需单独审核。

**应用任务**
为模型输出定义包含必填字段、类型、枚举和嵌套边界的 JSON Schema，并检查拒答、截断、缺字段和跨字段业务约束。

**预期结果**
得到可解析、可执行运行时校验的输出契约，并分别记录格式合法性与事实来源质量。

## Pydantic 数据校验
- **knowledge_id:** `pydantic_schema_validation`
- **category:** 后端开发
- **difficulty:** 2
- **tags:** pydantic, validation
- **source:** [Pydantic Documentation - Models and validators](https://docs.pydantic.dev/latest/concepts/validators/)
- **license:** MIT License; Pydantic official documentation summary
- **ability_weights:** `{"theory":0.25,"practice":0.4,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

Pydantic BaseModel 用类型标注定义请求、响应和 Agent 内部结构，并在构造模型时解析和验证输入。Field 可声明范围、长度、默认值和描述，field_validator 与 model_validator 处理字段或跨字段规则。对稳定公共契约，应明确 extra 字段策略、枚举、可空性和序列化格式，并通过 JSON Schema 与示例测试保持文档一致。Pydantic 能保证结构合法，但不能自行判断知识事实是否正确，因此契约校验与来源审核必须分开。

**应用任务**
为 Agent 输入定义严格模型，设置长度、范围、枚举、可空性、extra 策略和跨字段验证并生成合法与非法样例。

**预期结果**
结构错误在节点边界被拒绝，Schema、序列化和示例稳定，事实审核仍由来源校验负责。

## Python API 调用基础
- **knowledge_id:** `python_api_basics`
- **category:** 工程基础
- **difficulty:** 1
- **tags:** python, api
- **source:** [Python 3 Documentation - urllib.request](https://docs.python.org/3/library/urllib.request.html)
- **license:** PSF License; official documentation summary
- **ability_weights:** `{"theory":0.25,"practice":0.45,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

**请求结构**
Python 调用外部 API 时，应明确请求方法、URL、查询参数或 JSON 请求体，并通过请求头传递认证信息。密钥通过环境变量或密钥服务注入，不能写入源码和普通日志。

**超时与错误处理**
网络调用必须设置连接和读取超时，区分超时、连接失败、HTTP 错误和响应解析错误，避免无限等待或把错误页面当作正常 JSON。重试只适用于瞬时故障和可安全重复的操作，并应限制次数、设置退避间隔。

**响应验证**
调用完成后应先确认 HTTP 状态和响应内容类型，再解析 JSON 并校验业务必需字段。HTTP 成功并不代表模型输出符合业务契约；实际字段必须以目标服务文档和当次响应为准。

**操作步骤**
1. 创建一个最小 Python 脚本，从环境变量读取目标 URL 和认证信息。
2. 使用 urllib.request.Request 明确请求方法、请求头和可选请求体，并为 urlopen 设置超时。
3. 调用后先记录状态与内容类型，再按目标服务文档解析和校验业务字段。
4. 分别记录超时、连接失败、HTTP 错误和解析错误，不把错误响应当作正常 JSON。

```python
import os
from urllib.request import Request, urlopen

request = Request(os.environ["API_URL"], method="GET")
with urlopen(request, timeout=10) as response:
    print(response.status, response.headers.get_content_type())
```

**预期结果**
脚本输出实际 HTTP 状态和响应内容类型；具体状态、字段和值以目标服务文档和当次响应为准。

**常见错误**
把密钥写入源码、遗漏超时、未检查内容类型就解析 JSON，或对不可安全重复的操作进行无上限重试。

**验收标准**
代码从环境读取配置、设置超时，并在解析业务内容前检查 HTTP 状态和内容类型。

## Python 异步与并发
- **knowledge_id:** `python_async_concurrency`
- **category:** 工程基础
- **difficulty:** 3
- **tags:** python, asyncio, concurrency
- **source:** [Python 3 Documentation - asyncio](https://docs.python.org/3/library/asyncio.html)
- **license:** PSF License; Python official documentation summary
- **ability_weights:** `{"theory":0.2,"practice":0.5,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

asyncio 使用事件循环调度协程，适合同时等待多个网络或文件 I/O 的程序。协程只有在 await 可等待对象时才会把控制权交回事件循环，因此在协程中执行长时间同步计算或阻塞 I/O 会拖慢所有任务。并发任务应通过 TaskGroup 等结构化方式创建和等待，明确异常传播、取消和清理规则。调用模型 API 时还要限制并发量、设置超时并处理取消，避免瞬时创建过多请求触发限流。CPU 密集工作应转移到进程、线程或专用工作队列，而不是直接堵塞事件循环。

**应用任务**
设计并发模型调用，使用结构化任务管理、并发上限、超时、取消和清理，并区分 I/O、阻塞 I/O 与 CPU 工作。

**预期结果**
任务能等待完成并传播异常，取消后释放资源，不阻塞事件循环且不会瞬时触发过多请求。

## RAG 文档切片策略
- **knowledge_id:** `rag_chunking`
- **category:** RAG
- **difficulty:** 3
- **tags:** rag, retrieval
- **source:** [OpenAI Cookbook - Embedding long inputs](https://cookbook.openai.com/examples/embedding_long_inputs)
- **license:** MIT License; OpenAI Cookbook summary
- **ability_weights:** `{"theory":0.2,"practice":0.45,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

**RAG 文档切片策略**

**目标与约束**

文档切片要同时平衡语义完整性、召回粒度、向量表达质量和上下文成本。片段过长时，一个向量会混合多个主题，相关小节可能被平均掉，而且单条命中会占用大量模型上下文；片段过短时，定义、限定条件、步骤和异常处理容易分离，召回结果即使包含关键词也无法独立支持结论。切片策略必须结合文档结构和后续检索方式确定，不能只选择固定字符数后忽略标题、列表与代码边界。

**标题和段落感知**

Markdown 文档应识别标题层级，让正文继承最近的有效标题上下文。标题本身不宜成为没有正文的独立片段，而应与其后的段落、列表或代码说明组合。短段落可以在不超过目标上限时合并；超长段落优先按句子边界拆分，代码块和步骤列表尽量保持整体。片段内容中保留标题路径，可以让 embedding 同时表达局部正文和所属主题，也方便最终引用展示。清洗阶段还应去除重复页眉页脚、导航文字和空白噪声，避免它们在大量片段中形成错误高频信号。

**重叠上下文**

相邻片段保留适量重叠，可以减少定义和结论恰好落在边界两侧的问题。重叠应来自前一片段末尾的完整句子或小段，而不是机械复制固定数量的乱码字符；过大的重叠会制造近重复候选，使同一知识点占满 Top-K。项目候选索引以单个 chunk 约 800 字为目标上限，并保留约 100 字的相邻上下文。该数值是可测试的工程默认值，不是适用于所有语料的通用定律，后续只能根据开发评测集调整。

**标识与元数据**

每个片段使用稳定的 `{knowledge_id}::chunk::{index}` 标识，并保存 domain_code、knowledge_id、名称、分类、难度、标签、来源、许可、切片位置和 embedding 模型。稳定 ID 使增量更新可以先删除一个知识点的旧片段再写入新片段，也让引用、评审和失败案例能够定位到具体证据。内容或切片算法变化后必须更新索引版本并重新生成受影响向量，不能让数据库正文与向量库片段长期不一致。

**验证方法**

切片单元测试至少覆盖标题继承、短段落合并、超长句段拆分、空文本、中文标点、稳定 ID 和重叠边界。质量评测还要观察一个知识点产生的片段数、重复率、金标准知识召回率和来源完整性。只有真实长文本才能验证多片段行为；用几十字的短知识项通过测试，只能证明函数没有报错，不能证明标题继承和重叠策略有效。

**应用任务**
对包含标题、列表和代码块的长文档按标题与语义边界切片，保留标题路径、稳定 ID 和完整句重叠并检查重复率。

**预期结果**
片段能独立支持结论且近重复不会占满 Top-K，内容或算法变化会更新索引版本。

## RAG 流程总览
- **knowledge_id:** `rag_pipeline_overview`
- **category:** RAG
- **difficulty:** 2
- **tags:** rag, pipeline
- **source:** [OpenAI Cookbook - Question answering using embeddings](https://cookbook.openai.com/examples/question_answering_using_embeddings)
- **license:** MIT License; OpenAI Cookbook summary
- **ability_weights:** `{"theory":0.35,"practice":0.3,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

检索增强生成（RAG）先把可信文档解析、清洗并切成可检索片段，再使用 embedding 建立向量索引。运行时将用户目标与任务上下文构造成查询，通过显式 ID、知识关系或语义相似度召回候选，经过过滤、去重和排序后，把有限证据连同来源交给生成模型。生成结果必须保留片段或知识 ID，审核环节再逐条核对事实与来源。RAG 能降低脱离资料的回答，但不会自动消除幻觉；数据质量、召回覆盖、上下文构造和审核缺一不可。

**应用任务**
把 RAG 请求拆成解析、清洗、切片、embedding、索引、查询、召回、过滤、排序、生成引用和审核步骤并标注失败点。

**预期结果**
形成端到端流程图，生成事实可回查证据，数据、召回、上下文和审核缺口能够分别定位。

## 检索重排
- **knowledge_id:** `retrieval_reranking`
- **category:** RAG
- **difficulty:** 3
- **tags:** rerank, retrieval
- **source:** [OpenAI Cookbook - Search and reranking with embeddings](https://cookbook.openai.com/examples/search_reranking_with_cross-encoders)
- **license:** MIT License; OpenAI Cookbook summary
- **ability_weights:** `{"theory":0.2,"practice":0.35,"learning_speed":0.0,"problem_solving":0.35,"knowledge_breadth":0.1}`

重排在初步召回后，使用更丰富的任务信号重新评估候选片段。简单实现可以组合召回路径、向量相似度、目标难度和来源质量，并使用稳定 tie-break 保证相同输入得到相同顺序；更复杂的 Cross-Encoder 或 LLM reranker 虽可能提升相关性，也会增加延迟、成本和不可重复性。MVP 应先用开发评测集验证确定性排序，分别报告 semantic-only 与 full 策略的结果。显式 priority 和 prerequisite 知识需要预留覆盖位置，不能在普通重排中因语义分数略低而静默消失。

**应用任务**
组合召回路径、相似度、目标难度和来源质量稳定重排候选，为 priority 与 prerequisite 预留位置并对比两种策略。

**预期结果**
相同输入得到稳定顺序，多主题均有覆盖，显式优先和前置知识不会被普通重排静默移除。

## 评审与校验智能体
- **knowledge_id:** `review_validation_agent`
- **category:** 多智能体
- **difficulty:** 3
- **tags:** agent, review
- **source:** [OpenAI Documentation - Evaluation Best Practices](https://platform.openai.com/docs/guides/evaluation-best-practices)
- **license:** OpenAI official documentation; summarized for training
- **ability_weights:** `{"theory":0.25,"practice":0.3,"learning_speed":0.0,"problem_solving":0.35,"knowledge_breadth":0.1}`

**评审与校验智能体设计**

**独立评审**

评审智能体根据明确的评分标准检查生成结果，而不是因为语言流畅或格式完整就判定正确。标准应拆成可观察维度，例如事实是否得到证据支持、引用是否对应原文、任务要求是否覆盖、输出结构是否合法以及是否包含安全风险。评审输入要包含被评内容、必要上下文、参考答案或来源，并避免泄漏与评分无关的标签。生成者与评审者使用相同模型时仍需独立调用和独立上下文，不能让生成过程直接宣告自己通过。

**评分规则**

可自动判断的字段、枚举、长度、引用 ID 和数值范围优先使用确定性代码校验。需要语义判断的部分可以使用模型评分，但 rubric 必须定义分值含义、阻断条件和无法判定的处理方式。评分输出采用结构化格式，保存维度分数、问题列表、证据位置和结论。模型评审结果不是事实真值；应使用人工标注样例测量与专家判断的一致性，并通过正例、反例和边界例检查评分提示是否稳定。

**分歧处理**

多个评审通道出现分歧时，系统应先确认输入证据、评分规则和输出解析是否一致，再针对争议点重新检索并独立仲裁。不能简单平均相互矛盾的结论，也不能始终服从更高分的一方。明确矛盾、来源缺失或仲裁后仍无法判定的声明只阻止受影响资源发布，并发送自动局部修订；连续两次修订仍未通过时终止资源包。局部修订必须限制字段和循环次数，并保留每次修订的原因。

**评测与监控**

评审系统本身也需要评测。固定数据集应覆盖正确结果、事实错误、引用不支持、遗漏要求、模糊答案和对抗输入，并报告每类错误的分子、分母和失败样例。上线后抽查自动通过和自动拒绝的结果，监控评分分布漂移、证据不足比例、仲裁未解决比例和延迟。修改 rubric、评审模型或参考数据后要重新运行同一验收集，避免评分器变化被误认为生成质量提升。

**应用任务**
对资源执行确定性校验和两路独立事实审核，模拟冲突后完成输入复核、重新检索、仲裁、局部修订与发布决定。

**预期结果**
形成包含分数、声明判定、证据位置和分歧轨迹的报告，持续分歧受有限修订和发布门槛约束。

## 密钥与配置管理
- **knowledge_id:** `secret_management`
- **category:** 质量保障
- **difficulty:** 2
- **tags:** security, secrets, configuration
- **source:** [OWASP Cheat Sheet - Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- **license:** CC BY-SA 4.0; OWASP official guidance summary
- **ability_weights:** `{"theory":0.25,"practice":0.35,"learning_speed":0.0,"problem_solving":0.3,"knowledge_breadth":0.1}`

API 密钥、数据库口令和签名凭据不应写入源码、镜像、前端包或普通日志。开发环境可以从受版本控制忽略的环境文件注入配置，部署环境应使用专用密钥存储或平台 Secret，并按服务最小权限授权。应用启动时只验证必需配置是否存在和格式是否合法，不回显具体值。密钥需要可轮换、可吊销并记录访问审计；发生泄漏时应立即撤销而不是只删除 Git 中的文件。示例配置只保留变量名和安全占位符，测试使用独立低权限凭据。

**应用任务**
列出密钥和凭据的注入、最小权限、轮换、吊销与审计路径，检查源码、镜像、前端包和日志是否泄漏。

**预期结果**
形成密钥生命周期清单，启动只验证存在性与格式，示例仅含变量名，测试使用独立低权限凭据。

## SQLAlchemy 模型设计
- **knowledge_id:** `sqlalchemy_modeling`
- **category:** 后端开发
- **difficulty:** 3
- **tags:** sqlalchemy, orm
- **source:** [SQLAlchemy 2.0 Documentation - ORM Quick Start](https://docs.sqlalchemy.org/en/20/orm/quickstart.html)
- **license:** MIT License; SQLAlchemy official documentation summary
- **ability_weights:** `{"theory":0.25,"practice":0.4,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

SQLAlchemy Declarative 模型使用 mapped_column 定义列、类型、默认值、索引和外键，并通过 Session 管理对象生命周期和事务。稳定业务 ID 应设置唯一约束，关联关系使用数据库外键保持引用完整性，经常过滤的 domain_code、public_id 和状态字段需要索引。JSON 列适合整体读写的灵活结构，但需要关系查询、唯一性或统计的关键字段应保留为普通列。事务中应先 flush 获取主键，所有相关写入成功后再 commit，异常时 rollback 并避免返回未持久化状态。

**应用任务**
将任务、资源和审核报告建模为带业务 ID、外键、状态索引和时间字段的实体，区分普通列与 JSON 并设计事务顺序。

**预期结果**
模型通过唯一约束和外键保持一致，高频字段可索引，相关写入全部成功后才提交。

## SSE 进度事件设计
- **knowledge_id:** `sse_progress_events`
- **category:** 系统集成
- **difficulty:** 3
- **tags:** sse, progress
- **source:** [MDN Web Docs - Server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- **license:** MDN content license; official web documentation summary
- **ability_weights:** `{"theory":0.15,"practice":0.55,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

SSE 进度事件使用标准化 event 和 data 字段传递 task_id、处理节点、运行状态、时间戳与非敏感摘要。事件应来自真实任务或持久化运行状态变化，而不是前端硬编码步骤；每个节点至少区分等待、运行、完成和失败，最终事件明确任务终态。服务端设置 text/event-stream、禁用不合适的缓冲并处理客户端断开，前端按事件 ID 或状态版本去重。断线后可重连并通过任务查询补齐状态，不能把重放事件重复计为新的运行。

**应用任务**
为节点定义等待、运行、完成和失败事件，包含 task_id、节点、时间戳、事件 ID 和脱敏摘要，并设计重连与查询补偿。

**预期结果**
事件来自真实任务状态，最终事件明确终态，重放不重复计数，连接断开不被解释为成功。

## 流式响应与进度反馈
- **knowledge_id:** `streaming_responses`
- **category:** 模型调用
- **difficulty:** 3
- **tags:** streaming, sse
- **source:** [MDN Web Docs - Using server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)
- **license:** MDN content license; official web documentation summary
- **ability_weights:** `{"theory":0.2,"practice":0.5,"learning_speed":0.0,"problem_solving":0.2,"knowledge_breadth":0.1}`

流式响应让服务端在完整结果生成前逐步发送增量内容或状态，从而减少用户感知等待时间。Server-Sent Events 使用持久 HTTP 连接，以 text/event-stream 格式从服务端单向推送命名事件、数据、ID 和重试建议，适合任务进度与 Agent 状态。实现时要发送心跳或可观察状态，区分中间事件、错误事件和最终完成事件，并在断开后关闭服务端资源。前端不能把连接关闭自动解释为成功，而要依据终态事件或后续任务查询确认结果。

**应用任务**
设计区分进度、中间状态、错误和最终完成的 SSE 事件，定义 event、data、ID、心跳、断线重连和资源清理。

**预期结果**
形成可去重、可恢复的事件协议，连接关闭不被视为成功，任务终态可由最终事件或查询确认。

## 结构化输出校验
- **knowledge_id:** `structured_output_validation`
- **category:** 模型调用
- **difficulty:** 3
- **tags:** validation, json
- **source:** [Pydantic Documentation - Models](https://docs.pydantic.dev/latest/concepts/models/)
- **license:** MIT License; Pydantic official documentation summary
- **ability_weights:** `{"theory":0.2,"practice":0.4,"learning_speed":0.0,"problem_solving":0.3,"knowledge_breadth":0.1}`

结构化输出校验用于确认模型返回字段齐全、类型正确、枚举合法，并满足字段之间的业务约束。JSON 能被解析只是第一层，应用还需通过 Pydantic 模型执行长度、范围、默认值和嵌套结构检查，并拒绝未知或不安全的数据形态。校验失败后可根据错误类型进行有限重试：可修复格式问题可以把精简错误反馈给模型，缺少证据或权限问题则不应靠重试伪造结果。连续失败要转为明确失败、降级输出或人工复核，同时记录错误类别而非完整敏感载荷。

**应用任务**
依次检查模型 JSON 的解析、字段类型、长度范围、枚举、跨字段规则和未知字段，并按错误类型决定有限重试或失败。

**预期结果**
形成分层校验记录，格式问题可有限修复，证据或权限缺口不会靠重试伪造，连续失败有明确终态。

## Token 与上下文预算
- **knowledge_id:** `token_context_budget`
- **category:** 模型调用
- **difficulty:** 2
- **tags:** token, context
- **source:** [OpenAI Cookbook - How to count tokens with tiktoken](https://cookbook.openai.com/examples/how_to_count_tokens_with_tiktoken)
- **license:** MIT License; OpenAI Cookbook summary
- **ability_weights:** `{"theory":0.3,"practice":0.3,"learning_speed":0.0,"problem_solving":0.3,"knowledge_breadth":0.1}`

模型上下文窗口同时容纳系统指令、对话历史、用户上下文、检索片段、工具结果和待生成输出，因此不能把标称窗口全部用于输入。预算规划应先为输出和工具交互预留空间，再按任务价值给证据片段分配额度。超出预算时优先删除重复和低相关材料，压缩历史为带来源 ID 的摘要，或把复杂任务拆成检索、生成、审核多个阶段。截断必须在语义边界进行并保留引用标识，不能从字符串尾部任意裁切导致事实和限定条件分离。

**应用任务**
为系统指令、对话摘要、用户上下文、检索证据、工具结果和输出分别分配预算，超限时按相关性去重并在语义边界截断。

**预期结果**
形成不超过上下文窗口的预算表，输出和工具交互有预留，证据保留来源标识和限定条件。

## 向量相似度检索
- **knowledge_id:** `vector_similarity`
- **category:** RAG
- **difficulty:** 2
- **tags:** vector, similarity
- **source:** [Chroma Documentation - Collections and distance metrics](https://docs.trychroma.com/docs/collections/configure)
- **license:** Apache-2.0 project documentation; official Chroma summary
- **ability_weights:** `{"theory":0.4,"practice":0.25,"learning_speed":0.0,"problem_solving":0.25,"knowledge_breadth":0.1}`

向量检索使用余弦距离、内积或欧氏距离比较查询与文档向量，并按距离返回 Top-K 候选。距离含义取决于 collection 的度量配置，使用 cosine distance 时可以在确认范围后换算为 similarity = 1 - distance，但不能把不同度量的值混用。候选数量过小会降低召回，过大则增加排序和上下文成本。最终结果应结合 domain_code 等元数据过滤、显式知识 ID、关系扩展、难度和来源完整性，避免语义相似但跨领域或缺乏证据的片段进入生成上下文。

**应用任务**
选定 collection 距离度量，对同一查询比较不同 Top-K，再叠加领域、知识 ID、难度和来源完整性过滤。

**预期结果**
形成候选对比表，距离解释与配置一致，不混用度量，并能说明 Top-K 对召回和上下文成本的影响。
