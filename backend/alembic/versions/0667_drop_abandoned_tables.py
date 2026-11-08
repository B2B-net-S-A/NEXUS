"""Usunięcie 70 porzuconych tabel bez modelu (decyzja z 08.11.2026).

Revision ID: 0667_drop_abandoned_tables
Revises: 0664_dl_alert_invoice_no_line

Stare kopie sprzed scaleń, dane po DynaReporterze (routery usunięte w #1751),
resztki po wycofanych PR-ach #696–#708 i pusta `signature_links`. Żadna z nich
nie ma modelu ani odczytu w kodzie. Dwa klucze obce z tabel spoza listy trzeba
zdjąć najpierw, a bez CASCADE nieznana zależność przerwie migrację głośno.
Lustro jest w `entrypoint.sh`; pilnuje go
`tests/test_drop_abandoned_tables_migration_mirror.py`.
"""

from alembic import op

revision = "0667_drop_abandoned_tables"
down_revision = "0664_dl_alert_invoice_no_line"
branch_labels = None
depends_on = None

OUTSIDE_FK_DROPS = (
    "ALTER TABLE IF EXISTS dr_przetargi_allocations DROP CONSTRAINT IF EXISTS dr_przetargi_allocations_consultant_id_fkey",
    "ALTER TABLE IF EXISTS dr_sourcer_category_assignments DROP CONSTRAINT IF EXISTS dr_sourcer_category_assignments_category_id_fkey",
)
_COPIES = (
    "_alembic_backup_pre_heal",
    "client_norm_bak_calendar",
    "client_norm_bak_clients",
    "client_norm_bak_contacts",
    "client_norm_bak_drdl",
    "client_norm_bak_drpd",
    "client_norm_bak_jobs",
    "client_norm_bak_knowledge",
    "dr_przetargi_mrr_backup",
    "nordea_merge_bak_calendar",
    "nordea_merge_bak_clients",
    "nordea_merge_bak_contacts",
    "nordea_merge_bak_dl",
    "nordea_merge_bak_drdl",
    "nordea_merge_bak_drplace",
    "nordea_merge_bak_jobs",
    "nordea_merge_bak_knowledge",
    "nordea_merge_bak_notif",
    "nordea_merge_bak_reqdocs",
    "nordea_merge_bak_tac",
    "users_backup_2026_05_18",
    "users_cleanup_backup_2026_05_18",
)
_DYNAREPORTER = (
    "dr_about_calendar",
    "dr_about_career_paths",
    "dr_about_clients_partners",
    "dr_about_contacts",
    "dr_about_faq",
    "dr_about_feedback",
    "dr_about_glossary",
    "dr_about_links",
    "dr_about_org_chart",
    "dr_about_positions",
    "dr_about_procedures",
    "dr_about_templates",
    "dr_about_training",
    "dr_about_values",
    "dr_alerts",
    "dr_api_key_audit_log",
    "dr_api_keys",
    "dr_applied_migrations",
    "dr_competence_categories",
    "dr_consultant_group_assignments",
    "dr_consultant_rate_history",
    "dr_consultants",
    "dr_data_audit_log",
    "dr_delivery_lead_client_assignments",
    "dr_group_monthly_costs",
    "dr_monthly_mrr_data",
    "dr_mrr_import_history",
    "dr_project_cost_groups",
    "dr_project_monthly_costs",
    "dr_project_other_cost_items",
    "dr_przetargi_mrr",
    "dr_system_config",
    "dr_tac_linkedin_farming",
)
_ABANDONED_AI = (
    "ai_budget_reservations",
    "ai_call_ledger",
    "ai_eval_cases",
    "ai_eval_labels",
    "ai_eval_outputs",
    "ai_eval_runs",
    "ai_eval_sets",
    "ai_provider_compliance",
    "ai_rollout_events",
    "ai_rollout_observations",
    "ai_rollout_reports",
    "ai_rollout_state",
    "ai_routing_activation_log",
    "ai_routing_state",
)
_SIGNATURE = ("signature_links",)
TABLE_GROUPS = (_COPIES, _DYNAREPORTER, _ABANDONED_AI, _SIGNATURE)


def drop_statements() -> list[str]:
    return [f"DROP TABLE IF EXISTS {', '.join(group)}" for group in TABLE_GROUPS]


def upgrade() -> None:
    for statement in (*OUTSIDE_FK_DROPS, *drop_statements()):
        op.execute(statement)


def downgrade() -> None:
    """Bez cofania schematem: treść przywraca się z zaszyfrowanego zrzutu."""
