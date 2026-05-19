"""Convert 87 dr_* TIMESTAMP columns to TIMESTAMPTZ (timezone-aware).

Revision ID: 0117_dr_timestamptz_campaign
Revises: 0116_dr_fk_indexes
Create Date: 2026-05-19 18:30:00.000000

Quality check findings (3 parallel review agents, 2026-05-19):

DB-H-3: All 57 imported `dr_*` tables use `timestamp without time zone`
for created_at/updated_at columns. Rest of Nexus schema uses TIMESTAMPTZ.
This means:
- Any JOIN of dr_* timestamps with nexus timestamps requires implicit cast
- If server timezone ever changes from UTC, historical timestamps become
  ambiguous
- `CURRENT_TIMESTAMP` defaults are stored as local server time, not
  UTC-anchored

Migration 0115 fixed `dr_user_seniority.updated_at` (one column). This
migration fixes the remaining 87 columns across 50+ tables.

Strategy: `ALTER COLUMN ... TYPE TIMESTAMPTZ USING column AT TIME ZONE 'UTC'`.
Since dr_* tables were imported via pg_dump from a UTC-deployed DR instance
(Coolify standalone), interpreting existing values AS UTC is correct.

Safety:
- All operations idempotent (information_schema check before ALTER).
- ALTER TYPE on TIMESTAMP→TIMESTAMPTZ requires AccessExclusiveLock briefly,
  but no data rewrite (Postgres 12+ supports in-place conversion for
  TIMESTAMP→TIMESTAMPTZ when the conversion is timezone-agnostic — which
  `AT TIME ZONE 'UTC'` is).
- Tables are small (382 rows max in dr_kpi_body_leasing, most <100).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0117_dr_timestamptz_campaign"
down_revision: str | Sequence[str] | None = "0116_dr_fk_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# All (table, column) pairs that need TIMESTAMP → TIMESTAMPTZ.
# Source: `information_schema.columns WHERE data_type='timestamp without time
# zone' AND table_name LIKE 'dr_%'` on prod 2026-05-19 (87 columns total,
# checked via QA review).
_TIMESTAMP_COLS: list[tuple[str, str]] = [
    ("dr_about_calendar", "created_at"),
    ("dr_about_calendar", "updated_at"),
    ("dr_about_career_paths", "created_at"),
    ("dr_about_career_paths", "updated_at"),
    ("dr_about_clients_partners", "created_at"),
    ("dr_about_clients_partners", "updated_at"),
    ("dr_about_contacts", "created_at"),
    ("dr_about_contacts", "updated_at"),
    ("dr_about_faq", "created_at"),
    ("dr_about_faq", "updated_at"),
    ("dr_about_feedback", "created_at"),
    ("dr_about_feedback", "resolved_at"),
    ("dr_about_feedback", "updated_at"),
    ("dr_about_glossary", "created_at"),
    ("dr_about_glossary", "updated_at"),
    ("dr_about_links", "created_at"),
    ("dr_about_links", "updated_at"),
    ("dr_about_org_chart", "created_at"),
    ("dr_about_org_chart", "updated_at"),
    ("dr_about_positions", "created_at"),
    ("dr_about_positions", "updated_at"),
    ("dr_about_procedures", "created_at"),
    ("dr_about_procedures", "updated_at"),
    ("dr_about_templates", "created_at"),
    ("dr_about_templates", "updated_at"),
    ("dr_about_training", "created_at"),
    ("dr_about_training", "updated_at"),
    ("dr_about_values", "created_at"),
    ("dr_about_values", "updated_at"),
    ("dr_alerts", "created_at"),
    ("dr_alerts", "sent_at"),
    ("dr_api_key_audit_log", "created_at"),
    ("dr_api_keys", "created_at"),
    ("dr_api_keys", "expires_at"),
    ("dr_api_keys", "last_used_at"),
    ("dr_board_monthly_report", "created_at"),
    ("dr_board_monthly_report", "updated_at"),
    ("dr_board_placement_clients", "created_at"),
    ("dr_client_mrr", "created_at"),
    ("dr_clients", "created_at"),
    ("dr_competence_categories", "created_at"),
    ("dr_competition_notifications", "created_at"),
    ("dr_competition_winners", "created_at"),
    ("dr_consultant_group_assignments", "created_at"),
    ("dr_consultant_rate_history", "created_at"),
    ("dr_consultants", "created_at"),
    ("dr_consultants", "deactivated_at"),
    ("dr_data_audit_log", "performed_at"),
    ("dr_delivery_lead_client_assignments", "created_at"),
    ("dr_finances", "created_at"),
    ("dr_group_monthly_costs", "created_at"),
    ("dr_group_monthly_costs", "updated_at"),
    ("dr_kpi_body_leasing", "created_at"),
    ("dr_kpi_delivery_lead", "created_at"),
    ("dr_kpi_delivery_lead", "updated_at"),
    ("dr_kpi_sales", "created_at"),
    ("dr_monthly_mrr_data", "created_at"),
    ("dr_monthly_mrr_data", "updated_at"),
    ("dr_mrr_import_history", "created_at"),
    ("dr_placement_details", "created_at"),
    ("dr_project_cost_groups", "created_at"),
    ("dr_project_cost_groups", "updated_at"),
    ("dr_project_monthly_costs", "created_at"),
    ("dr_project_monthly_costs", "updated_at"),
    ("dr_project_other_cost_items", "created_at"),
    ("dr_przetargi_allocations", "created_at"),
    ("dr_przetargi_allocations", "updated_at"),
    ("dr_przetargi_consultants", "created_at"),
    ("dr_przetargi_mrr", "created_at"),
    ("dr_przetargi_mrr", "updated_at"),
    ("dr_przetargi_mrr_backup", "created_at"),
    ("dr_przetargi_mrr_backup", "updated_at"),
    ("dr_przetargi_project_costs", "created_at"),
    ("dr_przetargi_project_costs", "updated_at"),
    ("dr_przetargi_projects", "created_at"),
    ("dr_przetargi_projects", "updated_at"),
    ("dr_sales_leads", "created_at"),
    ("dr_sales_offers", "created_at"),
    ("dr_sales_people", "created_at"),
    ("dr_sales_people", "deactivated_at"),
    ("dr_sales_projects", "created_at"),
    ("dr_sourcer_category_assignments", "created_at"),
    ("dr_system_config", "updated_at"),
    ("dr_tac_delivery_lead_assignments", "created_at"),
    ("dr_tac_linkedin_farming", "created_at"),
    ("dr_upload_history", "created_at"),
    ("dr_weekly_sales_activity", "created_at"),
]


def upgrade() -> None:
    """Convert all 87 columns to TIMESTAMPTZ assuming existing data is UTC.

    Uses information_schema check so re-running on already-converted column
    is a no-op (idempotent).
    """
    for table_name, column_name in _TIMESTAMP_COLS:
        # Skip if already converted (idempotent guard).
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = '{table_name}'
                      AND column_name = '{column_name}'
                      AND data_type = 'timestamp without time zone'
                ) THEN
                    EXECUTE format(
                        'ALTER TABLE %I ALTER COLUMN %I '
                        'TYPE TIMESTAMP WITH TIME ZONE '
                        'USING %I AT TIME ZONE ''UTC''',
                        '{table_name}', '{column_name}', '{column_name}'
                    );
                END IF;
            END$$;
            """
        )


def downgrade() -> None:
    """Revert all 87 columns to TIMESTAMP (lossy — discards timezone info)."""
    for table_name, column_name in _TIMESTAMP_COLS:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = '{table_name}'
                      AND column_name = '{column_name}'
                      AND data_type = 'timestamp with time zone'
                ) THEN
                    EXECUTE format(
                        'ALTER TABLE %I ALTER COLUMN %I '
                        'TYPE TIMESTAMP WITHOUT TIME ZONE '
                        'USING %I AT TIME ZONE ''UTC''',
                        '{table_name}', '{column_name}', '{column_name}'
                    );
                END IF;
            END$$;
            """
        )
