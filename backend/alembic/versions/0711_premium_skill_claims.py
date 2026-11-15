"""Wnioski o dopłatę za technologię premium i alert DL „ponad limitem z umowy” (F3).

Revision ID: 0711_premium_skill_claims
Revises: 0710_framework_rate_categories

Tabela ``contract_premium_skill_claims`` (jedno źródło DDL:
``app/services/premium_skill_schema.py``) i nowy typ alertu DL
``framework_over_limit`` — kalka 0664: ``alert_type`` to VARCHAR + CHECK,
poszerzenie = DROP+ADD więzu. Lustra w ``entrypoint.sh``;
``tests/test_entrypoint_dl_alerts_check_mirror.py`` pilnuje zgodności z modelem.
"""

from alembic import op

from app.services import premium_skill_schema as schema

revision = "0711_premium_skill_claims"
down_revision = "0710_framework_rate_categories"
branch_labels = None
depends_on = None

_PREVIOUS = (
    "'cost_order_exhausted', 'draft_consultant_unassigned', 'md_budget_low', "
    "'missing_revenue_rate', 'md_consultant_ended', 'order_mail_review', "
    "'order_missing_successor', 'periodic_order_ending', "
    "'framework_contract_expiring', 'contract_ending', 'cost_budget_low', "
    "'new_contractor_draft', 'md_base_usage_high', 'candidate_conflict_expired', "
    "'invoice_without_order_line'"
)
_TYPES = f"{_PREVIOUS}, 'framework_over_limit'"


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_TYPES}))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM dl_alerts WHERE alert_type = 'framework_over_limit'")
    op.execute("ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type")
    op.execute(
        "ALTER TABLE dl_alerts ADD CONSTRAINT ck_dl_alerts_type "
        f"CHECK (alert_type IN ({_PREVIOUS}))"
    )
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
