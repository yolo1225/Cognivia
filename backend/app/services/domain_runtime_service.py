from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.agents.profile_analysis_config import (
    ABILITY_DIMENSIONS,
    MASTERY_BASELINES,
    KnowledgeProfileMetadata,
    ProfileAnalysisConfig,
)
from app.models import DiagnosticQuestion, Domain, KnowledgeItem, KnowledgeRelation
from app.rag.readiness import candidate_rag_status
from app.services.question_certification_service import (
    QUESTION_CERTIFICATION_RULE_VERSION,
)


DIAGNOSTIC_DISTRIBUTION = {
    ("single_choice", False): 3,
    ("single_choice", True): 3,
    ("short_answer", False): 2,
    ("short_answer", True): 2,
}
SAFE_CONCEPTUAL_DIAGNOSTIC_DISTRIBUTION = {
    "single_choice": 6,
    "short_answer": 4,
}


def practice_generation_mode_for_items(items: list[KnowledgeItem]) -> str:
    """Return the domain-level practice mode without inventing evidence labels."""
    capabilities = {
        str(capability)
        for item in items
        for capability in (item.evidence_capabilities_json or [])
    }
    return (
        "evidence_backed"
        if {"operation", "expected_result"}.issubset(capabilities)
        else "safe_conceptual"
    )


class DomainRuntimeError(ValueError):
    """Raised when a domain cannot safely drive the shared runtime."""


@dataclass(frozen=True, slots=True)
class LearningDirection:
    value: str
    label: str
    description: str
    match_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DomainRuntime:
    domain_code: str
    display_name: str
    status: str
    knowledge_ids: tuple[str, ...]
    relation_count: int
    diagnostic_question_count: int
    practice_generation_mode: str
    learning_directions: tuple[LearningDirection, ...]
    profile_config: ProfileAnalysisConfig | None
    profile_ready: bool
    diagnostic_ready: bool
    rag_ready: bool
    generation_ready: bool
    reasons: tuple[str, ...]
    rag: dict[str, Any]

    def readiness_payload(self) -> dict[str, Any]:
        return {
            "domain_code": self.domain_code,
            "display_name": self.display_name,
            "status": self.status,
            "profile_ready": self.profile_ready,
            "diagnostic_ready": self.diagnostic_ready,
            "rag_ready": self.rag_ready,
            "generation_ready": self.generation_ready,
            "reasons": list(self.reasons),
            "knowledge_item_count": len(self.knowledge_ids),
            "diagnostic_question_count": self.diagnostic_question_count,
            "practice_generation_mode": self.practice_generation_mode,
            "relation_count": self.relation_count,
            "rag": self.rag,
        }


def _profile_config(
    domain: Domain,
    items: list[KnowledgeItem],
    relations: list[KnowledgeRelation],
) -> ProfileAnalysisConfig:
    if not items:
        raise DomainRuntimeError("domain_has_no_published_knowledge")

    item_by_id = {item.id: item for item in items}
    prerequisites: dict[str, list[str]] = {item.public_id: [] for item in items}
    for relation in relations:
        source = item_by_id.get(relation.source_item_id)
        target = item_by_id.get(relation.target_item_id)
        if source is None or target is None:
            raise DomainRuntimeError("cross_domain_knowledge_relation")
        if relation.relation_type == "prerequisite":
            prerequisites[target.public_id].append(source.public_id)

    policy = dict((domain.config_json or {}).get("profile_policy") or {})
    dimensions = tuple(policy.get("ability_dimensions") or ABILITY_DIMENSIONS)
    if dimensions != ABILITY_DIMENSIONS:
        raise DomainRuntimeError("unsupported_ability_dimensions")

    configured_weights = policy.get("ability_weights") or {}
    ability_weights = {}
    for item in items:
        weights = dict(item.ability_weights_json or configured_weights.get(item.public_id) or {})
        if set(weights) != set(ABILITY_DIMENSIONS):
            raise DomainRuntimeError(f"ability_weights_missing:{item.public_id}")
        normalized = {key: float(weights[key]) for key in ABILITY_DIMENSIONS}
        if (
            any(value < 0 for value in normalized.values())
            or abs(sum(normalized.values()) - 1) > 1e-9
        ):
            raise DomainRuntimeError(f"ability_weights_invalid:{item.public_id}")
        ability_weights[item.public_id] = normalized

    thresholds = tuple(
        float(value) for value in policy.get("mastery_thresholds", (0.40, 0.60, 0.80))
    )
    if len(thresholds) != 3 or tuple(sorted(thresholds)) != thresholds:
        raise DomainRuntimeError("mastery_thresholds_invalid")

    return ProfileAnalysisConfig(
        version=str(policy.get("version") or f"{domain.domain_code}_profile_v1"),
        seed_sha256=str(policy.get("data_fingerprint") or f"database:{domain.domain_code}"),
        prior_mastery=float(policy.get("prior_mastery", 0.5)),
        prior_weight=float(policy.get("prior_weight", 1.0)),
        mastery_thresholds=thresholds,
        minimum_effective_change=int(policy.get("minimum_effective_change", 5)),
        max_ability_change_per_update=int(policy.get("max_ability_change_per_update", 10)),
        max_weakness_level_change_per_update=int(
            policy.get("max_weakness_level_change_per_update", 1)
        ),
        default_n_results=int(policy.get("default_n_results", 8)),
        multi_priority_remedial_n_results=int(policy.get("multi_priority_remedial_n_results", 10)),
        maximum_n_results=int(policy.get("maximum_n_results", 12)),
        ability_weights=ability_weights,
        knowledge_catalog={
            item.public_id: KnowledgeProfileMetadata(
                name=item.name,
                category=item.category,
                prerequisite_ids=tuple(prerequisites[item.public_id]),
            )
            for item in items
        },
        mastery_baselines={
            key: float(value)
            for key, value in (policy.get("mastery_baselines") or MASTERY_BASELINES).items()
        },
        minimum_category_coverage_for_practice_oriented=int(
            policy.get("minimum_category_coverage_for_practice_oriented", 3)
        ),
    )


def _learning_directions(domain: Domain) -> tuple[LearningDirection, ...]:
    directions = []
    for raw in (domain.config_json or {}).get("learning_directions") or []:
        value = str(raw.get("value") or "").strip()
        if not value:
            continue
        directions.append(
            LearningDirection(
                value=value,
                label=str(raw.get("label") or value),
                description=str(raw.get("description") or ""),
                match_tags=tuple(
                    str(tag).strip().lower()
                    for tag in (raw.get("match_tags") or [])
                    if str(tag).strip()
                ),
            )
        )
    return tuple(directions)


def load_domain_runtime(db: Session, domain_code: str) -> DomainRuntime:
    domain_code = str(domain_code or "").strip()
    if not domain_code:
        raise DomainRuntimeError("domain_code_required")
    domain = db.scalar(select(Domain).where(Domain.domain_code == domain_code))
    if domain is None:
        raise DomainRuntimeError("domain_not_found")

    items = list(
        db.scalars(
            select(KnowledgeItem)
            .where(
                KnowledgeItem.domain_code == domain_code,
                KnowledgeItem.status == "published",
            )
            .order_by(KnowledgeItem.public_id)
        )
    )
    item_by_id = {item.id: item for item in items}
    relations = (
        list(
            db.scalars(
                select(KnowledgeRelation).where(
                    or_(
                        KnowledgeRelation.source_item_id.in_(item_by_id),
                        KnowledgeRelation.target_item_id.in_(item_by_id),
                    )
                )
            )
        )
        if item_by_id
        else []
    )

    reasons: list[str] = []
    try:
        profile_config = _profile_config(domain, items, relations)
    except DomainRuntimeError as exc:
        profile_config = None
        reasons.append(str(exc))

    total_questions = int(
        db.scalar(
            select(func.count())
            .select_from(DiagnosticQuestion)
            .where(DiagnosticQuestion.domain_code == domain_code)
            .where(DiagnosticQuestion.status == "active")
            .where(DiagnosticQuestion.certification_status == "certified")
            .where(
                DiagnosticQuestion.certification_rule_version
                == QUESTION_CERTIFICATION_RULE_VERSION
            )
        )
        or 0
    )
    valid_questions = list(
        db.execute(
            select(DiagnosticQuestion, KnowledgeItem)
            .join(KnowledgeItem, DiagnosticQuestion.knowledge_item_id == KnowledgeItem.id)
            .where(
                DiagnosticQuestion.domain_code == domain_code,
                DiagnosticQuestion.status == "active",
                DiagnosticQuestion.certification_status == "certified",
                DiagnosticQuestion.certification_rule_version
                == QUESTION_CERTIFICATION_RULE_VERSION,
                KnowledgeItem.domain_code == domain_code,
                KnowledgeItem.status == "published",
            )
        )
    )
    if len(valid_questions) != total_questions:
        reasons.append("diagnostic_cross_domain_or_unpublished_knowledge")
    practice_generation_mode = practice_generation_mode_for_items(items)
    if practice_generation_mode == "evidence_backed":
        buckets = {key: 0 for key in DIAGNOSTIC_DISTRIBUTION}
        for question, item in valid_questions:
            key = (
                question.question_type,
                "operation" in (item.evidence_capabilities_json or []),
            )
            if key in buckets:
                buckets[key] += 1
        missing_buckets = [
            f"{question_type}:{'operation' if operation else 'theory'}"
            for (question_type, operation), required in DIAGNOSTIC_DISTRIBUTION.items()
            if buckets[(question_type, operation)] < required
        ]
    else:
        type_counts = {question_type: 0 for question_type in SAFE_CONCEPTUAL_DIAGNOSTIC_DISTRIBUTION}
        for question, _item in valid_questions:
            if question.question_type in type_counts:
                type_counts[question.question_type] += 1
        missing_buckets = [
            f"{question_type}:overall"
            for question_type, required in SAFE_CONCEPTUAL_DIAGNOSTIC_DISTRIBUTION.items()
            if type_counts[question_type] < required
        ]
    if missing_buckets:
        reasons.append(f"diagnostic_distribution_insufficient:{','.join(missing_buckets)}")

    rag = candidate_rag_status(domain_code)
    profile_ready = profile_config is not None
    diagnostic_ready = (
        profile_ready and not missing_buckets and len(valid_questions) == total_questions
    )
    rag_ready = bool(rag.get("ready"))
    return DomainRuntime(
        domain_code=domain_code,
        display_name=domain.name,
        status=domain.status,
        knowledge_ids=tuple(item.public_id for item in items),
        relation_count=len(relations),
        diagnostic_question_count=total_questions,
        practice_generation_mode=practice_generation_mode,
        learning_directions=_learning_directions(domain),
        profile_config=profile_config,
        profile_ready=profile_ready,
        diagnostic_ready=diagnostic_ready,
        rag_ready=rag_ready,
        generation_ready=profile_ready and rag_ready,
        reasons=tuple(
            dict.fromkeys(
                reasons + ([] if rag_ready else [str(rag.get("reason") or "rag_not_ready")])
            )
        ),
        rag=rag,
    )


def require_ready_domain(db: Session, domain_code: str) -> DomainRuntime:
    runtime = load_domain_runtime(db, domain_code)
    if runtime.status != "ready":
        raise DomainRuntimeError(f"domain_not_ready:{runtime.status}")
    return runtime


def unique_ready_domain_code(db: Session) -> str:
    codes = list(
        db.scalars(
            select(Domain.domain_code)
            .where(Domain.status == "ready")
            .order_by(Domain.domain_code)
            .limit(2)
        )
    )
    return codes[0] if len(codes) == 1 else ""


def load_profile_analysis_config(db: Session, domain_code: str) -> ProfileAnalysisConfig:
    runtime = load_domain_runtime(db, domain_code)
    if runtime.profile_config is None:
        raise DomainRuntimeError(
            runtime.reasons[0] if runtime.reasons else "profile_runtime_not_ready"
        )
    return runtime.profile_config
