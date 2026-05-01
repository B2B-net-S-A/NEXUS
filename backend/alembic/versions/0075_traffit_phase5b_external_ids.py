"""Faza 5b: external_id na pipeline_stage_defs, candidate_stages, activities

Revision ID: 0075_traffit_phase5b_external_ids
Revises: 0074_traffit_phase5_external_ids
Create Date: 2026-05-01 14:00:00.000000

Faza 5b importuje:
- recruitment_history (151k stage moves) → candidate_stages (idempotent UPSERT)
- /employees/activities (343k activity records) → activities (idempotent UPSERT)
- Per-workflow stage IDs (Traffit state.id) → pipeline_stage_defs (lookup table
  dla mapowania workflow_state.id na nasz stage_def_id przy historii ruchów)

Wymaga external_id na trzech tabelach żeby UPSERTy były idempotentne.
Wzór: 0009 (candidates) + 0071 (clients/contacts) + 0074 (jobs/talents/templates).

Idempotent (IF NOT EXISTS everywhere).
"""

from alembic import op
import sqlalchemy as sa

revision = "0075_traffit_phase5b_external_ids"
down_revision = "0074_traffit_phase5_external_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("pipeline_stage_defs", "candidate_stages", "activities"):
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
    for table in ("activities", "candidate_stages", "pipeline_stage_defs"):
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
