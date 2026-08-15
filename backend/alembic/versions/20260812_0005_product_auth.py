"""product authentication"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0005"
down_revision: str | None = "20260811_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.rename_table("demo_users", "users")
    op.add_column("users", sa.Column("username", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("status", sa.String(32), nullable=False, server_default="disabled"))
    op.add_column("users", sa.Column("learner_id", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_users_learner_id", "users", "learners", ["learner_id"], ["id"])
    op.create_unique_constraint("uq_users_username", "users", ["username"])
    op.create_unique_constraint("uq_users_learner_id", "users", ["learner_id"])
    op.create_index("ix_users_status", "users", ["status"])

def downgrade() -> None:
    op.drop_index("ix_users_status", table_name="users")
    op.drop_constraint("uq_users_learner_id", "users", type_="unique")
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.drop_constraint("fk_users_learner_id", "users", type_="foreignkey")
    for name in ["password_changed_at", "learner_id", "status", "password_hash", "username"]:
        op.drop_column("users", name)
    op.rename_table("users", "demo_users")
