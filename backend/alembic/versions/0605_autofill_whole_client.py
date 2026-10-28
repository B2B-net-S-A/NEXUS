"""Odrzucenie osoby od systemu na cały klient.

Revision ID: 0605_autofill_whole_client
Revises: 0604_esign_cc

Decyzja Artura 27.10.2026 po analizie 133 odrzuceń: 13 z 20 „Inne” to klient,
nie osoba („pracuje w Nordei przez inną firmę”, „nie chce do Nordei”). Dwa
nowe powody (``client_employed``, ``client_refused``) i kolumna
``whole_client`` — silnik nie podsuwa takiej osoby żadnej rekrutacji klienta.
SQL ma jedno źródło (``app/services/autofill_feedback_schema.py``); entrypoint
wykonuje cały ``TABLE_DDL`` z tym blokiem przy każdym starcie.
"""

from alembic import op

from app.services import autofill_feedback_schema as schema

revision = "0605_autofill_whole_client"
down_revision = "0604_esign_cc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.WHOLE_CLIENT_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Więz powodów zostaje szerszy — nowe powody w wierszach nie znikają.
    op.execute("ALTER TABLE autofill_feedback DROP COLUMN IF EXISTS whole_client")
