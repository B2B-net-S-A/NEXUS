"""Rozliczenia klientów: dodatki do rozliczenia kontraktora (polecenie,
weryfikacja techniczna, szkolenie, delegacja) — źródło zgłoszenia, karta sprawy,
fakturowanie klientowi, powód decyzji i dokumenty dodatku.

Revision ID: 0690_settlement_extra_sources
Revises: 0689_settlement_extras

Tabelę ``client_settlement_extras`` zakłada 0689 (koszty integracji BNP); tu
kolumny pozostałych rodzajów. SQL i powody:
``app/services/client_settlement_extras_schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import client_settlement_extras_schema as schema

revision = "0690_settlement_extra_sources"
down_revision = "0689_settlement_extras"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS client_settlement_extra_documents CASCADE")
    for column in schema.ADDED_COLUMNS:
        op.execute(f"ALTER TABLE client_settlement_extras DROP COLUMN IF EXISTS {column}")
