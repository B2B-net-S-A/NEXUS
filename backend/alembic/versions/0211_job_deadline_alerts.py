"""Job deadline alerts — nowe wartości enuma notificationtype.

Revision ID: 0211_job_deadline_alerts
Revises: 0210_role_dashboard_rbac_cutover
Create Date: 2026-08-04

Dodaje 3 wartości ``notificationtype`` dla alertów o zbliżającym się
``Job.deadline`` (progi 7/3/1 dni), emitowanych przez daily scanner
``app/tasks/job_deadline_alerts.py`` do przypisanych/delegowanych osób
projektu. Bez zmian struktury tabel — dedup jedzie na istniejącym
``related_entity=(job, id)`` + ``notification_type``.

Enum DDL w bloku autocommit (ALTER TYPE ADD VALUE nie może działać w
transakcji) — wzorzec z 0129/0100. Zdublowane w safety-net entrypoint.sh
bo prod alembic bywa orphaned.
"""

from alembic import op

revision = "0211_job_deadline_alerts"
down_revision = "0210_role_dashboard_rbac_cutover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_deadline_7d'"
        )
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_deadline_3d'"
        )
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_deadline_1d'"
        )


def downgrade() -> None:
    # PostgreSQL nie umie usuwać wartości enuma in-place — wartości zostają.
    pass
