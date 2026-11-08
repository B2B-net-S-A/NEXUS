"""dl_alerts: nowy typ ``invoice_without_order_line`` (faktura bez pozycji zamówienia).

Revision ID: 0664_dl_alert_invoice_no_line
Revises: 0663_client_close_reasons

Kalka 0322: ``alert_type`` to VARCHAR + CHECK, poszerzenie = DROP+ADD więzu.
Oba lustra w ``entrypoint.sh`` robią to samo;
``tests/test_entrypoint_dl_alerts_check_mirror.py`` pilnuje zgodności z modelem.
"""

from alembic import op

revision = "0664_dl_alert_invoice_no_line"
down_revision = "0663_client_close_reasons"
branch_labels = None
depends_on = None

_PREVIOUS = (
    "'cost_order_exhausted', 'draft_consultant_unassigned', 'md_budget_low', "
    "'missing_revenue_rate', 'md_consultant_ended', 'order_mail_review', "
    "'order_missing_successor', 'periodic_order_ending', "
    "'framework_contract_expiring', 'contract_ending', 'cost_budget_low', "
    "'new_contractor_draft', 'md_base_usage_high', 'candidate_conflict_expired'"
)
_TYPES = f"{_PREVIOUS}, 'invoice_without_order_line'"


def upgrade() -> None:
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_TYPES}))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM dl_alerts WHERE alert_type = 'invoice_without_order_line'")
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_PREVIOUS}))"
    )
