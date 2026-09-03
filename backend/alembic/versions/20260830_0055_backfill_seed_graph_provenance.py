"""Backfill declared curriculum-rule provenance for the initial seed graph.

Revision ID: 20260830_0055
Revises: 20260830_0054
"""

from alembic import op


revision = "20260830_0055"
down_revision = "20260830_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE domains
        SET config_json = JSON_SET(
            config_json,
            '$.learning_directions',
            JSON_ARRAY_APPEND(
                COALESCE(JSON_EXTRACT(config_json, '$.learning_directions'), JSON_ARRAY()),
                '$',
                JSON_OBJECT(
                    'value', 'application_engineering',
                    'label', 'AI application engineering foundations',
                    'description', 'Service development, data, deployment, testing, and observability',
                    'match_tags', JSON_ARRAY(
                        'python', 'http', 'rest', 'fastapi', 'pydantic', 'sqlalchemy',
                        'mysql', 'alembic', 'chromadb', 'docker', 'git', 'testing',
                        'pytest', 'frontend', 'vue', 'axios', 'sse', 'streaming',
                        'security', 'secrets', 'privacy', 'observability', 'logging',
                        'tracing', 'document', 'parsing', 'schema', 'database',
                        'validation', 'asyncio', 'concurrency', 'deployment',
                        'configuration', 'collection', 'citation', 'traceability'
                    )
                )
            )
        )
        WHERE domain_code = 'ai_app_dev'
          AND NOT JSON_CONTAINS(
              COALESCE(JSON_EXTRACT(config_json, '$.learning_directions'), JSON_ARRAY()),
              JSON_OBJECT('value', 'application_engineering')
          )
        """
    )

    # These relations are declared in data/seed/knowledge_items.json. They are
    # curriculum policy, not claims that require a fabricated text quotation.
    op.execute(
        """
        UPDATE knowledge_relations AS relation_row
        JOIN knowledge_items AS source_item ON source_item.id = relation_row.source_item_id
        JOIN knowledge_items AS target_item ON target_item.id = relation_row.target_item_id
        JOIN knowledge_documents AS seed_document
          ON seed_document.public_id = 'kdoc_ai_app_dev_seed'
        SET relation_row.evidence_json = JSON_OBJECT(
                'evidence_kind', 'curriculum_rule',
                'rule_version', 'ai-app-dev-seed-curriculum-v1',
                'reason', 'Initial seed package declares the curriculum relation',
                'source_document_public_id', seed_document.public_id,
                'source_knowledge_ids', JSON_ARRAY(source_item.public_id, target_item.public_id)
            ),
            relation_row.generation_method = 'seed_curriculum_rule',
            relation_row.source_document_id = seed_document.id
        WHERE source_item.domain_code = 'ai_app_dev'
          AND target_item.domain_code = 'ai_app_dev'
          AND relation_row.generation_method = 'manual'
          AND relation_row.source_document_id IS NULL
          AND (relation_row.evidence_json IS NULL OR JSON_LENGTH(relation_row.evidence_json) = 0)
        """
    )


def downgrade() -> None:
    # Keep provenance written during upgrade. Removing it would restore an
    # unauditable graph and may discard later maintenance evidence.
    pass
