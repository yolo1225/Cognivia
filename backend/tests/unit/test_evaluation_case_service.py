from app.services.evaluation_case_service import evaluation_profile_override
from app.core.config import settings


def test_v2_evaluation_profile_override_is_explicit_and_uses_active_knowledge_ids(
    monkeypatch,
) -> None:
    marker = "[[evaluation_case:V2-EVAL-001]] 目标知识点：ai_app_dev_overview"
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
