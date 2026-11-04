"""Wybór terminu = rozmowa w kalendarzu, DL odpisuje klientowi (20.10.2026).

Revision ID: 0487_slot_choice_client_reply
Revises: 0486_approval_settlement

Decyzja Artura 20.10.2026: wybór terminu przez rekrutera od razu zakłada
rozmowę u klienta (``interview_slots.confirm``), a Delivery Lead dostaje
zadanie „Odpisz klientowi”. ``client_reply_pending`` to flaga zadania —
wnioski potwierdzone przed tą rewizją mają ``false`` i nie stają się
zaległościami. Lustro w ``entrypoint.sh``.
"""

import sqlalchemy as sa
from alembic import op

revision = "0487_slot_choice_client_reply"
down_revision = "0486_approval_settlement"
branch_labels = None
depends_on = None

_TABLE = "client_interview_slot_requests"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "client_reply_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        _TABLE,
        sa.Column("client_replied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "client_replied_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(_TABLE, "client_replied_by")
    op.drop_column(_TABLE, "client_replied_at")
    op.drop_column(_TABLE, "client_reply_pending")
