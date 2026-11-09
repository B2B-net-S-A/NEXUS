"""Rekrutacja własna: proces, zgłoszenia, rezerwacje i historia.

Revision ID: 0673_own_hiring
Revises: 0672_sales_call_outcome
"""

from alembic import op

from app.services.own_hiring import schema as own_hiring_schema

revision = "0673_own_hiring"
down_revision = "0672_sales_call_outcome"
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
