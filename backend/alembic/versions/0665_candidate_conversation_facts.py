"""Rejestr faktów z rozmów: ``candidate_conversation_facts``.

Revision ID: 0665_conversation_facts
Revises: 0664_dl_alert_invoice_no_line

DDL i lustro w ``entrypoint.sh`` czytają ``services/conversation_facts_schema.py``.
"""

from alembic import op

from app.services.conversation_facts_schema import DOWNGRADE_DDL, TABLE_DDL

revision = "0665_conversation_facts"
down_revision = "0664_dl_alert_invoice_no_line"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
