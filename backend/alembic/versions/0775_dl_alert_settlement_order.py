"""dl_alerts: typy ``settlement_over_order`` i ``settlement_rate_mismatch``.

Revision ID: 0775_dl_alert_settlement_order
Revises: 0774_settlement_feedback

Rozliczenie ponad pulę albo na zamówieniu zakończonym w NEXUS-ie oraz stawka
linii inna niż kontrakt albo ostatnia faktura za osobę (próba IX–X 2026).
Kalka 0664: ``alert_type`` to VARCHAR + CHECK, poszerzenie = DROP+ADD więzu.
Oba lustra w ``entrypoint.sh`` robią to samo;
``tests/test_entrypoint_dl_alerts_check_mirror.py`` pilnuje zgodności z modelem.
"""

from alembic import op

revision = "0775_dl_alert_settlement_order"
down_revision = "0774_settlement_feedback"
branch_labels = None
depends_on = None

_PREVIOUS = (
    "'cost_order_exhausted', 'draft_consultant_unassigned', 'md_budget_low', "
    "'missing_revenue_rate', 'md_consultant_ended', 'order_mail_review', "
    "'order_missing_successor', 'periodic_order_ending', "
    "'framework_contract_expiring', 'contract_ending', 'cost_budget_low', "
    "'new_contractor_draft', 'md_base_usage_high', 'candidate_conflict_expired', "
    "'invoice_without_order_line', 'framework_over_limit'"
)
_NEW = ("settlement_over_order", "settlement_rate_mismatch")
_TYPES = _PREVIOUS + ", " + ", ".join(f"'{name}'" for name in _NEW)


def upgrade() -> None:
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_TYPES}))"
    )


def downgrade() -> None:
    names = ", ".join(f"'{name}'" for name in _NEW)
    op.execute(f"DELETE FROM dl_alerts WHERE alert_type IN ({names})")
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_PREVIOUS}))"
    )
