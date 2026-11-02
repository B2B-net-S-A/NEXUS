"""Dziennik zdarzeń z maili CPro i typy dzwonków.

Revision ID: 0634_cpro_mail_events
Revises: 0633_hr_m365_scope_alert

SQL: ``app/services/cpro_mail_schema.py`` (to samo źródło czyta ``entrypoint.sh``).
"""

from alembic import op

from app.services import cpro_mail_schema as schema

revision = "0634_cpro_mail_events"
down_revision = "0633_hr_m365_scope_alert"
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
