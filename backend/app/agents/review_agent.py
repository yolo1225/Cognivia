"""V6 review Agent with evidence-aware competition-quality metrics."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from threading import BoundedSemaphore, RLock
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.agents.contracts import (
    ArbitrationResult,
    EvidenceVerdict,
    FactCheck,
    GeneratedResourceArtifact,
    GradedQuizContent,
    LectureContent,
    ModelReview,
    PracticeGuideContent,
    GenerationPackageQuality,
    ResourceQualityMetrics,
    ReviewCriterionScores,
    ReviewDecision,
    ReviewIssue,
    ReviewIssueCode,
    ReviewReport,
    ReviewResourceInput,
    ReviewResourceOutput,
    ResourceType,
    RetrieveKnowledgeInput,
    RetrievedChunk,
    RetrievalPurpose,
)
from app.agents.domain_evidence_policy import (
    EvidenceCapability,
    get_domain_evidence_policy,
)
from app.agents.knowledge_coverage_policy import primary_owner_by_knowledge
from app.agents.observability import record_model_call
from app.agents.prompt_budget import bounded_text, estimate_tokens
from app.agents.retrieval_agent import KnowledgeRetrievalAgent
from app.core.config import settings
from app.services.llm_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelOutputTruncatedError,
    ModelResponseError,
    OpenAICompatibleGateway,
    gateway,
)


REVIEW_AGENT_NAME = "review_validation_agent_v3"
REVIEW_RULE_VERSION = "quality-v6-20260818"


def build_review_resource_output(
    *,
    task_id: str,
    reports: list[ReviewReport],
    expected_resource_types: list[ResourceType] | None = None,
    required_knowledge_ids: list[str],
    revision_count: int,
) -> ReviewResourceOutput:
    """Build package metrics from the final merged set of resource reports."""
    package_required = set(required_knowledge_ids)
    primary_owners = primary_owner_by_knowledge(
        required_knowledge_ids,
        {report.resource_type: report.target_knowledge_ids for report in reports},
    )
    package_covered = {
        knowledge_id
        for report in reports
        for knowledge_id in report.covered_knowledge_ids
        if primary_owners.get(knowledge_id) is report.resource_type
    } & package_required
    evaluated_count = sum(report.quality_metrics.evaluated_claim_count for report in reports)
    contradicted_count = sum(
        report.quality_metrics.contradicted_claim_count for report in reports
    )
    evidence_insufficient_count = sum(
        report.quality_metrics.evidence_insufficient_claim_count for report in reports
    )
    unresolved_count = sum(
        report.quality_metrics.unresolved_claim_count for report in reports
    )
    claim_count = evaluated_count
    hallucinated_count = sum(
        report.quality_metrics.hallucinated_claim_count for report in reports
    )
    # Competition coverage is package-wide and each target has one teaching
    # owner. Quiz assessment overlap neither expands nor backfills coverage.
    target_count = len(package_required)
    covered_count = len(package_covered)
    difficulty_denominator = sum(
        max(1, report.quality_metrics.verifiable_claim_count) for report in reports
    )
    difficulty_weight = sum(
        report.quality_metrics.difficulty_match_score
        * max(1, report.quality_metrics.verifiable_claim_count)
        for report in reports
    )
    hallucination_rate = (
        0.0 if claim_count == 0 else 100.0 * hallucinated_count / claim_count
    )
    difficulty_score = difficulty_weight / max(1, difficulty_denominator)
    core_coverage = 0.0 if target_count == 0 else 100.0 * covered_count / target_count
    expected_types = expected_resource_types or [report.resource_type for report in reports]
    report_types = [report.resource_type for report in reports]
    reports_complete = (
        bool(expected_types)
        and len(expected_types) == len(set(expected_types))
        and len(report_types) == len(set(report_types))
        and set(report_types) == set(expected_types)
    )
    metric_passed = (
        evaluated_count > 0
        and evidence_insufficient_count == 0
        and unresolved_count == 0
        and hallucination_rate < 5
        and difficulty_score >= 85
        and core_coverage >= 90
    )
    package_quality = GenerationPackageQuality(
        evaluated_claim_count=evaluated_count,
        contradicted_claim_count=contradicted_count,
        evidence_insufficient_claim_count=evidence_insufficient_count,
        unresolved_claim_count=unresolved_count,
        verifiable_claim_count=claim_count,
        hallucinated_claim_count=hallucinated_count,
        hallucination_rate=round(hallucination_rate, 2),
        difficulty_match_score=round(difficulty_score, 2),
        covered_core_knowledge_count=covered_count,
        target_core_knowledge_count=target_count,
        core_knowledge_coverage=round(core_coverage, 2),
        passed=metric_passed,
        revision_count=revision_count,
    )
    compatibility_coverage = 100.0 * len(package_covered) / max(1, len(package_required))
    return ReviewResourceOutput(
        task_id=task_id,
        reports=reports,
        package_required_knowledge_ids=sorted(package_required),
        package_covered_knowledge_ids=sorted(package_covered),
        package_missing_knowledge_ids=sorted(package_required - package_covered),
        package_coverage_score=round(compatibility_coverage, 2),
        package_passed=(
            reports_complete
            and all(report.quality_metrics.passed for report in reports)
            and package_quality.passed
        ),
        package_quality=package_quality,
    )
SYSTEM_PROMPT = (
    "你是审核校验智能体。你必须逐条审核输入 canonical_claims，原样返回每个 claim_id，"
    "不得新增、遗漏、合并或改写事实。verdict 只能是 supported、contradicted、"
    "evidence_insufficient：证据明确支持才是 supported，证据明确反驳才是 contradicted，"
    "证据没有提到、被截断或不足时必须是 evidence_insufficient。事实与来源结论只能引用"
    "输入 evidence 中的 source_ref_id。只返回 output_schema 要求的最小 JSON，不要重复"
    "claim 文本、证据正文、理由、评分、问题列表或任何未要求字段。"
    "即使某个结论符合通用常识或技术上看似合理，只要输入证据没有直接提及其关键行为、"
    "版本、参数、输出或错误语义，就必须返回 evidence_insufficient，不得使用模型自身知识补全。"
)
PRIMARY_SYSTEM_PROMPT = SYSTEM_PROMPT + (
    "你的职责是领域事实与来源审核：优先核验事实、代码、操作步骤、预期结果、题目答案"
    "及其引用是否被证据直接支持。"
)
SECONDARY_SYSTEM_PROMPT = SYSTEM_PROMPT + (
    "你的职责是对抗验证与教学适配审核：独立抽查关键事实和来源，并重点识别难度不匹配、"
    "目标知识遗漏、题目歧义及三类资源间的不一致。不得沿用主审核结论。"
)


def _role_system_prompt(role: "ReviewRole") -> str:
    return PRIMARY_SYSTEM_PROMPT if role == "primary_review_model" else SECONDARY_SYSTEM_PROMPT
PASS_THRESHOLD = 85.0
REVIEW_INPUT_TOKEN_BUDGET = 5_000
REVIEW_BATCH_TARGET_INPUT_TOKENS = 4_200
REVIEW_BATCH_OUTPUT_TOKEN_TARGET = 1_400
REVIEW_BATCH_MAX_CLAIMS = 12
MIN_EVIDENCE_CONTENT_CHARS = 256
MIN_SUPPLEMENTAL_EVIDENCE_CONTENT_CHARS = 96
MAX_SUPPLEMENTAL_EVIDENCE_PER_BATCH = 4
MAX_CLAIM_CHARS = 1_900
_REVIEW_MODEL_SEMAPHORE = BoundedSemaphore(settings.review_model_concurrency)
_SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])\s*")
_CLAUSE_RE = re.compile(r"(?<=[，,：:])\s*")
_LOGGER = logging.getLogger(__name__)
_PROVENANCE_META_RE = re.compile(
    r"(?:所有|全部|以上|本(?:讲义|资源|内容)).{0,24}"
    r"(?:均|都|严格)?(?:源自|来自|基于|依据).{0,24}"
    r"(?:官方|所列|所提供|输入|引用|检索)"
    r"(?:文档|资料|材料|来源|证据|内容|知识片段)|"
    r"(?:未|没有)(?:引入|使用).{0,16}"
    r"(?:外部常识|外部知识|工具能力|额外推断|自行推断)|"
    r"(?:引用|来源).{0,12}(?:完整|齐全|全部覆盖|均可追溯)"
)
_ORGANIZATIONAL_ONLY_RE = re.compile(
    r"^(?:本节|本章|下面|以下|接下来)(?:将|会|带你|帮助你|我们将).{0,80}"
    r"(?:介绍|讲解|学习|了解|掌握|回顾|总结).{0,40}$"
)
_PEDAGOGICAL_ACTION_RE = re.compile(
    r"^(?:(?:学习者|学员|你)(?:应|需|需要|可以|可)?|请)?(?:"
    r"(?:(?:在|于).{1,40}(?:中|内|旁|上)(?:请)?)?"
    r"(?:阅读|浏览|观察|记录|保存|提交|提供|整理|梳理|比较|对比|讨论|思考|分析|检查|核对|"
    r"完成|尝试|练习|复述|列出|总结|标注|注明|选择|填写|形成|准备|回顾|识别|描述|说明|映射|"
    r"能够?复述|能够?列出|能够?比较|能够?完成).{0,200}|"
    r"(?:将|把)(?!会|在).{1,120}(?:映射|记录|整理|核对|标注|描述|说明|明确).{0,160}"
    r")$"
)
_ENVIRONMENT_PRECONDITION_RE = re.compile(
    r"^(?:如|若|如果|需要时|练习前|开始前|请)?(?:可|可以|能够|能)?"
    r"(?:访问|查阅|打开|准备|使用).{0,120}(?:文档|资料|材料|环境|仓库|账号|凭证)"
    r"(?:(?:用于|以便|以)\S{0,60}(?:核对|查阅|记录|练习|学习|确认)\S{0,40})?$"
)
_CONDITIONAL_OR_SAFETY_ACTION_RE = re.compile(
    r"^(?:如|若|如果|需要时|练习前|开始前|请|建议)?(?:先|仅|务必)?"
    r"(?:确认|确保|避免|不要|勿|不得暴露|保护|记录|核对|检查).{0,160}$"
)
_CONDITIONAL_PEDAGOGICAL_ACTION_RE = re.compile(
    r"^(?:如|若|如果).{0,100}[，,](?:请)?"
    r"(?:说明|解释|记录|标注|描述|选择|填写|整理|比较|核对|检查).{0,120}$"
)
_FACTUAL_ASSERTION_RE = re.compile(
    r"(?:将会|将在|会自动|自动|固定|默认|必须|只能|不能|支持|不支持|兼容|不兼容|"
    r"返回|导致|触发|包含|等于|意味着|保证|始终|无需|要求安装|需要安装|"
    r"明确|规定|指出|列为|作为|属于|共同|核心|应为|应当|不应|需要|用于|决定|"
    r"\b\d+(?:\.\d+)+(?:\+|以上|以下)?\b|\d+(?:\.\d+)?\s*(?:秒|毫秒|次|%|mb|gb)\b|"
    r"\b(?:get|post|put|patch|delete)\b.{0,24}\b(?:2\d\d|4\d\d|5\d\d)\b)",
    re.I,
)
_QUIZ_INDEPENDENT_PREMISE_RE = re.compile(
    r"(?:将会|将在|会自动|自动|固定|默认|必须|只能|不能|支持|不支持|兼容|不兼容|"
    r"返回|导致|触发|包含|等于|意味着|保证|始终|无需|要求安装|需要安装|"
    r"规定|指出|列为|作为|属于|共同|核心|应为|应当|不应|"
    r"\b\d+(?:\.\d+)+(?:\+|以上|以下)?\b|\d+(?:\.\d+)?\s*(?:秒|毫秒|次|%|mb|gb)\b|"
    r"\b(?:get|post|put|patch|delete)\b.{0,24}\b(?:2\d\d|4\d\d|5\d\d)\b)",
    re.I,
)
_QUIZ_CONTEXT_ONLY_RE = re.compile(
    r"^(?:当|若|如果|假如|在|面向|针对|对于).{1,180}(?:时|情况下|场景中|过程中|期间)$"
)
_EMBEDDED_TECHNICAL_ASSERTION_RE = re.compile(
    r"(?:将会|将在|会自动|固定|默认|必须|只能|不能|支持|不支持|兼容|不兼容|"
    r"返回|导致|触发|等于|意味着|保证|始终|无需|要求安装|需要安装|"
    r"应为|应当|不应|决定|"
    r"(?:接口|api|响应|命令|模型|系统|工具|函数|服务).{0,40}(?:包含|属于|共同|核心)|"
    r"\b\d+(?:\.\d+)+(?:\+|以上|以下)?\b|\d+(?:\.\d+)?\s*(?:秒|毫秒|次|%|mb|gb)\b|"
    r"\b(?:get|post|put|patch|delete)\b.{0,24}\b(?:2\d\d|4\d\d|5\d\d)\b)",
    re.I,
)
_SAFE_EXPECTED_ACTION_RE = re.compile(
    r"^(?:记录|整理|比较|核对|形成|完成|提交|标注).{0,120}"
    r"(?:记录|清单|笔记|差异|材料|描述|结果|练习|表格|核对|对照|确认).{0,40}$"
)
_ACCEPTANCE_DELIVERABLE_RE = re.compile(
    r"^(?:(?:完成|提交|形成)(?:一份)?\s*)?"
    r"(?:学习记录|练习记录|检查表|自查清单|清单|报告|表格|提交内容|错误响应分析)"
    r".{0,120}(?:包含|记录|列出|标注|覆盖|附有).{0,120}$"
)
_PLACEHOLDER_TEXT = {"待补充", "暂无", "无", "todo", "tbd", "示例内容", "模板内容"}
_SAFE_REVISION_INSTRUCTIONS = {
    "阅读引用材料，整理其中明确描述的处理流程",
    "阅读并梳理引用材料中明确描述的处理流程",
}


@dataclass(frozen=True, slots=True)
class AtomicClaim:
    claim_id: str
    field_path: str
    claim: str
    knowledge_ids: tuple[str, ...]
    source_ref_ids: tuple[str, ...]

    def as_payload(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "field_path": self.field_path,
            "claim": self.claim,
            "knowledge_ids": list(self.knowledge_ids),
            "source_ref_ids": list(self.source_ref_ids),
        }


@dataclass(frozen=True, slots=True)
class ReviewBatch:
    batch_id: str
    claim_ids: tuple[str, ...]


class _CompactFactCheck(BaseModel):
    """Provider-facing minimum; V3 FactCheck fields are restored locally."""

    claim_id: str = Field(min_length=8, max_length=64)
    verdict: EvidenceVerdict
    source_ref_ids: list[str] = Field(default_factory=list, max_length=20)


class _CompactModelReview(BaseModel):
    fact_checks: list[_CompactFactCheck] = Field(min_length=1, max_length=100)


class ReviewBatchCache:
    """Payload-safe cache for completed model-channel review batches."""

    SNAPSHOT_VERSION = 1

    def __init__(self, seed: dict[str, Any] | None = None) -> None:
        self._lock = RLock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._hits = 0
        self._writes = 0
        self._persist_callback: Callable[[dict[str, Any]], None] | None = None
        if isinstance(seed, dict) and seed.get("version") == self.SNAPSHOT_VERSION:
            for entry in seed.get("entries", []):
                if isinstance(entry, dict) and isinstance(entry.get("cache_key"), str):
                    self._entries[entry["cache_key"]] = dict(entry)

    @staticmethod
    def _key(
        *,
        resource_type: ResourceType,
        claim_set_hash: str,
        evidence_packet_hash: str,
        role: ReviewRole,
        requested_model: str | None,
        actual_model: str | None,
        recheck: bool,
        batch_id: str,
    ) -> str:
        payload = {
            "rule": REVIEW_RULE_VERSION,
            "resource_type": resource_type.value,
            "claim_set_hash": claim_set_hash,
            "evidence_packet_hash": evidence_packet_hash,
            "role": role,
            "requested_model": requested_model or "",
            "actual_model": actual_model or "",
            "recheck": recheck,
            "batch_id": batch_id,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def get(
        self,
        *,
        resource_type: ResourceType,
        claim_set_hash: str,
        evidence_packet_hash: str,
        role: ReviewRole,
        requested_model: str | None,
        allowed_actual_models: Iterable[str | None],
        recheck: bool,
        batch_id: str,
        expected_claim_ids: tuple[str, ...],
    ) -> tuple[_CompactModelReview, str] | None:
        with self._lock:
            for actual_model in allowed_actual_models:
                key = self._key(
                    resource_type=resource_type,
                    claim_set_hash=claim_set_hash,
                    evidence_packet_hash=evidence_packet_hash,
                    role=role,
                    requested_model=requested_model,
                    actual_model=actual_model,
                    recheck=recheck,
                    batch_id=batch_id,
                )
                entry = self._entries.get(key)
                if entry is None:
                    continue
                compact = _CompactModelReview.model_validate(
                    {"fact_checks": entry.get("fact_checks", [])}
                )
                if tuple(item.claim_id for item in compact.fact_checks) != expected_claim_ids:
                    continue
                self._hits += 1
                return compact, str(entry.get("actual_model") or actual_model or "")
        return None

    def put(
        self,
        *,
        resource_type: ResourceType,
        claim_set_hash: str,
        evidence_packet_hash: str,
        role: ReviewRole,
        requested_model: str | None,
        actual_model: str | None,
        recheck: bool,
        batch_id: str,
        review: ModelReview,
    ) -> None:
        compact = _CompactModelReview(
            fact_checks=[
                _CompactFactCheck(
                    claim_id=item.claim_id or "",
                    verdict=item.verdict or EvidenceVerdict.EVIDENCE_INSUFFICIENT,
                    source_ref_ids=item.source_ref_ids,
                )
                for item in review.fact_checks
            ]
        )
        key = self._key(
            resource_type=resource_type,
            claim_set_hash=claim_set_hash,
            evidence_packet_hash=evidence_packet_hash,
            role=role,
            requested_model=requested_model,
            actual_model=actual_model,
            recheck=recheck,
            batch_id=batch_id,
        )
        entry = {
            "cache_key": key,
            "rule_version": REVIEW_RULE_VERSION,
            "resource_type": resource_type.value,
            "claim_set_hash": claim_set_hash,
            "evidence_packet_hash": evidence_packet_hash,
            "role": role,
            "requested_model": requested_model,
            "actual_model": actual_model,
            "recheck": recheck,
            "batch_id": batch_id,
            "fact_checks": compact.model_dump(mode="json")["fact_checks"],
        }
        with self._lock:
            self._entries[key] = entry
            self._writes += 1

    def set_persist_callback(self, callback: Callable[[dict[str, Any]], None] | None) -> None:
        with self._lock:
            self._persist_callback = callback

    def persist(self) -> None:
        with self._lock:
            callback = self._persist_callback
            snapshot = self.snapshot()
        if callback is not None:
            callback(snapshot)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            entries = sorted(
                (dict(item) for item in self._entries.values()),
                key=lambda item: item["cache_key"],
            )
            return {
                "version": self.SNAPSHOT_VERSION,
                "entries": entries,
                "entry_count": len(entries),
                "hits": self._hits,
                "writes": self._writes,
            }


def _difficulty_rubric(resource_type: ResourceType) -> list[str]:
    common = ["术语密度、前置知识和推理跨度应匹配 target_difficulty"]
    specific = {
        ResourceType.LECTURE: "讲义的解释层次、示例复杂度和概念跨度应逐步递进",
        ResourceType.PRACTICE_GUIDE: "实操步骤、环境要求和排错难度应可由目标学习者完成",
        ResourceType.GRADED_QUIZ: "测验应含基础、提升、挑战层级，题目难度与标注一致",
    }
    return [*common, specific[resource_type]]


class ReviewError(RuntimeError):
    """Controlled error raised at the V3 review boundary."""


ReviewRole = Literal["primary_review_model", "secondary_review_model"]

_REVIEW_ERROR_PRIORITY = {
    "review_model_configuration_error": 0,
    "review_model_non_retryable": 0,
    "review_task_timeout": 1,
    "review_payload_unrecoverable": 2,
    "review_structured_output_invalid": 3,
    "review_claim_set_mismatch": 3,
    "review_output_truncated": 4,
    "review_model_call_failed": 5,
}


def _primary_review_error(errors: Iterable[Exception]) -> Exception:
    return min(
        errors,
        key=lambda exc: _REVIEW_ERROR_PRIORITY.get(str(exc), 99),
    )


class ReviewChannel(Protocol):
    def review(
        self,
        *,
        role: ReviewRole,
        model: str | None,
        resource: GeneratedResourceArtifact,
        request: ReviewResourceInput,
        deterministic_review: ModelReview,
        recheck: bool,
        timeout_seconds: float | None = None,
    ) -> ModelReview: ...


class ReviewEvidenceRetriever(Protocol):
    def retrieve(
        self,
        *,
        query_terms: list[str],
        request: ReviewResourceInput,
        resource: GeneratedResourceArtifact,
    ) -> list[RetrievedChunk]: ...


class SuppliedEvidenceRetriever:
    """Re-rank supplied evidence without pretending that review owns retrieval."""

    def retrieve(
        self,
        *,
        query_terms: list[str],
        request: ReviewResourceInput,
        resource: GeneratedResourceArtifact,
    ) -> list[RetrievedChunk]:
        query_tokens = _tokenize(" ".join(query_terms))
        cited_ids = {source.source_ref_id for source in resource.source_refs}

        def rank(chunk: RetrievedChunk) -> tuple[bool, int, float]:
            tokens = _tokenize(f"{chunk.name} {chunk.content}")
            return (
                chunk.source.source_ref_id in cited_ids,
                len(query_tokens & tokens),
                chunk.similarity,
            )

        return sorted(request.evidence, key=rank, reverse=True)


class TaskScopedArbitrationRetriever:
    """Delegate source verification to the Knowledge Retrieval Agent."""

    def __init__(
        self,
        *,
        retrieval_agent: KnowledgeRetrievalAgent,
        original_request: RetrieveKnowledgeInput,
    ) -> None:
        self._retrieval_agent = retrieval_agent
        self._original_request = RetrieveKnowledgeInput.model_validate(
            original_request.model_dump(mode="python")
        )

    def retrieve(
        self,
        *,
        query_terms: list[str],
        request: ReviewResourceInput,
        resource: GeneratedResourceArtifact,
    ) -> list[RetrievedChunk]:
        original = self._original_request
        if request.task_id != original.task_id or request.context != original.context:
            raise ReviewError("arbitration_retrieval_task_context_mismatch")
        evidence_by_source = {chunk.source.source_ref_id: chunk for chunk in request.evidence}
        cited_source_ids = [source.source_ref_id for source in resource.source_refs]
        if any(source_id not in evidence_by_source for source_id in cited_source_ids):
            raise ReviewError("arbitration_retrieval_unknown_cited_source")
        cited_knowledge_ids = _ordered_unique(
            evidence_by_source[source_id].knowledge_id for source_id in cited_source_ids
        )
        plan = original.retrieval_plan.model_copy(
            update={
                "priority_knowledge_ids": _ordered_unique(
                    [*cited_knowledge_ids, *original.retrieval_plan.priority_knowledge_ids]
                ),
                "query_terms": _ordered_unique(
                    [*query_terms, *original.retrieval_plan.query_terms]
                )[:30],
                "n_results": min(
                    12,
                    max(original.retrieval_plan.n_results, len(cited_knowledge_ids) + 1),
                ),
            }
        )
        refreshed = self._retrieval_agent.execute(
            RetrieveKnowledgeInput(
                task_id=original.task_id,
                context=original.context,
                profile=original.profile,
                retrieval_plan=plan,
                revision_plan=original.revision_plan,
                purpose=RetrievalPurpose.SOURCE_VERIFICATION,
            )
        )
        # The original cited evidence remains in ReviewResourceInput and is merged
        # with this result later. Source verification may legitimately return only
        # new, higher-ranked chunks, so it must not require every original chunk to
        # appear again in a bounded retrieval window.
        return refreshed.chunks


def _normalize_claim_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _claim_id(resource_type: ResourceType, field_path: str, claim: str) -> str:
    raw = f"{resource_type.value}\n{field_path}\n{_normalize_claim_text(claim)}"
    return "clm_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _claim_set_hash(claims: list[AtomicClaim]) -> str:
    raw = "\n".join(claim.claim_id for claim in claims)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _split_factual_text(value: str, *, preserve: bool = False) -> list[str]:
    normalized = value.strip()
    if not normalized:
        return []

    initial = [normalized] if preserve else _SENTENCE_RE.split(normalized)
    parts: list[str] = []
    for item in initial:
        item = _normalize_claim_text(item)
        if not item:
            continue
        clauses = [item] if len(item) <= MAX_CLAIM_CHARS else _CLAUSE_RE.split(item)
        for clause in clauses:
            clause = _normalize_claim_text(clause)
            if not clause:
                continue
            parts.extend(
                clause[offset : offset + MAX_CLAIM_CHARS]
                for offset in range(0, len(clause), MAX_CLAIM_CHARS)
            )
    return parts


def _project_claim_source_ids(
    text: str,
    source_ids: tuple[str, ...],
    evidence_by_source: dict[str, RetrievedChunk],
) -> tuple[str, ...]:
    """Select only directly relevant declared sources for one atomic claim."""
    if len(source_ids) <= 1:
        return source_ids
    query_tokens = _tokenize(text)
    ranked: list[tuple[int, float, str]] = []
    for source_id in source_ids:
        chunk = evidence_by_source.get(source_id)
        if chunk is None:
            continue
        overlap = len(query_tokens & _tokenize(f"{chunk.name} {chunk.content}"))
        ranked.append((overlap, chunk.similarity, source_id))
    positive = [item for item in ranked if item[0] > 0]
    if not positive:
        return ()
    positive.sort(reverse=True)
    best_overlap = positive[0][0]
    return tuple(item[2] for item in positive if item[0] == best_overlap)[:3]


def _claim_exclusion_category(field_group: str, text: str) -> str | None:
    """Conservatively exclude only non-factual prose in selected container fields."""
    normalized = _normalize_claim_text(text)
    compact = re.sub(r"\s+", "", normalized).lower().strip("。！？!?;；")
    sentence = normalized.strip("。！？!?;；")
    if _PROVENANCE_META_RE.fullmatch(sentence):
        return "provenance_meta"
    if field_group == "summary":
        if _ORGANIZATIONAL_ONLY_RE.fullmatch(sentence):
            return "organizational"
    if field_group in {"environment_requirement", "acceptance_criterion"}:
        if compact in _PLACEHOLDER_TEXT:
            return "placeholder"
        if _ORGANIZATIONAL_ONLY_RE.fullmatch(sentence):
            return "organizational"
    if field_group == "acceptance_criterion":
        if _ACCEPTANCE_DELIVERABLE_RE.fullmatch(sentence):
            return "pedagogical_deliverable"
    if field_group == "environment_requirement":
        if _ENVIRONMENT_PRECONDITION_RE.fullmatch(sentence) and not _FACTUAL_ASSERTION_RE.search(
            sentence
        ):
            return "environment_precondition"
        if _CONDITIONAL_OR_SAFETY_ACTION_RE.fullmatch(
            sentence
        ) and not _FACTUAL_ASSERTION_RE.search(sentence):
            return "safety_action"
    if field_group in {
        "instruction",
        "environment_requirement",
        "acceptance_criterion",
    }:
        if (
            field_group == "instruction"
            and _CONDITIONAL_PEDAGOGICAL_ACTION_RE.fullmatch(sentence)
            and not _EMBEDDED_TECHNICAL_ASSERTION_RE.search(sentence)
        ):
            return "pedagogical_action"
        if field_group == "instruction" and sentence in _SAFE_REVISION_INSTRUCTIONS:
            return "pedagogical_action"
        if _PEDAGOGICAL_ACTION_RE.fullmatch(
            sentence
        ) and not _EMBEDDED_TECHNICAL_ASSERTION_RE.search(sentence):
            return "pedagogical_action"
    if field_group == "expected_result":
        if _SAFE_EXPECTED_ACTION_RE.fullmatch(sentence) and not _FACTUAL_ASSERTION_RE.search(
            sentence
        ):
            return "pedagogical_action"
    if field_group == "quiz_prompt":
        if re.search(r"[？?]", normalized):
            # The answer and explanation are reviewed separately, so the
            # interrogative itself is not an additional factual claim.  Keep
            # only a genuinely independent premise that precedes the question
            # (for example: "the system retries three times by default, which
            # option is correct?").  Keywords inside the unknown slot, such as
            # "which items should not...", do not turn the question into an
            # assertion.
            clauses = [
                item.strip()
                for item in re.split(r"[,，;；:：]", sentence)
                if item.strip()
            ]
            independent_premises = clauses[:-1]
            if not any(
                _QUIZ_INDEPENDENT_PREMISE_RE.search(item)
                and not _QUIZ_CONTEXT_ONLY_RE.fullmatch(item)
                for item in independent_premises
            ):
                return "pedagogical_question"
    return None


def extract_atomic_claims(
    resource: GeneratedResourceArtifact, request: ReviewResourceInput
) -> list[AtomicClaim]:
    """Create one stable claim set shared by both review channels."""
    evidence_by_source = {chunk.source.source_ref_id: chunk for chunk in request.evidence}
    all_sources = tuple(source.source_ref_id for source in resource.source_refs)
    claims: list[AtomicClaim] = []
    excluded: dict[str, list[str]] = {}

    def add(
        field_path: str,
        text: str,
        source_ids: Iterable[str],
        *,
        preserve: bool = False,
        prefix: str = "",
        filter_group: str | None = None,
    ) -> None:
        sources = tuple(_ordered_unique(source_ids))
        knowledge_ids = tuple(
            _ordered_unique(
                evidence_by_source[source_id].knowledge_id
                for source_id in sources
                if source_id in evidence_by_source
            )
        )
        parts = _split_factual_text(text, preserve=preserve)
        for index, part in enumerate(parts):
            path = field_path if preserve and len(parts) == 1 else f"{field_path}[{index}]"
            category = _claim_exclusion_category(filter_group or "factual", part)
            if category:
                excluded.setdefault(category, []).append(path)
                continue
            projected_sources = _project_claim_source_ids(part, sources, evidence_by_source)
            projected_knowledge_ids = tuple(
                _ordered_unique(
                    evidence_by_source[source_id].knowledge_id
                    for source_id in projected_sources
                    if source_id in evidence_by_source
                )
            )
            claim_text = f"{prefix}{part}" if prefix else part
            claims.append(
                AtomicClaim(
                    claim_id=_claim_id(resource.resource_type, path, claim_text),
                    field_path=path,
                    claim=claim_text,
                    knowledge_ids=projected_knowledge_ids or knowledge_ids,
                    source_ref_ids=projected_sources,
                )
            )

    content = resource.structured_content
    if isinstance(content, LectureContent):
        for index, block in enumerate(content.core_concepts):
            add(f"core_concepts[{index}].explanation", block.explanation, block.source_ref_ids)
            if block.example:
                add(f"core_concepts[{index}].example", block.example, block.source_ref_ids)
        for index, block in enumerate(content.misconceptions):
            combined = f"误区陈述：{block.misconception}；纠正：{block.correction}"
            add(
                f"misconceptions[{index}]",
                combined,
                block.source_ref_ids,
                preserve=True,
                prefix="请判断以下误区纠正是否准确：",
            )
        add("summary", content.summary, all_sources, filter_group="summary")
    elif isinstance(content, PracticeGuideContent):
        for index, requirement in enumerate(content.environment_requirements):
            add(
                f"environment_requirements[{index}]",
                requirement,
                all_sources,
                filter_group="environment_requirement",
            )
        for index, step in enumerate(content.steps):
            base = f"steps[{index}]"
            add(
                f"{base}.instruction",
                step.instruction,
                step.source_ref_ids,
                filter_group="instruction",
            )
            if step.code_or_command:
                add(
                    f"{base}.code_or_command",
                    step.code_or_command,
                    step.source_ref_ids,
                    preserve=True,
                    prefix="以下代码或命令应能完成该步骤：\n",
                )
            add(
                f"{base}.expected_result",
                step.expected_result,
                step.source_ref_ids,
                filter_group="expected_result",
            )
            if step.troubleshooting:
                add(f"{base}.troubleshooting", step.troubleshooting, step.source_ref_ids)
        for index, criterion in enumerate(content.acceptance_criteria):
            add(
                f"acceptance_criteria[{index}]",
                criterion,
                all_sources,
                filter_group="acceptance_criterion",
            )
    elif isinstance(content, GradedQuizContent):
        for index, question in enumerate(content.questions):
            add(
                f"questions[{index}].prompt",
                question.prompt,
                question.source_ref_ids,
                preserve=True,
                prefix="请判断该题题干中的事实前提是否准确：\n",
                filter_group="quiz_prompt",
            )
            add(
                f"questions[{index}].correct_answer",
                question.correct_answer,
                question.source_ref_ids,
                preserve=True,
                prefix=f"题目：{question.prompt}\n请判断该题正确答案是否准确：\n",
            )
            add(
                f"questions[{index}].explanation",
                question.explanation,
                question.source_ref_ids,
                preserve=True,
                prefix=(
                    f"题目：{question.prompt}\n正确答案：{question.correct_answer}\n"
                    "请判断该题解析是否准确：\n"
                ),
            )
    if not claims:
        raise ReviewError("review_claim_set_empty")
    _LOGGER.info(
        "review_claim_extraction task_id=%s resource_type=%s claim_count=%s "
        "excluded_counts=%s excluded_paths=%s",
        request.task_id,
        resource.resource_type.value,
        len(claims),
        {category: len(paths) for category, paths in excluded.items()},
        {category: paths[:20] for category, paths in excluded.items()},
    )
    return claims


def _structured_content_outline(
    resource: GeneratedResourceArtifact, claims: list[AtomicClaim]
) -> dict[str, object]:
    """Keep review-relevant structure without duplicating canonical claim prose."""

    content = resource.structured_content
    common: dict[str, object] = {
        "resource_type": resource.resource_type.value,
        "title": bounded_text(content.title, 160),
        "claim_field_paths": [claim.field_path for claim in claims],
    }
    field_paths = {claim.field_path for claim in claims}

    def includes(prefix: str) -> bool:
        return any(
            path == prefix or path.startswith(f"{prefix}.") or path.startswith(f"{prefix}[")
            for path in field_paths
        )

    if isinstance(content, LectureContent):
        common.update(
            {
                "learning_objective_count": len(content.learning_objectives),
                "prerequisite_count": len(content.prerequisite_knowledge),
                "core_concepts": [
                    {
                        "title": bounded_text(item.title, 120),
                        "source_ref_ids": item.source_ref_ids,
                        "has_example": bool(item.example),
                    }
                    for index, item in enumerate(content.core_concepts)
                    if includes(f"core_concepts[{index}]")
                ],
                "misconception_count": len(content.misconceptions),
            }
        )
    elif isinstance(content, PracticeGuideContent):
        common.update(
            {
                "learning_objective_count": len(content.learning_objectives),
                "environment_requirement_count": len(content.environment_requirements),
                "steps": [
                    {
                        "title": bounded_text(item.title, 120),
                        "source_ref_ids": item.source_ref_ids,
                        "has_command": bool(item.code_or_command),
                        "has_expected_result": bool(item.expected_result),
                        "has_troubleshooting": bool(item.troubleshooting),
                    }
                    for index, item in enumerate(content.steps)
                    if includes(f"steps[{index}]")
                ],
                "acceptance_criteria_count": len(content.acceptance_criteria),
            }
        )
    elif isinstance(content, GradedQuizContent):
        common.update(
            {
                "learning_objective_count": len(content.learning_objectives),
                "questions": [
                    {
                        "level": item.level,
                        "question_type": item.question_type,
                        "option_count": len(item.options),
                        "knowledge_ids": [item.knowledge_id],
                        "source_ref_ids": item.source_ref_ids,
                    }
                    for index, item in enumerate(content.questions)
                    if includes(f"questions[{index}]")
                ],
            }
        )
    return common


def _build_review_payload(
    *,
    role: ReviewRole,
    recheck: bool,
    resource: GeneratedResourceArtifact,
    request: ReviewResourceInput,
    claim_ids: set[str] | None = None,
    input_token_budget: int | None = None,
) -> tuple[dict[str, object], int, int]:
    """Build one claim-aligned payload and include supplemental recheck evidence."""
    claims = extract_atomic_claims(resource, request)
    if claim_ids is not None:
        claims = [claim for claim in claims if claim.claim_id in claim_ids]
        if not claims:
            raise ReviewError("review_claim_set_empty")
    cited_ids = {source_id for claim in claims for source_id in claim.source_ref_ids}
    claim_knowledge_ids = {knowledge_id for claim in claims for knowledge_id in claim.knowledge_ids}
    evidence = [
        item
        for item in request.evidence
        if item.source.source_ref_id in cited_ids
        or (recheck and item.knowledge_id in claim_knowledge_ids)
    ]
    evidence.sort(
        key=lambda item: (
            item.source.source_ref_id not in cited_ids,
            -item.similarity,
            item.chunk_id,
        )
    )
    if recheck:
        declared = [item for item in evidence if item.source.source_ref_id in cited_ids]
        supplemental = [item for item in evidence if item.source.source_ref_id not in cited_ids][
            :MAX_SUPPLEMENTAL_EVIDENCE_PER_BATCH
        ]
        evidence = [*declared, *supplemental]
    resource_payload = {
        "resource_type": resource.resource_type.value,
        # Canonical claims contain the complete factual prose. This outline
        # preserves the structured relationships needed by review without
        # sending the same text a second time. content_md remains excluded.
        "content_representation": "canonical_claims_with_structural_outline",
        "structured_content": _structured_content_outline(resource, claims),
        "difficulty": resource.difficulty,
        "source_refs": [
            source.model_dump(mode="json")
            for source in resource.source_refs
            if source.source_ref_id in cited_ids
        ],
    }
    claim_text = " ".join(claim.claim for claim in claims)

    def project_evidence(content: str, content_limit: int | None) -> str:
        if content_limit is None:
            return content
        segments = [segment.strip() for segment in _SENTENCE_RE.split(content) if segment.strip()]
        if not segments:
            return bounded_text(content, content_limit)
        query_tokens = _tokenize(claim_text)
        ranked = sorted(
            enumerate(segments),
            key=lambda item: (
                len(query_tokens & _tokenize(item[1])),
                -item[0],
            ),
            reverse=True,
        )
        selected: list[tuple[int, str]] = []
        used = 0
        for index, segment in ranked:
            if len(segment) > content_limit:
                segment = bounded_text(segment, content_limit)
            separator = 1 if selected else 0
            if used + separator + len(segment) > content_limit:
                continue
            selected.append((index, segment))
            used += separator + len(segment)
            if used >= content_limit:
                break
        if not selected:
            return bounded_text(ranked[0][1], content_limit)
        return " ".join(segment for _, segment in sorted(selected))

    def assemble(content_limit: int | None) -> dict[str, object]:
        compact_evidence: list[dict[str, object]] = []
        for item in evidence:
            is_declared = item.source.source_ref_id in cited_ids
            item_limit = content_limit
            if content_limit is not None and not is_declared:
                item_limit = min(content_limit, MIN_SUPPLEMENTAL_EVIDENCE_CONTENT_CHARS)
            content = project_evidence(item.content, item_limit)
            compact_evidence.append(
                {
                    "chunk_id": item.chunk_id,
                    "knowledge_id": item.knowledge_id,
                    "name": item.name,
                    "content": content,
                    "content_checksum": item.content_checksum,
                    "source_locator": item.source_locator,
                    "evidence_role": ("declared" if is_declared else "supplemental"),
                    "evidence_truncated": content != item.content,
                    "source": item.source.model_dump(mode="json"),
                }
            )
        return {
            "review_role": role,
            "recheck": recheck,
            "claim_set_hash": _claim_set_hash(claims),
            "canonical_claims": [claim.as_payload() for claim in claims],
            "resource": resource_payload,
            "evidence": compact_evidence,
            "evidence_rules": [
                "必须逐条返回 canonical_claims 中全部且仅有的 claim_id",
                "证据没有提及不等于反驳，应返回 evidence_insufficient",
                "evidence_truncated=true 时缺失部分不能作为 contradicted 的依据",
                "supplemental 证据可用于判断事实，但不能替代资源自身的声明引用",
            ],
            "output_schema": _CompactModelReview.model_json_schema(),
        }

    def token_count(payload: dict[str, object]) -> int:
        return estimate_tokens({"system_prompt": _role_system_prompt(role), "payload": payload})

    budget = input_token_budget or settings.review_batch_hard_input_tokens
    full_payload = assemble(None)
    full_tokens = token_count(full_payload)
    if full_tokens <= budget:
        return full_payload, full_tokens, 0
    minimum_payload = assemble(MIN_EVIDENCE_CONTENT_CHARS)
    minimum_tokens = token_count(minimum_payload)
    if minimum_tokens > budget:
        evidence_roles = [item["evidence_role"] for item in minimum_payload["evidence"]]
        if budget >= settings.review_batch_hard_input_tokens:
            logging.getLogger(__name__).warning(
                "review_payload_over_budget task_id=%s role=%s resource_type=%s "
                "claim_count=%s minimum_tokens=%s budget=%s declared_evidence=%s "
                "supplemental_evidence=%s",
                request.task_id,
                role,
                resource.resource_type.value,
                len(claims),
                minimum_tokens,
                budget,
                evidence_roles.count("declared"),
                evidence_roles.count("supplemental"),
            )
        raise ReviewError("review_payload_unrecoverable")
    low = MIN_EVIDENCE_CONTENT_CHARS
    high = max((len(item.content) for item in evidence), default=low)
    best_payload, best_tokens = minimum_payload, minimum_tokens
    while low <= high:
        middle = (low + high) // 2
        candidate = assemble(middle)
        candidate_tokens = token_count(candidate)
        if candidate_tokens <= budget:
            best_payload, best_tokens = candidate, candidate_tokens
            low = middle + 1
        else:
            high = middle - 1
    truncated_count = sum(1 for item in best_payload["evidence"] if item["evidence_truncated"])
    return best_payload, best_tokens, truncated_count


def _evidence_packet_hash(payload: dict[str, object]) -> str:
    packet: list[dict[str, object]] = []
    for item in payload.get("evidence", []):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "")
        packet.append(
            {
                "source_ref_id": (item.get("source") or {}).get("source_ref_id")
                if isinstance(item.get("source"), dict)
                else None,
                "chunk_id": item.get("chunk_id"),
                "knowledge_id": item.get("knowledge_id"),
                "content_checksum": item.get("content_checksum"),
                "projected_content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "name_hash": hashlib.sha256(
                    str(item.get("name") or "").encode("utf-8")
                ).hexdigest(),
                "source_locator": item.get("source_locator"),
                "evidence_role": item.get("evidence_role"),
                "evidence_truncated": item.get("evidence_truncated"),
            }
        )
    return hashlib.sha256(
        json.dumps(packet, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _estimate_compact_output_tokens(claim_count: int) -> int:
    return 80 + claim_count * 55


def _plan_review_batches(
    *,
    resource: GeneratedResourceArtifact,
    request: ReviewResourceInput,
    recheck: bool,
    claim_ids: set[str] | None = None,
) -> list[ReviewBatch]:
    """Greedily plan stable canonical-order batches under input/output budgets."""

    claims = extract_atomic_claims(resource, request)
    if claim_ids is not None:
        claims = [claim for claim in claims if claim.claim_id in claim_ids]
    if not claims:
        raise ReviewError("review_claim_set_empty")
    target = settings.review_batch_target_input_tokens
    max_claims = settings.review_batch_max_claims
    output_target = settings.review_batch_output_tokens
    batches: list[ReviewBatch] = []
    current: list[AtomicClaim] = []

    def fits(candidate: list[AtomicClaim]) -> bool:
        if len(candidate) > max_claims:
            return False
        if _estimate_compact_output_tokens(len(candidate)) > output_target:
            return False
        try:
            _, tokens, _ = _build_review_payload(
                role="primary_review_model",
                recheck=recheck,
                resource=resource,
                request=request,
                claim_ids={item.claim_id for item in candidate},
                input_token_budget=target,
            )
        except ReviewError:
            return False
        return tokens <= target

    def append_batch(items: list[AtomicClaim]) -> None:
        ids = tuple(item.claim_id for item in items)
        digest = hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()[:16]
        batches.append(
            ReviewBatch(
                batch_id=f"{'recheck' if recheck else 'initial'}-{digest}",
                claim_ids=ids,
            )
        )

    for claim in claims:
        candidate = [*current, claim]
        if current and not fits(candidate):
            append_batch(current)
            current = [claim]
        else:
            current = candidate
        if len(current) == 1 and not fits(current):
            # A single long claim is still allowed through the hard-budget
            # evidence trimmer. If that cannot recover it, payload building
            # raises the controlled unrecoverable error during execution.
            append_batch(current)
            current = []
    if current:
        append_batch(current)
    return batches


def _split_review_batch(batch: ReviewBatch) -> tuple[ReviewBatch, ReviewBatch]:
    middle = len(batch.claim_ids) // 2

    def child(ids: tuple[str, ...]) -> ReviewBatch:
        digest = hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()[:16]
        prefix = "recheck" if batch.batch_id.startswith("recheck") else "initial"
        return ReviewBatch(batch_id=f"{prefix}-{digest}", claim_ids=ids)

    return child(batch.claim_ids[:middle]), child(batch.claim_ids[middle:])


class OpenAICompatibleReviewChannel:
    def __init__(self, model_gateway: OpenAICompatibleGateway = gateway) -> None:
        self._gateway = model_gateway

    def review(
        self,
        *,
        role: ReviewRole,
        model: str | None,
        resource: GeneratedResourceArtifact,
        request: ReviewResourceInput,
        deterministic_review: ModelReview,
        recheck: bool,
        timeout_seconds: float | None = None,
    ) -> ModelReview:
        payload, estimated_tokens, truncated_count = _build_review_payload(
            role=role,
            recheck=recheck,
            resource=resource,
            request=request,
            claim_ids={
                check.claim_id for check in deterministic_review.fact_checks if check.claim_id
            },
        )

        def complete(
            current_payload: dict[str, object],
        ) -> tuple[_CompactModelReview, dict[str, object]]:
            result, metadata = self._gateway.complete_json(
                model=model,
                system_prompt=_role_system_prompt(role),
                payload=current_payload,
                fixture_factory=lambda: _compact_review_fixture(deterministic_review),
                response_model=_CompactModelReview,
                max_output_tokens=settings.review_batch_output_tokens,
                timeout_seconds=timeout_seconds or settings.review_timeout_seconds,
                transport_retry_delays=(1,),
                repair_truncated_output=False,
                response_adapter=lambda response: _adapt_model_review_payload(
                    response, role=role, model_name=model
                ),
            )
            return _CompactModelReview.model_validate(result), metadata

        try:
            with _REVIEW_MODEL_SEMAPHORE:
                compact, metadata = complete(payload)
                if not _compact_claim_sets_match(
                    compact.fact_checks, deterministic_review.fact_checks
                ):
                    repair_payload = dict(payload)
                    repair_payload["claim_set_correction"] = (
                        "上次输出的 claim_id 集合不正确。仅修正 fact_checks，使其逐条覆盖"
                        " canonical_claims 的全部 claim_id，不得新增、遗漏或重复。"
                    )
                    compact, repair_metadata = complete(repair_payload)
                    record_model_call(
                        repair_metadata,
                        role=role,
                        recheck=recheck,
                        correction_kind="claim_set",
                        resource_type=resource.resource_type.value,
                        estimated_input_tokens=estimated_tokens,
                        truncated_evidence_count=truncated_count,
                    )
        except ModelOutputTruncatedError as exc:
            record_model_call(
                exc.metadata,
                role=role,
                recheck=recheck,
                resource_type=resource.resource_type.value,
                estimated_input_tokens=estimated_tokens,
                truncated_evidence_count=truncated_count,
            )
            raise ReviewError("review_output_truncated") from exc
        except ModelResponseError as exc:
            record_model_call(
                exc.metadata,
                role=role,
                recheck=recheck,
                resource_type=resource.resource_type.value,
                estimated_input_tokens=estimated_tokens,
                truncated_evidence_count=truncated_count,
            )
            raise ReviewError("review_structured_output_invalid") from exc
        except ModelCallError as exc:
            record_model_call(
                exc.metadata,
                role=role,
                recheck=recheck,
                resource_type=resource.resource_type.value,
                estimated_input_tokens=estimated_tokens,
                truncated_evidence_count=truncated_count,
            )
            code = (
                "review_model_call_failed"
                if exc.metadata.get("retryable", True)
                else "review_model_non_retryable"
            )
            raise ReviewError(code) from exc
        except ModelConfigurationError as exc:
            raise ReviewError("review_model_configuration_error") from exc
        if not _compact_claim_sets_match(compact.fact_checks, deterministic_review.fact_checks):
            raise ReviewError("review_claim_set_mismatch")
        record_model_call(
            metadata,
            role=role,
            recheck=recheck,
            resource_type=resource.resource_type.value,
            estimated_input_tokens=estimated_tokens,
            truncated_evidence_count=truncated_count,
        )
        expected_model_name = model or metadata.get("model_name") or "deterministic-review"
        return _expand_compact_review(
            compact,
            deterministic_review=deterministic_review,
            role=role,
            model_name=str(expected_model_name),
        )


def _compact_review_fixture(review: ModelReview) -> dict[str, object]:
    return {
        "fact_checks": [
            {
                "claim_id": check.claim_id,
                "verdict": check.verdict.value if check.verdict else None,
                "source_ref_ids": check.source_ref_ids,
            }
            for check in review.fact_checks
        ]
    }


def _compact_claim_sets_match(actual: list[_CompactFactCheck], expected: list[FactCheck]) -> bool:
    actual_ids = [item.claim_id for item in actual]
    expected_ids = [item.claim_id for item in expected]
    return (
        len(actual_ids) == len(set(actual_ids))
        and len(actual_ids) == len(expected_ids)
        and set(actual_ids) == set(expected_ids)
    )


def _expand_compact_review(
    compact: _CompactModelReview,
    *,
    deterministic_review: ModelReview,
    role: ReviewRole,
    model_name: str,
) -> ModelReview:
    expected_by_id = {
        check.claim_id: check for check in deterministic_review.fact_checks if check.claim_id
    }
    compact_by_id = {item.claim_id: item for item in compact.fact_checks}
    checks = [
        FactCheck(
            claim_id=item.claim_id,
            field_path=expected_by_id[item.claim_id].field_path,
            claim=expected_by_id[item.claim_id].claim,
            verdict=item.verdict,
            source_ref_ids=item.source_ref_ids,
            reason=_verdict_reason(item.verdict),
        )
        for expected in deterministic_review.fact_checks
        if expected.claim_id
        for item in [compact_by_id[expected.claim_id]]
    ]
    return ModelReview(
        model_role=role,
        model_name=model_name,
        scores=deterministic_review.scores,
        passed=False,
        fact_checks=checks,
        issues=[],
        unable_to_determine=[
            item.claim_id
            for item in compact.fact_checks
            if item.verdict is EvidenceVerdict.EVIDENCE_INSUFFICIENT
        ],
    )


def _verdict_reason(verdict: EvidenceVerdict) -> str:
    return {
        EvidenceVerdict.SUPPORTED: "该审核通道判断所列证据明确支持该事实。",
        EvidenceVerdict.CONTRADICTED: "该审核通道判断所列证据与该事实明确冲突。",
        EvidenceVerdict.EVIDENCE_INSUFFICIENT: "该审核通道判断当前证据不足，无法确定该事实。",
    }[verdict]


def _adapt_model_review_payload(
    payload: dict[str, object], *, role: ReviewRole, model_name: str | None
) -> dict[str, object]:
    if not isinstance(payload, dict):
        return payload
    candidate: dict[str, object] = dict(payload)
    for wrapper in ("review", "result", "data"):
        nested = candidate.get(wrapper)
        if isinstance(nested, dict) and any(
            key in nested for key in ("scores", "review_scores", "fact_checks")
        ):
            candidate = dict(nested)
            break
    if "scores" not in candidate and isinstance(candidate.get("review_scores"), dict):
        candidate["scores"] = candidate.pop("review_scores")
    scores = candidate.get("scores")
    if isinstance(scores, dict):
        normalized_scores = dict(scores)
        aliases = {
            "accuracy": "factual_accuracy",
            "factual_score": "factual_accuracy",
            "traceability": "source_traceability",
            "source_score": "source_traceability",
            "difficulty": "difficulty_match",
            "difficulty_score": "difficulty_match",
            "coverage": "core_knowledge_coverage",
            "coverage_score": "core_knowledge_coverage",
        }
        for source, target in aliases.items():
            if target not in normalized_scores and source in normalized_scores:
                normalized_scores[target] = normalized_scores.pop(source)
        candidate["scores"] = normalized_scores
    checks = candidate.get("fact_checks")
    if isinstance(checks, list):
        adapted_checks: list[object] = []
        for check in checks:
            if not isinstance(check, dict):
                adapted_checks.append(check)
                continue
            normalized = dict(check)
            if "claim_id" not in normalized and "id" in normalized:
                normalized["claim_id"] = normalized.pop("id")
            if "field_path" not in normalized and "path" in normalized:
                normalized["field_path"] = normalized.pop("path")
            if "source_ref_ids" not in normalized:
                for alias in ("source_ids", "evidence_ids", "sources"):
                    if alias in normalized:
                        normalized["source_ref_ids"] = normalized.pop(alias)
                        break
            source_ids = normalized.get("source_ref_ids")
            if source_ids is None:
                normalized["source_ref_ids"] = []
            else:
                raw_source_ids = source_ids if isinstance(source_ids, list) else [source_ids]
                normalized_source_ids: list[str] = []
                for source_id in raw_source_ids:
                    if isinstance(source_id, dict):
                        source_id = source_id.get("source_ref_id")
                    if not isinstance(source_id, str):
                        continue
                    source_id = source_id.strip()
                    if source_id and source_id not in normalized_source_ids:
                        normalized_source_ids.append(source_id)
                normalized["source_ref_ids"] = normalized_source_ids[:20]
            if "supported" not in normalized and "is_supported" in normalized:
                normalized["supported"] = normalized.pop("is_supported")
            if "determinable" not in normalized and "is_determinable" in normalized:
                normalized["determinable"] = normalized.pop("is_determinable")
            if "verdict" not in normalized:
                if normalized.get("determinable") is False or normalized.get("supported") is None:
                    normalized["verdict"] = EvidenceVerdict.EVIDENCE_INSUFFICIENT.value
                elif normalized.get("supported") is True:
                    normalized["verdict"] = EvidenceVerdict.SUPPORTED.value
                elif normalized.get("supported") is False:
                    normalized["verdict"] = EvidenceVerdict.CONTRADICTED.value
            elif isinstance(normalized["verdict"], str):
                verdict_key = re.sub(r"[\s-]+", "_", normalized["verdict"].strip().lower())
                verdict_aliases = {
                    "supported": EvidenceVerdict.SUPPORTED.value,
                    "支持": EvidenceVerdict.SUPPORTED.value,
                    "证据支持": EvidenceVerdict.SUPPORTED.value,
                    "contradicted": EvidenceVerdict.CONTRADICTED.value,
                    "矛盾": EvidenceVerdict.CONTRADICTED.value,
                    "证据反驳": EvidenceVerdict.CONTRADICTED.value,
                    "unable_to_determine": EvidenceVerdict.EVIDENCE_INSUFFICIENT.value,
                    "无法确定": EvidenceVerdict.EVIDENCE_INSUFFICIENT.value,
                    "证据不足": EvidenceVerdict.EVIDENCE_INSUFFICIENT.value,
                }
                if verdict_key in verdict_aliases:
                    normalized["verdict"] = verdict_aliases[verdict_key]
            adapted_checks.append(normalized)
        candidate["fact_checks"] = adapted_checks
    issues = candidate.get("issues")
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict):
                if issue.get("knowledge_ids") is None:
                    issue["knowledge_ids"] = []
                elif isinstance(issue.get("knowledge_ids"), str):
                    issue["knowledge_ids"] = [issue["knowledge_ids"]]
    unable = candidate.get("unable_to_determine")
    if unable is None:
        candidate["unable_to_determine"] = []
    elif isinstance(unable, str):
        candidate["unable_to_determine"] = [unable]
    candidate["model_role"] = role
    candidate["model_name"] = model_name or str(candidate.get("model_name") or role)
    return candidate


def _merge_batch_reviews(
    reviews: list[ModelReview],
    *,
    deterministic_review: ModelReview,
    request: ReviewResourceInput,
) -> ModelReview:
    expected_ids = [item.claim_id for item in deterministic_review.fact_checks]
    by_id = {
        check.claim_id: check
        for review in reviews
        for check in review.fact_checks
        if check.claim_id
    }
    if set(by_id) != set(expected_ids) or len(by_id) != len(expected_ids):
        raise ReviewError("review_claim_set_mismatch")
    model_names = list(dict.fromkeys(review.model_name for review in reviews))
    candidate = deterministic_review.model_copy(
        update={
            "model_name": ",".join(model_names)[:128],
            "fact_checks": [by_id[claim_id] for claim_id in expected_ids],
            "issues": _unique_issues([issue for review in reviews for issue in review.issues]),
        }
    )
    return _cross_validate(candidate, deterministic_review, request)


class ReviewValidationAgent:
    name = REVIEW_AGENT_NAME
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        channel: ReviewChannel | None = None,
        evidence_retriever: ReviewEvidenceRetriever | None = None,
        batch_cache: ReviewBatchCache | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._channel = channel or OpenAICompatibleReviewChannel()
        self._evidence_retriever = evidence_retriever or SuppliedEvidenceRetriever()
        self._batch_cache = batch_cache or ReviewBatchCache()
        self._logger = logger or logging.getLogger(__name__)
        self._deadline_at: float | None = None

    def execute(self, request: ReviewResourceInput) -> ReviewResourceOutput:
        if not isinstance(request, ReviewResourceInput):
            self._logger.warning("review_rejected error_code=invalid_review_input_type")
            raise ReviewError("invalid_review_input_type")
        try:
            validated = ReviewResourceInput.model_validate(request.model_dump(mode="python"))
            self._deadline_at = time.monotonic() + settings.review_task_timeout_seconds
            reports = [
                self._review_resource(resource, validated) for resource in validated.resources
            ]
            revision_count = (
                validated.requirements.revision_plan.revision_count
                if validated.requirements.revision_plan
                else 0
            )
            output = build_review_resource_output(
                task_id=validated.task_id,
                reports=reports,
                expected_resource_types=[
                    resource.resource_type for resource in validated.resources
                ],
                required_knowledge_ids=validated.requirements.required_knowledge_ids,
                revision_count=revision_count,
            )
        except ReviewError as exc:
            self._log_failure(request, str(exc) or "review_policy_rejected")
            raise
        except ValidationError as exc:
            self._log_failure(request, "invalid_review_resource_output")
            raise ReviewError("invalid_review_resource_output") from exc
        except Exception as exc:
            self._log_failure(request, "review_execution_failed")
            raise ReviewError("review_execution_failed") from exc
        self._logger.info(
            "review_completed task_id=%s report_count=%s package_passed=%s claim_count=%s",
            output.task_id,
            len(output.reports),
            output.package_quality.passed,
            sum(
                len(report.supported_claim_ids)
                + len(report.contradicted_claim_ids)
                + len(report.undetermined_claim_ids)
                + len(report.unresolved_claim_ids)
                for report in output.reports
            ),
        )
        return output

    def _remaining_timeout(self) -> float:
        if self._deadline_at is None:
            return float(settings.review_timeout_seconds)
        remaining = self._deadline_at - time.monotonic()
        if remaining <= 3:
            raise ReviewError("review_task_timeout")
        # complete_json may perform one timeout retry. Divide the remaining
        # wall-clock budget so both attempts plus the one-second backoff stay
        # within the review-node deadline.
        return min(float(settings.review_timeout_seconds), (remaining - 1) / 2)

    def _review_resource(
        self, resource: GeneratedResourceArtifact, request: ReviewResourceInput
    ) -> ReviewReport:
        claims = extract_atomic_claims(resource, request)
        primary, secondary = self._review_pair(resource, request, recheck=False)
        disputed = _disputed_claim_ids(primary, secondary)
        non_supported = {
            claim_id
            for review in (primary, secondary)
            for claim_id, verdict in _fact_statuses(review).items()
            if verdict is not EvidenceVerdict.SUPPORTED
        }
        claims_to_refresh = disputed | non_supported
        disagreement = _reviews_disagree(primary, secondary)
        if disagreement and not claims_to_refresh:
            claims_to_refresh = {claim.claim_id for claim in claims}
        evidence_refresh_required = bool(claims_to_refresh)
        final_primary, final_secondary = primary, secondary
        primary_recheck: ModelReview | None = None
        secondary_recheck: ModelReview | None = None
        query_terms: list[str] = []
        refreshed_evidence: list[RetrievedChunk] = []
        recheck_request = request
        if evidence_refresh_required:
            query_terms = _arbitration_query_terms(
                resource, request, claims, claims_to_refresh
            )
            refreshed_evidence = self._evidence_retriever.retrieve(
                query_terms=query_terms, request=request, resource=resource
            )
            merged = _merge_evidence(request.evidence, refreshed_evidence)
            recheck_request = request.model_copy(update={"evidence": merged})
            primary_recheck, secondary_recheck = self._review_pair(
                resource,
                recheck_request,
                recheck=True,
                claim_ids=claims_to_refresh,
            )
            final_primary = _merge_recheck(primary, primary_recheck)
            final_secondary = _merge_recheck(secondary, secondary_recheck)

        final_disputed = _disputed_claim_ids(final_primary, final_secondary)
        disagreement_remains = bool(final_disputed)
        declared_ids = {source.source_ref_id for source in resource.source_refs}
        statuses = _resolved_claim_statuses(claims, final_primary, final_secondary, declared_ids)
        supported_ids = sorted(
            claim_id
            for claim_id, verdict in statuses.items()
            if verdict is EvidenceVerdict.SUPPORTED
        )
        contradicted_ids = sorted(
            claim_id
            for claim_id, verdict in statuses.items()
            if verdict is EvidenceVerdict.CONTRADICTED
        )
        undetermined_ids = sorted(
            claim_id
            for claim_id, verdict in statuses.items()
            if verdict is EvidenceVerdict.EVIDENCE_INSUFFICIENT
        )
        target_ids, covered_ids = _deterministic_coverage(
            resource, request, claims=claims, supported_claim_ids=set(supported_ids)
        )
        coverage = 100.0 * len(covered_ids) / max(1, len(target_ids))
        final_scores = _system_scores(
            statuses,
            unresolved_count=len(final_disputed),
            difficulty=min(
                final_primary.scores.difficulty_match,
                final_secondary.scores.difficulty_match,
            ),
            coverage=coverage,
        )
        issues = _final_issues(
            final_primary,
            final_secondary,
            contradicted_ids=contradicted_ids,
            undetermined_ids=undetermined_ids,
            missing_knowledge_ids=sorted(target_ids - covered_ids),
        )
        decision = _decision_from_claims(
            contradicted_ids=contradicted_ids,
            undetermined_ids=undetermined_ids,
            unresolved_ids=final_disputed,
        )
        evidence_ref_ids = sorted(
            {
                source_id
                for review in (final_primary, final_secondary)
                for check in review.fact_checks
                for source_id in check.source_ref_ids
            }
        )
        additional_ids = sorted(
            {
                chunk.source.source_ref_id
                for chunk in refreshed_evidence
                if chunk.source.source_ref_id not in declared_ids
            }
        )
        evaluated_count = (
            len(supported_ids)
            + len(contradicted_ids)
            + len(undetermined_ids)
            + len(final_disputed)
        )
        evidence_insufficient_count = len(undetermined_ids)
        hallucinated_count = len(set(contradicted_ids) | set(final_disputed))
        difficulty_score = final_scores.difficulty_match
        target_count = len(target_ids)
        covered_count = len(covered_ids)
        hallucination_rate = (
            0.0 if evaluated_count == 0 else 100.0 * hallucinated_count / evaluated_count
        )
        coverage_rate = 0.0 if target_count == 0 else 100.0 * covered_count / target_count
        metrics_passed = decision is ReviewDecision.PASSED
        revision_count = request.requirements.revision_plan.revision_count if request.requirements.revision_plan else 0
        return ReviewReport(
            resource_type=resource.resource_type,
            primary_review=primary,
            secondary_review=secondary,
            final_scores=final_scores,
            arbitration=ArbitrationResult(
                required=evidence_refresh_required,
                retrieval_performed=evidence_refresh_required,
                query_terms=query_terms,
                additional_source_ref_ids=additional_ids,
                disputed_claim_ids=sorted(claims_to_refresh),
                primary_recheck=primary_recheck,
                secondary_recheck=secondary_recheck,
                disagreement_remains=disagreement_remains,
            ),
            issues=issues,
            evidence_ref_ids=evidence_ref_ids or sorted(declared_ids),
            decision=decision,
            passed=decision is ReviewDecision.PASSED,
            quality_metrics=ResourceQualityMetrics(
                evaluated_claim_count=evaluated_count,
                contradicted_claim_count=len(contradicted_ids),
                evidence_insufficient_claim_count=evidence_insufficient_count,
                unresolved_claim_count=len(final_disputed),
                verifiable_claim_count=evaluated_count,
                hallucinated_claim_count=hallucinated_count,
                hallucination_rate=round(hallucination_rate, 2),
                difficulty_match_score=round(difficulty_score, 2),
                covered_core_knowledge_count=covered_count,
                target_core_knowledge_count=target_count,
                core_knowledge_coverage=round(coverage_rate, 2),
                passed=metrics_passed,
                revision_count=revision_count,
            ),
            target_knowledge_ids=sorted(target_ids),
            covered_knowledge_ids=sorted(covered_ids),
            missing_knowledge_ids=sorted(target_ids - covered_ids),
            claim_set_hash=_claim_set_hash(claims),
            supported_claim_ids=supported_ids,
            contradicted_claim_ids=contradicted_ids,
            undetermined_claim_ids=undetermined_ids,
            unresolved_claim_ids=sorted(final_disputed),
        )

    def _review_pair(
        self,
        resource: GeneratedResourceArtifact,
        request: ReviewResourceInput,
        *,
        recheck: bool,
        claim_ids: set[str] | None = None,
    ) -> tuple[ModelReview, ModelReview]:
        batches = _plan_review_batches(
            resource=resource,
            request=request,
            recheck=recheck,
            claim_ids=claim_ids,
        )
        batch_results: list[tuple[ModelReview, ModelReview] | None] = [None for _ in batches]
        batch_errors: list[tuple[str, Exception]] = []
        workers = max(
            1,
            min(len(batches), max(1, settings.review_model_concurrency // 2)),
        )
        contexts = [copy_context() for _ in batches]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    context.run,
                    self._review_batch_pair,
                    resource=resource,
                    request=request,
                    recheck=recheck,
                    batch=batch,
                )
                for context, batch in zip(contexts, batches, strict=True)
            ]
            for index, future in enumerate(futures):
                try:
                    batch_results[index] = future.result()
                except Exception as exc:
                    batch_errors.append((batches[index].batch_id, exc))
                finally:
                    # SQLAlchemy sessions are not thread-safe. Cache entries are
                    # collected under a lock in worker threads and persisted only
                    # here on the review node's main thread.
                    self._batch_cache.persist()
        if batch_errors:
            self._logger.warning(
                "review_batch_failures task_id=%s failures=%s",
                request.task_id,
                [
                    {"batch_id": batch_id, "error_code": str(exc)[:128]}
                    for batch_id, exc in batch_errors
                ],
            )
            raise _primary_review_error(exc for _, exc in batch_errors)
        completed = [item for item in batch_results if item is not None]
        primary_batches = [item[0] for item in completed]
        secondary_batches = [item[1] for item in completed]
        primary_deterministic = _deterministic_review(
            resource,
            request,
            "primary_review_model",
            settings.primary_review_model,
            claim_ids=claim_ids,
        )
        secondary_deterministic = _deterministic_review(
            resource,
            request,
            "secondary_review_model",
            settings.secondary_review_model,
            claim_ids=claim_ids,
        )
        return (
            _merge_batch_reviews(
                primary_batches,
                deterministic_review=primary_deterministic,
                request=request,
            ),
            _merge_batch_reviews(
                secondary_batches,
                deterministic_review=secondary_deterministic,
                request=request,
            ),
        )

    def _review_batch_pair(
        self,
        *,
        resource: GeneratedResourceArtifact,
        request: ReviewResourceInput,
        recheck: bool,
        batch: ReviewBatch,
    ) -> tuple[ModelReview, ModelReview]:
        calls: tuple[tuple[ReviewRole, str | None], ...] = (
            ("primary_review_model", settings.primary_review_model),
            ("secondary_review_model", settings.secondary_review_model),
        )
        contexts = [copy_context() for _ in calls]
        results: list[ModelReview | None] = [None, None]
        errors: list[tuple[ReviewRole, Exception]] = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    context.run,
                    self._review_batch_role,
                    role,
                    model,
                    resource,
                    request,
                    recheck,
                    batch,
                )
                for context, (role, model) in zip(contexts, calls, strict=True)
            ]
            for index, future in enumerate(futures):
                try:
                    results[index] = future.result()
                except Exception as exc:  # preserve completed peer result in cache
                    errors.append((calls[index][0], exc))
        if not errors:
            assert results[0] is not None and results[1] is not None
            return results[0], results[1]
        recoverable = all(
            isinstance(exc, ReviewError)
            and str(exc)
            in {
                "review_output_truncated",
                "review_model_call_failed",
                "review_claim_set_mismatch",
            }
            for _, exc in errors
        )
        if recoverable and len(batch.claim_ids) > 1:
            first, second = _split_review_batch(batch)
            first_pair = self._review_batch_pair(
                resource=resource,
                request=request,
                recheck=recheck,
                batch=first,
            )
            second_pair = self._review_batch_pair(
                resource=resource,
                request=request,
                recheck=recheck,
                batch=second,
            )
            parent_ids = set(batch.claim_ids)
            merged: list[ModelReview] = []
            for role, model, index in (
                ("primary_review_model", settings.primary_review_model, 0),
                ("secondary_review_model", settings.secondary_review_model, 1),
            ):
                deterministic = _deterministic_review(
                    resource, request, role, model, claim_ids=parent_ids
                )
                merged.append(
                    _merge_batch_reviews(
                        [first_pair[index], second_pair[index]],
                        deterministic_review=deterministic,
                        request=request,
                    )
                )
            return merged[0], merged[1]
        self._logger.warning(
            "review_channel_failures task_id=%s batch_id=%s claim_count=%s failures=%s",
            request.task_id,
            batch.batch_id,
            len(batch.claim_ids),
            [{"role": role, "error_code": str(exc)[:128]} for role, exc in errors],
        )
        raise _primary_review_error(exc for _, exc in errors)

    def _review_batch_role(
        self,
        role: ReviewRole,
        requested_model: str | None,
        resource: GeneratedResourceArtifact,
        request: ReviewResourceInput,
        recheck: bool,
        batch: ReviewBatch,
    ) -> ModelReview:
        claim_ids = set(batch.claim_ids)
        deterministic = _deterministic_review(
            resource, request, role, requested_model, claim_ids=claim_ids
        )
        payload, _, _ = _build_review_payload(
            role=role,
            recheck=recheck,
            resource=resource,
            request=request,
            claim_ids=claim_ids,
            input_token_budget=settings.review_batch_hard_input_tokens,
        )
        claim_hash = str(payload["claim_set_hash"])
        evidence_hash = _evidence_packet_hash(payload)
        fallback_model = (
            settings.primary_review_fallback_model
            if role == "primary_review_model"
            else settings.secondary_review_fallback_model
        )
        actual_candidates = list(
            dict.fromkeys(
                [
                    requested_model,
                    fallback_model,
                    "deterministic-review",
                    role,
                ]
            )
        )
        cached = self._batch_cache.get(
            resource_type=resource.resource_type,
            claim_set_hash=claim_hash,
            evidence_packet_hash=evidence_hash,
            role=role,
            requested_model=requested_model,
            allowed_actual_models=actual_candidates,
            recheck=recheck,
            batch_id=batch.batch_id,
            expected_claim_ids=batch.claim_ids,
        )
        if cached is not None:
            compact, actual_model = cached
            self._logger.info(
                "review_batch_cache_hit resource_type=%s role=%s batch_id=%s claim_count=%s",
                resource.resource_type.value,
                role,
                batch.batch_id,
                len(batch.claim_ids),
            )
            return _cross_validate(
                _expand_compact_review(
                    compact,
                    deterministic_review=deterministic,
                    role=role,
                    model_name=actual_model,
                ),
                deterministic,
                request,
            )

        def invoke(model: str | None) -> ModelReview:
            reviewed = self._channel.review(
                role=role,
                model=model,
                resource=resource,
                request=request,
                deterministic_review=deterministic,
                recheck=recheck,
                timeout_seconds=self._remaining_timeout(),
            )
            return _cross_validate(reviewed, deterministic, request)

        actual_model = requested_model
        try:
            reviewed = invoke(requested_model)
        except ReviewError as exc:
            if (
                str(exc) not in {"review_model_call_failed", "review_structured_output_invalid"}
                or not fallback_model
                or fallback_model == requested_model
            ):
                raise
            actual_model = fallback_model
            reviewed = invoke(fallback_model)
        actual_model = reviewed.model_name or actual_model
        self._batch_cache.put(
            resource_type=resource.resource_type,
            claim_set_hash=claim_hash,
            evidence_packet_hash=evidence_hash,
            role=role,
            requested_model=requested_model,
            actual_model=actual_model,
            recheck=recheck,
            batch_id=batch.batch_id,
            review=reviewed,
        )
        return reviewed

    def _log_failure(self, request: ReviewResourceInput, error_code: str) -> None:
        self._logger.warning(
            "review_failed task_id=%s error_code=%s",
            getattr(request, "task_id", "unknown"),
            error_code,
        )


def _tokenize(text: str) -> set[str]:
    lowered = text.lower()
    words = set(re.findall(r"[a-z0-9_]+", lowered))
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    words.update(cjk[index : index + 3] for index in range(max(0, len(cjk) - 2)))
    return {token for token in words if token}


def _ordered_unique(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _merge_evidence(
    original: list[RetrievedChunk], refreshed: list[RetrievedChunk]
) -> list[RetrievedChunk]:
    merged: dict[str, RetrievedChunk] = {chunk.source.source_ref_id: chunk for chunk in original}
    for chunk in refreshed:
        merged[chunk.source.source_ref_id] = chunk
    return list(merged.values())[:12]


def _source_overlap(claim: str, evidence: list[RetrievedChunk]) -> float:
    claim_tokens = _tokenize(claim)
    evidence_tokens = _tokenize(" ".join(chunk.content for chunk in evidence))
    if not claim_tokens or not evidence_tokens:
        return 0.0
    return len(claim_tokens & evidence_tokens) / len(claim_tokens)


def _deterministic_review(
    resource: GeneratedResourceArtifact,
    request: ReviewResourceInput,
    role: ReviewRole,
    model: str | None,
    *,
    claim_ids: set[str] | None = None,
) -> ModelReview:
    claims = extract_atomic_claims(resource, request)
    if claim_ids is not None:
        claims = [claim for claim in claims if claim.claim_id in claim_ids]
        if not claims:
            raise ReviewError("review_claim_set_empty")
    evidence_by_source = {chunk.source.source_ref_id: chunk for chunk in request.evidence}
    checks: list[FactCheck] = []
    for claim in claims:
        evidence = [
            evidence_by_source[source_id]
            for source_id in claim.source_ref_ids
            if source_id in evidence_by_source
        ]
        source_valid = len(evidence) == len(claim.source_ref_ids) and bool(evidence)
        overlap = _source_overlap(claim.claim, evidence) if source_valid else 0.0
        verdict = (
            EvidenceVerdict.SUPPORTED
            if source_valid and overlap > 0
            else EvidenceVerdict.EVIDENCE_INSUFFICIENT
        )
        checks.append(
            FactCheck(
                claim_id=claim.claim_id,
                field_path=claim.field_path,
                claim=claim.claim,
                verdict=verdict,
                source_ref_ids=list(claim.source_ref_ids)
                if verdict is EvidenceVerdict.SUPPORTED
                else [],
                reason=(
                    "确定性检查发现事实文本与声明证据存在内容重叠。"
                    if verdict is EvidenceVerdict.SUPPORTED
                    else "确定性检查无法从声明证据确认该事实；这不表示证据反驳该事实。"
                ),
            )
        )
    difficulty_delta = abs(resource.difficulty - request.requirements.target_difficulty)
    difficulty = max(0.0, 100.0 - difficulty_delta * 25.0)
    targets, structural = _deterministic_coverage(resource, request, claims=claims)
    coverage = 100.0 * len(structural) / max(1, len(targets))
    scores = _scores_from_checks(checks, difficulty=difficulty, coverage=coverage)
    return ModelReview(
        model_role=role,
        model_name=model or "deterministic-review",
        scores=scores,
        passed=all(check.verdict is EvidenceVerdict.SUPPORTED for check in checks)
        and all(value >= PASS_THRESHOLD for value in scores.model_dump().values()),
        fact_checks=checks,
        unable_to_determine=[
            check.claim_id or check.claim
            for check in checks
            if check.verdict is EvidenceVerdict.EVIDENCE_INSUFFICIENT
        ],
    )


def _claim_sets_match(actual: list[FactCheck], expected: list[FactCheck]) -> bool:
    actual_ids = [item.claim_id for item in actual]
    expected_ids = [item.claim_id for item in expected]
    return actual_ids == expected_ids and all(actual_ids)


def _cross_validate(
    reviewed: ModelReview,
    deterministic: ModelReview,
    request: ReviewResourceInput,
) -> ModelReview:
    if not _claim_sets_match(reviewed.fact_checks, deterministic.fact_checks):
        raise ReviewError("review_claim_set_mismatch")
    valid_source_ids = {chunk.source.source_ref_id for chunk in request.evidence}
    expected_by_id = {item.claim_id: item for item in deterministic.fact_checks}
    checks: list[FactCheck] = []
    for check in reviewed.fact_checks:
        expected = expected_by_id[check.claim_id]
        source_ids = [
            source_id for source_id in check.source_ref_ids if source_id in valid_source_ids
        ]
        verdict = check.verdict or EvidenceVerdict.EVIDENCE_INSUFFICIENT
        literal_source_ids = _direct_literal_evidence_source_ids(expected, request)
        if literal_source_ids:
            verdict = EvidenceVerdict.SUPPORTED
            source_ids = literal_source_ids
        elif (
            verdict is EvidenceVerdict.SUPPORTED
            and not source_ids
            and expected.verdict is EvidenceVerdict.SUPPORTED
        ):
            # The model made the semantic support decision but may omit the
            # optional source array. Restore only canonical sources already
            # bound to this claim and validated against the evidence packet.
            source_ids = [
                source_id
                for source_id in expected.source_ref_ids
                if source_id in valid_source_ids
            ]
        if verdict is EvidenceVerdict.SUPPORTED and not source_ids:
            verdict = EvidenceVerdict.EVIDENCE_INSUFFICIENT
        checks.append(
            check.model_copy(
                update={
                    "claim": expected.claim,
                    "field_path": expected.field_path,
                    "verdict": verdict,
                    "supported": (
                        True
                        if verdict is EvidenceVerdict.SUPPORTED
                        else False
                        if verdict is EvidenceVerdict.CONTRADICTED
                        else None
                    ),
                    "determinable": verdict is not EvidenceVerdict.EVIDENCE_INSUFFICIENT,
                    "source_ref_ids": source_ids,
                }
            )
        )
    scores = _scores_from_checks(
        checks,
        difficulty=deterministic.scores.difficulty_match,
        coverage=deterministic.scores.core_knowledge_coverage,
    )
    issues = _unique_issues([*deterministic.issues, *reviewed.issues])
    if any(check.verdict is EvidenceVerdict.CONTRADICTED for check in checks):
        issues.append(
            ReviewIssue(
                code=ReviewIssueCode.CONTRADICTED_CLAIM,
                section="事实核验",
                description="审核证据明确反驳了一个或多个事实。",
                suggested_revision="修正或删除明确冲突的事实后重新审核。",
            )
        )
    if any(check.verdict is EvidenceVerdict.EVIDENCE_INSUFFICIENT for check in checks):
        issues.append(
            ReviewIssue(
                code=ReviewIssueCode.EVIDENCE_INSUFFICIENT,
                section="事实核验",
                description="当前证据不足以确认一个或多个事实，但没有证据表明其错误。",
                suggested_revision="由知识检索智能体补充证据，或删除、弱化相应结论。",
            )
        )
    passed = all(check.verdict is EvidenceVerdict.SUPPORTED for check in checks) and all(
        value >= PASS_THRESHOLD for value in scores.model_dump().values()
    )
    return reviewed.model_copy(
        update={
            "scores": scores,
            "passed": passed,
            "fact_checks": checks,
            "issues": _unique_issues(issues),
            "unable_to_determine": [
                check.claim_id or check.claim
                for check in checks
                if check.verdict is EvidenceVerdict.EVIDENCE_INSUFFICIENT
            ],
        }
    )


def _scores_from_checks(
    checks: list[FactCheck], *, difficulty: float, coverage: float
) -> ReviewCriterionScores:
    supported = sum(check.verdict is EvidenceVerdict.SUPPORTED for check in checks)
    contradicted = sum(check.verdict is EvidenceVerdict.CONTRADICTED for check in checks)
    determinable = supported + contradicted
    factual = 100.0 if determinable == 0 else 100.0 * supported / determinable
    traceability = 100.0 * supported / max(1, len(checks))
    return ReviewCriterionScores(
        factual_accuracy=round(factual, 2),
        source_traceability=round(traceability, 2),
        difficulty_match=round(difficulty, 2),
        core_knowledge_coverage=round(coverage, 2),
    )


def _review_average(review: ModelReview) -> float:
    return sum(review.scores.model_dump().values()) / 4


def _fact_statuses(review: ModelReview) -> dict[str, EvidenceVerdict]:
    return {
        check.claim_id: check.verdict or EvidenceVerdict.EVIDENCE_INSUFFICIENT
        for check in review.fact_checks
        if check.claim_id
    }


def _disputed_claim_ids(primary: ModelReview, secondary: ModelReview) -> set[str]:
    first, second = _fact_statuses(primary), _fact_statuses(secondary)
    return {
        claim_id
        for claim_id in set(first) | set(second)
        if first.get(claim_id) != second.get(claim_id)
    }


def _reviews_disagree(primary: ModelReview, secondary: ModelReview) -> bool:
    return (
        bool(_disputed_claim_ids(primary, secondary))
        or abs(_review_average(primary) - _review_average(secondary)) > 10
        or primary.passed != secondary.passed
    )


def _direct_literal_evidence_source_ids(
    check: FactCheck,
    request: ReviewResourceInput,
) -> list[str]:
    """Prove code/command claims by exact literal presence in their cited evidence."""
    if not check.field_path.endswith(".code_or_command"):
        return []
    marker = "以下代码或命令应能完成该步骤："
    body = check.claim.split(marker, 1)[-1]
    normalized_body = re.sub(r"\s+", " ", body).strip()
    if not normalized_body:
        return []
    evidence_by_source = {chunk.source.source_ref_id: chunk for chunk in request.evidence}
    supported: list[str] = []
    for source_id in check.source_ref_ids:
        chunk = evidence_by_source.get(source_id)
        if chunk is None:
            continue
        normalized_evidence = re.sub(r"\s+", " ", chunk.content).strip()
        if normalized_body in normalized_evidence:
            supported.append(source_id)
    return supported


def _merge_recheck(original: ModelReview, recheck: ModelReview) -> ModelReview:
    """Replace only disputed claim results while preserving agreed work."""
    replacements = {check.claim_id: check for check in recheck.fact_checks}
    checks = [replacements.get(check.claim_id, check) for check in original.fact_checks]
    scores = _scores_from_checks(
        checks,
        difficulty=original.scores.difficulty_match,
        coverage=original.scores.core_knowledge_coverage,
    )
    passed = all(check.verdict is EvidenceVerdict.SUPPORTED for check in checks) and all(
        value >= PASS_THRESHOLD for value in scores.model_dump().values()
    )
    return original.model_copy(
        update={
            "scores": scores,
            "passed": passed,
            "fact_checks": checks,
            "issues": _unique_issues([*original.issues, *recheck.issues]),
            "unable_to_determine": [
                check.claim_id or check.claim
                for check in checks
                if check.verdict is EvidenceVerdict.EVIDENCE_INSUFFICIENT
            ],
        }
    )


def _resolved_claim_statuses(
    claims: list[AtomicClaim],
    primary: ModelReview,
    secondary: ModelReview,
    declared_source_ids: set[str],
) -> dict[str, EvidenceVerdict]:
    first = {item.claim_id: item for item in primary.fact_checks}
    second = {item.claim_id: item for item in secondary.fact_checks}
    result: dict[str, EvidenceVerdict] = {}
    for claim in claims:
        left, right = first[claim.claim_id], second[claim.claim_id]
        if left.verdict != right.verdict:
            continue
        verdict = left.verdict or EvidenceVerdict.EVIDENCE_INSUFFICIENT
        if verdict is EvidenceVerdict.SUPPORTED:
            supporting = set(left.source_ref_ids) | set(right.source_ref_ids)
            if not supporting or not supporting.issubset(declared_source_ids):
                verdict = EvidenceVerdict.EVIDENCE_INSUFFICIENT
        result[claim.claim_id] = verdict
    return result


def _system_scores(
    statuses: dict[str, EvidenceVerdict],
    *,
    unresolved_count: int,
    difficulty: float,
    coverage: float,
) -> ReviewCriterionScores:
    supported = sum(value is EvidenceVerdict.SUPPORTED for value in statuses.values())
    contradicted = sum(value is EvidenceVerdict.CONTRADICTED for value in statuses.values())
    determinable = supported + contradicted
    total = len(statuses) + unresolved_count
    factual = 100.0 if determinable == 0 else 100.0 * supported / determinable
    traceability = 100.0 * supported / max(1, total)
    return ReviewCriterionScores(
        factual_accuracy=round(factual, 2),
        source_traceability=round(traceability, 2),
        difficulty_match=round(difficulty, 2),
        core_knowledge_coverage=round(coverage, 2),
    )


def _deterministic_coverage(
    resource: GeneratedResourceArtifact,
    request: ReviewResourceInput,
    *,
    claims: list[AtomicClaim] | None = None,
    supported_claim_ids: set[str] | None = None,
) -> tuple[set[str], set[str]]:
    canonical = claims or extract_atomic_claims(resource, request)
    evidence_by_source = {chunk.source.source_ref_id: chunk for chunk in request.evidence}
    targets = set(request.requirements.resource_knowledge_targets[resource.resource_type])
    covered: set[str] = set()
    for claim in canonical:
        if supported_claim_ids is not None and claim.claim_id not in supported_claim_ids:
            continue
        compact = re.sub(r"\s+", "", _normalize_claim_text(claim.claim))
        if len(compact) < 8 or compact.lower() in {
            "待补充",
            "暂无",
            "无",
            "todo",
            "tbd",
            "示例内容",
            "模板内容",
        }:
            continue
        for knowledge_id in claim.knowledge_ids:
            if knowledge_id not in targets:
                continue
            if any(
                source_id in evidence_by_source
                and evidence_by_source[source_id].knowledge_id == knowledge_id
                for source_id in claim.source_ref_ids
            ):
                covered.add(knowledge_id)

    # Practice instructions can be substantive teaching actions without being
    # factual assertions (for example, "record the actual response fields").
    # Count such a step only when it is linked to operational evidence for the
    # target and has lexical overlap with that evidence. Technical assertions
    # are intentionally excluded here and must still pass claim-level review.
    if isinstance(resource.structured_content, PracticeGuideContent):
        policy = get_domain_evidence_policy(request.context.domain_code)
        for step in resource.structured_content.steps:
            if _claim_exclusion_category("instruction", step.instruction) != "pedagogical_action":
                continue
            compact = re.sub(r"\s+", "", step.instruction)
            if len(compact) < 8:
                continue
            for source_id in step.source_ref_ids:
                chunk = evidence_by_source.get(source_id)
                if (
                    chunk is None
                    or chunk.knowledge_id not in targets
                    or EvidenceCapability.OPERATION not in policy.classify(chunk)
                    or _source_overlap(step.instruction, [chunk]) <= 0
                ):
                    continue
                covered.add(chunk.knowledge_id)
    return targets, covered


def _final_issues(
    primary: ModelReview,
    secondary: ModelReview,
    *,
    contradicted_ids: list[str],
    undetermined_ids: list[str],
    missing_knowledge_ids: list[str],
) -> list[ReviewIssue]:
    issues = _unique_issues([*primary.issues, *secondary.issues])
    if contradicted_ids:
        issues.append(
            ReviewIssue(
                code=ReviewIssueCode.CONTRADICTED_CLAIM,
                section="事实核验",
                description=f"{len(contradicted_ids)} 条事实被证据明确反驳。",
                suggested_revision="只修正对应 claim_id 的事实内容。",
            )
        )
    if undetermined_ids:
        issues.append(
            ReviewIssue(
                code=ReviewIssueCode.EVIDENCE_INSUFFICIENT,
                section="证据覆盖",
                description=f"{len(undetermined_ids)} 条事实当前证据不足，未判定为错误。",
                suggested_revision="补充可追溯证据，或删除、弱化对应结论。",
            )
        )
    if missing_knowledge_ids:
        issues.append(
            ReviewIssue(
                code=ReviewIssueCode.MISSING_KNOWLEDGE,
                section="核心知识",
                knowledge_ids=missing_knowledge_ids,
                description="部分目标知识点没有获得事实级证据支持。",
                suggested_revision="补充实质教学内容并绑定同一知识点的证据块。",
            )
        )
    return _unique_issues(issues)


def _decision_from_claims(
    *,
    contradicted_ids: list[str],
    undetermined_ids: list[str],
    unresolved_ids: set[str],
) -> ReviewDecision:
    if unresolved_ids:
        return ReviewDecision.REVISION_REQUIRED
    if contradicted_ids or undetermined_ids:
        return ReviewDecision.REVISION_REQUIRED
    # Difficulty and coverage are competition metrics at package scope. The
    # resource report still records its assigned targets and missing IDs so the
    # orchestrator can revise only the contributors to a failed package metric.
    return ReviewDecision.PASSED


def _conservative_scores(primary: ModelReview, secondary: ModelReview) -> ReviewCriterionScores:
    first, second = primary.scores.model_dump(), secondary.scores.model_dump()
    return ReviewCriterionScores(**{key: min(first[key], second[key]) for key in first})


def _unsupported_fact_checks(fact_checks: Iterable[FactCheck]) -> list[FactCheck]:
    return [check for check in fact_checks if check.verdict is EvidenceVerdict.CONTRADICTED]


def _has_unsupported_fact(review: ModelReview) -> bool:
    return bool(_unsupported_fact_checks(review.fact_checks))


def _review_decision(
    primary: ModelReview,
    secondary: ModelReview,
    scores: ReviewCriterionScores,
    disagreement_remains: bool,
) -> ReviewDecision:
    if disagreement_remains:
        return ReviewDecision.REVISION_REQUIRED
    checks = [*primary.fact_checks, *secondary.fact_checks]
    if any(check.verdict is EvidenceVerdict.CONTRADICTED for check in checks):
        return ReviewDecision.REVISION_REQUIRED
    if any(check.verdict is EvidenceVerdict.EVIDENCE_INSUFFICIENT for check in checks):
        return ReviewDecision.REVISION_REQUIRED
    if (
        primary.passed
        and secondary.passed
        and all(value >= PASS_THRESHOLD for value in scores.model_dump().values())
    ):
        return ReviewDecision.PASSED
    return ReviewDecision.REVISION_REQUIRED


def _arbitration_query_terms(
    resource: GeneratedResourceArtifact,
    request: ReviewResourceInput,
    claims: list[AtomicClaim] | None = None,
    disputed_claim_ids: set[str] | None = None,
) -> list[str]:
    canonical = claims or extract_atomic_claims(resource, request)
    disputed = disputed_claim_ids or {claim.claim_id for claim in canonical}
    terms: list[str] = []
    for claim in canonical:
        if claim.claim_id not in disputed:
            continue
        terms.append(bounded_text(claim.claim, 300))
        terms.extend(claim.knowledge_ids)
    terms.extend(source.source_title for source in resource.source_refs)
    return _ordered_unique(terms)[:30] or [resource.resource_type.value]


def _unique_issues(issues: list[ReviewIssue]) -> list[ReviewIssue]:
    unique: list[ReviewIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (issue.code.value, issue.section, issue.description)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique
