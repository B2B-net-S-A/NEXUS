"""Własny pulpit startowy: jeden układ kafelków na osobę.

Revision ID: 0337_user_dashboards
Revises: 0336_saved_search_reapproval_notif

Decyzja Artura 21.09.2026: każdy ustawia swój pulpit sam (kafelki z katalogu
i własne metryki na siatce 12 kolumn), jeden pulpit na osobę. Układ to JSON
walidowany w ``app/services/dashboard_tiles.py`` — tu wyłącznie tabela.

Osobna tabela, nie kolumna na ``users``: kolumna na ``users`` bez lustra
w entrypoincie wywraca każde ``select(User)`` (lekcja z 0330). ``version``
jest licznikiem optymistycznej współbieżności — dwie karty przeglądarki nie
nadpisują sobie układu po cichu.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0337_user_dashboards"
down_revision = "0336_saved_search_reapproval_notif"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_dashboards",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "layout",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("""'{"tiles": []}'::jsonb"""),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("version >= 0", name="ck_user_dashboards_version"),
    )


def downgrade() -> None:
    op.drop_table("user_dashboards")
