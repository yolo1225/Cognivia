from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, GenerationTask, Learner, LearnerProfile, LearningResource
from app.services.learning_package_export_service import export_learning_package
from app.services.learning_package_service import ensure_package_members


def _complete_package(db) -> GenerationTask:
    learner = Learner(public_id="learner_export", target_domain="ai_app_dev")
    db.add(learner)
    db.flush()
    profile = LearnerProfile(
        public_id="profile_export",
        learner_id=learner.id,
        ability_profile_json={},
        weak_knowledge_json=[],
        diagnosis_completed=True,
    )
    db.add(profile)
    db.flush()
    task = GenerationTask(
        public_id="task_export",
        learner_id=learner.id,
        profile_id=profile.id,
        domain_code="ai_app_dev",
        status="completed",
        decision="completed",
        resource_types_json=["lecture", "practice_guide", "graded_quiz"],
    )
    db.add(task)
    db.flush()
    for resource_type in ("lecture", "practice_guide", "graded_quiz"):
        content = "学习内容"
        if resource_type == "graded_quiz":
            content = "题目：什么是 RAG？\n参考答案：检索增强生成\n解析：先检索再生成"
        db.add(
            LearningResource(
                public_id=f"resource_export_{resource_type}",
                generation_task_id=task.id,
                resource_type=resource_type,
                title=resource_type,
                content_md=content,
                difficulty=2,
                sources_json=[{"name": f"{resource_type} 来源"}],
                review_status="passed",
                version=1,
            )
        )
    db.flush()
    ensure_package_members(db, task)
    db.flush()
    return task


@pytest.mark.parametrize(
    ("export_format", "suffix"),
    [("markdown", ".md"), ("pdf", ".pdf"), ("word", ".docx")],
)
def test_export_learning_package_contains_manifest_and_learner_safe_resources(
    tmp_path, monkeypatch, export_format: str, suffix: str
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        task = _complete_package(db)
        monkeypatch.setattr("app.services.learning_package_export_service.EXPORT_ROOT", tmp_path)

        result = export_learning_package(db, task, export_format)

        with ZipFile(tmp_path / result["file_name"]) as archive:
            names = archive.namelist()
            assert names[0] == "00_学习包说明.md"
            assert len(names) == 4
            assert any(name.startswith("01_定制化讲义_") and name.endswith(suffix) for name in names)
            assert any(name.startswith("02_实操指南_") and name.endswith(suffix) for name in names)
            assert any(name.startswith("03_分阶测试_") and name.endswith(suffix) for name in names)
            if export_format == "markdown":
                quiz = archive.read(next(name for name in names if name.startswith("03_"))).decode("utf-8")
                assert "题目：什么是 RAG？" in quiz
                assert "参考答案：" not in quiz
                assert "解析：" not in quiz


@pytest.mark.parametrize("export_format", ["invalid", "markdown "])
def test_export_learning_package_rejects_unknown_format(tmp_path, monkeypatch, export_format: str) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        task = _complete_package(db)
        monkeypatch.setattr("app.services.learning_package_export_service.EXPORT_ROOT", tmp_path)

        with pytest.raises(ValueError, match="export_format"):
            export_learning_package(db, task, export_format)


def test_export_learning_package_requires_completed_full_package(tmp_path, monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        task = _complete_package(db)
        task.status = "running"
        monkeypatch.setattr("app.services.learning_package_export_service.EXPORT_ROOT", tmp_path)

        with pytest.raises(ValueError, match="learning_package_not_completed"):
            export_learning_package(db, task)
