from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, Learner, LearnerProfile, LearningPath
from app.scripts.seed_evaluation_profiles import seed_evaluation_profiles
from app.services.profile_service import is_initial_profile_ready


def test_evaluation_profile_seed_is_idempotent_and_ready() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        assert seed_evaluation_profiles(db) == {
            "learners": 3,
            "profiles": 3,
            "learning_paths": 3,
        }
        db.commit()
        seed_evaluation_profiles(db)
        db.commit()

        learners = list(db.scalars(select(Learner).order_by(Learner.public_id)))
        profiles = list(db.scalars(select(LearnerProfile).order_by(LearnerProfile.public_id)))
        paths = list(db.scalars(select(LearningPath).order_by(LearningPath.public_id)))

        assert len(learners) == len(profiles) == len(paths) == 3
        assert all(is_initial_profile_ready(profile) for profile in profiles)
        assert {profile.ability_profile_json["profile_type"] for profile in profiles} == {
            "beginner",
            "intermediate",
            "advanced",
        }
