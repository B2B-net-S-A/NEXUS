"""Propozycje: status „wygasła” i otwarcia skrzynki (audyt 06.10.2026).

Revision ID: 0422_job_proposal_expiry
Revises: 0421_recommendation_card_assist

Zamknięcie rekrutacji wygasza jej otwarte propozycje (``expired``), a każde
otwarcie „Do przejrzenia” zostawia jedno zdarzenie na (rekrutację, osobę,
dzień) w ``job_proposal_inbox_opens``. DDL ma jedno źródło z entrypointem:
``app/services/job_proposal_expiry_schema.py``. Jednorazowe wygaszenie
propozycji w rekrutacjach zamkniętych przed wdrożeniem robi blok
w ``entrypoint.sh`` (paragon w ``app_settings``).
"""

from alembic import op

from app.services import job_proposal_expiry_schema as schema

revision = "0422_job_proposal_expiry"
down_revision = "0421_recommendation_card_assist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.CONSTRAINT_DDL:
        op.execute(stmt)
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Kod sprzed tej rewizji nie zna statusu `expired` — skasowanie wierszy
    # zgubiłoby historię propozycji, a przepisanie na `proposed` wskrzesiłoby
    # osoby z zamkniętych rekrutacji.
    op.execute(
        """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM job_proposals WHERE status = 'expired') THEN
                RAISE EXCEPTION 'Downgrade 0422 odmawia: job_proposals ma wiersze expired.';
            END IF;
        END $$"""
    )
    op.execute(
        """DO $$ BEGIN
            ALTER TABLE job_proposals DROP CONSTRAINT IF EXISTS ck_job_proposals_status;
            ALTER TABLE job_proposals ADD CONSTRAINT ck_job_proposals_status
                CHECK (status IN ('proposed', 'dismissed', 'added'));
        END $$"""
    )
    op.execute("DROP TABLE IF EXISTS job_proposal_inbox_opens")
