"""Radar przepisów: biegi dwóch Grok Botów, pozycje po bramce, zmiany w prawie.

Revision ID: 0714_law_radar
Revises: 0713_job_team_variants

SQL i powody: ``app/services/law_radar/schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``). Reguły:
``docs/claude/przepisy/radar-przepisow-dwa-boty.md``.
"""

from alembic import op

from app.services.law_radar import schema

revision = "0714_law_radar"
down_revision = "0713_job_team_variants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
