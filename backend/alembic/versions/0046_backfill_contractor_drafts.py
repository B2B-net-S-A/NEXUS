"""Contractor module: backfill draft contracts for historical `hired` stages + new NotificationType value

Revision ID: 0046_backfill_contractor_drafts
Revises: 0045_rejection_emails
Create Date: 2026-04-23 12:00:00.000000

Two things happen in this migration:

1. Add `contract_activated` to the `notificationtype` enum — previously
   auto-drafted contracts used `contract_ending` which is semantically wrong
   for a newly hired candidate. New notifications (from pipeline
   auto-draft + the activate endpoint) will use `contract_activated`.

2. Backfill: for every `CandidateStage` with stage='hired' that has no
   matching Contract (candidate_id + client_id + job_id triple), insert a
   draft Contract with `start_date = CURRENT_DATE` and `status = 'draft'`.
   This exposes every hired candidate in the new `/contractors` view even
   if they were hired before the auto-draft pipeline hook was introduced.

Idempotent: rerunning is safe because the INSERT is guarded by NOT EXISTS.
Downgrade is a no-op — we intentionally don't delete the drafts (they
represent real hired candidates and dropping them would lose data).
"""

from alembic import op


revision = "0046_backfill_contractor_drafts"
down_revision = "0045_rejection_emails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Add new enum value — must live in its own transaction block
    #    because PostgreSQL disallows ALTER TYPE ... ADD VALUE inside a
    #    transaction that later references the new label. alembic wraps
    #    each upgrade() in a transaction so we commit between steps via
    #    explicit COMMIT; this matches the pattern used by 0034_kpi_coach.
    op.execute("COMMIT")
    op.execute(
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'contract_activated'"
    )
    op.execute("BEGIN")

    # 2) Backfill draft contracts for orphaned `hired` stages.
    #    Only consider stages whose job has a client_id — mirrors the
    #    logic in pipeline.py that skips auto-drafts when client_id is
    #    NULL. Rely on SQL-level NOT EXISTS for idempotency.
    op.execute(
        """
        INSERT INTO contracts (
            candidate_id, client_id, job_id, start_date, status,
            currency, rate_unit, billing_hours_per_month, contract_type,
            created_at, updated_at
        )
        SELECT DISTINCT
            cs.candidate_id,
            j.client_id,
            j.id,
            CURRENT_DATE,
            'draft',
            'PLN',
            'monthly',
            160,
            'b2b',
            NOW(),
            NOW()
        FROM candidate_stages cs
        JOIN jobs j ON j.id = cs.job_id
        WHERE cs.stage = 'hired'
          AND j.client_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM contracts c
            WHERE c.candidate_id = cs.candidate_id
              AND c.client_id = j.client_id
              AND c.job_id = j.id
          )
        """
    )


def downgrade() -> None:
    # Soft-forward migration: we don't remove the enum value (downgrading
    # enums is destructive in PG) nor the backfilled drafts (they are real
    # business data). Intentional no-op.
    pass
