from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.agents.contract_adapters import render_resource_markdown
from app.agents.contracts import (
    AgentMessage,
    AgentName,
    AbilityScores,
    AffectedScope,
    AnalyzeProfileInput,
    AnalyzeProfileOutput,
    ArbitrationResult,
    ConceptBlock,
    ConversationSummary,
    DiagnosticSummary,
    EvidenceRef,
    EvidenceVerdict,
    EvidenceType,
    ExecutionMode,
    FactCheck,
    FeedbackContext,
    FeedbackIntent,
    FinalizeTaskInput,
    FinalizeTaskOutput,
    GenerateResourceInput,
    GenerateResourceOutput,
    GeneratedResourceArtifact,
    GenerationRequirements,
    GenerationPackageQuality,
    GenerationStrategy,
    GradedQuizContent,
    InterpretFeedbackInput,
    InterpretFeedbackOutput,
    KnowledgeAssessment,
    LectureContent,
    MasteryType,
    MisconceptionBlock,
    ModelReview,
    MessagePayload,
    MessageType,
    NodeName,
    PracticeGuideContent,
    PracticeStep,
    PrepareTaskInput,
    PrepareTaskOutput,
    ProfileSnapshot,
    ProfileType,
    QuestionType,
    QuizLevel,
    QuizQuestion,
    RecommendedAction,
    ResourceSummary,
    ResourceType,
    RetrieveKnowledgeInput,
    RetrieveKnowledgeOutput,
    RetrievalMatchType,
    RetrievalPlan,
    RetrievalPurpose,
    ReviewCriterionScores,
    ReviewDecision,
    ReviewReport,
    ResourceQualityMetrics,
    ReviewResourceInput,
    ReviewResourceOutput,
    RetrievedChunk,
    SourceRef,
    TaskContext,
    TaskDecision,
    TaskRequest,
    TriggerType,
    WeakKnowledge,
)


TASK_ID = "task_contract_example"
SOURCE = SourceRef(
    source_ref_id="AIAPP-K029::chunk::0",
    knowledge_id="AIAPP-K029",
    source_title="自建 AI 应用开发实训知识库",
    source_url=None,
    license_note="team-authored",
)
PREREQUISITE_SOURCE = SourceRef(
    source_ref_id="AIAPP-K028::chunk::0",
    knowledge_id="AIAPP-K028",
    source_title="自建 AI 应用开发实训知识库",
    source_url=None,
    license_note="team-authored",
)
PROFILE = ProfileSnapshot(
    profile_id="profile_contract_example",
    profile_version=1,
    profile_type=ProfileType.BEGINNER,
    ability_scores=AbilityScores(
        theory=55,
        practice=40,
        problem_solving=48,
        knowledge_breadth=52,
        learning_speed=60,
    ),
    weak_knowledge=[
        WeakKnowledge(
            knowledge_id="AIAPP-K029",
            name="RAG 检索与来源追溯",
            category="RAG",
            weakness_level=4,
            mastery_type=MasteryType.PARTIAL_MASTERY,
            prerequisite_ids=["AIAPP-K028"],
            evidence_ids=["evidence_diag_1"],
            reason="检索和重排题目得分较低",
        )
    ],
    blind_spot_ids=[],
)
PLAN = RetrievalPlan(
    strategy=GenerationStrategy.REMEDIAL,
    target_difficulty=2,
    resource_types=list(ResourceType),
    priority_knowledge_ids=["AIAPP-K029"],
    prerequisite_knowledge_ids=["AIAPP-K028"],
    query_terms=["RAG 检索", "来源追溯"],
    n_results=8,
)


def agent_message_example() -> AgentMessage:
    return AgentMessage(
        message_id="message_contract_example",
        sender=AgentName.ORCHESTRATOR,
        receiver=AgentName.KNOWLEDGE_RETRIEVAL,
        message_type=MessageType.COMMAND,
        payload=MessagePayload(
            node_name=NodeName.RETRIEVE_KNOWLEDGE,
            summary="按画像薄弱点检索 RAG 来源证据",
            reference_ids=["AIAPP-K029"],
        ),
        timestamp=datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        session_id=TASK_ID,
        task_id=TASK_ID,
    )


def _initial_context() -> TaskContext:
    return TaskContext(
        task_id=TASK_ID,
        session_id=TASK_ID,
        trigger_type=TriggerType.INITIAL_GENERATION,
        execution_mode=ExecutionMode.AUTO,
        learner_id="learner_001",
        profile_id=PROFILE.profile_id,
        domain_code="ai_app_dev",
        resource_types=list(ResourceType),
        learning_goal="掌握 RAG 检索与来源追溯",
    )


def _feedback_context() -> TaskContext:
    return TaskContext(
        task_id="task_feedback_example",
        session_id="task_feedback_example",
        trigger_type=TriggerType.RESOURCE_FEEDBACK,
        execution_mode=ExecutionMode.AUTO,
        learner_id="learner_001",
        profile_id=PROFILE.profile_id,
        domain_code="ai_app_dev",
        resource_types=[ResourceType.LECTURE],
        learning_goal="理解 RAG 检索",
        resource_id="resource_lecture_v1",
        feedback_id="feedback_001",
        tutoring_session_id="tutoring_001",
        tutoring_message_id="message_001",
    )


def _chunk() -> RetrievedChunk:
    content = "RAG 检索需要保留知识片段与来源标识，生成内容只能引用已检索证据。"
    return RetrievedChunk(
        chunk_id="AIAPP-K029::chunk::0",
        knowledge_id="AIAPP-K029",
        name="RAG 检索与来源追溯",
        category="RAG",
        difficulty=2,
        content=content,
        similarity=0.92,
        matched_by=RetrievalMatchType.PRIORITY,
        used_for=RetrievalPurpose.REMEDIAL_EXPLANATION,
        source=SOURCE,
        content_checksum=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        source_locator="knowledge:AIAPP-K029#chunk=0",
    )


def _prerequisite_chunk() -> RetrievedChunk:
    content = "文本向量将语义映射为可比较的数值表示，相似度用于召回候选知识片段。"
    return RetrievedChunk(
        chunk_id="AIAPP-K028::chunk::0",
        knowledge_id="AIAPP-K028",
        name="文本向量与语义相似度",
        category="RAG",
        difficulty=2,
        content=content,
        similarity=0.88,
        matched_by=RetrievalMatchType.PREREQUISITE,
        used_for=RetrievalPurpose.REMEDIAL_EXPLANATION,
        source=PREREQUISITE_SOURCE,
        content_checksum=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        source_locator="knowledge:AIAPP-K028#chunk=0",
    )


def _requirements(resource_types: list[ResourceType]) -> GenerationRequirements:
    return GenerationRequirements(
        resource_types=resource_types,
        target_difficulty=2,
        strategy=GenerationStrategy.REMEDIAL,
        required_knowledge_ids=["AIAPP-K029", "AIAPP-K028"],
        source_whitelist=[SOURCE.source_ref_id, PREREQUISITE_SOURCE.source_ref_id],
        adaptation_notes=["使用小步解释和明确检查点"],
    )


def _lecture_artifact() -> GeneratedResourceArtifact:
    content = LectureContent(
        title="RAG 检索与来源追溯讲义",
        target_audience="RAG 初学者",
        learning_objectives=["能说明检索片段与来源引用的关系"],
        prerequisite_knowledge=["文本向量基础"],
        core_concepts=[
            ConceptBlock(
                title="向量相似度召回",
                explanation="文本向量和相似度计算为候选知识片段召回提供基础。",
                example="先用语义相似度召回候选片段，再检查片段来源。",
                source_ref_ids=[PREREQUISITE_SOURCE.source_ref_id],
            ),
            ConceptBlock(
                title="可追溯检索",
                explanation="检索结果必须携带稳定的来源标识。",
                example="生成讲义中的事实引用 AIAPP-K029::chunk::0。",
                source_ref_ids=[SOURCE.source_ref_id],
            )
        ],
        misconceptions=[
            MisconceptionBlock(
                misconception="只要语义相似就不需要来源。",
                correction="语义匹配负责召回，来源标识负责追溯。",
                source_ref_ids=[SOURCE.source_ref_id],
            )
        ],
        summary="可靠 RAG 需要同时保留检索内容和来源引用。",
    )
    return GeneratedResourceArtifact(
        resource_type=ResourceType.LECTURE,
        structured_content=content,
        content_md=render_resource_markdown(content, [SOURCE, PREREQUISITE_SOURCE]),
        difficulty=2,
        source_refs=[SOURCE, PREREQUISITE_SOURCE],
        knowledge_coverage={
            "AIAPP-K029": [SOURCE.source_ref_id],
            "AIAPP-K028": [PREREQUISITE_SOURCE.source_ref_id],
        },
    )


def _practice_artifact() -> GeneratedResourceArtifact:
    content = PracticeGuideContent(
        title="RAG 检索证据链实操",
        target_audience="具备 Python 基础的初学者",
        learning_objectives=["完成一次带来源的向量检索"],
        environment_requirements=["Python 3.12", "ChromaDB"],
        steps=[
            PracticeStep(
                order=1,
                title="执行检索",
                instruction="使用学习目标构造查询并保留来源标识。",
                code_or_command="检查 candidate index 的 active collection 和来源标识。",
                expected_result="返回知识点 ID 和来源标题。",
                troubleshooting="无结果时检查索引状态。",
                source_ref_ids=[SOURCE.source_ref_id],
            )
        ],
        acceptance_criteria=["检索结果包含 knowledge_id 和 source_ref_id"],
    )
    return GeneratedResourceArtifact(
        resource_type=ResourceType.PRACTICE_GUIDE,
        structured_content=content,
        content_md=render_resource_markdown(content, [SOURCE]),
        difficulty=2,
        source_refs=[SOURCE],
    )


def _quiz_artifact() -> GeneratedResourceArtifact:
    questions: list[QuizQuestion] = []
    for index, level in enumerate(
        [
            QuizLevel.FOUNDATION,
            QuizLevel.FOUNDATION,
            QuizLevel.IMPROVEMENT,
            QuizLevel.IMPROVEMENT,
            QuizLevel.CHALLENGE,
            QuizLevel.CHALLENGE,
        ],
        start=1,
    ):
        questions.append(
            QuizQuestion(
                question_id=f"Q{index}",
                level=level,
                question_type=QuestionType.SHORT_ANSWER,
                prompt=f"说明 RAG 证据链检查点 {index}。",
                correct_answer="结果应包含知识点、片段和来源标识。",
                explanation="完整证据链用于事实复核。",
                knowledge_id="AIAPP-K029",
                difficulty=min(5, 1 + index // 2),
                source_ref_ids=[SOURCE.source_ref_id],
            )
        )
    content = GradedQuizContent(
        title="RAG 检索分级测验",
        target_audience="RAG 初学者",
        learning_objectives=["检查检索和来源追溯能力"],
        questions=questions,
    )
    return GeneratedResourceArtifact(
        resource_type=ResourceType.GRADED_QUIZ,
        structured_content=content,
        content_md=render_resource_markdown(content, [SOURCE]),
        difficulty=2,
        source_refs=[SOURCE],
    )


def resource_examples() -> list[GeneratedResourceArtifact]:
    return [_lecture_artifact(), _practice_artifact(), _quiz_artifact()]


def _passed_review(resource_type: ResourceType) -> ReviewReport:
    scores = ReviewCriterionScores(
        factual_accuracy=95,
        source_traceability=96,
        difficulty_match=92,
        core_knowledge_coverage=94,
    )
    fact_check = FactCheck(
        claim_id="clm_contract_supported_001",
        field_path="core_concepts[0].explanation[0]",
        claim="RAG 资源需保留来源标识。",
        verdict=EvidenceVerdict.SUPPORTED,
        source_ref_ids=[SOURCE.source_ref_id],
        reason="检索证据明确支持该声明。",
    )
    primary = ModelReview(
        model_role="primary_review_model",
        model_name="review-primary",
        scores=scores,
        passed=True,
        fact_checks=[fact_check],
    )
    secondary = ModelReview(
        model_role="secondary_review_model",
        model_name="review-secondary",
        scores=scores,
        passed=True,
        fact_checks=[fact_check],
    )
    return ReviewReport(
        resource_type=resource_type,
        primary_review=primary,
        secondary_review=secondary,
        final_scores=scores,
        arbitration=ArbitrationResult(
            required=False,
            retrieval_performed=False,
            disagreement_remains=False,
        ),
        evidence_ref_ids=[SOURCE.source_ref_id],
        decision=ReviewDecision.PASSED,
        passed=True,
        quality_metrics=ResourceQualityMetrics(
            verifiable_claim_count=1,
            hallucinated_claim_count=0,
            hallucination_rate=0,
            difficulty_match_score=92,
            covered_core_knowledge_count=1,
            target_core_knowledge_count=1,
            core_knowledge_coverage=100,
            passed=True,
            revision_count=0,
        ),
        claim_set_hash=hashlib.sha256(
            fact_check.claim_id.encode("utf-8")
        ).hexdigest(),
        supported_claim_ids=[fact_check.claim_id],
    )


def initial_generation_flow_example() -> dict[str, object]:
    context = _initial_context()
    request = TaskRequest.model_validate(context.model_dump(exclude={"contract_version"}))
    diagnostic = DiagnosticSummary(
        diagnostic_session_id="diagnostic_001",
        question_count=10,
        answered_count=10,
        correct_count=5,
        skipped_count=0,
        score_percent=50,
        evidence=[
            EvidenceRef(
                evidence_id="evidence_diag_1",
                evidence_type=EvidenceType.DIAGNOSTIC_RESULT,
                summary="RAG 检索题目得分较低",
                knowledge_id="AIAPP-K029",
                confidence=0.95,
                confirmed=True,
            )
        ],
    )
    prepare_input = PrepareTaskInput(task_id=TASK_ID, request=request)
    prepare_output = PrepareTaskOutput(
        task_id=TASK_ID, context=context, next_node="analyze_profile"
    )
    analyze_input = AnalyzeProfileInput(
        task_id=TASK_ID,
        context=context,
        current_profile=PROFILE,
        diagnostic_summary=diagnostic,
        knowledge_assessments=[
            KnowledgeAssessment(
                assessment_id="assessment_diag_1",
                evidence_id="evidence_diag_1",
                knowledge_id="AIAPP-K029",
                score=0.4,
                difficulty=3,
                attempted=True,
                confidence=0.95,
            )
        ],
    )
    analyze_output = AnalyzeProfileOutput(
        task_id=TASK_ID,
        profile=PROFILE,
        profile_update_required=False,
        evidence_refs=diagnostic.evidence,
        confidence=0.95,
        decision_reason="初次生成使用已有诊断画像",
        affected_scope=AffectedScope(knowledge_ids=["AIAPP-K029"]),
        retrieval_plan=PLAN,
        needs_generation=True,
    )
    chunk = _chunk()
    prerequisite_chunk = _prerequisite_chunk()
    retrieve_input = RetrieveKnowledgeInput(
        task_id=TASK_ID,
        context=context,
        profile=PROFILE,
        retrieval_plan=PLAN,
        purpose=RetrievalPurpose.REMEDIAL_EXPLANATION,
    )
    retrieve_output = RetrieveKnowledgeOutput(
        task_id=TASK_ID,
        query_text="RAG 检索 来源追溯",
        chunks=[chunk, prerequisite_chunk],
        covered_knowledge_ids=["AIAPP-K029", "AIAPP-K028"],
        missing_knowledge_ids=[],
        warnings=[],
    )
    requirements = _requirements(list(ResourceType))
    generate_input = GenerateResourceInput(
        task_id=TASK_ID,
        context=context,
        profile=PROFILE,
        retrieved_chunks=[chunk, prerequisite_chunk],
        requirements=requirements,
    )
    resources = resource_examples()
    generate_output = GenerateResourceOutput(task_id=TASK_ID, resources=resources)
    review_input = ReviewResourceInput(
        task_id=TASK_ID,
        context=context,
        resources=resources,
        requirements=requirements,
        evidence=[chunk, prerequisite_chunk],
    )
    reports = [_passed_review(resource_type) for resource_type in ResourceType]
    package_quality = GenerationPackageQuality(
        verifiable_claim_count=3,
        hallucinated_claim_count=0,
        hallucination_rate=0,
        difficulty_match_score=92,
        covered_core_knowledge_count=3,
        target_core_knowledge_count=3,
        core_knowledge_coverage=100,
        passed=True,
        revision_count=0,
    )
    review_output = ReviewResourceOutput(
        task_id=TASK_ID, reports=reports, package_quality=package_quality
    )
    finalize_input = FinalizeTaskInput(
        task_id=TASK_ID,
        context=context,
        resources=resources,
        review_reports=reports,
        revision_count=0,
        package_quality=package_quality,
    )
    finalize_output = FinalizeTaskOutput(
        task_id=TASK_ID,
        decision=TaskDecision.COMPLETED,
        revision_count=0,
        passed_resource_types=list(ResourceType),
        decision_reason="两路审核通过",
    )
    return {
        "prepare_task": {"input": prepare_input, "output": prepare_output},
        "analyze_profile": {"input": analyze_input, "output": analyze_output},
        "retrieve_knowledge": {"input": retrieve_input, "output": retrieve_output},
        "generate_resource": {"input": generate_input, "output": generate_output},
        "review_resource": {"input": review_input, "output": review_output},
        "finalize_task": {"input": finalize_input, "output": finalize_output},
    }


def feedback_flow_example() -> dict[str, object]:
    context = _feedback_context()
    request = TaskRequest.model_validate(context.model_dump(exclude={"contract_version"}))
    feedback = FeedbackContext(
        resource=ResourceSummary(
            resource_id="resource_lecture_v1",
            resource_type=ResourceType.LECTURE,
            title="RAG 讲义",
            difficulty=2,
            source_ref_ids=[SOURCE.source_ref_id],
        ),
        conversation=ConversationSummary(
            tutoring_session_id="tutoring_001",
            turn_count=1,
            latest_message_summary="这一节有点难",
        ),
        feedback_summary="学习者表示当前讲解偏难",
        quick_tag=FeedbackIntent.TOO_HARD,
        rating=2,
    )
    prepare_input = PrepareTaskInput(task_id=context.task_id, request=request)
    prepare_output = PrepareTaskOutput(
        task_id=context.task_id, context=context, next_node="interpret_feedback"
    )
    tutoring_input = InterpretFeedbackInput(
        task_id=context.task_id,
        context=context,
        profile=PROFILE,
        feedback=feedback,
    )
    evidence = EvidenceRef(
        evidence_id="evidence_feedback_1",
        evidence_type=EvidenceType.QUICK_FEEDBACK,
        summary="单次 too_hard 快捷反馈",
        knowledge_id="AIAPP-K029",
        confidence=0.3,
    )
    tutoring_output = InterpretFeedbackOutput(
        task_id=context.task_id,
        feedback_intent=FeedbackIntent.TOO_HARD,
        recommended_action=RecommendedAction.ASK_FOLLOW_UP,
        reply="请说明是检索过程还是来源引用不易理解。",
        evidence=[evidence],
        needs_generation=False,
        decision_reason="单次主观反馈证据不足",
    )
    analyze_input = AnalyzeProfileInput(
        task_id=context.task_id,
        context=context,
        current_profile=PROFILE,
        feedback_evidence=[evidence],
        recommended_action=RecommendedAction.ASK_FOLLOW_UP,
    )
    analyze_output = AnalyzeProfileOutput(
        task_id=context.task_id,
        profile=PROFILE,
        profile_update_required=False,
        evidence_refs=[evidence],
        confidence=0.3,
        decision_reason="证据不足，保留原画像",
        affected_scope=AffectedScope(),
        retrieval_plan=PLAN,
        needs_generation=False,
    )
    finalize_input = FinalizeTaskInput(
        task_id=context.task_id,
        context=context,
        revision_count=0,
        tutoring_result=tutoring_output,
    )
    finalize_output = FinalizeTaskOutput(
        task_id=context.task_id,
        decision=TaskDecision.NO_CHANGE,
        revision_count=0,
        decision_reason="证据不足，仅继续追问",
    )
    return {
        "prepare_task": {"input": prepare_input, "output": prepare_output},
        "interpret_feedback": {"input": tutoring_input, "output": tutoring_output},
        "analyze_profile": {"input": analyze_input, "output": analyze_output},
        "finalize_task": {"input": finalize_input, "output": finalize_output},
    }


def dump_example(value):
    if isinstance(value, dict):
        return {key: dump_example(item) for key, item in value.items()}
    if isinstance(value, list):
        return [dump_example(item) for item in value]
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value
