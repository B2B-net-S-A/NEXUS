"""Linki aplikacyjne: dzienne wejścia.

Revision ID: 0640_invite_link_visit_days
Revises: 0639_client_panel

SQL ma jedno źródło (``app/services/invite_link_visits_schema.py``) — ten sam moduł
czyta ``entrypoint.sh``.
"""

from alembic import op

from app.services import invite_link_visits_schema as schema

revision = "0640_invite_link_visit_days"
down_revision = "0639_client_panel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS candidate_invite_link_visit_days")
