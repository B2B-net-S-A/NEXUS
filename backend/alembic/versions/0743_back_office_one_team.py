"""Jeden zespół back office'u, sprawy „na zewnątrz” i ściąga klienta (19.11.2026).

Revision ID: 0743_back_office_one_team
Revises: 0742_ledger_bank_balances

Decyzje Artura z 10.11 i 19.11.2026: back office to jeden zespół bez podziału
na Opiekę, Finanse, Umowy i Zamówienia; sprawę bierze pierwsza wolna osoba,
a dawne kolumny zespołów zostają na kartach jako etykiety. Tabela
``bo_members`` trzyma skład z rolą i przełącznikiem rozmów z portalu,
``bo_cards.outside_team`` — dział, na który sprawa czeka, a ``bo_client_notes``
— ściągę klienta. DDL ma jedno źródło
(``app/services/back_office_team_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import back_office_team_schema as schema

revision = "0743_back_office_one_team"
down_revision = "0742_ledger_bank_balances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
