from typing import Literal, TypedDict

from app.agents.contracts import (
    AnalyzeProfileOutput,
    DiagnosticSummary,
    FeedbackContext,
    FinalizeTaskOutput,
    GenerateResourceOutput,
    InterpretFeedbackOutput,
    LearningPathNodeSnapshot,
    LearningPathSnapshot,
    PrepareTaskOutput,
    ProfileSnapshot,
    RetrieveKnowledgeOutput,
    ReviewResourceOutput,
    RevisionPlan,
    TaskRequest,
)


class AgentGraphState(TypedDict, total=False):
    """Agent Contract V9 state shape for production workflows."""

    contract_version: Literal["agent-contract-v9"]
    task_request: TaskRequest
    current_profile: ProfileSnapshot
    learning_path: LearningPathSnapshot
    current_path_node: LearningPathNodeSnapshot
    diagnostic_summary: DiagnosticSummary
    feedback_context: FeedbackContext
    revision_plan: RevisionPlan
    prepare_task: PrepareTaskOutput
    interpret_feedback: InterpretFeedbackOutput
    analyze_profile: AnalyzeProfileOutput
    retrieve_knowledge: RetrieveKnowledgeOutput
    generate_resource: GenerateResourceOutput
    review_resource: ReviewResourceOutput
    finalize_task: FinalizeTaskOutput
    error_code: str
    error_summary: str
