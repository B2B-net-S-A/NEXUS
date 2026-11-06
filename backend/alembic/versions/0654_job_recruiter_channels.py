"""Koszyki „Baza” / „LinkedIn” w zespole rekrutacji (0654).

Revision ID: 0654_job_recruiter_channels
Revises: 0653_hr_bonus_guarantee

Decyzja Artura 06.11.2026 (wariant B z makiet): przy każdej rekrutacji widać,
kto szuka w bazie NEXUSA, a kto na LinkedInie, oraz plan liczby osób w każdym
koszyku. SQL: ``app/services/job_channels_schema.py`` (to samo źródło czyta
``entrypoint.sh``).
"""

from alembic import op

from app.services import job_channels_schema as schema

revision = "0654_job_recruiter_channels"
down_revision = "0653_hr_bonus_guarantee"
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
