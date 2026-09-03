from app.models import Base
from app.scripts.schema_smoke import REQUIRED_COLUMNS


def test_runtime_schema_smoke_requirements_are_present_in_orm_metadata() -> None:
    for table_name, required_columns in REQUIRED_COLUMNS.items():
        table = Base.metadata.tables[table_name]
        assert required_columns.issubset(table.c.keys())
