"""Limit z umowy ramowej: kategoria na kontrakcie i dopłaty technologiczne (F1).

Revision ID: 0708_framework_rate_categories
Revises: 0707_ledger_fx

Kategoria i poziom z umowy ramowej (pozycja ``rate_cards``) na kontrakcie,
dopłaty za technologie premium per klient (``rate_card_adders``) i przyznana
dopłata z potwierdzeniem klienta. DDL ma jedno źródło
(``app/services/framework_rate_schema.py``); lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import framework_rate_schema as schema

revision = "0708_framework_rate_categories"
down_revision = "0707_ledger_fx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
