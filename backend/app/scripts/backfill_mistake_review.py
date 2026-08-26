"""Idempotently materialize existing diagnostic and path mistakes."""

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import AnswerRecord, DiagnosticQuestion, Learner
from app.services.mistake_review_service import sync_existing_mistakes


def main() -> None:
    processed = 0
    with SessionLocal() as db:
        pairs = list(
            db.execute(
                select(Learner, DiagnosticQuestion.domain_code)
                .join(AnswerRecord, AnswerRecord.learner_id == Learner.id)
                .join(DiagnosticQuestion, DiagnosticQuestion.id == AnswerRecord.question_id)
                .distinct()
            )
        )
        for learner, domain_code in pairs:
            sync_existing_mistakes(db, learner=learner, domain_code=str(domain_code))
            processed += 1
        db.commit()
    print(f"mistake review backfill completed learner_domains={processed}")


if __name__ == "__main__":
    main()
