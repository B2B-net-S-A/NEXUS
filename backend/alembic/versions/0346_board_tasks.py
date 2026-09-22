"""Kolejka „Czeka na Ciebie": kto wysyła do Cpro + dwa typy powiadomień.

Revision ID: 0346_board_tasks
Revises: 0345_billing_hours_168

Odznaki DZ i Cpro są etapami szablonu (import z Traffita zapisuje ruch na
dokładny stan), więc „co czeka" wylicza się z najnowszego wiersza pary.
Jedyne, czego nie da się wyliczyć, to OSOBA, która ma wysłać kandydata do
Cpro — za każdym razem inna, typowana przy oznaczeniu gotowości. Trzymamy ją
na wierszu etapu „Wysłać do Cpro" (``candidate_stages.task_assignee_id``).

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

import sqlalchemy as sa
from alembic import op

revision = "0346_board_tasks"
down_revision = "0345_billing_hours_168"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'board_tasks_digest'"
        )
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'cpro_send_assigned'"
        )
    op.add_column(
        "candidate_stages",
        sa.Column(
            "task_assignee_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("candidate_stages", "task_assignee_id")
    # Wartości enuma zostają — Postgres nie ma `ALTER TYPE … DROP VALUE`.
