"""dl_alerts: nowy typ ``candidate_conflict_expired`` (wygasł konflikt z klientem).

Revision ID: 0322_dl_alert_conflict_expired
Revises: 0321_conflict_audit_type_unique

Kalka 0318: ``alert_type`` to VARCHAR + CHECK, poszerzenie = DROP+ADD więzu.
Oba lustra w ``entrypoint.sh`` (CREATE TABLE i atomowy blok DO) robią to samo;
``tests/test_entrypoint_dl_alerts_check_mirror.py`` pilnuje zgodności z modelem.
"""

from alembic import op

revision = "0322_dl_alert_conflict_expired"
down_revision = "0321_conflict_audit_type_unique"
branch_labels = None
depends_on = None

_PREVIOUS = (
    "'cost_order_exhausted', 'draft_consultant_unassigned', 'md_budget_low', "
    "'missing_revenue_rate', 'md_consultant_ended', 'order_mail_review', "
    "'order_missing_successor', 'periodic_order_ending', "
    "'framework_contract_expiring', 'contract_ending', 'cost_budget_low', "
    "'new_contractor_draft', 'md_base_usage_high'"
)
_TYPES = f"{_PREVIOUS}, 'candidate_conflict_expired'"


def upgrade() -> None:
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_TYPES}))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM dl_alerts WHERE alert_type = 'candidate_conflict_expired'")
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_PREVIOUS}))"
    )
