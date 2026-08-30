"""Preview or apply deterministic knowledge evidence-capability backfill."""

from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.domain_evidence_policy import classify_evidence_capabilities
from app.core.db import SessionLocal
from app.models import KnowledgeItem, LearningPath


def _collect_strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_collect_strings(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_collect_strings(item) for item in value), set())
    return set()


def backfill_evidence_capabilities(
    db: Session,
    *,
    domain_code: str,
    apply: bool = False,
) -> dict[str, object]:
    """Recompute item aggregates and optionally mark affected index/path state."""
    items = list(
        db.scalars(
            select(KnowledgeItem)
            .where(KnowledgeItem.domain_code == domain_code)
            .order_by(KnowledgeItem.public_id)
        )
    )
    changes: list[dict[str, object]] = []
    for item in items:
        before = sorted(str(value) for value in (item.evidence_capabilities_json or []))
        after = classify_evidence_capabilities(item.content_md)
        if before == after:
            continue
        changes.append(
            {
                "knowledge_id": item.public_id,
                "before": before,
                "after": after,
            }
        )
        if apply:
            item.evidence_capabilities_json = after
            item.needs_reembedding = True

    changed_ids = {str(change["knowledge_id"]) for change in changes}
    refreshed_paths = 0
    if apply and changed_ids:
        paths = list(
            db.scalars(
                select(LearningPath)
                .where(LearningPath.domain_code == domain_code)
                .order_by(LearningPath.public_id)
            )
        )
        for path in paths:
            affected = sorted(_collect_strings(path.path_json or {}) & changed_ids)
            if not affected:
                continue
            path.needs_refresh = True
            path.path_json = {
                **(path.path_json or {}),
                "knowledge_update_reason": "evidence_capability_backfill",
                "affected_knowledge_ids": affected,
            }
            refreshed_paths += 1
        db.flush()

    return {
        "domain_code": domain_code,
        "mode": "apply" if apply else "preview",
        "total_items": len(items),
        "changed_items": len(changes),
        "refreshed_paths": refreshed_paths,
        "changes": changes,
        "next_action": "rebuild_candidate_index" if apply and changes else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill deterministic evidence capabilities for one domain."
    )
    parser.add_argument("--domain", required=True, dest="domain_code")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        result = backfill_evidence_capabilities(
            db,
            domain_code=args.domain_code,
            apply=args.apply,
        )
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
