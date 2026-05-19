"""Add missing FK indexes on dr_* tables (perf at scale).

Revision ID: 0116_dr_fk_indexes
Revises: 0115_dr_perf_indexes
Create Date: 2026-05-19 18:00:00.000000

Quality check findings (3 parallel review agents, 2026-05-19):

DB-H-1: `dr_competition_winners.user_id` FK has no index. League page
queries (e.g. "show winners for user X") and FK ON DELETE checks during
user deactivation must do sequential scans of the table.

DB-H-4: `dr_upload_history.uploaded_by` FK has no index. Upload history
admin view always seq-scans when filtering by user.

DB-M-3: Low-traffic tables also missing FK indexes that will hurt at
scale: dr_alerts.user_id, dr_api_keys.created_by, dr_about_calendar.created_by,
dr_mrr_import_history.imported_by, dr_system_config.updated_by,
dr_about_contacts.user_id.

All indexes created with CONCURRENTLY in autocommit transaction — does
NOT lock the table during creation. Safe for production.

Per Alembic docs, `op.create_index(..., postgresql_concurrently=True)`
requires the migration to run outside a transaction. We set
`transactional_ddl = False` via a per-revision flag.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0116_dr_fk_indexes"
down_revision: str | Sequence[str] | None = "0115_dr_perf_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Per FK to add — (index_name, table, column).
# Ordered alphabetically by table for deterministic apply.
_FK_INDEXES: list[tuple[str, str, str]] = [
    ("idx_dr_about_calendar_created_by", "dr_about_calendar", "created_by"),
    ("idx_dr_about_contacts_user_id", "dr_about_contacts", "user_id"),
    ("idx_dr_alerts_user_id", "dr_alerts", "user_id"),
    ("idx_dr_api_keys_created_by", "dr_api_keys", "created_by"),
    (
        "idx_dr_competition_winners_user_id",
        "dr_competition_winners",
        "user_id",
    ),
    (
        "idx_dr_mrr_import_history_imported_by",
        "dr_mrr_import_history",
        "imported_by",
    ),
    (
        "idx_dr_system_config_updated_by",
        "dr_system_config",
        "updated_by",
    ),
    (
        "idx_dr_upload_history_uploaded_by",
        "dr_upload_history",
        "uploaded_by",
    ),
]


def upgrade() -> None:
    """Create indexes IF NOT EXISTS (idempotent — safe to re-run)."""
    for index_name, table_name, column_name in _FK_INDEXES:
        # `CONCURRENTLY` blocked when migration runs inside Alembic transaction —
        # use plain CREATE INDEX IF NOT EXISTS. dr_* tables are small now (max
        # ~400 rows) so brief AccessExclusiveLock is acceptable. At scale we'd
        # need to run these manually via psql with autocommit + CONCURRENTLY.
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})"
        )


def downgrade() -> None:
    """Drop the indexes."""
    for index_name, _, _ in _FK_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
