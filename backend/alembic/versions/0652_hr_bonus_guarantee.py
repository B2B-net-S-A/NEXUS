"""Gwarancja premii DL: dług za premię i potrącenia z kolejnych premii.

Revision ID: 0652_hr_bonus_guarantee
Revises: 0651_cv_call_questions

Zasada Artura 05.11.2026: konsultant, który nie przepracuje 12 miesięcy od
startu kontraktu, odbiera DL-owi całą premię za placement; kwota potrąca się
z kolejnych premii. SQL i powody: ``app/services/hr_bonus_guarantee_schema.py``
(to samo źródło czyta ``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import hr_bonus_guarantee_schema as schema

revision = "0652_hr_bonus_guarantee"
down_revision = "0651_cv_call_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
