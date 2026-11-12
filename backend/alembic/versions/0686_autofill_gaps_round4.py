"""Powody z porcji dnia (runda 4) i braki przy pozycjach.

Revision ID: 0686_autofill_gaps_round4
Revises: 0685_sales_payment_ebi24

Decyzja Artura 12.11.2026 po analizie 323 odrzuceń z porcji dnia: „Brak
polskiego”, „Angielski za słaby”, „Forma umowy (UoP / B2B)” i kolumna
``gaps`` z brakami klikniętymi przy pozycjach wymagań. DDL ma jedno źródło
(``app/services/autofill_feedback_schema.py``); entrypoint wykonuje je przy
każdym starcie.
"""

from alembic import op

from app.services import autofill_feedback_schema as schema

revision = "0686_autofill_gaps_round4"
down_revision = "0685_sales_payment_ebi24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.GAPS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Więz zostaje szerszy, a kolumna zostaje — nowe wiersze nie tracą danych.
    pass
