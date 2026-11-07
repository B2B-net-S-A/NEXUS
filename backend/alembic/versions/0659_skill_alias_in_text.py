"""Wariant nazwy w słowniku: znacznik „liczy się w tekście CV”.

Revision ID: 0659_skill_alias_in_text
Revises: 0658_skill_proposals

Decyzja Artura 07.11.2026 (etap 3a słownika): QC i strażnik generatora
szukają wymagania w tekście także po wariantach narzędzi, metodyk, AI,
standardów i dziedzin. Wariant będący zwykłym słowem („project” przy
„Microsoft Project”) domyślnie się nie liczy, a osoba prowadząca słownik
może to przestawić. DDL w ``app/services/skill_alias_text_schema.py``,
lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.skill_alias_text_schema import COLUMN_DDL, DOWNGRADE_DDL

revision = "0659_skill_alias_in_text"
down_revision = "0658_skill_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in COLUMN_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
