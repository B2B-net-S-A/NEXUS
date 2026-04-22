"""Phase 13: Notification triggers — 5 new types + delivery_lead + dedup index

Revision ID: 0029
Revises: 0028
Create Date: 2026-04-21 10:00:00.000000

Adds infrastructure for 5 automated notification triggers without touching the
existing `slack_sla_alerts_loop`:

- `userrole` enum  → + `head_of_recruitment`        (Olaf-type managers)
- `notificationtype` enum → + 5 new values (dl_stage_stale_6h, client_feedback_eobd,
  powercalling_kpi, candidate_feedback_1h, stage_stuck_7d)
- `notifications` → + related_entity_type, related_entity_id (polymorphic dedup key)
- `jobs`          → + delivery_lead_id FK (adresat DL alertów)
- Unique partial index `ix_notif_dedup_daily`  — jeden alert na (user, type,
  entity, dzień-lokalny Europe/Warsaw). Twarda gwarancja idempotentności.

NB: `ALTER TYPE ... ADD VALUE` wymaga autocommit (PG nie pozwala na to w
bloku transakcyjnym) — używamy `op.execute` na końcu z COMMIT forsowanym przez
Alembic `autocommit_block`.
"""

from alembic import op
import sqlalchemy as sa


# NB: `revision` jest wyjątkowy (nie "0029") bo w repo istnieje 5 innych plików
# 0029_*.py z tym samym `revision = "0029"` — multi-head bałagan z innych PR-ów
# który trzeba kiedyś rozwiązać `alembic merge`. Do tego czasu ten slug izoluje
# Phase 13 na własnej gałęzi od 0028 i pozwala wzwyż uruchamiać go adresowo.
revision = "notif_triggers_13"
down_revision = "0028"
branch_labels = None
depends_on = None


_NEW_NOTIF_TYPES = (
    "dl_stage_stale_6h",
    "client_feedback_eobd",
    "powercalling_kpi",
    "candidate_feedback_1h",
    "stage_stuck_7d",
)


def upgrade() -> None:
    """Idempotentna upgrade ścieżka.

    Używamy IF NOT EXISTS w surowym SQL wszędzie gdzie się da, bo w DEV tryb
    `Base.metadata.create_all()` (patrz main.py lifespan) może już utworzyć
    kolumny z modelu. Migracja ma być bezpieczna do re-runu na takiej bazie.
    """
    # 1) Enum extensions — poza transakcją (PG wymóg dla ADD VALUE).
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'head_of_recruitment'"
        )
        for value in _NEW_NOTIF_TYPES:
            op.execute(
                f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
            )

    # 2) Polymorphic dedup key na notifications.
    op.execute(
        "ALTER TABLE notifications "
        "ADD COLUMN IF NOT EXISTS related_entity_type VARCHAR(50)"
    )
    op.execute(
        "ALTER TABLE notifications "
        "ADD COLUMN IF NOT EXISTS related_entity_id INTEGER"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_related_entity_id "
        "ON notifications (related_entity_id)"
    )

    # 3) Delivery Lead na jobs — adresat alertów #1 (DL_STAGE_STALE_6H) i #2
    #    (CLIENT_FEEDBACK_EOBD). Jeśli NULL → fallback broadcast do wszystkich
    #    userów z rolą delivery_lead w trigger logic.
    op.execute(
        "ALTER TABLE jobs "
        "ADD COLUMN IF NOT EXISTS delivery_lead_id INTEGER "
        "REFERENCES users(id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_delivery_lead_id "
        "ON jobs (delivery_lead_id)"
    )

    # 4) Twarda idempotentność: jeden alert na (user, type, entity, dzień-lokalny).
    #    Partial index — pomija rekordy bez related_entity_id (stare typy typu
    #    contract_ending nie mają entity tracking, więc nie powinny kolidować).
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_notif_dedup_daily
          ON notifications
          (user_id, notification_type, related_entity_id,
           (date_trunc('day', created_at AT TIME ZONE 'Europe/Warsaw')))
          WHERE related_entity_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_notif_dedup_daily")
    op.drop_index("ix_jobs_delivery_lead_id", table_name="jobs")
    op.drop_column("jobs", "delivery_lead_id")
    op.drop_index(
        "ix_notifications_related_entity_id", table_name="notifications"
    )
    op.drop_column("notifications", "related_entity_id")
    op.drop_column("notifications", "related_entity_type")
    # Nie usuwamy enum values — PG nie wspiera DROP VALUE bez recreacji typu,
    # a istniejące dane mogłyby na nie wskazywać. To jest akceptowalny trade-off
    # jak przy innych migracjach w repo.
