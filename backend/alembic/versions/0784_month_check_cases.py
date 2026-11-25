"""Kontrola miesiąca: rozbieżności faktur klient ↔ konsultant (decyzja Artura 25.11.2026).

Revision ID: 0784_month_check_cases
Revises: 0782_contract_rate_history_ksef

Tabela ``month_check_cases`` — sprawy z nocnej kontroli faktur do klientów
i faktur konsultantów z KSeF (godziny, brak faktury po jednej ze stron,
więcej godzin niż dni roboczych) ze stanem, który ustawiają Finanse.
DDL ma jedno źródło (``app/services/month_check/schema_sql.py``); entrypoint
wykonuje je przy każdym starcie przez ``hr_schema_bundle``.

Do tego typ alertu DL ``month_check_data`` (sprawa danych: brak kontraktu albo
zamówienia). Kalka 0775: ``alert_type`` to VARCHAR + CHECK, poszerzenie =
DROP+ADD więzu; oba lustra w ``entrypoint.sh`` robią to samo.
"""

from alembic import op

from app.services.month_check import schema_sql as schema

revision = "0784_month_check_cases"
down_revision = "0782_contract_rate_history_ksef"
branch_labels = None
depends_on = None

_PREVIOUS = (
    "'cost_order_exhausted', 'draft_consultant_unassigned', 'md_budget_low', "
    "'missing_revenue_rate', 'md_consultant_ended', 'order_mail_review', "
    "'order_missing_successor', 'periodic_order_ending', "
    "'framework_contract_expiring', 'contract_ending', 'cost_budget_low', "
    "'new_contractor_draft', 'md_base_usage_high', 'candidate_conflict_expired', "
    "'invoice_without_order_line', 'framework_over_limit', "
    "'settlement_over_order', 'settlement_rate_mismatch'"
)
_NEW = ("month_check_data",)
_TYPES = _PREVIOUS + ", " + ", ".join(f"'{name}'" for name in _NEW)


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)
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
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
