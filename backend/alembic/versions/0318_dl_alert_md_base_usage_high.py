"""dl_alerts: nowy typ ``md_base_usage_high`` (wysokie zużycie podstawy MD).

Revision ID: 0318_dl_alert_md_base_usage_high
Revises: 0317_pipeline_stage_posting

``alert_type`` to VARCHAR + CHECK (nie enum PG) — poszerzenie wymaga DROP+ADD
więzu; oba lustra w ``entrypoint.sh`` (CREATE TABLE i atomowy blok DO) robią
to samo, a ``tests/test_entrypoint_dl_alerts_check_mirror.py`` pilnuje, że
żaden z zapisów nie zawęzi więzu przy najbliższym deployu.
"""

from alembic import op

revision = "0318_dl_alert_md_base_usage_high"
down_revision = "0317_pipeline_stage_posting"
branch_labels = None
depends_on = None

_PREVIOUS = (
    "'cost_order_exhausted', 'draft_consultant_unassigned', 'md_budget_low', "
    "'missing_revenue_rate', 'md_consultant_ended', 'order_mail_review', "
    "'order_missing_successor', 'periodic_order_ending', "
    "'framework_contract_expiring', 'contract_ending', 'cost_budget_low', "
    "'new_contractor_draft'"
)
_TYPES = f"{_PREVIOUS}, 'md_base_usage_high'"


def upgrade() -> None:
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_TYPES}))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM dl_alerts WHERE alert_type = 'md_base_usage_high'")
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_PREVIOUS}))"
    )
