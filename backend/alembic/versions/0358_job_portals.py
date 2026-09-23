"""Multiposting (Pracuj.pl, JustJoinIT): szkielet kolejki publikacji.

Revision ID: 0358_job_portals
Revises: 0357_order_group_cancel

* ``job_postings`` dostaje kolumny kolejki: ``last_error``, ``attempts``,
  ``payload_hash`` (odcisk treści wysłanej do portalu), ``public_profile_hash``
  (odcisk zatwierdzonego opisu publicznego, z którego zbudowano treść),
  ``created_by``, ``last_synced_at``.
* ``postingstatus`` + ``publishing`` (czeka na worker) i ``failed``.
* Najwyżej jedna ŻYWA publikacja rekrutacji na portal (częściowy UNIQUE).
* Symulowane wiersze ``SIM-…`` z dawnej zakładki „Portale” znikają — to nie
  były publikacje, tylko losowe liczby wyświetleń.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0358_job_portals"
down_revision = "0357_order_group_cancel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE poza transakcją migracji: nowa wartość jest używana niżej
    # w predykacie indeksu, a Postgres nie pozwala użyć jej w tej samej
    # transakcji, w której ją dodano.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE postingstatus ADD VALUE IF NOT EXISTS 'publishing'")
        op.execute("ALTER TYPE postingstatus ADD VALUE IF NOT EXISTS 'failed'")
    op.execute("DELETE FROM job_postings WHERE external_id LIKE 'SIM-%'")
    op.execute("ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS last_error TEXT")
    op.execute(
        "ALTER TABLE job_postings "
        "ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS payload_hash VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE job_postings "
        "ADD COLUMN IF NOT EXISTS public_profile_hash VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS created_by INTEGER "
        "REFERENCES users (id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_job_postings_live_per_portal "
        "ON job_postings (job_id, portal) "
        "WHERE status IN ('publishing', 'published')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_job_postings_live_per_portal")
    op.execute(
        "UPDATE job_postings SET status = 'draft' "
        "WHERE status IN ('publishing', 'failed')"
    )
    for column in (
        "last_synced_at",
        "created_by",
        "public_profile_hash",
        "payload_hash",
        "attempts",
        "last_error",
    ):
        op.execute(f"ALTER TABLE job_postings DROP COLUMN IF EXISTS {column}")
    # Wartości enuma zostają — Postgres nie ma `ALTER TYPE … DROP VALUE`.
