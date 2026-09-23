"""Audyt 22.09.2026, druga runda: schemat dla trzech poprawek.

Revision ID: 0350_audit_round2
Revises: 0349_notification_mutes

* ``candidate_stage_cvs.original_cv_storage_key`` / ``original_cv_sha256`` —
  snapshot CV etapu może wskazywać plik w object storage zamiast kopiować
  bajty do bazy (PROD-02: 2,35 GB duplikatów w ``original_cv_content``).
* ``my_people_overrides.restore_kind`` — „Uśpij” przypiętej osoby pamięta
  przypięcie, a „Przywróć” do niego wraca (CAND-07).
* ``md_consumption_import_rows``: status ``cost_only`` (wiersz z samą fakturą)
  i ``cost_status = non_positive_amount`` (korekta/kwota ≤ 0) — FIN-MD-06.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0350_audit_round2"
down_revision = "0349_notification_mutes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_stage_cvs ADD COLUMN IF NOT EXISTS "
        "original_cv_storage_key VARCHAR(512) NULL"
    )
    op.execute(
        "ALTER TABLE candidate_stage_cvs ADD COLUMN IF NOT EXISTS "
        "original_cv_sha256 VARCHAR(64) NULL"
    )
    op.execute(
        "ALTER TABLE my_people_overrides ADD COLUMN IF NOT EXISTS "
        "restore_kind VARCHAR(16) NULL"
    )
    op.execute(
        "ALTER TABLE my_people_overrides "
        "DROP CONSTRAINT IF EXISTS ck_my_people_overrides_restore_kind"
    )
    op.execute(
        "ALTER TABLE my_people_overrides ADD CONSTRAINT "
        "ck_my_people_overrides_restore_kind "
        "CHECK (restore_kind IS NULL OR restore_kind IN ('pinned'))"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "DROP CONSTRAINT IF EXISTS ck_md_import_rows_status"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows ADD CONSTRAINT "
        "ck_md_import_rows_status CHECK (status IN "
        "('applied', 'needs_assignment', 'unmatched', 'cost_only'))"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "DROP CONSTRAINT IF EXISTS ck_md_import_rows_cost_status"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows ADD CONSTRAINT "
        "ck_md_import_rows_cost_status CHECK (cost_status IS NULL OR cost_status IN "
        "('applied', 'unmatched_number', 'unmatched_consultant', "
        "'non_positive_amount'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "DROP CONSTRAINT IF EXISTS ck_md_import_rows_cost_status"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows ADD CONSTRAINT "
        "ck_md_import_rows_cost_status CHECK (cost_status IS NULL OR cost_status IN "
        "('applied', 'unmatched_number', 'unmatched_consultant')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "DROP CONSTRAINT IF EXISTS ck_md_import_rows_status"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows ADD CONSTRAINT "
        "ck_md_import_rows_status CHECK (status IN "
        "('applied', 'needs_assignment', 'unmatched')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE my_people_overrides "
        "DROP CONSTRAINT IF EXISTS ck_my_people_overrides_restore_kind"
    )
    op.execute("ALTER TABLE my_people_overrides DROP COLUMN IF EXISTS restore_kind")
    op.execute(
        "ALTER TABLE candidate_stage_cvs DROP COLUMN IF EXISTS original_cv_sha256"
    )
    op.execute(
        "ALTER TABLE candidate_stage_cvs DROP COLUMN IF EXISTS original_cv_storage_key"
    )
