"""Close the schema drift measured by /api/admin/schema-drift on 2026-07-20.

Revision ID: 0180_close_measured_schema_drift
Revises: 0179_merge_analytics_recruitment_heads
Create Date: 2026-07-20 17:00:00.000000

The first run of the drift report — comparing ``Base.metadata`` against the
live schema — turned up three classes of gap that no migration had ever
created. This closes all three for any database built from migrations.

Production is a separate matter: its alembic bookmark sits far behind these
revisions, so this migration will not run there. The same statements are
mirrored idempotently in ``entrypoint.sh`` for that path. Both are needed —
without the mirror production stays broken, and without this migration every
*fresh* database (a restore, a new environment, CI) is born broken.

**Enum labels (9).** Each is a label the ORM sends that the type did not have,
so the write failed with ``invalid input value for enum``:

- ``notificationtype.rejection_email_*`` (5) — written by
  ``rejection_email_scheduler.py`` at lines 171/296/332. Added by migration
  0045, which production never reached; a live, silent failure there.
- ``notificationtype.similar_job_candidates`` — mirrored in entrypoint.sh but
  in no migration, so production had it and CI did not. Exactly backwards from
  the previous item, and the reason blind fixes are dangerous here.
- ``callstatus.initiated`` — written by ``POST /api/cloudtalk/initiate-call``.
  Dormant only because ``CLOUDTALK_ENABLED`` is false; armed the moment it flips.
- ``contracttype.zlecenie`` — the type was created with the typo ``uzlecenie``
  in 0001_initial. The typo is left in place deliberately: rows may reference
  it and PostgreSQL cannot drop an enum label.
- ``nextsteppreference.pass_`` — the DB has the sensible ``pass``; the ORM
  member is ``pass_`` because ``pass`` is a Python keyword, and SQLAlchemy
  persists member NAMES. Adding the label disarms it now; the better fix is
  ``values_callable`` on the column so the ORM sends the value instead.

**Foreign keys (2).** ``competence_category_id`` on ``candidates`` and ``jobs``
had no referential integrity: the entrypoint safety-net adds COLUMNS but never
their CONSTRAINTS. Added ``NOT VALID`` so the constraint governs new writes
without a full-table scan and without failing on any pre-existing orphan.

**Indexes (36).** Declared ``index=True`` in the models and created by no
migration. All non-unique — this is silent performance loss, not an integrity
gap (zero UNIQUE indexes were missing). The clearest cost:
``calendar_events.external_id`` is queried by ``ical_import.py`` once per
VEVENT, so every calendar import scanned the table once per event. Ten of them
are ``external_id`` columns — the very keys the Traffit and M365 integrations
look records up by.
"""

from alembic import op

revision = "0180_close_measured_schema_drift"
down_revision = "0179_merge_analytics_recruitment_heads"
branch_labels = None
depends_on = None

_ENUM_VALUES = [
    ("notificationtype", "rejection_email_scheduled"),
    ("notificationtype", "rejection_email_sent"),
    ("notificationtype", "rejection_email_failed"),
    ("notificationtype", "rejection_email_cancelled"),
    ("notificationtype", "rejection_email_skipped"),
    ("notificationtype", "similar_job_candidates"),
    ("callstatus", "initiated"),
    ("contracttype", "zlecenie"),
    ("nextsteppreference", "pass_"),
]

_FOREIGN_KEYS = [
    ("candidates", "fk_candidates_competence_category", "competence_category_id"),
    ("jobs", "fk_jobs_competence_category", "competence_category_id"),
]

_INDEXES = [
    ("ix_activities_external_id", "activities", "external_id"),
    ("ix_analytics_metric_snapshots_module", "analytics_metric_snapshots", "module"),
    ("ix_analytics_metric_snapshots_period_label", "analytics_metric_snapshots", "period_label"),
    ("ix_calendar_events_external_id", "calendar_events", "external_id"),
    ("ix_calendar_events_external_source", "calendar_events", "external_source"),
    ("ix_calls_contract_id", "calls", "contract_id"),
    ("ix_candidate_stages_external_id", "candidate_stages", "external_id"),
    ("ix_candidates_availability_status", "candidates", "availability_status"),
    ("ix_candidates_competence_category_id", "candidates", "competence_category_id"),
    ("ix_candidates_created_by", "candidates", "created_by"),
    ("ix_candidates_external_id", "candidates", "external_id"),
    ("ix_champion_profile_suggestions_job_id", "champion_profile_suggestions", "job_id"),
    ("ix_clients_external_id", "clients", "external_id"),
    ("ix_contacts_external_id", "contacts", "external_id"),
    ("ix_contracts_client_order_end_date", "contracts", "client_order_end_date"),
    ("ix_contracts_termination_reason", "contracts", "termination_reason"),
    ("ix_delivery_lead_client_assignments_delivery_lead_user_id", "delivery_lead_client_assignments", "delivery_lead_user_id"),
    ("ix_dr_client_mrr_client_id", "dr_client_mrr", "client_id"),
    ("ix_dr_sales_leads_user_id", "dr_sales_leads", "user_id"),
    ("ix_dr_sales_offers_user_id", "dr_sales_offers", "user_id"),
    ("ix_jobs_competence_category_id", "jobs", "competence_category_id"),
    ("ix_jobs_delivery_lead_id", "jobs", "delivery_lead_id"),
    ("ix_jobs_external_id", "jobs", "external_id"),
    ("ix_jobs_needs_sourcing", "jobs", "needs_sourcing"),
    ("ix_jobs_train_name", "jobs", "train_name"),
    ("ix_notes_contract_id", "notes", "contract_id"),
    ("ix_notifications_related_entity_id", "notifications", "related_entity_id"),
    ("ix_pipeline_stage_defs_external_id", "pipeline_stage_defs", "external_id"),
    ("ix_pipeline_templates_external_id", "pipeline_templates", "external_id"),
    ("ix_proposal_snapshots_job_id", "proposal_snapshots", "job_id"),
    ("ix_rate_benchmarks_role", "rate_benchmarks", "role"),
    ("ix_rate_benchmarks_seniority", "rate_benchmarks", "seniority"),
    ("ix_talent_pools_competence_category_id", "talent_pools", "competence_category_id"),
    ("ix_talent_pools_external_id", "talent_pools", "external_id"),
    ("ix_talent_pools_is_marketplace", "talent_pools", "is_marketplace"),
    ("ix_talent_pools_is_personal", "talent_pools", "is_personal"),
]


def upgrade() -> None:
    for type_name, label in _ENUM_VALUES:
        op.execute(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{label}'")

    for table, constraint, column in _FOREIGN_KEYS:
        # DO/EXCEPTION rather than a bare ALTER: this must stay idempotent for
        # databases that already acquired the constraint via entrypoint.sh.
        op.execute(
            f"""DO $$ BEGIN
                ALTER TABLE {table}
                    ADD CONSTRAINT {constraint}
                    FOREIGN KEY ({column})
                    REFERENCES competence_categories (id) NOT VALID;
            EXCEPTION WHEN duplicate_object THEN NULL; END $$"""
        )

    for name, table, columns in _INDEXES:
        # Not CONCURRENTLY: migrations run inside a transaction, which forbids
        # it. entrypoint.sh uses CONCURRENTLY for the production path, where a
        # previous container may still be serving traffic.
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")


def downgrade() -> None:
    for name, _table, _columns in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    for table, constraint, _column in _FOREIGN_KEYS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
    # Enum labels are intentionally NOT removed: PostgreSQL cannot drop an enum
    # value, and rows may already reference them.
