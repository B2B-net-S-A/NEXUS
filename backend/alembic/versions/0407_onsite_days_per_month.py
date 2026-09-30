"""Dni w biurze w miesiącu przy rekrutacji (30.09.2026).

Revision ID: 0407_onsite_days_per_month
Revises: 0406_job_deadline_time

Klienci piszą „raz w miesiącu” — rekrutacja znała tylko dni na tydzień.
``jobs.onsite_days_per_month`` trzyma wpis miesięczny; liczbę tygodniową
dla bramek liczy ``app/services/office_days.py``. DDL ma jedno źródło
z entrypointem (``office_days.COLUMN_DDL``).
"""

from alembic import op

from app.services import office_days

revision = "0407_onsite_days_per_month"
down_revision = "0406_job_deadline_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(office_days.COLUMN_DDL)


def downgrade() -> None:
    # Wpis miesięczny istnieje tylko w tej kolumnie — kod sprzed tej rewizji
    # widziałby wyłącznie wyliczoną liczbę tygodniową.
    op.execute(
        """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM jobs WHERE onsite_days_per_month IS NOT NULL) THEN
                RAISE EXCEPTION 'Downgrade 0407 odmawia: jobs ma wpisy onsite_days_per_month.';
            END IF;
        END $$"""
    )
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS onsite_days_per_month")
