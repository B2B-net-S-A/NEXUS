"""Kolejka odczytów CV wsadem: tabela ``cv_parse_batch_items``.

Revision ID: 0750_cv_parse_batch_items
Revises: 0749_rebate_collective_correction

Decyzja Artura z 22.11.2026: CV wgrane przez integrację (scrapery pracuj.pl
i JJIT) do istniejącego profilu czytamy przez Message Batches API, a nie na
żywo. DDL ma jedno źródło (``app/services/cv_parse_batch_schema.py``);
entrypoint wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
Nowa tabela — stary kod jej nie zna, więc zmiana jest zgodna wstecz.
"""

from alembic import op

from app.services import cv_parse_batch_schema as schema

revision = "0750_cv_parse_batch_items"
down_revision = "0749_rebate_collective_correction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
