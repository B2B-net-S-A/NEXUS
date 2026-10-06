"""Propozycje z bazy: status ``expired`` (07.10.2026).

Revision ID: 0422_job_proposals_expired
Revises: 0421_recommendation_card_assist

Nocny przegląd bazy publikuje od 07.10.2026 WSZYSTKIE osoby powyżej progu
(bez limitu 60), a propozycje ``full_base``, których nowszy, kompletny przegląd
rekrutacji już nie zaproponował, dostają ``expired`` zamiast znikać — wiersz
zostaje (``request_allocation`` czyta istnienie ``full_base`` jako dowód
przeglądu). DDL ma jedno źródło z entrypointem:
``app/services/job_proposal_feedback_schema.py``.
"""

from alembic import op

from app.services import job_proposal_feedback_schema as schema

revision = "0422_job_proposals_expired"
down_revision = "0421_recommendation_card_assist"
branch_labels = None
depends_on = None

_OLD_STATUSES = tuple(s for s in schema.STATUSES if s != "expired")


def upgrade() -> None:
    for stmt in schema.STATUS_CONSTRAINT_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Kod sprzed tej rewizji nie zna `expired` — zamiana na `proposed` po cichu
    # wróciłaby do skrzynki osoby, których nowszy przegląd już nie proponuje.
    op.execute(
        """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM job_proposals WHERE status = 'expired') THEN
                RAISE EXCEPTION 'Downgrade 0422 odmawia: job_proposals ma wiersze expired.';
            END IF;
        END $$"""
    )
    old = ", ".join(f"'{s}'" for s in _OLD_STATUSES)
    op.execute(
        f"""DO $$ BEGIN
            ALTER TABLE job_proposals DROP CONSTRAINT IF EXISTS ck_job_proposals_status;
            ALTER TABLE job_proposals ADD CONSTRAINT ck_job_proposals_status
                CHECK (status IN ({old}));
        END $$"""
    )
