"""Gotówka i archiwum raportów Rady nadzorczej (R7).

Revision ID: 0737_board_reports
Revises: 0736_board_votes

Tabele ``board_cash_positions`` (stan gotówki na dzień, wpis admina) i
``board_reports`` (zamrożone raporty PDF). DDL ma jedno źródło
(``app/services/board_reports_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import board_reports_schema as schema

revision = "0737_board_reports"
down_revision = "0736_board_votes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
