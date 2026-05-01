"""Faza 1: external_id/external_source na clients i contacts (Traffit migracja)

Revision ID: 0071_traffit_external_ids
Revises: 0070_backfill_candidate_stage_cv
Create Date: 2026-05-01 09:30:00.000000

Adds idempotent-import columns to `clients` and `contacts` (już istnieje na
`candidates` — migracja 0009). Pozwala UPSERT na `(external_source, external_id)`
przy imporcie z Traffita / future external sources.

- clients.external_id        VARCHAR(100)
- clients.external_source    VARCHAR(50)  DEFAULT 'manual'
- contacts.external_id       VARCHAR(100)
- contacts.external_source   VARCHAR(50)  DEFAULT 'manual'

Indeksy:
- ux_{table}_external_source_id — partial unique (external_source, external_id) WHERE external_id IS NOT NULL
- ix_{table}_external_source    — single column dla source-based analytics

Idempotent (IF NOT EXISTS everywhere). Backfill istniejących rekordów na
'manual'.
"""

from alembic import op
import sqlalchemy as sa

revision = "0071_traffit_external_ids"
down_revision = "0070_backfill_candidate_stage_cv"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("clients", "contacts"):
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
    for table in ("contacts", "clients"):
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
