"""Verify runtime-critical columns after ``alembic upgrade head``."""

from sqlalchemy import create_engine, inspect

from app.core.config import settings


REQUIRED_COLUMNS = {
    "path_node_assessments": {"external_id"},
    "diagnostic_questions": {"status", "disabled_at", "disabled_reason"},
    "idempotency_records": {
        "scope",
        "request_key",
        "status",
        "result_json",
    },
}


def verify_schema(database_url: str | None = None) -> None:
    engine = create_engine(database_url or settings.database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        missing_tables = set(REQUIRED_COLUMNS) - tables
        if missing_tables:
            raise RuntimeError(f"missing runtime tables: {sorted(missing_tables)}")
        for table, required_columns in REQUIRED_COLUMNS.items():
            actual_columns = {column["name"] for column in inspector.get_columns(table)}
            missing_columns = required_columns - actual_columns
            if missing_columns:
                raise RuntimeError(
                    f"missing runtime columns for {table}: {sorted(missing_columns)}"
                )
    finally:
        engine.dispose()


if __name__ == "__main__":
    verify_schema()
