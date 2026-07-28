# V2 交互导学智能体算法实现方案

> 文档状态：执行方案  
> 适用范围：`ai_app_dev` MVP、V2 Agent 算法实现阶段  
> 前置约束：V2 契约已冻结；生产运行链仍为 V1。本方案只实现可独立验证的 V2 导学智能体内部算法，不切换生产图。

## 1. 目标与结论

交互导学智能体不是资源页上的普通聊天机器人，也不是画像修改者或资源发布者。它是反馈链路中负责**理解学习者自然语言、开展启发式追问、整理反馈证据并提出下一步建议**的独立 Agent。

本阶段一次定型的实现原则是：

```text
模型负责自然语言理解与表达
确定性策略负责教学流程、证据边界与动作约束
V2 契约负责输入输出边界与可验证性
```

因此，不采用“先写关键词规则、后续再替换为模型”的过渡路径；也不采用“模型自由决定一切”的不可控路径。正式算法从第一版开始就采用模型驱动、规则约束的混合实现。

## 2. 阶段二边界

本方案符合 `docs/v2-agents/agent-algorithm-implementation-roadmap.md` 的阶段二要求：

```text
InterpretFeedbackInput -> 导学算法 -> InterpretFeedbackOutput
```

本阶段只做：

- 新增符合 V2 契约的 `V2TutoringAgent`；
- 实现模型结构化理解、确定性导学策略和输出校验；
- 编写单元测试、模型失败测试，并准备阶段三所需的跨 Agent fixture；
- 保持算法可由后续 V2 LangGraph 节点直接调用。

本阶段不做：

- 不修改 `backend/app/agents/contracts.py`、`state.py`、适配器、Schema 或契约测试；
- 不修改 `graphs.py`、`nodes.py`、`generation_worker.py` 或数据库结构；
- 不切换现有 V1 生产图，不重构前端和 API；
- 不让导学 Agent 自行修改画像、生成正式资源或发布资源。

### 2.1 与项目路线图一致的分阶段实施

本方案不是要求在一次开发中完成从对话到资源发布的全链路，而是将导学 Agent 放入路线图既定的四个阶段中实施。当前只执行**阶段二**；后续阶段以本阶段通过验收的算法内核为前提，不得反向替换其职责或决策规则。

| 项目阶段 | 导学 Agent 在该阶段的交付 | 是否属于当前实现 |
|---|---|---|
| 阶段一：共同基线 | 确认冻结契约、最小合法 fixture、V1 回归基线和文件边界。 | 前置检查 |
| 阶段二：算法实现 | 完成模型结构化理解、确定性策略、受控回复、降级处理、V2 输入输出封装和单元测试。 | **是** |
| 阶段三：跨 Agent 交叉验证 | 以 `InterpretFeedbackOutput.evidence` 驱动 Profile Analysis Agent，验证“无证据不更新画像、有效证据可供画像判断”。 | 否，保留 fixture 与验证用例 |
| 阶段四：V2 集成切换 | 在 `interpret_feedback` 节点调用本 Agent，接入 State、持久化、SSE 和后续检索—生成—审核链路。 | 否 |

阶段二内部按下列顺序完成，四项都属于同一个“算法实现”交付，不是日后需要推倒重写的临时版本：

1. **策略内核**：先以内部语义 DTO 和固定 fixture 实现全部意图、证据门槛、优先级与安全降级规则；策略函数保持纯函数、可单测。
2. **模型语义层**：接入可注入的 OpenAI-compatible 结构化模型客户端，完成自然语言意图、困难点、未解决状态和候选回复的提取；模型异常统一落入策略内核的安全分支。
3. **Agent 边界封装**：实现 `V2TutoringAgent.execute(InterpretFeedbackInput) -> InterpretFeedbackOutput`，完成 Pydantic 校验、脱敏日志和重试策略。
4. **阶段二验收**：用 fake/mock 模型覆盖全部策略、无效 JSON、低置信与模型失败；运行 V2 契约测试和现有 V1 回归测试。

阶段三和阶段四只增加消费者、节点和持久化接线；不得将“是否更新画像”“是否发布资源”等裁决回填给导学 Agent。

## 3. 职责边界

### 3.1 交互导学 Agent 的职责

输入为当前画像、资源摘要、会话摘要、快捷反馈及辅助证据。输出必须是 V2 `InterpretFeedbackOutput`：

- `feedback_intent`：反馈意图；
- `recommended_action`：建议动作；
- `reply`：面向学习者的自然语言回复；
- `evidence`：可传递的脱敏证据引用；
- `needs_generation`：是否需要进入后续生成或复核；
- `decision_reason`：对当前动作的可解释理由。

它只负责做出“现在应追问、提示、挑战确认或资源复核”的建议，并把对话中的信息转化为可被后续 Agent 使用的结构化证据。

### 3.2 不属于交互导学 Agent 的职责

| 工作 | 唯一责任方 |
|---|---|
| 基于证据创建画像新版本、计算变更维度与影响范围 | Profile Analysis Agent |
| 检索来源、前置/关联知识 | Knowledge Retrieval Agent |
| 生成正式补救解释、挑战任务或修订资源 | Content Generation Agent |
| 事实、来源、难度、覆盖率的双模型审核 | Review Validation Agent |
| 发布通过资源、刷新局部路径、任务终态路由 | Orchestrator Agent / `finalize_task` |

“画像不更新”不等于“一定不生成资源”。例如学习者第二轮仍无法解决困难时，可以生成补救解释，但画像仍保持不变；只有 Profile Analysis Agent 认为计分结果或已验证行为等证据充分时，才允许创建画像新版本。

## 4. 最终内部算法

### 4.1 执行流程

```text
InterpretFeedbackInput
    -> 模型结构化理解：意图、困难点、未解决状态、掌握证据、候选回复
    -> 确定性导学策略：按会话、证据和项目规则确定最终动作
    -> 受策略约束的自然语言回复
    -> InterpretFeedbackOutput Pydantic 校验
```

模型是实时导学能力的正式组成部分，不是未来替换项；确定性策略也不是临时兜底，而是项目关键规则的唯一裁决者。

### 4.2 模型结构化理解

模型读取 `InterpretFeedbackInput` 中的受控摘要，不读取无边界的完整业务数据库。它应返回仅供 Agent 内部使用的语义结果：

```text
- intent：六类反馈意图之一
- difficulty_focus：学习者困难的概念、步骤或验证环节摘要
- unresolved：本轮是否仍未解决先前困难
- mastery_evidence_present：是否观察到可用的掌握证据
- candidate_reply：符合当前资源上下文的候选追问或提示
- evidence_candidates：可转换为 EvidenceRef 的脱敏证据摘要
- confidence：意图判断置信度
```

模型调用应使用 OpenAI-compatible API 的结构化输出能力。模型返回的任意自由文本、未知枚举、未引用的证据或低置信判断，都不得直接成为最终动作。

模型只被允许：

- 理解自然语言的困难点、错误报告和进阶诉求；
- 生成自然、简洁的追问或提示表述；
- 整理已存在的对话与辅助证据。

模型不得：

- 直接判定或写入画像更新；
- 自行发布、修改或审核资源；
- 将资源事实错误归因于学习者能力；
- 编造知识来源、测验成绩或学习行为。

### 4.3 确定性导学策略

策略函数读取模型语义结果与 `FeedbackContext`，并覆盖模型的动作建议。最少规则如下。

| 条件 | 最终 `recommended_action` | `needs_generation` | 说明 |
|---|---:|---:|---|
| `too_hard` 或 `confusing`，首轮表达困难 | `ask_follow_up` | `false` | 聚焦概念、步骤、代码或结果验证中的具体障碍；先提示，不直接给正式答案。 |
| 同一困难在后续轮次仍未解决 | `explain` | `true` | 请求后续链路生成带来源、可审核的降维解释或补救资源；困难本身不更新画像。 |
| `too_easy`，尚无掌握证据 | `ask_follow_up` | `false` | 通过迁移问题或小任务确认掌握，不能仅因主观评价生成挑战任务。 |
| `too_easy`，存在计分题或已确认行为等掌握证据 | `challenge` | `true` | 请求后续链路生成挑战任务；画像是否更新仍交由学情分析 Agent。 |
| `incorrect`，或存在错误文本标记 | `review` | `true` | 请求重新检索和审核；明确资源错误不影响学习者画像。 |
| `helpful` | `no_change` | `false` | 记录为后续画像判断的辅助证据。 |
| 意图不明确、模型低置信或输入冲突 | `ask_follow_up` | `false` | 不猜测、不创建任务、不更新画像。 |

补充约束：

1. 单次快捷标签、评分或自然语言主观反馈不得产生画像更新结论。
2. `too_easy` 的“掌握证据”必须来自受控的计分题、诊断结果或已确认学习行为；模型表述本身不是掌握证据。
3. `incorrect` 优先级高于“太难”“太简单”等难度意图。
4. 当模型调用失败、结构化输出无效或置信度不足时，必须安全降级为模板化追问，不能将错误判断传给下游。
5. 导学 Agent 的 `reply` 是即时对话回应；需形成正式学习内容的补救解释、挑战任务和资源修订，必须由后续检索、生成、审核闭环完成。

## 5. 代码组织与依赖

建议新增 V2 实现文件，例如：

```text
backend/app/agents/v2_tutoring_agent.py
backend/app/services/tutoring_policy.py
backend/tests/unit/test_v2_tutoring_agent.py
backend/tests/unit/test_tutoring_policy.py
```

`V2TutoringAgent.execute()` 的正式边界固定为：

```python
def execute(self, request: InterpretFeedbackInput) -> InterpretFeedbackOutput:
    ...
```

实现内部允许依赖一个可注入的模型客户端；测试中使用固定的 fake/mock 模型返回结构化语义结果。这样生产环境使用真实模型，测试环境仍能稳定覆盖策略分支，且不需要在未来替换 Agent 主体。

新实现只导入 `app.agents.contracts` 与 `app.agents.state` 中需要的 V2 类型；不导入 `legacy_contracts` 或 `legacy_state`，也不修改现有 V1 `TutoringAgent`。

## 6. Prompt 与安全要求

系统提示词应明确：

1. 当前领域为人工智能应用开发实训，导学目标是定位困难并帮助学习者完成下一步，而非泛化闲聊；
2. 只基于输入的资源、画像、会话和证据摘要判断，不得虚构来源或成绩；
3. 首轮困难优先追问和提示；
4. 疑似资源错误必须建议复核，不能评价学习者能力；
5. 输出必须满足内部结构化 JSON Schema。

普通日志只记录 `task_id`、会话 ID、资源 ID、意图、推荐动作、模型状态、证据数量与置信度；不得记录完整画像、完整学习者消息或完整资源正文。

模型调用最多重试 3 次，等待 1 秒、3 秒、5 秒。三次失败后返回安全的 `ask_follow_up` 模板回复，并记录可读错误码。

## 7. 测试与验收

### 7.1 单元测试

使用固定模型语义结果，验证：

- `too_hard` 首轮追问；
- `too_hard` 第二轮仍困难时触发补救解释生成；
- `confusing` 的追问和补救分支；
- `too_easy` 在无掌握证据时继续确认；
- `too_easy` 在有有效掌握证据时触发挑战；
- `incorrect` 触发复核且不产生画像更新导向；
- `helpful` 返回 `no_change`；
- 低置信、冲突意图、空文本与模型 JSON 无效时安全降级；
- 所有正常输出均通过 `InterpretFeedbackOutput` 校验。

### 7.2 阶段三的跨 Agent 验证（当前预留）

验证导学输出能够被后续 V2 学情分析输入消费：

```text
FeedbackContext
    -> InterpretFeedbackOutput.evidence
    -> AnalyzeProfileInput.feedback_evidence
    -> no_change 或新的 ProfileSnapshot
```

该验证在阶段三执行。验收重点是：单次主观反馈不会创建画像版本；包含计分题或已确认行为的有效证据能够被学情分析算法识别；导学 Agent 不越权输出画像变化。阶段二只需提供稳定 fixture 与可消费的合法输出。

#### 阶段三前置：学情分析 Agent 的算法修正项

当前导学算法已将“`confirmed=true` 的 `validated_behavior`”视为可触发挑战确认的**受控学习行为证据**；但现有 Profile Analysis Agent 的 `_effective_assessments()` 仅将 `diagnostic_result`、`scored_quiz`、`manual_review` 视为可计算评估证据。因此，阶段三交叉验证开始前，应由**学情分析 Agent 功能分支**处理如下修正：

1. 在 `backend/app/services/profile_analysis_service.py` 的有效评估证据白名单中加入 `EvidenceType.VALIDATED_BEHAVIOR`；
2. 保持既有全部门槛：证据必须 `confirmed=true`，必须同时有合法 `KnowledgeAssessment`，且评估必须已作答、有分数、引用一致的知识点和证据 ID；
3. 不得让 `validated_behavior` 的自然语言摘要、快捷标签或单次导学回复直接更新画像；只有上述结构化评估进入 Profile Analysis Agent 后，才可计算画像新版本；
4. 为“已确认行为 + 结构化评估可更新画像”与“仅行为/仅主观反馈不更新画像”分别补充 Profile Analysis Agent 单元测试。

该修正不需要改变冻结 V2 契约，也不应由 Tutoring Agent 分支修改。完成后，阶段三再验证 `InterpretFeedbackOutput.evidence -> AnalyzeProfileInput.feedback_evidence -> AnalyzeProfileOutput` 的数据流。


### 7.3 阶段二完成标准

- `V2TutoringAgent` 使用正式 V2 Input/Output，不以 `dict[str, Any]` 作为边界；
- 真实模型调用与 fake/mock 模型调用都可工作；
- 所有策略分支、异常分支和契约校验测试通过；
- 不修改冻结契约、V1 图、worker、数据库或前端；
- 当前 V1 演示链回归不受影响。

## 8. 后续集成方式

阶段四接入 V2 LangGraph 时，只需由 `interpret_feedback` 节点构造 `InterpretFeedbackInput`、调用本 Agent，并将 `InterpretFeedbackOutput` 写入该节点拥有的 State 字段。随后按既有图路由至 `analyze_profile` 或后续检索生成链路。

由于本阶段已经固定了模型调用、策略算法、V2 契约边界和测试方式，后续工作只是节点、持久化和 SSE 集成，不需要替换或重写导学智能体算法。
