"""candidate_documents.storage_key — Hetzner Object Storage key reference.

Revision ID: 0079_candidate_documents_storage_key
Revises: 0078_password_reset_infrastructure
Create Date: 2026-05-07 14:00:00.000000

Wprowadza kolumnę ``storage_key`` (Optional[str]) na ``candidate_documents``,
która trzyma S3-compatible key w Hetzner Object Storage. Po migracji
``backend/scripts/migrate_cvs_to_object_storage.py`` pole ``file_content``
(BYTEA) zostanie zerowane dla rekordów które mają ``storage_key`` set —
dzięki temu DB skurczy się z 29 GB do ~16 GB (audit-2026-05-07 P-disk).

Reverse strategy: skrypt download-back-to-bytea (nie w tej migracji) wzorem
copy_phase.

Safety:
- Idempotent: ``IF NOT EXISTS`` na index, ``add_column`` nullable=True default NULL.
- Bez DELETE / DROP w upgrade — tylko ADD.
"""

import sqlalchemy as sa
from alembic import op

revision = "0079_candidate_documents_storage_key"
down_revision = "0078_password_reset_infrastructure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_documents",
        sa.Column("storage_key", sa.String(500), nullable=True),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_documents_storage_key "
        "ON candidate_documents (storage_key)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidate_documents_storage_key")
    op.drop_column("candidate_documents", "storage_key")
