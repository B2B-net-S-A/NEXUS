"""„Ludzie w NEXUSIE” — rozliczenia zespołu (etap 4, R1–R12).

Revision ID: 0467_hr_settlements
Revises: 0466_care_announcements

Zakres: dane do rozliczeń osoby (NIP, wykaz VAT, rachunek zaszyfrowany,
identyfikator w Symfonii), rozliczenia zamkniętego miesiąca, faktury od osób
(KSeF albo PDF) i zdarzenia płatności. SQL ma jedno źródło
(``app/services/hr_settlement_schema.py``) — ten sam moduł czyta
``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_settlement_schema as schema

revision = "0467_hr_settlements"
down_revision = "0466_care_announcements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
