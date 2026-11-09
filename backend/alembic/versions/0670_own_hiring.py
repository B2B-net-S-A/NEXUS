"""Rekrutacja własna: proces, zgłoszenia, rezerwacje i historia.

Revision ID: 0670_own_hiring
Revises: 0669_drop_embedding_queue_trg
"""

from alembic import op

from app.services.own_hiring import schema as own_hiring_schema

revision = "0670_own_hiring"
down_revision = "0669_drop_embedding_queue_trg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in own_hiring_schema.TABLE_DDL:
        op.execute(statement)
    with op.get_context().autocommit_block():
        op.execute(own_hiring_schema.ENUM_DDL)


def downgrade() -> None:
    for table in (
        "own_hiring_events",
        "own_hiring_bookings",
        "own_hiring_applications",
        "own_hiring_processes",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
