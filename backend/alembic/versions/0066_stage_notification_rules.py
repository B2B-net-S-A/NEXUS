"""Configurable stage-transition notification rules + Nordrea seed

Revision ID: 0066_stage_notification_rules
Revises: 0065_chat_phase2
Create Date: 2026-04-27 18:00:00.000000

Context:
    Silnik konfigurowalnych powiadomień przy ruchach kandydata w pipeline.
    Reguły wiszą na ``pipeline_stage_defs`` (baseline per template), z
    opcjonalnym override per klient. Wcześniej istniał hardcoded notify do
    ``job.recruiter_id`` z ``backend/app/api/pipeline.py:430``; teraz robi to
    silnik reguł, a hardcoded fragment zastępuje wywołanie
    ``stage_notification_emitter.notify_stage_change``.

What this migration does:
    1. ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'stage_rule'
    2. CREATE TYPE recipienttype (PG enum, idempotent via DO/EXCEPTION)
    3. CREATE TABLE stage_notification_rules + indeksy + 2 CHECK
    4. CREATE TABLE client_stage_notification_overrides + indeks +
       UNIQUE z COALESCE (PG-only) — pozwala wiele override'ów per pair,
       blokuje dokładne duplikaty.
    5. Seed baseline — dla każdego istniejącego pipeline_stage_def utwórz
       domyślną regułę ``(job_recruiter, in-app only)``. ``WHERE NOT
       EXISTS`` → idempotent. Zachowuje obecny behavior.
    6. Seed Nordrea override — dla klienta o nazwie zaczynającej się
       'nordrea' + dla stage_def z ``legacy_enum_value='verified'`` →
       override ``(specific_user=Artur, email+inapp)``. Soft-fail jeśli
       klient/Artur nie istnieje.

Safety-net: każde DDL idempotentne (IF NOT EXISTS / DO $$ EXCEPTION).
"""

from alembic import op


revision = "0066_stage_notification_rules"
down_revision = "0065_chat_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Dodaj wartość 'stage_rule' do enum notificationtype (PG 12+).
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'stage_rule'")

    # 2) PG-level enum recipienttype.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE recipienttype AS ENUM (
                'job_delivery_lead',
                'job_recruiter',
                'client_head_dl',
                'client_primary_tac',
                'specific_user',
                'role',
                'candidate_creator'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )

    # 3) stage_notification_rules
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stage_notification_rules (
            id SERIAL PRIMARY KEY,
            stage_def_id INTEGER NOT NULL
                REFERENCES pipeline_stage_defs(id) ON DELETE CASCADE,
            recipient_type recipienttype NOT NULL,
            specific_user_id INTEGER NULL
                REFERENCES users(id) ON DELETE SET NULL,
            role VARCHAR(32) NULL,
            notify_inapp BOOLEAN NOT NULL DEFAULT TRUE,
            notify_email BOOLEAN NOT NULL DEFAULT FALSE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_stage_notif_specific_user CHECK (
                (recipient_type = 'specific_user' AND specific_user_id IS NOT NULL)
                OR (recipient_type <> 'specific_user' AND specific_user_id IS NULL)
            ),
            CONSTRAINT ck_stage_notif_role CHECK (
                (recipient_type = 'role' AND role IS NOT NULL)
                OR (recipient_type <> 'role' AND role IS NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stage_notif_rule_stage "
        "ON stage_notification_rules (stage_def_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_stage_notif_rule_active "
        "ON stage_notification_rules (is_active)"
    )

    # 4) client_stage_notification_overrides
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_stage_notification_overrides (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL
                REFERENCES clients(id) ON DELETE CASCADE,
            stage_def_id INTEGER NOT NULL
                REFERENCES pipeline_stage_defs(id) ON DELETE CASCADE,
            recipient_type recipienttype NOT NULL,
            specific_user_id INTEGER NULL
                REFERENCES users(id) ON DELETE SET NULL,
            role VARCHAR(32) NULL,
            notify_inapp BOOLEAN NOT NULL DEFAULT TRUE,
            notify_email BOOLEAN NOT NULL DEFAULT FALSE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_client_override_specific_user CHECK (
                (recipient_type = 'specific_user' AND specific_user_id IS NOT NULL)
                OR (recipient_type <> 'specific_user' AND specific_user_id IS NULL)
            ),
            CONSTRAINT ck_client_override_role CHECK (
                (recipient_type = 'role' AND role IS NOT NULL)
                OR (recipient_type <> 'role' AND role IS NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_override_client_stage "
        "ON client_stage_notification_overrides (client_id, stage_def_id)"
    )
    # COALESCE-based UNIQUE — zwykłe UNIQUE z NULL-ami nie traktuje (NULL,NULL)
    # jako duplikaty, więc dla `recipient_type=role` (specific_user_id IS NULL)
    # mielibyśmy nieskończoną liczbę kopii. COALESCE-y traktują NULL jak
    # sentinel value (0 / '') i naprawiają deduplication. Tworzymy expression
    # index zamiast UniqueConstraint (SQLAlchemy nie wspiera wyrażeń w UC).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_stage_override "
        "ON client_stage_notification_overrides ("
        "client_id, stage_def_id, recipient_type, "
        "COALESCE(specific_user_id, 0), COALESCE(role, '')"
        ")"
    )

    # 5) Seed baseline — `job_recruiter, in-app only` dla każdego stage_def.
    #    WHERE NOT EXISTS gwarantuje idempotency (re-run nic nie psuje).
    op.execute(
        """
        INSERT INTO stage_notification_rules (
            stage_def_id, recipient_type, notify_inapp, notify_email, is_active
        )
        SELECT psd.id, 'job_recruiter'::recipienttype, TRUE, FALSE, TRUE
        FROM pipeline_stage_defs psd
        WHERE NOT EXISTS (
            SELECT 1 FROM stage_notification_rules snr
            WHERE snr.stage_def_id = psd.id
              AND snr.recipient_type = 'job_recruiter'::recipienttype
              AND snr.specific_user_id IS NULL
              AND snr.role IS NULL
        )
        """
    )

    # 6) Seed Nordrea override → Artur dostaje email+in-app na 'verified'.
    #    ON CONFLICT DO NOTHING — bezpieczne przy re-runie.
    op.execute(
        """
        INSERT INTO client_stage_notification_overrides (
            client_id, stage_def_id, recipient_type, specific_user_id,
            notify_inapp, notify_email, is_active
        )
        SELECT c.id, psd.id, 'specific_user'::recipienttype, u.id, TRUE, TRUE, TRUE
        FROM clients c
        CROSS JOIN pipeline_stage_defs psd
        CROSS JOIN users u
        WHERE LOWER(c.name) LIKE 'nordrea%'
          AND psd.legacy_enum_value = 'verified'
          AND LOWER(u.email) = 'artek9321@gmail.com'
        ON CONFLICT (
            client_id, stage_def_id, recipient_type,
            COALESCE(specific_user_id, 0), COALESCE(role, '')
        ) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_client_stage_override")
    op.execute("DROP INDEX IF EXISTS ix_client_override_client_stage")
    op.execute("DROP TABLE IF EXISTS client_stage_notification_overrides")
    op.execute("DROP INDEX IF EXISTS ix_stage_notif_rule_active")
    op.execute("DROP INDEX IF EXISTS ix_stage_notif_rule_stage")
    op.execute("DROP TABLE IF EXISTS stage_notification_rules")
    op.execute("DROP TYPE IF EXISTS recipienttype")
    # NIE usuwamy 'stage_rule' z notificationtype — Postgres nie wspiera
    # bezpiecznego DROP VALUE z enuma. Zostaje jako no-op enum value.
