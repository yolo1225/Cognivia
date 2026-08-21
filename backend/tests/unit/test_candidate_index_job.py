from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, Domain
from app.services import candidate_index_job


def _db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_rebuild_lock_is_scoped_to_domain() -> None:
    db = _db()
    db.add_all(
        [
            Domain(domain_code="domain_a", name="领域 A", status="ready", config_json={}),
            Domain(domain_code="domain_b", name="领域 B", status="ready", config_json={}),
        ]
    )
    db.commit()

    first = candidate_index_job.try_start(db, "domain_a")
    duplicate = candidate_index_job.try_start(db, "domain_a")
    parallel = candidate_index_job.try_start(db, "domain_b")

    assert first is not None
    assert duplicate is None
    assert parallel is not None
    assert parallel.domain_code == "domain_b"
