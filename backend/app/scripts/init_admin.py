from datetime import UTC, datetime
from sqlalchemy import select
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import Learner, User


def ensure_admin_learner(db, user: User) -> None:
    if user.learner_id:
        return
    learner = db.scalar(select(Learner).where(Learner.public_id == "learner_admin_initial"))
    if learner is None:
        learner = Learner(
            public_id="learner_admin_initial",
            background="管理员个人学习档案",
            target_domain="ai_app_dev",
            experience_years=0,
            learning_style="mixed",
        )
        db.add(learner)
        db.flush()
    user.learner_id = learner.id

def main() -> None:
    if not settings.initial_admin_password:
        raise SystemExit("INITIAL_ADMIN_PASSWORD is required")
    username = settings.initial_admin_username.strip().lower()
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == username))
        if existing:
            ensure_admin_learner(db, existing)
            db.commit()
            print("Initial administrator already exists; learner profile ensured.")
            return
        user = User(public_id="admin_initial", username=username,
            password_hash=hash_password(settings.initial_admin_password),
            display_name=settings.initial_admin_display_name, role="admin", status="active",
            password_changed_at=datetime.now(UTC))
        db.add(user); db.flush(); ensure_admin_learner(db, user); db.commit()
        print("Initial administrator created with learner profile.")

if __name__ == "__main__": main()
