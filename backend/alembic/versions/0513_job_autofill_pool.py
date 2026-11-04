"""Pula dopełniania „Nowych” z nocnego przeglądu bazy.

Revision ID: 0513_job_autofill_pool
Revises: 0512_care_board_waiting_decision

Najlepsze osoby z najnowszego przeglądu automatycznego rekrutacji, z każdym
wynikiem (decyzja Artura 23.10.2026). SQL ma jedno źródło
(``app/services/job_autofill_pool_schema.py``); entrypoint wykonuje ten sam blok.
"""

from alembic import op

from app.services import job_autofill_pool_schema as schema

revision = "0513_job_autofill_pool"
down_revision = "0512_care_board_waiting_decision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
