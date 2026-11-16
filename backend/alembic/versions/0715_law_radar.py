"""Radar przepisów: biegi dwóch Grok Botów, pozycje po bramce, zmiany w prawie.

Revision ID: 0715_law_radar
Revises: 0714_drop_traffit_sync_cortex_trace

SQL i powody: ``app/services/law_radar/schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``). Reguły:
``docs/claude/przepisy/radar-przepisow-dwa-boty.md``.
"""

from alembic import op

from app.services.law_radar import schema

revision = "0715_law_radar"
down_revision = "0714_drop_traffit_sync_cortex_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
