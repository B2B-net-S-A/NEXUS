"""Phase 7a: CV source columns for Traffit / talent-radar / CSV imports

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-16 16:00:00.000000

Adds to `candidates`:
- external_id       VARCHAR(100)  — source-specific id (e.g. traffit_id as string)
- external_source   VARCHAR(50)   — 'manual' | 'traffit' | 'talent_radar' | 'import_csv'
- cv_file_content   BYTEA         — raw CV bytes (PDF/DOCX), optional
- cv_language       VARCHAR(10)   — ISO 639-1 code (pl/en/de/...)
- cv_extracted_data JSONB         — parsed CV payload from source

Plus:
- partial unique index on (external_source, external_id) WHERE external_id IS NOT NULL
  (enables idempotent re-import — same traffit_id won't duplicate)
- index on external_source alone for analytics / source-based filters

Idempotent (IF NOT EXISTS everywhere).
"""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            ALTER TABLE candidates
              ADD COLUMN IF NOT EXISTS external_id VARCHAR(100),
              ADD COLUMN IF NOT EXISTS external_source VARCHAR(50) DEFAULT 'manual',
              ADD COLUMN IF NOT EXISTS cv_file_content BYTEA,
              ADD COLUMN IF NOT EXISTS cv_language VARCHAR(10),
              ADD COLUMN IF NOT EXISTS cv_extracted_data JSONB DEFAULT '{}'::jsonb
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
              ux_candidates_external_source_id
              ON candidates (external_source, external_id)
              WHERE external_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS
              ix_candidates_external_source
              ON candidates (external_source)
            """
        )
    )
    # Backfill existing rows to 'manual' (all rows pre-Phase 7a had no source)
    op.execute(
        sa.text(
            "UPDATE candidates SET external_source='manual' WHERE external_source IS NULL"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DROP INDEX IF EXISTS ix_candidates_external_source")
    )
    op.execute(
        sa.text("DROP INDEX IF EXISTS ux_candidates_external_source_id")
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE candidates
              DROP COLUMN IF EXISTS cv_extracted_data,
              DROP COLUMN IF EXISTS cv_language,
              DROP COLUMN IF EXISTS cv_file_content,
              DROP COLUMN IF EXISTS external_source,
              DROP COLUMN IF EXISTS external_id
            """
        )
    )
