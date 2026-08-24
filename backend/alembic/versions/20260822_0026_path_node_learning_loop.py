"""Bind learning packages to path nodes and add node assessments.

Revision ID: 20260822_0026
Revises: 20260820_0025
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "20260822_0026"
down_revision = "20260820_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_tasks", sa.Column("learning_path_id", sa.Integer(), nullable=True))
    op.add_column("generation_tasks", sa.Column("path_node_id", sa.String(length=128), nullable=True))
    op.create_foreign_key(
        "fk_generation_tasks_learning_path_id",
        "generation_tasks",
        "learning_paths",
        ["learning_path_id"],
        ["id"],
    )
    op.create_index("ix_generation_tasks_learning_path_id", "generation_tasks", ["learning_path_id"])
    op.create_index("ix_generation_tasks_path_node_id", "generation_tasks", ["path_node_id"])
    op.create_table(
        "path_node_assessments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("learning_path_id", sa.Integer(), nullable=False),
        sa.Column("path_node_id", sa.String(length=128), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("answer_record_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["learning_path_id"], ["learning_paths.id"]),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["question_id"], ["diagnostic_questions.id"]),
        sa.ForeignKeyConstraint(["answer_record_id"], ["answer_records.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns, unique in (
        ("ix_path_node_assessments_public_id", ["public_id"], True),
        ("ix_path_node_assessments_learning_path_id", ["learning_path_id"], False),
        ("ix_path_node_assessments_path_node_id", ["path_node_id"], False),
        ("ix_path_node_assessments_learner_id", ["learner_id"], False),
        ("ix_path_node_assessments_status", ["status"], False),
    ):
        op.create_index(name, "path_node_assessments", columns, unique=unique)

    connection = op.get_bind()
    for row in connection.execute(sa.text("SELECT id, path_json FROM learning_paths")):
        payload = json.loads(row.path_json) if isinstance(row.path_json, str) else row.path_json
        if not isinstance(payload, dict) or not isinstance(payload.get("node_states"), dict):
            continue
        current_ids = [
            node_id
            for node_id, state in payload["node_states"].items()
            if isinstance(state, dict) and state.get("status") == "current"
        ]
        if len(current_ids) <= 1:
            continue
        selected = payload.get("current_node_id")
        selected = selected if selected in current_ids else current_ids[0]
        for node_id in current_ids:
            if node_id != selected:
                payload["node_states"][node_id]["status"] = "locked"
        payload["current_node_id"] = selected
        connection.execute(
            sa.text("UPDATE learning_paths SET path_json = :payload WHERE id = :id"),
            {"payload": json.dumps(payload, ensure_ascii=False), "id": row.id},
        )


def downgrade() -> None:
    for name in (
        "ix_path_node_assessments_status",
        "ix_path_node_assessments_learner_id",
        "ix_path_node_assessments_path_node_id",
        "ix_path_node_assessments_learning_path_id",
        "ix_path_node_assessments_public_id",
    ):
        op.drop_index(name, table_name="path_node_assessments")
    op.drop_table("path_node_assessments")
    op.drop_index("ix_generation_tasks_path_node_id", table_name="generation_tasks")
    op.drop_index("ix_generation_tasks_learning_path_id", table_name="generation_tasks")
    op.drop_constraint("fk_generation_tasks_learning_path_id", "generation_tasks", type_="foreignkey")
    op.drop_column("generation_tasks", "path_node_id")
    op.drop_column("generation_tasks", "learning_path_id")
