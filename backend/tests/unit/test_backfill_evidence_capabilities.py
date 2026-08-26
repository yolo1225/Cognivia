from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Domain, KnowledgeItem, Learner, LearningPath
from app.scripts.backfill_evidence_capabilities import backfill_evidence_capabilities


def build_db() -> tuple[Session, KnowledgeItem, LearningPath]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(Domain(domain_code="ad_dev", name="测试领域", status="ready", config_json={}))
    learner = Learner(public_id="learner_backfill", target_domain="ad_dev")
    db.add(learner)
    db.flush()
    item = KnowledgeItem(
        public_id="ki_backfill",
        domain_code="ad_dev",
        name="命令执行",
        category="practice",
        difficulty=2,
        content_md="## 操作步骤\n1. 执行以下命令。\n```bash\npython -m pytest\n```",
        source_title="test",
        ability_weights_json={},
        evidence_capabilities_json=["concept"],
        needs_reembedding=False,
        status="published",
    )
    db.add(item)
    db.flush()
    path = LearningPath(
        public_id="path_backfill",
        learner_id=learner.id,
        domain_code="ad_dev",
        path_json={"nodes": [{"knowledge_id": item.public_id}]},
        needs_refresh=False,
    )
    db.add(path)
    db.commit()
    return db, item, path


def test_preview_does_not_write_and_apply_is_idempotent() -> None:
    db, item, path = build_db()

    preview = backfill_evidence_capabilities(db, domain_code="ad_dev")
    db.refresh(item)
    db.refresh(path)
    assert preview["changed_items"] == 1
    assert item.evidence_capabilities_json == ["concept"]
    assert item.needs_reembedding is False
    assert path.needs_refresh is False

    applied = backfill_evidence_capabilities(db, domain_code="ad_dev", apply=True)
    db.commit()
    db.refresh(item)
    db.refresh(path)
    assert applied["changed_items"] == 1
    assert applied["refreshed_paths"] == 1
    assert item.evidence_capabilities_json == ["command", "concept", "operation"]
    assert item.needs_reembedding is True
    assert path.needs_refresh is True

    repeated = backfill_evidence_capabilities(db, domain_code="ad_dev", apply=True)
    assert repeated["changed_items"] == 0
    assert repeated["refreshed_paths"] == 0
