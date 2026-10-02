"""Powiadomienie „karta czeka na Ciebie" przy przekazaniu na Tablicy.

Revision ID: 0408_board_task_waiting_notif
Revises: 0407_onsite_days_per_month

Dzwonek „karta trafiła do Ciebie" (przegląd Delivery Leada, kolejka Cpro,
zwrot z kolejki Cpro — `services/stage_handoff_recipients.py`) szedł typem
`stage_rule`, czyli w kategorii „Ruchy w rekrutacjach", którą każdy może
wyciszyć: Delivery Lead po wyciszeniu nie widział, że ktoś czeka na przegląd.
Osobny typ należy do kategorii „Wzmianki" (imienne zadanie, nie do wyciszenia).

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

from alembic import op

revision = "0408_board_task_waiting_notif"
down_revision = "0407_onsite_days_per_month"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'board_task_waiting'"
        )


def downgrade() -> None:
    # Wartość enuma zostaje — Postgres nie ma `ALTER TYPE … DROP VALUE`.
    pass
