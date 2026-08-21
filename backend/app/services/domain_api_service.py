from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.agents.profile_analysis_config import ABILITY_DIMENSIONS
from app.models import (
    DiagnosticQuestion,
    Domain,
    IndexBuildJob,
    KnowledgeItem,
    KnowledgeRelation,
)
from app.rag.readiness import candidate_rag_status
from app.services.domain_runtime_service import DomainRuntimeError, load_domain_runtime


DOMAIN_STATUSES = {"draft", "preparing", "ready", "disabled"}
PRIMARY_READINESS_POLICY = {"minimum_published_knowledge": 50, "minimum_diagnostic_questions": 60}
SECONDARY_READINESS_POLICY = {"minimum_published_knowledge": 10, "minimum_diagnostic_questions": 10}
DEFAULT_ABILITY_WEIGHTS = {
    "theory": 0.3,
    "practice": 0.25,
    "problem_solving": 0.2,
    "knowledge_breadth": 0.25,
    "learning_speed": 0.0,
}


class DomainServiceError(ValueError):
    pass


def readiness_policy(domain: Domain) -> dict[str, int]:
    raw = dict((domain.config_json or {}).get("readiness_policy") or {})
    defaults = (
        PRIMARY_READINESS_POLICY
        if domain.domain_code == "ai_app_dev"
        else SECONDARY_READINESS_POLICY
    )
    return {
        "minimum_published_knowledge": max(
            defaults["minimum_published_knowledge"],
            int(raw.get("minimum_published_knowledge", defaults["minimum_published_knowledge"])),
        ),
        "minimum_diagnostic_questions": max(
            defaults["minimum_diagnostic_questions"],
            int(raw.get("minimum_diagnostic_questions", defaults["minimum_diagnostic_questions"])),
        ),
    }


def serialize_domain(domain: Domain) -> dict[str, Any]:
    config = domain.config_json or {}
    return {
        "domain_code": domain.domain_code,
        "name": domain.name,
        "description": str(config.get("description") or ""),
        "domain_schema_version": domain.schema_version,
        "status": domain.status,
        "learning_directions": list(config.get("learning_directions") or []),
        "config": config,
        "created_at": domain.created_at.isoformat() if domain.created_at else None,
        "updated_at": domain.updated_at.isoformat() if domain.updated_at else None,
    }


def mark_domain_preparing(db: Session, domain_code: str) -> None:
    domain = db.scalar(select(Domain).where(Domain.domain_code == domain_code))
    if domain is not None and domain.status in {"draft", "ready"}:
        domain.status = "preparing"


def default_ability_weights() -> dict[str, float]:
    return dict(DEFAULT_ABILITY_WEIGHTS)


class DomainApiService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def require(self, domain_code: str) -> Domain:
        domain = self.db.scalar(select(Domain).where(Domain.domain_code == domain_code))
        if domain is None:
            raise DomainServiceError("DOMAIN_NOT_FOUND")
        return domain

    def list(self, *, ready_only: bool = False) -> list[dict[str, Any]]:
        statement = select(Domain).order_by(Domain.domain_code)
        if ready_only:
            statement = statement.where(Domain.status == "ready")
        return [serialize_domain(domain) for domain in self.db.scalars(statement)]

    def detail(self, domain_code: str) -> dict[str, Any]:
        return serialize_domain(self.require(domain_code))

    def create(
        self,
        *,
        domain_code: str,
        name: str,
        description: str,
        learning_directions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.db.scalar(select(Domain).where(Domain.domain_code == domain_code)):
            raise DomainServiceError("DOMAIN_ALREADY_EXISTS")
        domain = Domain(
            domain_code=domain_code,
            name=name,
            status="draft",
            config_json={
                "description": description,
                "learning_directions": learning_directions,
                "readiness_policy": dict(SECONDARY_READINESS_POLICY),
            },
        )
        self.db.add(domain)
        self.db.commit()
        self.db.refresh(domain)
        return serialize_domain(domain)

    def update(
        self,
        domain_code: str,
        *,
        name: str | None = None,
        description: str | None = None,
        learning_directions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        domain = self.require(domain_code)
        if name is not None:
            domain.name = name
        config = dict(domain.config_json or {})
        if description is not None:
            config["description"] = description
        if learning_directions is not None:
            config["learning_directions"] = learning_directions
        domain.config_json = config
        if domain.status == "ready" and learning_directions is not None:
            domain.status = "preparing"
        self.db.commit()
        self.db.refresh(domain)
        return serialize_domain(domain)

    def disable(self, domain_code: str) -> dict[str, Any]:
        domain = self.require(domain_code)
        domain.status = "disabled"
        self.db.commit()
        self.db.refresh(domain)
        return serialize_domain(domain)

    @staticmethod
    def _has_cycle(item_ids: set[int], relations: list[KnowledgeRelation]) -> bool:
        graph: dict[int, list[int]] = defaultdict(list)
        for relation in relations:
            if (
                relation.relation_type == "prerequisite"
                and relation.source_item_id in item_ids
                and relation.target_item_id in item_ids
            ):
                graph[relation.source_item_id].append(relation.target_item_id)
        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(node: int) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            if any(visit(target) for target in graph.get(node, [])):
                return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in item_ids)

    def readiness(self, domain_code: str) -> dict[str, Any]:
        domain = self.require(domain_code)
        policy = readiness_policy(domain)
        items = list(
            self.db.scalars(
                select(KnowledgeItem).where(
                    KnowledgeItem.domain_code == domain_code, KnowledgeItem.status == "published"
                )
            )
        )
        item_ids = {item.id for item in items}
        relations = (
            list(
                self.db.scalars(
                    select(KnowledgeRelation).where(
                        or_(
                            KnowledgeRelation.source_item_id.in_(item_ids),
                            KnowledgeRelation.target_item_id.in_(item_ids),
                        )
                    )
                )
            )
            if item_ids
            else []
        )
        cross_domain_relations = sum(
            relation.source_item_id not in item_ids or relation.target_item_id not in item_ids
            for relation in relations
        )
        valid_question_count = len(
            list(
                self.db.execute(
                    select(DiagnosticQuestion.id)
                    .join(KnowledgeItem, DiagnosticQuestion.knowledge_item_id == KnowledgeItem.id)
                    .where(
                        DiagnosticQuestion.domain_code == domain_code,
                        KnowledgeItem.domain_code == domain_code,
                        KnowledgeItem.status == "published",
                    )
                )
            )
        )
        missing_weights = sum(
            set(item.ability_weights_json or {}) != set(ABILITY_DIMENSIONS)
            or abs(sum(float(value) for value in (item.ability_weights_json or {}).values()) - 1)
            > 1e-9
            for item in items
        )
        missing_sources = sum(not str(item.source_title or "").strip() for item in items)
        directions = list((domain.config_json or {}).get("learning_directions") or [])
        rag = candidate_rag_status(domain_code)
        latest_job = self.db.scalar(
            select(IndexBuildJob)
            .where(IndexBuildJob.domain_code == domain_code, IndexBuildJob.status == "success")
            .order_by(IndexBuildJob.id.desc())
        )
        smoke = dict(((latest_job.result_json or {}).get("smoke_test") or {})) if latest_job else {}
        smoke_matches = bool(
            smoke.get("passed")
            and smoke.get("index_version")
            and smoke.get("index_version") == rag.get("index_version")
        )
        smoke_passed = smoke_matches
        check_data = [
            (
                "published_knowledge",
                len(items),
                policy["minimum_published_knowledge"],
                ">=",
                "已发布知识点",
            ),
            (
                "diagnostic_questions",
                valid_question_count,
                policy["minimum_diagnostic_questions"],
                ">=",
                "可用诊断题",
            ),
            ("learning_directions", len(directions), 1, ">=", "学习方向"),
            ("missing_ability_weights", missing_weights, 0, "==", "缺失能力权重"),
            ("missing_sources", missing_sources, 0, "==", "缺失来源定位"),
            ("invalid_relations", cross_domain_relations, 0, "==", "无效或跨领域关系"),
            (
                "prerequisite_cycles",
                int(self._has_cycle(item_ids, relations)),
                0,
                "==",
                "前置关系环",
            ),
            ("candidate_rag_ready", int(bool(rag.get("ready"))), 1, "==", "Candidate RAG"),
            (
                "retrieval_smoke_passed",
                int(smoke_passed),
                1,
                "==",
                "检索与领域隔离验证",
            ),
        ]
        checks = []
        for key, actual, target, operator, label in check_data:
            passed = actual >= target if operator == ">=" else actual == target
            checks.append(
                {
                    "key": key,
                    "label": label,
                    "passed": passed,
                    "level": "ok" if passed else "error",
                    "actual": actual,
                    "target": target,
                }
            )
        try:
            runtime = load_domain_runtime(self.db, domain_code).readiness_payload()
        except DomainRuntimeError as exc:
            runtime = {
                "profile_ready": False,
                "diagnostic_ready": False,
                "rag_ready": bool(rag.get("ready")),
                "generation_ready": False,
                "reasons": [str(exc)],
            }
        for key, label, value in (
            ("profile_runtime_ready", "画像运行时", runtime.get("profile_ready")),
            ("diagnostic_runtime_ready", "诊断运行时", runtime.get("diagnostic_ready")),
            ("generation_runtime_ready", "生成运行时", runtime.get("generation_ready")),
        ):
            passed = bool(value)
            checks.append(
                {
                    "key": key,
                    "label": label,
                    "passed": passed,
                    "level": "ok" if passed else "error",
                    "actual": int(passed),
                    "target": 1,
                }
            )
        return {
            "domain_code": domain_code,
            "status": domain.status,
            "passed": all(check["passed"] for check in checks),
            "policy": policy,
            "checks": checks,
            "counts": {
                "knowledge_items": len(items),
                "diagnostic_questions": valid_question_count,
                "knowledge_relations": len(relations),
            },
            "issues": [
                {
                    "level": check["level"],
                    "message": check["label"],
                    "actual": check["actual"],
                    "target": check["target"],
                }
                for check in checks
                if not check["passed"]
            ],
            "rag": rag,
            "profile_ready": bool(runtime.get("profile_ready")),
            "diagnostic_ready": bool(runtime.get("diagnostic_ready")),
            "rag_ready": bool(runtime.get("rag_ready")),
            "generation_ready": bool(runtime.get("generation_ready")),
            "runtime_reasons": list(runtime.get("reasons") or []),
        }

    def validate(self, domain_code: str) -> dict[str, Any]:
        return self.readiness(domain_code)

    def publish(self, domain_code: str) -> dict[str, Any]:
        domain = self.require(domain_code)
        readiness = self.readiness(domain_code)
        if not readiness["passed"]:
            raise DomainServiceError("DOMAIN_READINESS_FAILED")
        domain.status = "ready"
        self.db.commit()
        self.db.refresh(domain)
        return {"domain": serialize_domain(domain), "readiness": readiness}
