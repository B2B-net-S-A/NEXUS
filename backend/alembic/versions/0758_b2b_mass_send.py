"""Masowa wysyłka nowej umowy B2B do aktywnych kontraktorów (E5b, 22.11.2026).

Revision ID: 0758_b2b_mass_send
Revises: 0757_notice_mail

Tabele ``b2b_mass_send_batches`` i ``b2b_mass_send_items``. DDL ma jedno
źródło (``app/services/b2b_mass_send/schema_sql.py``); ``entrypoint.sh``
wykonuje je przy każdym starcie. Same dodania: stary kod działa na nowym
schemacie.
"""

from alembic import op

from app.services.b2b_mass_send import schema_sql as schema

revision = "0758_b2b_mass_send"
down_revision = "0757_notice_mail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
