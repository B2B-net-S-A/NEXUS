"""Wersje Profilu Championa i „Przeczytane” per osoba.

Revision ID: 0730_champion_profile_revisions
Revises: 0729_candidate_terms_requests

Pomysł rekruterki 17.11.2026, decyzja Artura tego dnia (makiety runda 2):
karta „Co się zmieniło od przekazania” w Briefie, zakładka „Zmiany” i zdanie
Delivery Leada. Do tej migracji zapis profilu zostawiał w ``activities`` tylko
„kto i kiedy”, a poprzednia wersja profilu ginęła. DDL ma jedno źródło
(``app/services/champion_profile_revisions_schema.py``); entrypoint wykonuje
je przy każdym starcie.
"""

from alembic import op

from app.services import champion_profile_revisions_schema as schema

revision = "0730_champion_profile_revisions"
down_revision = "0729_candidate_terms_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
