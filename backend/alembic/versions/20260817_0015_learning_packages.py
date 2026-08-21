"""Add composable learning packages and knowledge freshness impacts.

Revision ID: 20260817_0015
Revises: 20260816_0014
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "20260817_0015"
down_revision = "20260816_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_tasks", sa.Column("source_task_id", sa.Integer(), nullable=True))
    op.add_column(
        "generation_tasks",
        sa.Column("is_current_package", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "generation_tasks",
        sa.Column("event_type", sa.String(length=32), nullable=False, server_default="generation"),
    )
    op.create_index("ix_generation_tasks_is_current_package", "generation_tasks", ["is_current_package"])
    op.create_foreign_key(
        "fk_generation_tasks_source_task_id",
        "generation_tasks",
        "generation_tasks",
        ["source_task_id"],
        ["id"],
    )

    op.create_table(
        "learning_package_resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("package_task_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("membership_type", sa.String(length=16), nullable=False, server_default="generated"),
        sa.Column("freshness_status", sa.String(length=32), nullable=False, server_default="current"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["package_task_id"], ["generation_tasks.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["learning_resources.id"]),
        sa.UniqueConstraint("package_task_id", "resource_id", name="uq_package_resource"),
    )
    op.create_index("ix_learning_package_resources_package_task_id", "learning_package_resources", ["package_task_id"])
    op.create_index("ix_learning_package_resources_resource_id", "learning_package_resources", ["resource_id"])

    op.create_table(
        "knowledge_update_impacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("package_task_id", sa.Integer(), nullable=False),
        sa.Column("affected_knowledge_ids_json", sa.JSON(), nullable=False),
        sa.Column("affected_resource_ids_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String(length=255), nullable=False, server_default="knowledge_item_updated"),
        sa.Column("change_sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_task_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["package_task_id"], ["generation_tasks.id"]),
        sa.ForeignKeyConstraint(["resolved_by_task_id"], ["generation_tasks.id"]),
    )
    op.create_index("ix_knowledge_update_impacts_public_id", "knowledge_update_impacts", ["public_id"], unique=True)
    op.create_index("ix_knowledge_update_impacts_package_task_id", "knowledge_update_impacts", ["package_task_id"])
    op.create_index("ix_knowledge_update_impacts_status", "knowledge_update_impacts", ["status"])

    connection = op.get_bind()
    now = datetime.now(UTC)
    tasks = connection.execute(
        sa.text(
            "SELECT id, learner_id, domain_code, status, created_at "
            "FROM generation_tasks ORDER BY learner_id, domain_code, created_at, id"
        )
    ).mappings().all()
    latest_completed: dict[tuple[int, str], int] = {}
    for task in tasks:
        resources = connection.execute(
            sa.text(
                "SELECT id, resource_type, review_status FROM learning_resources "
                "WHERE generation_task_id = :task_id ORDER BY id"
            ),
            {"task_id": task["id"]},
        ).mappings().all()
        for position, resource in enumerate(resources):
            freshness = "knowledge_changed" if resource["review_status"] == "review_stale" else "current"
            connection.execute(
                sa.text(
                    "INSERT INTO learning_package_resources "
                    "(package_task_id, resource_id, membership_type, freshness_status, sort_order, created_at, updated_at) "
                    "VALUES (:task_id, :resource_id, 'generated', :freshness, :sort_order, :now, :now)"
                ),
                {
                    "task_id": task["id"],
                    "resource_id": resource["id"],
                    "freshness": freshness,
                    "sort_order": position,
                    "now": now,
                },
            )
        if task["status"] == "completed" and resources:
            latest_completed[(task["learner_id"], task["domain_code"])] = task["id"]

    for task_id in latest_completed.values():
        connection.execute(
            sa.text("UPDATE generation_tasks SET is_current_package = :current WHERE id = :task_id"),
            {"current": True, "task_id": task_id},
        )
        stale_rows = connection.execute(
            sa.text(
                "SELECT lpr.resource_id FROM learning_package_resources lpr "
                "WHERE lpr.package_task_id = :task_id AND lpr.freshness_status = 'knowledge_changed'"
            ),
            {"task_id": task_id},
        ).mappings().all()
        stale_ids = [row["resource_id"] for row in stale_rows]
        if stale_ids:
            passed_ids: list[int] = []
            for resource_id in stale_ids:
                passed = connection.execute(
                    sa.text(
                        "SELECT id FROM review_reports WHERE resource_id = :resource_id "
                        "AND passed = :passed ORDER BY id DESC"
                    ),
                    {"resource_id": resource_id, "passed": True},
                ).first()
                if passed:
                    passed_ids.append(resource_id)
                    connection.execute(
                        sa.text("UPDATE learning_resources SET review_status = 'passed' WHERE id = :resource_id"),
                        {"resource_id": resource_id},
                    )
            if passed_ids:
                public_ids = [
                    row[0]
                    for row in connection.execute(
                        sa.text("SELECT public_id FROM learning_resources WHERE id IN (" + ",".join(str(value) for value in passed_ids) + ")")
                    )
                ]
                connection.execute(
                    sa.text(
                        "INSERT INTO knowledge_update_impacts "
                        "(public_id, package_task_id, affected_knowledge_ids_json, affected_resource_ids_json, status, reason, change_sequence, created_at, updated_at) "
                        "VALUES (:public_id, :task_id, :knowledge_ids, :resource_ids, 'pending', 'migration_review_stale', 1, :now, :now)"
                    ),
                    {
                        "public_id": f"impact_{uuid4().hex[:12]}",
                        "task_id": task_id,
                        "knowledge_ids": "[]",
                        "resource_ids": json.dumps(public_ids),
                        "now": now,
                    },
                )


def downgrade() -> None:
    op.drop_table("knowledge_update_impacts")
    op.drop_table("learning_package_resources")
    op.drop_constraint("fk_generation_tasks_source_task_id", "generation_tasks", type_="foreignkey")
    op.drop_index("ix_generation_tasks_is_current_package", table_name="generation_tasks")
    op.drop_column("generation_tasks", "event_type")
    op.drop_column("generation_tasks", "is_current_package")
    op.drop_column("generation_tasks", "source_task_id")
