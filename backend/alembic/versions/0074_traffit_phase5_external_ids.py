"""Faza 5: external_id na jobs, talent_pools, pipeline_templates (Traffit migracja)

Revision ID: 0074_traffit_phase5_external_ids
Revises: 0073_client_required_documents
Create Date: 2026-05-01 12:00:00.000000

Adds idempotent-import columns na pozostałe tabele migrowane z Traffita
(Faza 5 = kandydaci/joby/pipelines/talents). Rozszerzenie wzoru z 0009
(candidates) i 0071 (clients/contacts).

- jobs.external_id, jobs.external_source
- talent_pools.external_id, talent_pools.external_source
- pipeline_templates.external_id, pipeline_templates.external_source

Indeksy: partial unique (external_source, external_id) WHERE external_id
IS NOT NULL + single column index na external_source.

Idempotent (IF NOT EXISTS everywhere).
"""

from alembic import op
import sqlalchemy as sa

revision = "0074_traffit_phase5_external_ids"
down_revision = "0073_client_required_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("jobs", "talent_pools", "pipeline_templates"):
        op.execute(
            sa.text(
                f"""
                ALTER TABLE {table}
                  ADD COLUMN IF NOT EXISTS external_id VARCHAR(100),
                  ADD COLUMN IF NOT EXISTS external_source VARCHAR(50) DEFAULT 'manual'
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS
                  ux_{table}_external_source_id
                  ON {table} (external_source, external_id)
                  WHERE external_id IS NOT NULL
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE INDEX IF NOT EXISTS
                  ix_{table}_external_source
                  ON {table} (external_source)
                """
            )
        )
        op.execute(
            sa.text(
                f"UPDATE {table} SET external_source='manual' WHERE external_source IS NULL"
            )
        )


def downgrade() -> None:
    for table in ("pipeline_templates", "talent_pools", "jobs"):
        op.execute(sa.text(f"DROP INDEX IF EXISTS ix_{table}_external_source"))
        op.execute(sa.text(f"DROP INDEX IF EXISTS ux_{table}_external_source_id"))
        op.execute(
            sa.text(
                f"""
                ALTER TABLE {table}
                  DROP COLUMN IF EXISTS external_source,
                  DROP COLUMN IF EXISTS external_id
                """
            )
        )
