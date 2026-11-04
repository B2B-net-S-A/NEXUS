"""„Prowadzi” — ręczne przypisanie osoby do kandydata w rekrutacji.

Revision ID: 0519_candidate_job_owners
Revises: 0518_autofill_quality_report

Prośba Olafa z 23.10.2026, decyzje Artura z 25.10.2026: admin i Head of
Recruitment przypisują osobę prowadzącą parę kandydat–rekrutacja. Tabele mają
jedno źródło (``app/services/pair_owner_schema.py``) — lustro w
``entrypoint.sh``.
"""

from alembic import op

from app.services import pair_owner_schema as schema

revision = "0519_candidate_job_owners"
down_revision = "0518_autofill_quality_report"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
