"""dl_alerts: nowy typ ``order_mail_review`` (zamówienie z maila do weryfikacji).

Revision ID: 0265_dl_alert_order_mail_review
Revises: 0264_order_mail_ingest

``alert_type`` to VARCHAR + CHECK (nie enum PG) — poszerzenie wymaga DROP+ADD
więzu; lustro w ``entrypoint.sh`` robi to samo.
"""

from alembic import op

revision = "0265_dl_alert_order_mail_review"
down_revision = "0264_order_mail_ingest"
branch_labels = None
depends_on = None

_TYPES = (
    "'cost_order_exhausted', 'draft_consultant_unassigned', 'md_budget_low', "
    "'missing_revenue_rate', 'md_consultant_ended', 'order_mail_review'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        f"ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type CHECK (alert_type IN ({_TYPES}))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM dl_alerts WHERE alert_type = 'order_mail_review'")
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type CHECK (alert_type IN ("
        "'cost_order_exhausted', 'draft_consultant_unassigned', 'md_budget_low', "
        "'missing_revenue_rate', 'md_consultant_ended'))"
    )
