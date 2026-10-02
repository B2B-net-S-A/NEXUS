"""Powiadomienie „karta czeka na Ciebie" przy przekazaniu na Tablicy.

Revision ID: 0408_board_task_waiting_notif
Revises: 0407_onsite_days_per_month

„Przekaż Delivery Leadowi" i „Przekaż do Cpro" przesuwały kartę do kolejki
drugiej osoby bez dzwonka — odbiorca dowiadywał się z porannego skrótu albo
z Tablicy rekrutacji (zgłoszenie testerów 02.10.2026). Nowy typ powiadomienia
wychodzi od razu przy ruchu (`services/pipeline_handoff_notifications.py`).

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
