"""Rejestr faktów z rozmów: ``candidate_conversation_facts``.

Revision ID: 0670_conversation_facts
Revises: 0669_drop_embedding_queue_trg

DDL i lustro w ``entrypoint.sh`` czytają ``services/conversation_facts_schema.py``.
"""

from alembic import op

from app.services.conversation_facts_schema import DOWNGRADE_DDL, TABLE_DDL

revision = "0670_conversation_facts"
down_revision = "0669_drop_embedding_queue_trg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
