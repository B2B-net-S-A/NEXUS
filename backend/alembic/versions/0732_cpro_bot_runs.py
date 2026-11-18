"""Bot Cpro: biegi rutyny Grok Bota, która wrzuca kandydatów Nordei do Cpro.

Revision ID: 0732_cpro_bot_runs
Revises: 0731_champion_profile_revisions

SQL i powody: ``app/services/cpro_bot/schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``). Reguły:
``docs/claude/integracje/cpro-bot-grok.md``.
"""

from alembic import op

from app.services.cpro_bot import schema

revision = "0732_cpro_bot_runs"
down_revision = "0731_champion_profile_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
