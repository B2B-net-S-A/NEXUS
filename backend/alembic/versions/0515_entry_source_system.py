"""Źródło wejścia ``system`` — osoba dodana przez silnik dopełniania „Nowych”.

Revision ID: 0515_entry_source_system
Revises: 0514_b2b_generated_signed_on

Decyzje Artura 23.10.2026. SQL ma jedno źródło
(``app/services/new_column_autofill_schema.py``); lista w ``entrypoint.sh``
(blok 0352) jest jej literalnym lustrem.
"""

from alembic import op

from app.services import new_column_autofill_schema as schema

revision = "0515_entry_source_system"
down_revision = "0514_b2b_generated_signed_on"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.CONSTRAINT_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute(
        "UPDATE recruitment_processes SET entry_source = NULL "
        "WHERE entry_source = 'system'"
    )
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
