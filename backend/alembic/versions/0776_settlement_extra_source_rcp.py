"""Dodatki do rozliczenia kontraktora: źródło ``rcp`` (koszty delegacji z RCP).

Revision ID: 0776_settlement_extra_source_rcp
Revises: 0775_dl_alert_settlement_order

Przeliczenie rozliczenia zakłada delegację na fakturę dla klienta z wiersza
„Koszty wyjazdu” w RCP (próba IX–X 2026, BNP; ``extras.sync_from_rcp``).
``source`` to VARCHAR + CHECK, poszerzenie = DROP+ADD więzu. SQL i lustro
entrypointu: ``app/services/client_settlement_extras_schema.py``
(``CONSTRAINT_DDL`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import client_settlement_extras_schema as schema

revision = "0776_settlement_extra_source_rcp"
down_revision = "0775_dl_alert_settlement_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(schema.source_constraint_ddl())


def downgrade() -> None:
    op.execute("DELETE FROM client_settlement_extras WHERE source = 'rcp'")
    op.execute(schema.source_constraint_ddl(schema.SOURCES_BEFORE_RCP))
