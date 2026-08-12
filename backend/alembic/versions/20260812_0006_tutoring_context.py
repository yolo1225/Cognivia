"""persist contextual tutoring metadata"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0006"
down_revision: str | None = "20260812_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # MySQL does not allow a DEFAULT on JSON columns. Backfill existing rows
    # before applying the non-null constraint used by the ORM model.
    op.add_column("tutoring_messages", sa.Column("metadata_json", sa.JSON(), nullable=True))
    op.execute("UPDATE tutoring_messages SET metadata_json = JSON_OBJECT() WHERE metadata_json IS NULL")
    op.alter_column("tutoring_messages", "metadata_json", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    op.drop_column("tutoring_messages", "metadata_json")
