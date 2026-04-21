"""KPI Coach — role defaults, user targets, nudge log

Revision ID: 0034_kpi_coach
Revises: 0033_cc_entities
Create Date: 2026-04-21 20:00:00.000000

Dodaje infrastrukturę pod system "KPI Coach" — dynamiczną analizę KPI
rekruterów z chwaleniem (przy hit) i przypominaniem (przy behind).

Scope:
- `kpi_role_defaults` — per-rola default target_value dla każdego kpi_id z
  katalogu w kodzie (app/services/kpi_catalog.py). Admin edytuje wartości
  liczbowe; definicje KPI żyją w kodzie.
- `user_kpi_targets` — opcjonalny per-user override defaults.
- `kpi_nudge_log` — historia wysłanych nudge'y, służy do dedupu
  per (user, kpi, type, period_bucket). period_bucket: "YYYY-MM-DD" dla
  dziennych, "YYYY-Www" dla tygodniowych, "YYYY-MM" dla miesięcznych.
- Composite index `ix_user_activities_user_action_created` przyspieszający
  liczenie per-user per-action w oknie czasu.
- Rozszerzenie enum `notificationtype` o `kpi_coach` (wspólny typ dla
  wszystkich powiadomień z KPI Coach; rodzaj praise/remind jest w
  `kpi_nudge_log.nudge_type`).
- Seed `kpi_role_defaults` z defaultami per rola wg planu MVP.

Idempotentne + reversible.
"""

from alembic import op
import sqlalchemy as sa


revision = "0034_kpi_coach"
down_revision = "0033_cc_entities"
branch_labels = None
depends_on = None


# Defaulty per rola zgodnie z planem MVP. Jeśli rola nie występuje dla
# danego kpi_id, target = 0 → KPI niewidoczne dla tej roli.
_ROLE_DEFAULT_ROWS = [
    # (kpi_id, role, target_value)
    ("daily_activity_count", "recruiter", 10),
    ("daily_activity_count", "tac", 12),
    ("daily_activity_count", "sourcer", 8),
    ("daily_new_candidates", "recruiter", 3),
    ("daily_new_candidates", "tac", 2),
    ("daily_new_candidates", "sourcer", 5),
    ("weekly_cvs_sent", "recruiter", 15),
    ("weekly_cvs_sent", "tac", 12),
    ("weekly_screenings", "recruiter", 5),
    ("weekly_screenings", "tac", 7),
    ("weekly_screenings", "sourcer", 3),
    ("monthly_placements", "recruiter", 2),
    ("monthly_placements", "tac", 3),
    ("monthly_placements", "sourcer", 1),
]


def upgrade() -> None:
    # ── Enum: nudge_type, nudge_channel ──────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE kpinudgetype AS ENUM (
                'praise_hit', 'remind_behind', 'eod_summary', 'streak_bonus'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE kpinudgechannel AS ENUM (
                'toast', 'notification', 'slack'
            );
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    # Rozszerzenie enum notificationtype o kpi_coach (in-app powiadomienia
    # z systemu KPI Coach).
    op.execute(
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'kpi_coach'"
    )

    # ── kpi_role_defaults ────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kpi_role_defaults (
            id            SERIAL PRIMARY KEY,
            role          userrole NOT NULL,
            kpi_id        VARCHAR(64) NOT NULL,
            target_value  INTEGER NOT NULL CHECK (target_value >= 0),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_kpi_role_defaults_role_kpi UNIQUE (role, kpi_id)
        )
        """
    )

    # ── user_kpi_targets ────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_kpi_targets (
            id            SERIAL PRIMARY KEY,
            user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kpi_id        VARCHAR(64) NOT NULL,
            target_value  INTEGER NOT NULL CHECK (target_value >= 0),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_kpi_targets_user_kpi UNIQUE (user_id, kpi_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_kpi_targets_user "
        "ON user_kpi_targets(user_id)"
    )

    # ── kpi_nudge_log ────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kpi_nudge_log (
            id               BIGSERIAL PRIMARY KEY,
            user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kpi_id           VARCHAR(64) NOT NULL,
            nudge_type       kpinudgetype NOT NULL,
            channel          kpinudgechannel NOT NULL,
            message_variant  INTEGER NOT NULL,
            period_bucket    VARCHAR(20) NOT NULL,
            sent_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kpi_nudge_log_dedup "
        "ON kpi_nudge_log(user_id, kpi_id, nudge_type, period_bucket)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kpi_nudge_log_user_sent "
        "ON kpi_nudge_log(user_id, sent_at DESC)"
    )

    # ── Composite index na user_activities dla szybkiego COUNT per
    # (user, action_type, window) ────────────────────────────────────────
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_activities_user_action_created "
        "ON user_activities(user_id, action_type, created_at)"
    )

    # ── Seed role_defaults ───────────────────────────────────────────────
    # ON CONFLICT DO NOTHING żeby re-run nie psuł istniejących, zmienionych
    # wartości — reseed tylko tam gdzie rekord nie istnieje.
    bind = op.get_bind()
    for kpi_id, role, target in _ROLE_DEFAULT_ROWS:
        bind.execute(
            sa.text(
                "INSERT INTO kpi_role_defaults (role, kpi_id, target_value) "
                "VALUES (:role, :kpi_id, :target) "
                "ON CONFLICT ON CONSTRAINT uq_kpi_role_defaults_role_kpi "
                "DO NOTHING"
            ),
            {"role": role, "kpi_id": kpi_id, "target": target},
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_activities_user_action_created")
    op.execute("DROP INDEX IF EXISTS ix_kpi_nudge_log_user_sent")
    op.execute("DROP INDEX IF EXISTS ix_kpi_nudge_log_dedup")
    op.execute("DROP TABLE IF EXISTS kpi_nudge_log")
    op.execute("DROP INDEX IF EXISTS ix_user_kpi_targets_user")
    op.execute("DROP TABLE IF EXISTS user_kpi_targets")
    op.execute("DROP TABLE IF EXISTS kpi_role_defaults")
    op.execute("DROP TYPE IF EXISTS kpinudgechannel")
    op.execute("DROP TYPE IF EXISTS kpinudgetype")
    # notificationtype.kpi_coach — Postgres nie wspiera usuwania wartości
    # z enum bez recreate'u. Pozostawiamy; brak wpływu na funkcjonalność.
