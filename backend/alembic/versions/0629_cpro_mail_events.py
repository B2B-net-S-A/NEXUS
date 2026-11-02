"""Dziennik zdarzeń z maili CPro i typy dzwonków.

Revision ID: 0629_cpro_mail_events
Revises: 0628_sales_meeting_transcripts

SQL: ``app/services/cpro_mail_schema.py`` (to samo źródło czyta ``entrypoint.sh``).
"""

from alembic import op

from app.services import cpro_mail_schema as schema

revision = "0629_cpro_mail_events"
down_revision = "0628_sales_meeting_transcripts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)
    with op.get_context().autocommit_block():
        for name in schema.NOTIFICATION_TYPES:
            op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{name}'")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cpro_mail_events")
