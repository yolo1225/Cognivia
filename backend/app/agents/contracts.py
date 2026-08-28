from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "agent-contract-v10"
QUALITY_RULE_VERSION = "quality-v8-official-gates"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NodeContract(ContractModel):
    contract_version: Literal["agent-contract-v10"] = CONTRACT_VERSION
    task_id: str = Field(min_length=1, max_length=64)


class AgentName(StrEnum):
    ORCHESTRATOR = "orchestrator_agent"
    PROFILE_ANALYSIS = "profile_analysis_agent"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval_agent"
    CONTENT_GENERATION = "content_generation_agent"
    REVIEW_VALIDATION = "review_validation_agent"
    TUTORING = "tutoring_agent"


class NodeName(StrEnum):
    PREPARE_TASK = "prepare_task"
    INTERPRET_FEEDBACK = "interpret_feedback"
    ANALYZE_PROFILE = "analyze_profile"
    RETRIEVE_KNOWLEDGE = "retrieve_knowledge"
    GENERATE_RESOURCE = "generate_resource"
    REVIEW_RESOURCE = "review_resource"
    FINALIZE_TASK = "finalize_task"


class ResourceType(StrEnum):
    LECTURE = "lecture"
    PRACTICE_GUIDE = "practice_guide"
    GRADED_QUIZ = "graded_quiz"


class ReviewClaimKind(StrEnum):
    PROFESSIONAL_FACT = "professional_fact"
    OPERATIONAL_FACT = "operational_fact"
    CODE_BEHAVIOR = "code_behavior"
    EXPECTED_RESULT = "expected_result"
    ERROR_HANDLING = "error_handling"


class TriggerType(StrEnum):
    INITIAL_GENERATION = "initial_generation"
    RESOURCE_FEEDBACK = "resource_feedback"


class ExecutionMode(StrEnum):
    AUTO = "auto"
    ASSISTED = "assisted"


class ProfileType(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    PRACTICE_ORIENTED = "practice_oriented"


class GenerationStrategy(StrEnum):
    REMEDIAL = "remedial"
    CONSOLIDATION = "consolidation"
    CHALLENGE = "challenge"


class FeedbackIntent(StrEnum):
    TOO_HARD = "too_hard"
    TOO_EASY = "too_easy"
    CONFUSING = "confusing"
    INCORRECT = "incorrect"
    HELPFUL = "helpful"
    OTHER = "other"


class RecommendedAction(StrEnum):
    ASK_FOLLOW_UP = "ask_follow_up"
    EXPLAIN = "explain"
    CHALLENGE = "challenge"
    REVIEW = "review"
    REGENERATE = "regenerate"
    NO_CHANGE = "no_change"


class TaskDecision(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    NO_CHANGE = "no_change"
    REVISION_REQUIRED = "revision_required"
    FAILED = "failed"
    REJECTED = "rejected"


class ReviewDecision(StrEnum):
    PASSED = "passed"
    REVISION_REQUIRED = "revision_required"
    REJECTED = "rejected"


class EvidenceVerdict(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    UNRESOLVED = "unresolved"


class MessageType(StrEnum):
    COMMAND = "command"
    OBSERVATION = "observation"
    RESULT = "result"
    REVIEW = "review"
    DECISION = "decision"
    FEEDBACK = "feedback"
    ERROR = "error"


class EvidenceType(StrEnum):
    QUICK_FEEDBACK = "quick_feedback"
    NATURAL_LANGUAGE = "natural_language"
    SCORED_QUIZ = "scored_quiz"
    DIAGNOSTIC_RESULT = "diagnostic_result"
    VALIDATED_BEHAVIOR = "validated_behavior"


class MasteryType(StrEnum):
    KNOWN = "known"
    PARTIAL_MASTERY = "partial_mastery"
    CONFUSED = "confused"
    UNMASTERED = "unmastered"
    UNASSESSED = "unassessed"


class RetrievalMatchType(StrEnum):
    PRIORITY = "priority"
    PREREQUISITE = "prerequisite"
    SEMANTIC = "semantic"
    RELATED = "related"
    DEPENDENT = "dependent"


class RetrievalPurpose(StrEnum):
    REMEDIAL_EXPLANATION = "remedial_explanation"
    CONSOLIDATION_PRACTICE = "consolidation_practice"
    CHALLENGE_TASK = "challenge_task"
    SOURCE_VERIFICATION = "source_verification"


class QuizLevel(StrEnum):
    FOUNDATION = "foundation"
    IMPROVEMENT = "improvement"
    CHALLENGE = "challenge"


class QuestionType(StrEnum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    SHORT_ANSWER = "short_answer"
    CODING = "coding"


class ReviewIssueCode(StrEnum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    CONTRADICTED_CLAIM = "contradicted_claim"
    CLAIM_SET_MISMATCH = "claim_set_mismatch"
    MISSING_SOURCE = "missing_source"
    DIFFICULTY_MISMATCH = "difficulty_mismatch"
    MISSING_KNOWLEDGE = "missing_knowledge"
    STRUCTURAL_ERROR = "structural_error"


class MetricValue(ContractModel):
    name: str = Field(min_length=1, max_length=64)
    value: str | int | float | bool


class MessagePayload(ContractModel):
    node_name: NodeName
    summary: str = Field(min_length=1, max_length=500)
    reference_ids: list[str] = Field(default_factory=list, max_length=20)
    decision: TaskDecision | None = None
    error_code: str | None = Field(default=None, max_length=64)
    metrics: list[MetricValue] = Field(default_factory=list, max_length=20)


class AgentMessage(ContractModel):
    contract_version: Literal["agent-contract-v10"] = CONTRACT_VERSION
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    sender: AgentName
    receiver: AgentName
    message_type: MessageType
    payload: MessagePayload
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str = Field(min_length=1, max_length=64)
    task_id: str = Field(min_length=1, max_length=64)


class EvidenceRef(ContractModel):
    evidence_id: str = Field(min_length=1, max_length=64)
    evidence_type: EvidenceType
    summary: str = Field(min_length=1, max_length=500)
    knowledge_id: str | None = Field(default=None, max_length=64)
    source_ref_id: str | None = Field(default=None, max_length=128)
    confidence: float = Field(ge=0, le=1)
    confirmed: bool = False


class KnowledgeAssessment(ContractModel):
    assessment_id: str = Field(min_length=1, max_length=64)
    evidence_id: str = Field(min_length=1, max_length=64)
    knowledge_id: str = Field(min_length=1, max_length=64)
    score: float | None = Field(default=None, ge=0, le=1)
    difficulty: int = Field(ge=1, le=5)
    attempted: bool
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_attempt(self) -> "KnowledgeAssessment":
        if not self.attempted and self.score is not None:
            raise ValueError("unattempted assessments cannot include a score")
        return self


class SourceRef(ContractModel):
    source_ref_id: str = Field(min_length=1, max_length=128)
    knowledge_id: str = Field(min_length=1, max_length=64)
    source_title: str = Field(min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=512)
    license_note: str = Field(min_length=1, max_length=255)


class AbilityScores(ContractModel):
    theory: int = Field(ge=0, le=100)
    practice: int = Field(ge=0, le=100)
    problem_solving: int = Field(ge=0, le=100)
    knowledge_breadth: int = Field(ge=0, le=100)
    learning_speed: int = Field(ge=0, le=100)


class WeakKnowledge(ContractModel):
    knowledge_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=64)
    weakness_level: int = Field(ge=1, le=5)
    mastery_type: MasteryType
    prerequisite_ids: list[str] = Field(default_factory=list, max_length=20)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    reason: str = Field(min_length=1, max_length=500)


class ProfileSnapshot(ContractModel):
    profile_id: str = Field(min_length=1, max_length=64)
    profile_version: int = Field(ge=1)
    profile_type: ProfileType
    ability_scores: AbilityScores
    weak_knowledge: list[WeakKnowledge] = Field(default_factory=list, max_length=50)
    blind_spot_ids: list[str] = Field(default_factory=list, max_length=50)


class LearningPathNodeSnapshot(ContractModel):
    path_node_id: str = Field(min_length=1, max_length=64)
    knowledge_ids: list[str] = Field(min_length=1, max_length=6)
    focus_knowledge_ids: list[str] = Field(default_factory=list, max_length=3)
    title: str = Field(min_length=1, max_length=255)
    path_order: int = Field(ge=1)
    target_difficulty: int = Field(ge=1, le=5)
    learning_objective: str = Field(min_length=1, max_length=500)
    recommendation_reason: str = Field(min_length=1, max_length=500)
    prerequisite_knowledge_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_focus_knowledge(self) -> "LearningPathNodeSnapshot":
        if not set(self.focus_knowledge_ids).issubset(self.knowledge_ids):
            raise ValueError("focus_knowledge_ids must be a subset of knowledge_ids")
        return self


class LearningPathSnapshot(ContractModel):
    path_id: str = Field(min_length=1, max_length=64)
    nodes: list[LearningPathNodeSnapshot] = Field(default_factory=list, max_length=50)
    current_node_id: str | None = Field(default=None, max_length=64)


class AffectedScope(ContractModel):
    knowledge_ids: list[str] = Field(default_factory=list, max_length=50)
    path_node_ids: list[str] = Field(default_factory=list, max_length=50)
    resource_ids: list[str] = Field(default_factory=list, max_length=50)


class TaskRequest(ContractModel):
    task_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=64)
    trigger_type: TriggerType
    execution_mode: ExecutionMode
    learner_id: str = Field(min_length=1, max_length=64)
    profile_id: str = Field(min_length=1, max_length=64)
    domain_code: str = Field(min_length=1, max_length=64)
    resource_types: list[ResourceType] = Field(min_length=1, max_length=3)
    learning_goal: str = Field(min_length=1, max_length=512)
    resource_knowledge_targets: dict[ResourceType, list[str]] = Field(
        default_factory=dict
    )
    resource_id: str | None = Field(default=None, max_length=64)
    feedback_id: str | None = Field(default=None, max_length=64)
    tutoring_session_id: str | None = Field(default=None, max_length=64)
    tutoring_message_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_feedback_references(self) -> "TaskRequest":
        if len(self.resource_types) != len(set(self.resource_types)):
            raise ValueError("resource_types must be unique")
        if self.resource_knowledge_targets:
            if set(self.resource_knowledge_targets) != set(self.resource_types):
                raise ValueError("inherited resource targets must match requested resource types")
            if any(not values for values in self.resource_knowledge_targets.values()):
                raise ValueError("inherited resource targets cannot be empty")
        if self.trigger_type == TriggerType.RESOURCE_FEEDBACK:
            if not self.resource_id or not self.feedback_id:
                raise ValueError("resource feedback requires resource_id and feedback_id")
        return self


class TaskContext(TaskRequest):
    contract_version: Literal["agent-contract-v10"] = CONTRACT_VERSION


class ContextNodeContract(NodeContract):
    context: TaskContext

    @model_validator(mode="after")
    def validate_context_task_id(self) -> "ContextNodeContract":
        if self.task_id != self.context.task_id:
            raise ValueError("node task_id must match context.task_id")
        return self


class DiagnosticSummary(ContractModel):
    diagnostic_session_id: str = Field(min_length=1, max_length=64)
    question_count: int = Field(ge=1)
    answered_count: int = Field(ge=0)
    correct_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    score_percent: float = Field(ge=0, le=100)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_counts(self) -> "DiagnosticSummary":
        if self.answered_count + self.skipped_count > self.question_count:
            raise ValueError("answered_count plus skipped_count cannot exceed question_count")
        if self.correct_count > self.answered_count:
            raise ValueError("correct_count cannot exceed answered_count")
        return self


class RetrievalPlan(ContractModel):
    strategy: GenerationStrategy
    target_difficulty: int = Field(ge=1, le=5)
    resource_types: list[ResourceType] = Field(min_length=1, max_length=3)
    priority_knowledge_ids: list[str] = Field(default_factory=list, max_length=20)
    prerequisite_knowledge_ids: list[str] = Field(default_factory=list, max_length=20)
    query_terms: list[str] = Field(min_length=1, max_length=30)
    n_results: int = Field(default=12, ge=1, le=18)

    @model_validator(mode="after")
    def validate_unique_values(self) -> "RetrievalPlan":
        if len(self.resource_types) != len(set(self.resource_types)):
            raise ValueError("retrieval resource_types must be unique")
        if len(self.query_terms) != len(set(self.query_terms)):
            raise ValueError("retrieval query_terms must be unique")
        return self


class RevisionPlan(ContractModel):
    revision_count: int = Field(ge=0, le=2)
    resource_types: list[ResourceType] = Field(default_factory=list, max_length=3)
    issue_codes: list[ReviewIssueCode] = Field(default_factory=list, max_length=20)
    query_terms: list[str] = Field(default_factory=list, max_length=30)
    required_changes: list[str] = Field(default_factory=list, max_length=30)
    missing_knowledge_ids_by_resource: dict[ResourceType, list[str]] = Field(default_factory=dict)
    preserve_knowledge_ids_by_resource: dict[ResourceType, list[str]] = Field(default_factory=dict)
    claim_ids_by_resource: dict[ResourceType, list[str]] = Field(default_factory=dict)
    field_paths_by_resource: dict[ResourceType, list[str]] = Field(default_factory=dict)


class PrepareTaskInput(NodeContract):
    request: TaskRequest

    @model_validator(mode="after")
    def validate_request_task_id(self) -> "PrepareTaskInput":
        if self.task_id != self.request.task_id:
            raise ValueError("node task_id must match request.task_id")
        return self


class PrepareTaskOutput(ContextNodeContract):
    next_node: Literal["analyze_profile", "interpret_feedback"]

    @model_validator(mode="after")
    def validate_route(self) -> "PrepareTaskOutput":
        expected = (
            "interpret_feedback"
            if self.context.trigger_type == TriggerType.RESOURCE_FEEDBACK
            else "analyze_profile"
        )
        if self.next_node != expected:
            raise ValueError("next_node must match the task trigger_type")
        return self


class ResourceSummary(ContractModel):
    resource_id: str = Field(min_length=1, max_length=64)
    resource_type: ResourceType
    title: str = Field(min_length=1, max_length=255)
    difficulty: int = Field(ge=1, le=5)
    source_ref_ids: list[str] = Field(default_factory=list, max_length=20)


class ConversationSummary(ContractModel):
    tutoring_session_id: str = Field(min_length=1, max_length=64)
    turn_count: int = Field(ge=1)
    latest_message_summary: str = Field(min_length=1, max_length=500)
    previous_intents: list[FeedbackIntent] = Field(default_factory=list, max_length=20)


class FeedbackContext(ContractModel):
    resource: ResourceSummary
    conversation: ConversationSummary
    feedback_summary: str = Field(min_length=1, max_length=500)
    quick_tag: FeedbackIntent | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    selected_text_summary: str | None = Field(default=None, max_length=500)
    supporting_evidence: list[EvidenceRef] = Field(default_factory=list, max_length=50)


class InterpretFeedbackInput(ContextNodeContract):
    profile: ProfileSnapshot
    feedback: FeedbackContext


class InterpretFeedbackOutput(NodeContract):
    feedback_intent: FeedbackIntent
    recommended_action: RecommendedAction
    reply: str = Field(min_length=1, max_length=2000)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=50)
    needs_generation: bool
    decision_reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_generation_action(self) -> "InterpretFeedbackOutput":
        generation_actions = {
            RecommendedAction.CHALLENGE,
            RecommendedAction.REVIEW,
            RecommendedAction.REGENERATE,
        }
        non_generation_actions = {
            RecommendedAction.ASK_FOLLOW_UP,
            RecommendedAction.NO_CHANGE,
        }
        if self.recommended_action in generation_actions and not self.needs_generation:
            raise ValueError("the recommended action requires resource generation or review")
        if self.recommended_action in non_generation_actions and self.needs_generation:
            raise ValueError("the recommended action cannot require resource generation")
        return self


class AnalyzeProfileInput(ContextNodeContract):
    current_profile: ProfileSnapshot
    learning_path: LearningPathSnapshot | None = None
    current_path_node: LearningPathNodeSnapshot | None = None
    diagnostic_summary: DiagnosticSummary | None = None
    feedback_evidence: list[EvidenceRef] = Field(default_factory=list, max_length=100)
    recommended_action: RecommendedAction | None = None
    knowledge_assessments: list[KnowledgeAssessment] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_knowledge_assessments(self) -> "AnalyzeProfileInput":
        assessment_ids = [item.assessment_id for item in self.knowledge_assessments]
        if len(assessment_ids) != len(set(assessment_ids)):
            raise ValueError("knowledge assessment IDs must be unique")

        evidence = list(self.feedback_evidence)
        if self.diagnostic_summary is not None:
            evidence.extend(self.diagnostic_summary.evidence)
        evidence_by_id = {item.evidence_id: item for item in evidence}

        for assessment in self.knowledge_assessments:
            source = evidence_by_id.get(assessment.evidence_id)
            if source is None:
                raise ValueError("knowledge assessments must reference available evidence")
            if source.knowledge_id is None:
                raise ValueError("assessment evidence must identify a knowledge ID")
            if source.knowledge_id != assessment.knowledge_id:
                raise ValueError("assessment and evidence knowledge IDs must match")
        return self


class AnalyzeProfileOutput(NodeContract):
    profile: ProfileSnapshot
    profile_update_required: bool
    changed_dimensions: list[str] = Field(default_factory=list, max_length=20)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=100)
    confidence: float = Field(ge=0, le=1)
    decision_reason: str = Field(min_length=1, max_length=1000)
    affected_scope: AffectedScope
    retrieval_plan: RetrievalPlan
    needs_generation: bool
    current_path_node: LearningPathNodeSnapshot | None = None
    resource_knowledge_targets: dict[ResourceType, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_profile_change(self) -> "AnalyzeProfileOutput":
        if self.profile_update_required:
            if not self.changed_dimensions or not self.evidence_refs:
                raise ValueError("profile updates require changed dimensions and evidence")
        elif self.changed_dimensions:
            raise ValueError("unchanged profiles cannot report changed dimensions")
        return self


class RetrievedChunk(ContractModel):
    chunk_id: str = Field(min_length=1, max_length=128)
    knowledge_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=64)
    difficulty: int = Field(ge=1, le=5)
    content: str = Field(min_length=1, max_length=6000)
    similarity: float = Field(ge=0, le=1)
    matched_by: RetrievalMatchType
    used_for: RetrievalPurpose
    source: SourceRef
    content_checksum: str | None = Field(default=None, min_length=8, max_length=64)
    source_locator: str | None = Field(default=None, max_length=512)


class RetrievedQuestion(ContractModel):
    question_id: str = Field(min_length=1, max_length=64)
    knowledge_id: str = Field(min_length=1, max_length=64)
    related_knowledge_ids: list[str] = Field(default_factory=list, max_length=10)
    question_type: QuestionType
    stem: str = Field(min_length=1, max_length=3000)
    options: list[str] = Field(default_factory=list, max_length=10)
    answer_key: dict = Field(default_factory=dict)
    explanation: str | None = Field(default=None, max_length=3000)
    difficulty: int = Field(ge=1, le=5)


class RetrieveKnowledgeInput(ContextNodeContract):
    profile: ProfileSnapshot
    retrieval_plan: RetrievalPlan
    revision_plan: RevisionPlan | None = None
    purpose: RetrievalPurpose


class RetrieveKnowledgeOutput(NodeContract):
    query_text: str = Field(min_length=1, max_length=2000)
    chunks: list[RetrievedChunk] = Field(default_factory=list, max_length=18)
    covered_knowledge_ids: list[str] = Field(default_factory=list, max_length=50)
    missing_knowledge_ids: list[str] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    reference_questions: list[RetrievedQuestion] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_coverage_sets(self) -> "RetrieveKnowledgeOutput":
        overlap = set(self.covered_knowledge_ids) & set(self.missing_knowledge_ids)
        if overlap:
            raise ValueError("covered and missing knowledge ids must be disjoint")
        return self


class GenerationRequirements(ContractModel):
    resource_types: list[ResourceType] = Field(min_length=1, max_length=3)
    target_difficulty: int = Field(ge=1, le=5)
    strategy: GenerationStrategy
    required_knowledge_ids: list[str] = Field(min_length=1, max_length=30)
    resource_knowledge_targets: dict[ResourceType, list[str]] = Field(default_factory=dict)
    package_coverage_threshold: float = Field(default=90, ge=0, le=100)
    resource_coverage_threshold: float = Field(default=100, ge=0, le=100)
    source_whitelist: list[str] = Field(min_length=1, max_length=30)
    adaptation_notes: list[str] = Field(default_factory=list, max_length=20)
    revision_plan: RevisionPlan | None = None

    @model_validator(mode="after")
    def validate_resource_targets(self) -> "GenerationRequirements":
        if not self.resource_knowledge_targets:
            self.resource_knowledge_targets = {
                resource_type: list(self.required_knowledge_ids)
                for resource_type in self.resource_types
            }
        if set(self.resource_knowledge_targets) != set(self.resource_types):
            raise ValueError("resource knowledge targets must match requested resource types")
        required = set(self.required_knowledge_ids)
        allocated: set[str] = set()
        for values in self.resource_knowledge_targets.values():
            if not values or not set(values).issubset(required):
                raise ValueError("resource knowledge targets must be non-empty task target subsets")
            allocated.update(values)
        if allocated != required:
            raise ValueError("resource knowledge target union must equal task targets")
        return self


class ConceptBlock(ContractModel):
    title: str = Field(min_length=1, max_length=255)
    explanation: str = Field(min_length=1, max_length=3000)
    example: str | None = Field(default=None, max_length=3000)
    source_ref_ids: list[str] = Field(min_length=1, max_length=10)


class MisconceptionBlock(ContractModel):
    misconception: str = Field(min_length=1, max_length=500)
    correction: str = Field(min_length=1, max_length=1000)
    source_ref_ids: list[str] = Field(min_length=1, max_length=10)


class LectureContent(ContractModel):
    resource_type: Literal["lecture"] = "lecture"
    title: str = Field(min_length=1, max_length=255)
    target_audience: str = Field(min_length=1, max_length=500)
    learning_objectives: list[str] = Field(min_length=1, max_length=10)
    prerequisite_knowledge: list[str] = Field(default_factory=list, max_length=20)
    core_concepts: list[ConceptBlock] = Field(min_length=1, max_length=20)
    misconceptions: list[MisconceptionBlock] = Field(default_factory=list, max_length=10)
    summary: str = Field(min_length=1, max_length=2000)


class PracticeStep(ContractModel):
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)
    instruction: str = Field(min_length=1, max_length=3000)
    code_or_command: str | None = Field(default=None, max_length=6000)
    expected_result: str = Field(min_length=1, max_length=2000)
    troubleshooting: str | None = Field(default=None, max_length=2000)
    source_ref_ids: list[str] = Field(min_length=1, max_length=10)


class PracticeGuideContent(ContractModel):
    resource_type: Literal["practice_guide"] = "practice_guide"
    title: str = Field(min_length=1, max_length=255)
    target_audience: str = Field(min_length=1, max_length=500)
    learning_objectives: list[str] = Field(min_length=1, max_length=10)
    environment_requirements: list[str] = Field(min_length=1, max_length=20)
    steps: list[PracticeStep] = Field(min_length=1, max_length=30)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=20)


class QuizQuestion(ContractModel):
    question_id: str = Field(min_length=1, max_length=64)
    level: QuizLevel
    question_type: QuestionType
    prompt: str = Field(min_length=1, max_length=3000)
    options: list[str] = Field(default_factory=list, max_length=10)
    correct_answer: str = Field(min_length=1, max_length=3000)
    explanation: str = Field(min_length=1, max_length=3000)
    knowledge_id: str = Field(min_length=1, max_length=64)
    related_knowledge_ids: list[str] = Field(default_factory=list, max_length=10)
    difficulty: int = Field(ge=1, le=5)
    source_ref_ids: list[str] = Field(min_length=1, max_length=10)
    reference_question_ids: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_options(self) -> "QuizQuestion":
        choice_types = {QuestionType.SINGLE_CHOICE, QuestionType.MULTIPLE_CHOICE}
        if self.question_type in choice_types and len(self.options) < 2:
            raise ValueError("choice questions require at least two options")
        if self.question_type not in choice_types and self.options:
            raise ValueError("non-choice questions cannot define options")
        return self


class GradedQuizContent(ContractModel):
    resource_type: Literal["graded_quiz"] = "graded_quiz"
    title: str = Field(min_length=1, max_length=255)
    target_audience: str = Field(min_length=1, max_length=500)
    learning_objectives: list[str] = Field(min_length=1, max_length=10)
    # A resource quiz is selected from the certified formal bank for the current
    # learning unit.  Its size and teaching-level mix are profile-dependent;
    # question difficulty remains the certified, immutable item difficulty.
    questions: list[QuizQuestion] = Field(min_length=3, max_length=8)


StructuredResourceContent = Annotated[
    LectureContent | PracticeGuideContent | GradedQuizContent,
    Field(discriminator="resource_type"),
]


def structured_source_ref_ids(content: StructuredResourceContent) -> set[str]:
    if isinstance(content, LectureContent):
        return {
            source_ref_id
            for block in [*content.core_concepts, *content.misconceptions]
            for source_ref_id in block.source_ref_ids
        }
    if isinstance(content, PracticeGuideContent):
        return {
            source_ref_id
            for step in content.steps
            for source_ref_id in step.source_ref_ids
        }
    return {
        source_ref_id
        for question in content.questions
        for source_ref_id in question.source_ref_ids
    }


class ReviewClaim(ContractModel):
    claim_id: str = Field(min_length=8, max_length=64)
    resource_type: ResourceType
    field_path: str = Field(min_length=1, max_length=512)
    claim_kind: ReviewClaimKind
    claim: str = Field(min_length=1, max_length=2000)
    source_ref_ids: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_claim_sources(self) -> "ReviewClaim":
        if len(self.source_ref_ids) != len(set(self.source_ref_ids)):
            raise ValueError("review claim source ids must be unique")
        return self


class GeneratedResourceArtifact(ContractModel):
    resource_type: ResourceType
    structured_content: StructuredResourceContent
    content_md: str = Field(min_length=1)
    difficulty: int = Field(ge=1, le=5)
    source_refs: list[SourceRef] = Field(min_length=1, max_length=30)
    knowledge_coverage: dict[str, list[str]] = Field(default_factory=dict)
    review_claims: list[ReviewClaim] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_resource_type(self) -> "GeneratedResourceArtifact":
        if self.resource_type.value != self.structured_content.resource_type:
            raise ValueError("resource_type must match structured_content.resource_type")
        declared = [source.source_ref_id for source in self.source_refs]
        if len(declared) != len(set(declared)):
            raise ValueError("source_refs must be unique")
        used = structured_source_ref_ids(self.structured_content)
        if used != set(declared):
            raise ValueError("structured content source ids must exactly match source_refs")
        claim_ids = [claim.claim_id for claim in self.review_claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("review claim ids must be unique")
        for claim in self.review_claims:
            if claim.resource_type is not self.resource_type:
                raise ValueError("review claim resource type must match artifact")
            if not set(claim.source_ref_ids).issubset(set(declared)):
                raise ValueError("review claims may only cite artifact sources")
        return self


class GenerateResourceInput(ContextNodeContract):
    profile: ProfileSnapshot
    retrieved_chunks: list[RetrievedChunk] = Field(min_length=1, max_length=18)
    reference_questions: list[RetrievedQuestion] = Field(default_factory=list, max_length=30)
    current_path_node: LearningPathNodeSnapshot | None = None
    requirements: GenerationRequirements

    @model_validator(mode="after")
    def validate_generation_scope(self) -> "GenerateResourceInput":
        if not set(self.requirements.resource_types).issubset(self.context.resource_types):
            raise ValueError("generation resource types must be part of the task context")
        available_sources = {chunk.source.source_ref_id for chunk in self.retrieved_chunks}
        if not set(self.requirements.source_whitelist).issubset(available_sources):
            raise ValueError("source_whitelist may only contain retrieved sources")
        return self


class GenerateResourceOutput(NodeContract):
    resources: list[GeneratedResourceArtifact] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_unique_resource_types(self) -> "GenerateResourceOutput":
        resource_types = [resource.resource_type for resource in self.resources]
        if len(resource_types) != len(set(resource_types)):
            raise ValueError("generated resource types must be unique")
        return self


class ReviewCriterionScores(ContractModel):
    factual_accuracy: float = Field(ge=0, le=100)
    source_traceability: float = Field(ge=0, le=100)
    difficulty_match: float = Field(ge=0, le=100)
    core_knowledge_coverage: float = Field(ge=0, le=100)


class FactCheck(ContractModel):
    claim_id: str | None = Field(default=None, min_length=8, max_length=64)
    field_path: str | None = Field(default=None, max_length=512)
    claim: str = Field(min_length=1, max_length=2000)
    verdict: EvidenceVerdict | None = None
    supported: bool | None = None
    source_ref_ids: list[str] = Field(default_factory=list, max_length=20)
    reason: str = Field(min_length=1, max_length=1000)
    determinable: bool = True

    @model_validator(mode="after")
    def validate_support_state(self) -> "FactCheck":
        if self.verdict is None:
            if not self.determinable or self.supported is None:
                self.verdict = EvidenceVerdict.EVIDENCE_INSUFFICIENT
            elif self.supported:
                self.verdict = EvidenceVerdict.SUPPORTED
            else:
                self.verdict = EvidenceVerdict.CONTRADICTED
        if self.verdict in {
            EvidenceVerdict.EVIDENCE_INSUFFICIENT,
            EvidenceVerdict.UNRESOLVED,
        }:
            self.determinable = False
            self.supported = None
        else:
            self.determinable = True
            self.supported = self.verdict is EvidenceVerdict.SUPPORTED
        return self


class ReviewIssue(ContractModel):
    code: ReviewIssueCode
    section: str = Field(min_length=1, max_length=255)
    knowledge_ids: list[str] = Field(default_factory=list, max_length=20)
    description: str = Field(min_length=1, max_length=1000)
    suggested_revision: str = Field(min_length=1, max_length=1000)


class ModelReview(ContractModel):
    model_role: Literal["primary_review_model", "secondary_review_model"]
    model_name: str = Field(min_length=1, max_length=128)
    scores: ReviewCriterionScores
    passed: bool
    fact_checks: list[FactCheck] = Field(default_factory=list, max_length=100)
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=50)
    unable_to_determine: list[str] = Field(default_factory=list, max_length=50)

    # Claim-set completeness and uniqueness are validated against the canonical
    # ordered set by the review boundary. Keeping parsing permissive here allows
    # one targeted correction call for missing, extra, or duplicate claim IDs.


class ArbitrationResult(ContractModel):
    required: bool
    retrieval_performed: bool
    query_terms: list[str] = Field(default_factory=list, max_length=30)
    additional_source_ref_ids: list[str] = Field(default_factory=list, max_length=30)
    disputed_claim_ids: list[str] = Field(default_factory=list, max_length=100)
    primary_recheck: ModelReview | None = None
    secondary_recheck: ModelReview | None = None
    disagreement_remains: bool

    @model_validator(mode="after")
    def validate_arbitration(self) -> "ArbitrationResult":
        if self.required:
            if not self.retrieval_performed or not self.query_terms:
                raise ValueError("required arbitration must perform retrieval with query terms")
            if self.primary_recheck is None or self.secondary_recheck is None:
                raise ValueError("required arbitration must include both rechecks")
        elif any(
            (
                self.retrieval_performed,
                self.disagreement_remains,
                bool(self.query_terms),
                bool(self.additional_source_ref_ids),
                bool(self.disputed_claim_ids),
                self.primary_recheck is not None,
                self.secondary_recheck is not None,
            )
        ):
            raise ValueError("non-required arbitration cannot contain arbitration activity")
        return self


class ResourceQualityMetrics(ContractModel):
    quality_rule_version: Literal["quality-v8-official-gates"] = QUALITY_RULE_VERSION
    evaluated_claim_count: int = Field(ge=0)
    contradicted_claim_count: int = Field(ge=0)
    evidence_insufficient_claim_count: int = Field(ge=0)
    unresolved_claim_count: int = Field(ge=0)
    verifiable_claim_count: int = Field(ge=0)
    hallucinated_claim_count: int = Field(ge=0)
    hallucination_rate: float = Field(ge=0, le=100)
    difficulty_match_score: float = Field(ge=0, le=100)
    covered_core_knowledge_count: int = Field(ge=0)
    target_core_knowledge_count: int = Field(ge=0)
    core_knowledge_coverage: float = Field(ge=0, le=100)
    passed: bool
    revision_count: int = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def validate_deterministic_metrics(self) -> "ResourceQualityMetrics":
        if self.verifiable_claim_count != self.evaluated_claim_count:
            raise ValueError("verifiable_claim_count must equal evaluated_claim_count in V6")
        classified_failure_count = (
            self.contradicted_claim_count
            + self.evidence_insufficient_claim_count
            + self.unresolved_claim_count
        )
        if classified_failure_count > self.evaluated_claim_count:
            raise ValueError("claim verdict counts cannot exceed evaluated claims")
        if self.hallucinated_claim_count != classified_failure_count:
            raise ValueError("hallucinated claims must equal all non-supported reviewable claims")
        if self.hallucinated_claim_count > self.verifiable_claim_count:
            raise ValueError("hallucinated claims cannot exceed verifiable claims")
        if self.covered_core_knowledge_count > self.target_core_knowledge_count:
            raise ValueError("covered knowledge cannot exceed target knowledge")
        expected_hallucination = (
            0.0
            if self.verifiable_claim_count == 0
            else 100.0 * self.hallucinated_claim_count / self.verifiable_claim_count
        )
        expected_coverage = (
            0.0
            if self.target_core_knowledge_count == 0
            else 100.0
            * self.covered_core_knowledge_count
            / self.target_core_knowledge_count
        )
        if abs(self.hallucination_rate - expected_hallucination) > 0.011:
            raise ValueError("hallucination_rate must be derived from claim counts")
        if abs(self.core_knowledge_coverage - expected_coverage) > 0.011:
            raise ValueError("core_knowledge_coverage must be derived from knowledge counts")
        expected_passed = (
            self.evaluated_claim_count > 0
            and self.hallucination_rate < 5
            and self.difficulty_match_score >= 85
            and self.target_core_knowledge_count > 0
            and self.core_knowledge_coverage >= 90
        )
        if self.passed != expected_passed:
            raise ValueError("resource passed must match V6 claim publication gates")
        return self


class GenerationPackageQuality(ContractModel):
    quality_rule_version: Literal["quality-v8-official-gates"] = QUALITY_RULE_VERSION
    evaluated_claim_count: int = Field(ge=0)
    contradicted_claim_count: int = Field(ge=0)
    evidence_insufficient_claim_count: int = Field(ge=0)
    unresolved_claim_count: int = Field(ge=0)
    verifiable_claim_count: int = Field(ge=0)
    hallucinated_claim_count: int = Field(ge=0)
    hallucination_rate: float = Field(ge=0, le=100)
    difficulty_match_score: float = Field(ge=0, le=100)
    covered_core_knowledge_count: int = Field(ge=0)
    target_core_knowledge_count: int = Field(ge=0)
    core_knowledge_coverage: float = Field(ge=0, le=100)
    passed: bool
    revision_count: int = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def validate_deterministic_metrics(self) -> "GenerationPackageQuality":
        if self.verifiable_claim_count != self.evaluated_claim_count:
            raise ValueError("verifiable_claim_count must equal evaluated_claim_count in V6")
        classified_failure_count = (
            self.contradicted_claim_count
            + self.evidence_insufficient_claim_count
            + self.unresolved_claim_count
        )
        if classified_failure_count > self.evaluated_claim_count:
            raise ValueError("claim verdict counts cannot exceed evaluated claims")
        if self.hallucinated_claim_count != classified_failure_count:
            raise ValueError("hallucinated claims must equal all non-supported reviewable claims")
        if self.covered_core_knowledge_count > self.target_core_knowledge_count:
            raise ValueError("covered knowledge cannot exceed target knowledge")
        expected_hallucination = (
            0.0
            if self.evaluated_claim_count == 0
            else 100.0 * self.hallucinated_claim_count / self.evaluated_claim_count
        )
        expected_coverage = (
            0.0
            if self.target_core_knowledge_count == 0
            else 100.0 * self.covered_core_knowledge_count / self.target_core_knowledge_count
        )
        if abs(self.hallucination_rate - expected_hallucination) > 0.011:
            raise ValueError("hallucination_rate must be derived from V6 claim counts")
        if abs(self.core_knowledge_coverage - expected_coverage) > 0.011:
            raise ValueError("core_knowledge_coverage must be derived from unique package targets")
        expected_passed = (
            self.evaluated_claim_count > 0
            and self.hallucination_rate < 5
            and self.difficulty_match_score >= 85
            and self.target_core_knowledge_count > 0
            and self.core_knowledge_coverage >= 90
        )
        if self.passed != expected_passed:
            raise ValueError("package passed must match V6 publication gates")
        return self


class ReviewReport(ContractModel):
    quality_rule_version: Literal["quality-v8-official-gates"] = QUALITY_RULE_VERSION
    resource_type: ResourceType
    primary_review: ModelReview
    secondary_review: ModelReview
    final_scores: ReviewCriterionScores
    arbitration: ArbitrationResult
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=50)
    evidence_ref_ids: list[str] = Field(default_factory=list, max_length=50)
    decision: ReviewDecision
    passed: bool
    quality_metrics: ResourceQualityMetrics
    target_knowledge_ids: list[str] = Field(default_factory=list, max_length=30)
    covered_knowledge_ids: list[str] = Field(default_factory=list, max_length=30)
    missing_knowledge_ids: list[str] = Field(default_factory=list, max_length=30)
    claim_set_hash: str | None = Field(default=None, min_length=8, max_length=64)
    supported_claim_ids: list[str] = Field(default_factory=list, max_length=100)
    contradicted_claim_ids: list[str] = Field(default_factory=list, max_length=100)
    undetermined_claim_ids: list[str] = Field(default_factory=list, max_length=100)
    unresolved_claim_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_decision_flags(self) -> "ReviewReport":
        if self.primary_review.model_role != "primary_review_model":
            raise ValueError("primary_review must use the primary model role")
        if self.secondary_review.model_role != "secondary_review_model":
            raise ValueError("secondary_review must use the secondary model role")
        if self.passed != (self.decision == ReviewDecision.PASSED):
            raise ValueError("passed must match the review decision")
        if self.passed != self.quality_metrics.passed:
            raise ValueError("review decision and quality metrics must agree")
        return self


class ReviewResourceInput(ContextNodeContract):
    resources: list[GeneratedResourceArtifact] = Field(min_length=1, max_length=3)
    requirements: GenerationRequirements
    evidence: list[RetrievedChunk] = Field(min_length=1, max_length=18)

    @model_validator(mode="after")
    def validate_review_scope(self) -> "ReviewResourceInput":
        resource_types = {resource.resource_type for resource in self.resources}
        if resource_types != set(self.requirements.resource_types):
            raise ValueError("review resources must match generation requirements")
        evidence_sources = {chunk.source.source_ref_id for chunk in self.evidence}
        cited_sources = {
            source.source_ref_id
            for resource in self.resources
            for source in resource.source_refs
        }
        if not cited_sources.issubset(evidence_sources):
            raise ValueError("review resources may only cite supplied evidence")
        return self


class ReviewResourceOutput(NodeContract):
    reports: list[ReviewReport] = Field(min_length=1, max_length=3)
    package_required_knowledge_ids: list[str] = Field(default_factory=list, max_length=30)
    package_covered_knowledge_ids: list[str] = Field(default_factory=list, max_length=30)
    package_missing_knowledge_ids: list[str] = Field(default_factory=list, max_length=30)
    package_coverage_score: float = Field(default=0, ge=0, le=100)
    package_passed: bool = True
    package_quality: GenerationPackageQuality

    @model_validator(mode="after")
    def validate_unique_resource_types(self) -> "ReviewResourceOutput":
        resource_types = [report.resource_type for report in self.reports]
        if len(resource_types) != len(set(resource_types)):
            raise ValueError("review report resource types must be unique")
        return self


class FinalizeTaskInput(ContextNodeContract):
    resources: list[GeneratedResourceArtifact] = Field(default_factory=list, max_length=3)
    review_reports: list[ReviewReport] = Field(default_factory=list, max_length=3)
    revision_count: int = Field(ge=0, le=2)
    tutoring_result: InterpretFeedbackOutput | None = None
    package_coverage_score: float = Field(default=0, ge=0, le=100)
    package_passed: bool = True
    package_quality: GenerationPackageQuality | None = None

    @model_validator(mode="after")
    def validate_resource_reports(self) -> "FinalizeTaskInput":
        resource_types = {resource.resource_type for resource in self.resources}
        report_types = {report.resource_type for report in self.review_reports}
        if report_types and report_types != resource_types:
            raise ValueError("finalization reports must match generated resources")
        return self


class FinalizeTaskOutput(NodeContract):
    decision: TaskDecision
    revision_count: int = Field(ge=0, le=2)
    revision_plan: RevisionPlan | None = None
    passed_resource_types: list[ResourceType] = Field(default_factory=list, max_length=3)
    decision_reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_decision(self) -> "FinalizeTaskOutput":
        if self.decision == TaskDecision.REVISION_REQUIRED:
            if self.revision_plan is None or self.revision_count == 0:
                raise ValueError("revision_required needs a non-empty revision plan and count")
        elif self.revision_plan is not None:
            raise ValueError("only revision_required may include a revision plan")
        if self.decision == TaskDecision.COMPLETED and not self.passed_resource_types:
            raise ValueError("completed generation tasks require passed resources")
        return self


class AgentContractSchema(ContractModel):
    agent_message: AgentMessage
    prepare_task_input: PrepareTaskInput
    prepare_task_output: PrepareTaskOutput
    interpret_feedback_input: InterpretFeedbackInput
    interpret_feedback_output: InterpretFeedbackOutput
    analyze_profile_input: AnalyzeProfileInput
    analyze_profile_output: AnalyzeProfileOutput
    retrieve_knowledge_input: RetrieveKnowledgeInput
    retrieve_knowledge_output: RetrieveKnowledgeOutput
    generate_resource_input: GenerateResourceInput
    generate_resource_output: GenerateResourceOutput
    review_resource_input: ReviewResourceInput
    review_resource_output: ReviewResourceOutput
    finalize_task_input: FinalizeTaskInput
    finalize_task_output: FinalizeTaskOutput
