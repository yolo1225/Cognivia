from collections import Counter

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, Learner, LearnerProfile
from app.services.evaluation_case_service import (
    _cases,
    contains_evaluation_marker,
    evaluation_profile_override,
    prepare_evaluation_case,
)
from app.core.config import settings
from app.services.profile_service import (
    default_profile_for_learner,
    is_initial_profile_ready,
    latest_profile_for_learner,
)


def test_v4_evaluation_profile_override_is_explicit_and_uses_active_knowledge_ids(
    monkeypatch,
) -> None:
    marker = "[[evaluation_case:V4-EVAL-001]] 目标知识点：ai_app_dev_overview"
    monkeypatch.setattr(settings, "enable_evaluation_overrides", False)
    assert evaluation_profile_override(marker) is None

    monkeypatch.setattr(settings, "enable_evaluation_overrides", True)
    profile = evaluation_profile_override(marker)

    assert profile is not None
    assert profile.profile_id == "evaluation-profile-beginner-001"
    assert [item.knowledge_id for item in profile.weak_knowledge] == [
        "ai_app_dev_overview",
        "python_api_basics",
    ]


def test_v4_evaluation_cases_cover_generation_feedback_and_challenge() -> None:
    scenarios = Counter(str(item.get("scenario_type")) for item in _cases().values())

    assert scenarios == {
        "initial_generation": 40,
        "feedback_revision": 5,
        "challenge_task": 5,
    }


def test_evaluation_marker_is_reserved_and_case_identity_is_isolated() -> None:
    assert contains_evaluation_marker("[[evaluation_case:V4-EVAL-001]]") is True
    assert contains_evaluation_marker("普通学习目标") is False
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        prepared = prepare_evaluation_case(db, "V4-EVAL-001")
        db.commit()
        learner = db.scalar(select(Learner).where(Learner.public_id == prepared["learner_id"]))
        profile = db.scalar(
            select(LearnerProfile).where(LearnerProfile.public_id == prepared["profile_id"])
        )
        assert learner is not None and learner.is_evaluation is True
        assert profile is not None and profile.profile_source == "evaluation_fixture"
        assert profile.learner_id == learner.id
        assert is_initial_profile_ready(profile) is True
        assert profile.context_snapshot_json["direction_tags"] == [
            "ai_application_engineering"
        ]


def test_normal_learner_never_selects_legacy_evaluation_profile() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        learner = Learner(public_id="learner_normal", is_evaluation=False)
        db.add(learner)
        db.flush()
        db.add(
            LearnerProfile(
                public_id="evaluation_profile_legacy",
                learner_id=learner.id,
                profile_source="evaluation_fixture",
            )
        )
        db.flush()

        assert latest_profile_for_learner(db, learner) is None
        normal = default_profile_for_learner(db, learner)

        assert normal.profile_source == "default_seed"
        assert not normal.public_id.startswith("evaluation_")


def test_evaluation_learner_can_select_evaluation_profile() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        learner = Learner(public_id="evaluation_learner_case", is_evaluation=True)
        db.add(learner)
        db.flush()
        profile = LearnerProfile(
            public_id="evaluation_profile_case",
            learner_id=learner.id,
            profile_source="evaluation_fixture",
        )
        db.add(profile)
        db.flush()

        assert latest_profile_for_learner(db, learner) is profile
