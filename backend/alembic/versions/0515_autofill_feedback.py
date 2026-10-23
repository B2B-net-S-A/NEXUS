"""Powody odrzucenia osób od systemu (silnik „Nowi na 20”).

Revision ID: 0515_autofill_feedback
Revises: 0514_entry_source_system

Decyzja Artura 23.10.2026: osobę dodaną przez system rekruter odrzuca
z powodem — z powodów poprawiamy wyszukiwanie. SQL ma jedno źródło
(``app/services/autofill_feedback_schema.py``); entrypoint wykonuje ten sam blok.
"""

from alembic import op

from app.services import autofill_feedback_schema as schema

revision = "0515_autofill_feedback"
down_revision = "0514_entry_source_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
