"""Nowości do przeklikania: postęp osoby przy nowości NEXUSA.

Revision ID: 0617_novelty_progress
Revises: 0616_autofill_more_reasons

Decyzja Artura z 28.10.2026: nowości zamiast artefaktu „co nowego” pokazują
się kropką na przycisku i zaliczają przeklikaniem albo użyciem w pracy. DDL
w ``app/services/novelty_schema.py``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.novelty_schema import TABLE_DDL

revision = "0617_novelty_progress"
down_revision = "0616_autofill_more_reasons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS novelty_progress")
