"""Imienne prawo do maila „Podsumowanie Rady”.

Revision ID: 0630_user_receives_board_report
Revises: 0629_company_results_permission

Decyzja Artura 02.11.2026: zbiorczy przychód i marżę firmy mailem dostają Rada
i wskazane osoby, a sama rola admin już nie. Lustro w ``entrypoint.sh``.
"""

import sqlalchemy as sa
from alembic import op

revision = "0630_user_receives_board_report"
down_revision = "0629_company_results_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "receives_board_report",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "receives_board_report")
