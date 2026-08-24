"""Add evidence-backed, recoverable knowledge imports.

Revision ID: 20260823_0032
Revises: 20260823_0031
"""

import hashlib

from alembic import op
import sqlalchemy as sa


revision = "20260823_0032"
down_revision = "20260823_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_items", sa.Column("external_id", sa.String(128), nullable=True))
    op.create_unique_constraint(
        "uq_knowledge_items_domain_external", "knowledge_items", ["domain_code", "external_id"]
    )
    for column in (
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("evidence_json", sa.JSON(), nullable=False, server_default=sa.text("('{}')")),
        sa.Column("generation_method", sa.String(64), nullable=False, server_default="manual"),
        sa.Column("source_document_id", sa.Integer(), nullable=True),
    ):
        op.add_column("knowledge_relations", column)
    op.create_foreign_key(
        "fk_knowledge_relations_source_document",
        "knowledge_relations",
        "knowledge_documents",
        ["source_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_knowledge_relations_source_document_id", "knowledge_relations", ["source_document_id"]
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("domain_code", sa.String(64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading_path_json", sa.JSON(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("previous_chunk_id", sa.Integer(), nullable=True),
        sa.Column("next_chunk_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["previous_chunk_id"], ["knowledge_chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["next_chunk_id"], ["knowledge_chunks.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunks_document_index"),
    )
    op.create_index("ix_knowledge_chunks_public_id", "knowledge_chunks", ["public_id"])
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_index("ix_knowledge_chunks_domain_code", "knowledge_chunks", ["domain_code"])
    op.create_index("ix_knowledge_chunks_checksum", "knowledge_chunks", ["checksum"])

    op.create_table(
        "knowledge_import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False, unique=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("domain_code", sa.String(64), nullable=False),
        sa.Column("current_step", sa.String(64), nullable=False, server_default="queued"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("input_version", sa.String(64), nullable=False),
        sa.Column("artifact_manifest_json", sa.JSON(), nullable=False),
        sa.Column("step_state_json", sa.JSON(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_knowledge_import_runs_public_id", "knowledge_import_runs", ["public_id"])
    op.create_index("ix_knowledge_import_runs_document_id", "knowledge_import_runs", ["document_id"])
    op.create_index("ix_knowledge_import_runs_domain_code", "knowledge_import_runs", ["domain_code"])
    op.create_index("ix_knowledge_import_runs_status", "knowledge_import_runs", ["status"])
    op.create_index("ix_knowledge_import_runs_input_version", "knowledge_import_runs", ["input_version"])
    op.create_index(
        "ix_import_runs_domain_status", "knowledge_import_runs", ["domain_code", "status"]
    )

    op.create_table(
        "knowledge_item_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("knowledge_item_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("import_run_id", sa.Integer(), nullable=True),
        sa.Column("source_quote_hash", sa.String(64), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(32), nullable=False, server_default="staged"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["knowledge_item_id"], ["knowledge_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["knowledge_chunks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["import_run_id"], ["knowledge_import_runs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "knowledge_item_id", "chunk_id", name="uq_knowledge_item_sources_item_chunk"
        ),
    )
    for name, columns in (
        ("ix_knowledge_item_sources_knowledge_item_id", ["knowledge_item_id"]),
        ("ix_knowledge_item_sources_chunk_id", ["chunk_id"]),
        ("ix_knowledge_item_sources_document_id", ["document_id"]),
        ("ix_knowledge_item_sources_import_run_id", ["import_run_id"]),
        ("ix_knowledge_item_sources_status", ["status"]),
    ):
        op.create_index(name, "knowledge_item_sources", columns)

    op.create_table(
        "domain_index_manifests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_code", sa.String(64), nullable=False, unique=True),
        sa.Column("active_collection", sa.String(255), nullable=False),
        sa.Column("previous_collection", sa.String(255), nullable=True),
        sa.Column("index_version", sa.String(80), nullable=False),
        sa.Column("source_data_version", sa.String(80), nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("distance_metric", sa.String(32), nullable=False, server_default="cosine"),
        sa.Column("chunker_version", sa.String(64), nullable=False),
        sa.Column("indexed_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_domain_index_manifests_domain_code", "domain_index_manifests", ["domain_code"])
    op.create_index("ix_domain_index_manifests_index_version", "domain_index_manifests", ["index_version"])
    op.create_index("ix_domain_index_manifests_status", "domain_index_manifests", ["status"])

    _backfill_sources()


def _backfill_sources() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, public_id, domain_code, name, content_md, source_document_id "
            "FROM knowledge_items WHERE source_document_id IS NOT NULL"
        )
    ).mappings()
    for row in rows:
        content = str(row["content_md"] or "").strip()
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        public_id = f"kchunk_seed_{hashlib.sha256(str(row['public_id']).encode()).hexdigest()[:16]}"
        result = bind.execute(
            sa.text(
                "INSERT INTO knowledge_chunks "
                "(public_id, document_id, domain_code, chunk_index, heading_path_json, content, "
                "checksum, created_at, updated_at) "
                "VALUES (:public_id, :document_id, :domain_code, :chunk_index, :heading, :content, "
                ":checksum, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "public_id": public_id,
                "document_id": row["source_document_id"],
                "domain_code": row["domain_code"],
                "chunk_index": int(row["id"]),
                "heading": '["' + str(row["name"]).replace('"', '\\"') + '"]',
                "content": content,
                "checksum": checksum,
            },
        )
        chunk_id = result.lastrowid
        if chunk_id is None:
            chunk_id = bind.execute(
                sa.text("SELECT id FROM knowledge_chunks WHERE public_id=:public_id"),
                {"public_id": public_id},
            ).scalar_one()
        bind.execute(
            sa.text(
                "INSERT INTO knowledge_item_sources "
                "(knowledge_item_id, chunk_id, document_id, source_quote_hash, is_primary, status, "
                "created_at, updated_at) VALUES (:item_id, :chunk_id, :document_id, :checksum, 1, "
                "'published', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "item_id": row["id"],
                "chunk_id": chunk_id,
                "document_id": row["source_document_id"],
                "checksum": checksum,
            },
        )


def downgrade() -> None:
    op.drop_table("domain_index_manifests")
    op.drop_table("knowledge_item_sources")
    op.drop_table("knowledge_import_runs")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_relations_source_document_id", table_name="knowledge_relations")
    op.drop_constraint(
        "fk_knowledge_relations_source_document", "knowledge_relations", type_="foreignkey"
    )
    for column in ("source_document_id", "generation_method", "evidence_json", "confidence"):
        op.drop_column("knowledge_relations", column)
    op.drop_constraint("uq_knowledge_items_domain_external", "knowledge_items", type_="unique")
    op.drop_column("knowledge_items", "external_id")
