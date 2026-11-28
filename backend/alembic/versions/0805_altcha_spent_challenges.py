"""ALTCHA: zużyte wyzwania formularzy zgłoszeń (ochrona przed powtórką).

Revision ID: 0805_altcha_spent_challenges
Revises: 0804_sales_call_record_removed

Decyzja Artura z 28.11.2026 (pakiet „Ochrona wejścia”: ClamAV + ALTCHA).
Tabela ``altcha_spent_challenges`` — jedno rozwiązanie zagadki = jedno
zgłoszenie, także przy kilku procesach web. Same dodania, stary kod działa
na nowym schemacie. DDL w ``app/services/altcha_schema.py``; lustro
w ``entrypoint.sh``. → docs/claude/podstawy/skan-plikow-i-altcha.md
"""

from alembic import op

from app.services import altcha_schema as schema

revision = "0805_altcha_spent_challenges"
down_revision = "0804_sales_call_record_removed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in schema.TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in schema.DOWNGRADE_DDL:
        op.execute(statement)
