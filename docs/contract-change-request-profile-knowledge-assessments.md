# Agent Contract V2 变更申请：知识点评估输入

> 申请状态：已批准并应用  
> 申请日期：2026-07-22  
> 申请范围：Profile Analysis Agent  
> 兼容性目标：向后兼容的增量变更  
> 关联方案：`docs/v2-profile-analysis-agent-implementation-plan.md`

## 1. 申请结论

申请为 `AnalyzeProfileInput` 增加可选的结构化知识点评估列表
`knowledge_assessments`，并新增契约模型 `KnowledgeAssessment`。

该字段用于向 Profile Analysis Agent 提供诊断服务和计分测验服务产生的客观评估事实，使
学情分析智能体能够独立计算五维能力、掌握类型、薄弱知识和画像变化，而不读取原始答案，
也不从 `EvidenceRef.summary` 中解析隐式数据。

本申请只提出契约变更，不在申请阶段直接修改以下冻结文件：

- `backend/app/agents/contracts.py`
- `backend/app/agents/state.py`
- `backend/app/agents/contract_adapters.py`
- `backend/tests/contracts/`
- `docs/agent-contract-v2.md`
- `docs/contracts/v2/`

## 2. 当前阻塞

当前 `AnalyzeProfileInput` 包含：

- `current_profile`
- `diagnostic_summary`
- `feedback_evidence`
- `recommended_action`

其中 `DiagnosticSummary` 只有题目数量、作答数量、正确数量、跳过数量、总分和
`EvidenceRef`；`EvidenceRef` 只有证据类型、脱敏摘要、知识 ID、置信度和确认状态。

现有字段无法表达：

- 某个知识点的实际得分。
- 该评估是否来自有效作答或跳过。
- 题目难度。
- 评分结果的置信度。
- 诊断和后续计分测验对同一知识点形成的连续证据。

因此 Profile Analysis Agent 无法仅依据冻结输入可靠地完成逐知识点掌握度计算。若不增加
结构化字段，只能由诊断服务提前生成完整画像，Profile Agent 在首次生成场景中主要负责转发
画像和生成 `RetrievalPlan`，无法充分承担独立的学情分析职责。

通过解析 `EvidenceRef.summary` 传递分数不可接受，因为摘要不是数据协议，容易产生语言、格式
和隐私问题。

## 3. 请求的模型与字段

### 3.1 新增模型

建议新增：

```python
class KnowledgeAssessment(ContractModel):
    assessment_id: str = Field(min_length=1, max_length=64)
    evidence_id: str = Field(min_length=1, max_length=64)
    knowledge_id: str = Field(min_length=1, max_length=64)
    score: float | None = Field(default=None, ge=0, le=1)
    difficulty: int = Field(ge=1, le=5)
    attempted: bool
    confidence: float = Field(ge=0, le=1)
```

字段语义：

| 字段 | 含义 |
|---|---|
| `assessment_id` | 单条结构化评估的稳定 ID，用于去重和追踪 |
| `evidence_id` | 对应 `EvidenceRef.evidence_id`，建立事实与证据引用关系 |
| `knowledge_id` | 被评估知识点的稳定 ID |
| `score` | 归一化得分，范围 0-1；跳过或无法判断时为 `null` |
| `difficulty` | 产生该评估的题目或任务难度，范围 1-5 |
| `attempted` | 是否形成了有效作答尝试 |
| `confidence` | 评分结果置信度，范围 0-1 |

### 3.2 修改输入模型

建议修改：

```python
class AnalyzeProfileInput(ContextNodeContract):
    current_profile: ProfileSnapshot
    diagnostic_summary: DiagnosticSummary | None = None
    feedback_evidence: list[EvidenceRef] = Field(default_factory=list, max_length=100)
    recommended_action: RecommendedAction | None = None
    knowledge_assessments: list[KnowledgeAssessment] = Field(
        default_factory=list,
        max_length=100,
    )
```

请求字段：`AnalyzeProfileInput.knowledge_assessments`

- 必填性：非必填。
- 默认值：空列表。
- 最大数量：100。
- 空列表语义：没有新的可计分知识点评估，Agent 只能使用当前画像和现有证据做保守决策。

## 4. 生产与消费关系

### 4.1 生产方

结构化评估事实由以下组件产生：

- 诊断服务：选择题确定性评分和简答题 rubric 辅助评分。
- 计分测验服务：反馈闭环中的分阶测试和挑战任务评分。
- V2 `analyze_profile` 节点输入构造器：读取受控评分记录，组装
  `KnowledgeAssessment`，但不修改评分结果。

诊断服务不负责根据该结果选择补救、巩固或挑战策略。

### 4.2 消费方

- `analyze_profile` 节点。
- V2 Profile Analysis Agent。
- 画像证据和画像版本算法。

后续 Knowledge Retrieval Agent 不直接消费 `KnowledgeAssessment`，只消费 Profile Analysis
Agent 输出的 `ProfileSnapshot` 和 `RetrievalPlan`。

### 4.3 数据流

```text
原始答案
    -> DiagnosticService / ScoredQuizService
    -> KnowledgeAssessment + EvidenceRef
    -> AnalyzeProfileInput
    -> Profile Analysis Agent
    -> ProfileSnapshot + RetrievalPlan
    -> Knowledge Retrieval Agent
```

## 5. 校验规则

建议由 Pydantic 模型和 `AnalyzeProfileInput` 联合校验实现以下规则：

1. `score` 必须为 `null` 或 0-1。
2. `difficulty` 必须为 1-5。
3. `confidence` 必须为 0-1。
4. `attempted=false` 时 `score` 必须为 `null`。
5. `attempted=true` 时允许 `score=null`，表示评分无法确定，但该记录不得作为能力增减依据。
6. 同一个输入中的 `assessment_id` 必须唯一。
7. 每个 `knowledge_assessment.evidence_id` 必须能够在以下集合中找到：
   - `diagnostic_summary.evidence`；或
   - `feedback_evidence`。
8. `knowledge_id` 必须与对应证据的 `knowledge_id` 一致；证据知识 ID 为空时不得用于画像更新。
9. `score=null` 或低于实现侧置信度阈值的记录只能作为待确认事实，不能直接改变画像。

第 7、8 条属于跨字段一致性校验。若考虑兼容历史诊断证据，可由契约维护者决定是在 Pydantic
层强制，还是在 Profile Agent 输入校验层返回受控错误。

## 6. 输入示例

```json
{
  "task_id": "task_profile_001",
  "context": {
    "contract_version": "agent-contract-v2",
    "task_id": "task_profile_001",
    "session_id": "session_001",
    "trigger_type": "initial_generation",
    "execution_mode": "auto",
    "learner_id": "learner_001",
    "profile_id": "profile_001",
    "domain_code": "ai_app_dev",
    "resource_types": ["lecture", "practice_guide", "graded_quiz"],
    "learning_goal": "掌握 RAG 检索与切片策略"
  },
  "current_profile": {
    "profile_id": "profile_001",
    "profile_version": 1,
    "profile_type": "beginner",
    "ability_scores": {
      "theory": 50,
      "practice": 50,
      "problem_solving": 50,
      "knowledge_breadth": 50,
      "learning_speed": 50
    },
    "weak_knowledge": [],
    "blind_spot_ids": []
  },
  "diagnostic_summary": {
    "diagnostic_session_id": "diagnostic_001",
    "question_count": 2,
    "answered_count": 2,
    "correct_count": 1,
    "skipped_count": 0,
    "score_percent": 70,
    "evidence": [
      {
        "evidence_id": "evidence_diag_rag_001",
        "evidence_type": "diagnostic_result",
        "summary": "RAG 切片知识点诊断结果",
        "knowledge_id": "rag_chunking",
        "source_ref_id": null,
        "confidence": 0.9,
        "confirmed": true
      }
    ]
  },
  "feedback_evidence": [],
  "recommended_action": null,
  "knowledge_assessments": [
    {
      "assessment_id": "assessment_diag_rag_001",
      "evidence_id": "evidence_diag_rag_001",
      "knowledge_id": "rag_chunking",
      "score": 0.4,
      "difficulty": 3,
      "attempted": true,
      "confidence": 0.9
    }
  ]
}
```

示例不包含原始答案、题目正文、真实姓名或完整画像历史。

## 7. 兼容性分析

### 7.1 V2 调用兼容性

该字段使用空列表默认值，现有合法 `AnalyzeProfileInput` fixture 和调用方无需立即提供，属于
向后兼容的增量字段。

现有调用方不提供该字段时：

- 输入仍然合法。
- Profile Agent 不得伪造知识点评估。
- 首次生成只能使用已准备的 `current_profile`。
- 反馈场景按照现有证据门槛执行 `no_change` 或保守策略。

### 7.2 V1 兼容性

当前 V1 运行链继续使用 `legacy_contracts` 和 `legacy_state`，本变更不要求同步修改 V1 数据形状。
在所有 V2 Agent 完成前，不进行 import-only 切换。

### 7.3 State 与持久化影响

建议不在顶层 `AgentGraphState` 新增完整评估列表。统一集成时由 `analyze_profile` 节点输入构造器
根据任务 ID 和诊断/测验记录构造瞬时 `AnalyzeProfileInput`。

如 LangGraph checkpoint 回放必须保存这些结构化事实，契约维护者需要统一评估 State 所有权和
隐私影响，不由 Profile Agent 实现者自行扩展 State。

数据库暂不要求新增表；MVP 可从已有答题记录和测验结果构造。如果现有记录无法稳定提供所需
字段，应由数据模型负责人另行评估，不能在 AgentMessage 中保存完整答案作为替代。

## 8. 隐私与日志

- `KnowledgeAssessment` 不包含原始答案和题目正文。
- 普通日志只记录 `assessment_id`、`knowledge_id`、是否有效和错误代码。
- 不记录完整 `AnalyzeProfileInput`。
- 简答题原文只存在于受控诊断业务存储和模型调用边界，不写入 Agent 普通日志。
- `AgentMessage` 只保存评估数量、涉及知识 ID、画像是否变化、置信度和决策摘要。

## 9. 需要同步更新的冻结产物

审批通过后，只能由指定契约维护者统一修改并生成：

1. `backend/app/agents/contracts.py`
2. `docs/agent-contract-v2.md`
3. `docs/contracts/v2/agent-contract-v2.schema.json`
4. 相关 V2 JSON 示例
5. `backend/tests/contracts/test_agent_contract_v2.py`
6. 必要的 `contract_adapters.py` 说明或适配逻辑

原则上不修改 `backend/app/agents/state.py`。如审批决定将评估列表持久化到 State，则必须同时
明确字段所有权、checkpoint 行为和隐私规则。

## 10. 合同测试建议

审批通过后建议增加：

- 不提供 `knowledge_assessments` 时默认空列表。
- 合法知识点评估通过校验。
- `score < 0`、`score > 1` 被拒绝。
- `difficulty` 超出 1-5 被拒绝。
- `confidence` 超出 0-1 被拒绝。
- `attempted=false` 且存在分数被拒绝。
- 重复 `assessment_id` 被拒绝。
- 找不到对应 `evidence_id` 时被拒绝或由明确兼容策略处理。
- 评估与证据的 `knowledge_id` 不一致时被拒绝。
- JSON Schema 与 Pydantic 模型一致。
- 现有 V2 示例继续通过校验。
- V1 合同和生产测试不受影响。

## 11. 审批选项

契约维护者需要从以下方案中确认一个：

### 方案 A：批准推荐变更

新增 `KnowledgeAssessment` 和可选的
`AnalyzeProfileInput.knowledge_assessments`，保持 V1 不变，由节点输入构造器提供结构化评估。

这是本申请推荐方案。

### 方案 B：维持当前契约

由诊断服务提前生成完整 `current_profile`，Profile Analysis Agent 只负责证据门槛、画像是否
继续更新、影响范围和 `RetrievalPlan`。

该方案无需契约变更，但必须接受首次诊断画像主要由业务服务生成，Profile Agent 的独立画像
分析能力受限。

### 方案 C：要求重新设计

如果契约维护者认为评估事实应属于 `DiagnosticSummary` 或独立 State 字段，应给出统一的数据
所有权方案，再由合同维护者集中修改模型、Schema、示例和测试。

## 12. 审批记录

审批人：项目契约维护者（用户确认）  
审批日期：2026-07-22  
审批结果：批准并已完成契约工件同步  
批准方案：方案 A  
附加条件：`knowledge_assessments` 通过节点输入构造器瞬时注入，默认不写入顶层 State
