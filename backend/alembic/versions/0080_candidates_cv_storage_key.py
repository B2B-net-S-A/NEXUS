"""candidates.cv_storage_key — round 2 of Hetzner Object Storage migration.

Revision ID: 0080_candidates_cv_storage_key
Revises: 0079_candidate_documents_storage_key
Create Date: 2026-05-07 14:00:00.000000

Round 1 (migracja 0079) zmigrowała `candidate_documents.file_content` (13 GB).
Round 2 (ta migracja) zmigruje `candidates.cv_file_content` (11 GB, 41,017 rec)
— main "primary CV" per kandydat, używany przez Traffit/Talent Radar importerów.

Wprowadza kolumnę `cv_storage_key` (Optional[str], indexed) na `candidates`.
Po migracji `backend/scripts/migrate_candidates_cv_to_object_storage.py`
+ --finalize-delete-bytea + VACUUM FULL → DB skurczy się o ~11 GB więcej.

Safety: idempotent, ADD only, nullable=True default NULL.
"""

import sqlalchemy as sa
from alembic import op

revision = "0080_candidates_cv_storage_key"
down_revision = "0079_candidate_documents_storage_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidates", sa.Column("cv_storage_key", sa.String(500), nullable=True)
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_cv_storage_key "
        "ON candidates (cv_storage_key)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidates_cv_storage_key")
    op.drop_column("candidates", "cv_storage_key")
