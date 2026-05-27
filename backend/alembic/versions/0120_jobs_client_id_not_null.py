"""Enforce NOT NULL on jobs.client_id + cleanup orphan jobs.

Revision ID: 0120_jobs_client_id_not_null
Revises: 0119_candidate_notice_period_unit
Create Date: 2026-05-27 14:00:00.000000

Backstory: QA sweep 2026-05-27 wykrył na /jobs orphan record "[E2E-PendingVerif]
DELETE ME" (status=published, client_id=NULL) oraz 20 innych junk recordów
(NO CLIENT, POLL × 16, Smoke Prepy × 2, [CC-smoke]) — wszystkie z `created_by=9`
(Artur, testy z 2026-04-22/23). Importer Traffit już dawno skipuje takie
wpisy (services/traffit/importer.py L1023), ale API POST /jobs nadal przyjmuje
client_id=None bo Pydantic schema ma `Optional[int] = None`.

Ta migracja:
1. Safety-net: jeszcze raz oznacza wszystkie orphan jobs jako `status='closed'`
   z `close_reason='other'` i auditem w `close_notes` (poprzednia ręczna
   sesja zrobiła to samo, ale migracja musi być idempotent i sama-w-sobie
   poprawna gdy odpalana na świeżej replice).
2. ALTER TABLE jobs ALTER COLUMN client_id SET NOT NULL — niezgodny INSERT
   blokowany na poziomie DB. Towarzysząca zmiana w `app/models/job.py`
   (Mapped[int]) i `app/schemas/job.py` (Field(..., gt=0)) dopina warstwy
   wyżej.

Reversible: downgrade przywraca nullability (dane nie znikają — close_notes
zachowane przy reverted constraint).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0120_jobs_client_id_not_null"
down_revision = "0119_candidate_notice_period_unit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent cleanup of any remaining orphan jobs (client_id IS NULL).
    # On prod already done manually during PR fix/qa-jobs-orphan-cleanup
    # session; this is a safety net for restored snapshots / fresh replicas.
    op.execute(
        """
        UPDATE jobs
        SET
            status = 'closed',
            close_reason = 'other',
            close_notes = COALESCE(
                close_notes,
                'cleanup 2026-05-27: orphan job (NULL client_id) - test/junk data'
            ),
            closed_at = COALESCE(closed_at, NOW()),
            updated_at = NOW()
        WHERE client_id IS NULL;
        """
    )

    # Belt-and-braces: assert post-cleanup state before ALTER. If any orphan
    # somehow slipped through (concurrent INSERT during migration window —
    # extremely unlikely but cheap to check), abort the migration.
    connection = op.get_bind()
    remaining = connection.execute(
        sa.text("SELECT COUNT(*) FROM jobs WHERE client_id IS NULL")
    ).scalar_one()
    if remaining > 0:
        raise RuntimeError(
            f"Refusing to ALTER jobs.client_id NOT NULL: {remaining} orphan "
            f"rows still present. Investigate and re-run."
        )

    op.alter_column(
        "jobs",
        "client_id",
        existing_type=sa.Integer(),
        nullable=False,
    )


def downgrade() -> None:
    # Revert NOT NULL. close_notes stays — operator can find / replay the
    # cleanup post-mortem if needed.
    op.alter_column(
        "jobs",
        "client_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
