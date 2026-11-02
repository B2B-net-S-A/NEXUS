"""Linki aplikacyjne: dzienne wejścia.

Revision ID: 0638_invite_link_visit_days
Revises: 0637_viewer_role_no_sections

SQL ma jedno źródło (``app/services/invite_link_visits_schema.py``) — ten sam moduł
czyta ``entrypoint.sh``.
"""

from alembic import op

from app.services import invite_link_visits_schema as schema

revision = "0638_invite_link_visit_days"
down_revision = "0637_viewer_role_no_sections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS candidate_invite_link_visit_days")
