"""Źródła kandydatów: linki we własnych kanałach, osobno od portali.

Revision ID: 0641_career_link_channels
Revises: 0640_invite_link_visit_days

SQL ma jedno źródło (``app/services/career_link_channels_schema.py``) — ten sam
moduł czyta ``entrypoint.sh``.
"""

from alembic import op

from app.services import career_link_channels_schema as schema

revision = "0641_career_link_channels"
down_revision = "0640_invite_link_visit_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for stmt in schema.ENUM_DDL:
            op.execute(stmt)
    for stmt in schema.BACKFILL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Wartości enuma zostają (Postgres ich nie usuwa); zdarzenia wracają do ``posting``.
    op.execute(
        "UPDATE candidate_source_events SET channel = 'posting' "
        "WHERE channel IN ('career_link_general', 'career_link_job')"
    )
