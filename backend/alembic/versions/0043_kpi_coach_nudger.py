"""KPI Coach Nudger — dedup constraint + opt-out flag

Revision ID: 0043_kpi_coach_nudger
Revises: 0042_interview_questions
Create Date: 2026-04-22 23:59:30.000000

Uzupełnia infrastrukturę KPI Coach o elementy potrzebne dla schedulera
z `app/tasks/kpi_coach_nudger.py`:

1. **Unique constraint na `kpi_nudge_log`** — hard guarantee dedupu przy
   wyścigu między cron sweep'em a ew. event-driven ścieżką. Klucz: (user_id,
   kpi_id, nudge_type, period_bucket). Migracja 0034 dodała tylko non-unique
   composite index o tych samych kolumnach — zostawiamy go (używany przez
   ORDER BY/WHERE, inny niż unique index) i dokładamy osobny unique.
2. **`users.kpi_coach_enabled BOOLEAN NOT NULL DEFAULT TRUE`** — per-user
   opt-out. Default True (system opt-in by default — spójne z filozofią
   "koleżeński coach domyślnie włączony"), toggle w Settings → Coaching.

Migracja 0034 już dodała wartość `kpi_coach` do enum `notificationtype`,
więc tutaj żadnej zmiany enum nie ma.

Idempotent + reversible.
"""

from alembic import op


revision = "0043_kpi_coach_nudger"
down_revision = "0042_interview_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Unique constraint dla dedupu nudge'y ─────────────────────────────
    # Jeśli constraint już istnieje (np. re-run) → DO NOTHING.
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE kpi_nudge_log
                ADD CONSTRAINT uq_kpi_nudge_log_dedup
                UNIQUE (user_id, kpi_id, nudge_type, period_bucket);
        EXCEPTION
            WHEN duplicate_object THEN null;
            WHEN duplicate_table THEN null;
        END $$;
        """
    )

    # ── Per-user opt-out flag ────────────────────────────────────────────
    # Backfill istniejących userów: kpi_coach_enabled = TRUE (default on).
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS kpi_coach_enabled BOOLEAN NOT NULL
            DEFAULT TRUE
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS kpi_coach_enabled")
    op.execute(
        "ALTER TABLE kpi_nudge_log DROP CONSTRAINT IF EXISTS "
        "uq_kpi_nudge_log_dedup"
    )
