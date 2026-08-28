"""Idempotently materialize formal evidence from completed graded quizzes."""

from app.core.db import SessionLocal
from app.services.resource_quiz_attempt_service import (
    backfill_completed_attempt_evidence,
)


def main() -> None:
    with SessionLocal() as db:
        materialized = backfill_completed_attempt_evidence(db)
        db.commit()
    print(f"resource quiz evidence backfill completed materialized={materialized}")


if __name__ == "__main__":
    main()
