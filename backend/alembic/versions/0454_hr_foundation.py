"""„Ludzie w NEXUSIE”: kartoteka pracownika, pule urlopowe, dni wolne firmy,
ślad HR, rezerwacje zadań i import z Compassa.

Revision ID: 0454_hr_foundation
Revises: 0453_prep_candidate_responses

Decyzja Artura 16.10.2026: wszystko z Compassa poza Akademią przechodzi do
NEXUSA. Ta migracja zakłada fundament; moduły wchodzą „ciemne”
(``app_settings['hr_modules']`` = wszystko wyłączone).

SQL ma jedno źródło (``app/services/hr_foundation_schema.py``) — ten sam moduł
czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_foundation_schema as schema

revision = "0454_hr_foundation"
down_revision = "0453_prep_candidate_responses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute(f"DELETE FROM app_settings WHERE key = '{schema.HR_MODULES_SETTING}'")
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
