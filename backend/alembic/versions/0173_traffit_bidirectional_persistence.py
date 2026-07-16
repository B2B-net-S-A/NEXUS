"""Traffit bidirectional integration — persistence primitives (plan PR2).

Dziewięć nowych tabel (entity links / field contracts / outbox / webhook inbox /
conflicts / runs+phases / leases / runtime control) plus rozszerzenia encji
(candidates.profile_about + custom_fields, notes.external_*, candidate_documents
content-identity, rejection_reasons.external_*, traffit_sync_state cursors).

Wszystkie statusy lifecycle'owe są VARCHAR (walidacja w warstwie aplikacji) —
workery integracji muszą móc wprowadzić nowy stan retry/dead-letter bez
blokującej migracji enuma.

Idempotentne CREATE TABLE / INDEX / ADD COLUMN z IF NOT EXISTS — współgra z
entrypointowym ``alembic upgrade heads`` + safety-netem ``Base.metadata
.create_all`` (nowe TABELE lądują na prod nawet przy multi-head; lustro DDL
w ``backend/entrypoint.sh`` zgodnie z repozytoryjną pułapką produkcyjną).

UWAGA: zapisów do tych tabel nie wykonuje jeszcze żaden worker — wszystkie
gate'y środowiskowe (TRAFFIT_INTEGRATION_*) są domyślnie OFF.
"""

from alembic import op

revision = "0173_traffit_bidirectional_persistence"
down_revision = "0172_job_shortlist_entries"
branch_labels = None
depends_on = None


_NEW_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS traffit_entity_links (
        id                     BIGSERIAL PRIMARY KEY,
        entity_type            VARCHAR(50) NOT NULL,
        nexus_entity_id        BIGINT NULL,
        traffit_entity_id      VARCHAR(255) NULL,
        candidate_id           INTEGER NULL
                                   REFERENCES candidates(id) ON DELETE SET NULL,
        status                 VARCHAR(40) NOT NULL DEFAULT 'active',
        base_snapshot          JSONB NULL,
        base_schema_hash       VARCHAR(64) NULL,
        nexus_snapshot_hash    VARCHAR(64) NULL,
        traffit_snapshot_hash  VARCHAR(64) NULL,
        nexus_updated_at       TIMESTAMPTZ NULL,
        traffit_updated_at     TIMESTAMPTZ NULL,
        last_synced_at         TIMESTAMPTZ NULL,
        last_seen_at           TIMESTAMPTZ NULL,
        missing_since          TIMESTAMPTZ NULL,
        missing_strikes        INTEGER NOT NULL DEFAULT 0,
        source_deleted_at      TIMESTAMPTZ NULL,
        pending_delete_at      TIMESTAMPTZ NULL,
        last_direction         VARCHAR(20) NULL,
        last_error             TEXT NULL,
        created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_traffit_entity_links_nexus "
    "ON traffit_entity_links (entity_type, nexus_entity_id) "
    "WHERE nexus_entity_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_traffit_entity_links_remote "
    "ON traffit_entity_links (entity_type, traffit_entity_id) "
    "WHERE traffit_entity_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_traffit_entity_links_candidate_status "
    "ON traffit_entity_links (candidate_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_traffit_entity_links_last_seen "
    "ON traffit_entity_links (entity_type, last_seen_at)",
    """
    CREATE TABLE IF NOT EXISTS traffit_field_contracts (
        id                 BIGSERIAL PRIMARY KEY,
        field_name         VARCHAR(255) NOT NULL,
        capability         VARCHAR(20) NOT NULL,
        endpoint           VARCHAR(255) NULL,
        local_path         VARCHAR(255) NULL,
        data_type          VARCHAR(100) NULL,
        adapter            VARCHAR(100) NULL,
        required           BOOLEAN NOT NULL DEFAULT false,
        readable           BOOLEAN NOT NULL DEFAULT true,
        writable           BOOLEAN NOT NULL DEFAULT false,
        choices            JSONB NULL,
        raw_metadata       JSONB NULL,
        schema_hash        VARCHAR(64) NOT NULL,
        status             VARCHAR(30) NOT NULL DEFAULT 'active',
        quarantine_reason  TEXT NULL,
        discovered_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_traffit_field_contract_capability
            UNIQUE (field_name, capability)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_traffit_field_contracts_status "
    "ON traffit_field_contracts (status)",
    """
    CREATE TABLE IF NOT EXISTS traffit_outbox_events (
        id               BIGSERIAL PRIMARY KEY,
        event_uuid       VARCHAR(36) NOT NULL UNIQUE,
        aggregate_type   VARCHAR(50) NOT NULL,
        aggregate_id     BIGINT NOT NULL,
        candidate_id     INTEGER NULL
                             REFERENCES candidates(id) ON DELETE SET NULL,
        entity_link_id   BIGINT NULL
                             REFERENCES traffit_entity_links(id) ON DELETE SET NULL,
        event_type       VARCHAR(100) NOT NULL,
        payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
        changed_fields   JSONB NOT NULL DEFAULT '[]'::jsonb,
        actor_user_id    INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        origin           VARCHAR(20) NOT NULL DEFAULT 'nexus',
        idempotency_key  VARCHAR(128) NOT NULL UNIQUE,
        sequence         BIGINT NOT NULL DEFAULT 0,
        priority         INTEGER NOT NULL DEFAULT 100,
        status           VARCHAR(30) NOT NULL DEFAULT 'pending',
        attempts         INTEGER NOT NULL DEFAULT 0,
        max_attempts     INTEGER NOT NULL DEFAULT 8,
        next_attempt_at  TIMESTAMPTZ NULL DEFAULT now(),
        locked_at        TIMESTAMPTZ NULL,
        locked_by        VARCHAR(255) NULL,
        processed_at     TIMESTAMPTZ NULL,
        remote_response  JSONB NULL,
        last_error       TEXT NULL,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_traffit_outbox_due "
    "ON traffit_outbox_events (priority, next_attempt_at, id) "
    "WHERE status IN ('pending', 'retry')",
    "CREATE INDEX IF NOT EXISTS ix_traffit_outbox_aggregate_order "
    "ON traffit_outbox_events (aggregate_type, aggregate_id, sequence, id)",
    "CREATE INDEX IF NOT EXISTS ix_traffit_outbox_candidate_status "
    "ON traffit_outbox_events (candidate_id, status)",
    """
    CREATE TABLE IF NOT EXISTS traffit_webhook_events (
        id                  BIGSERIAL PRIMARY KEY,
        subscription_id     VARCHAR(100) NOT NULL,
        dedupe_key          VARCHAR(128) NOT NULL,
        event_type          VARCHAR(100) NOT NULL,
        remote_entity_type  VARCHAR(50) NULL,
        remote_entity_id    VARCHAR(255) NULL,
        payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
        payload_hash        VARCHAR(64) NOT NULL,
        status              VARCHAR(30) NOT NULL DEFAULT 'pending',
        attempts            INTEGER NOT NULL DEFAULT 0,
        max_attempts        INTEGER NOT NULL DEFAULT 8,
        next_attempt_at     TIMESTAMPTZ NULL DEFAULT now(),
        locked_at           TIMESTAMPTZ NULL,
        locked_by           VARCHAR(255) NULL,
        processed_at        TIMESTAMPTZ NULL,
        last_error          TEXT NULL,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_traffit_webhook_dedupe
            UNIQUE (subscription_id, dedupe_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_traffit_webhook_due "
    "ON traffit_webhook_events (next_attempt_at, id) "
    "WHERE status IN ('pending', 'retry')",
    "CREATE INDEX IF NOT EXISTS ix_traffit_webhook_remote_entity "
    "ON traffit_webhook_events (remote_entity_type, remote_entity_id)",
    """
    CREATE TABLE IF NOT EXISTS traffit_sync_conflicts (
        id                 BIGSERIAL PRIMARY KEY,
        entity_link_id     BIGINT NULL
                               REFERENCES traffit_entity_links(id) ON DELETE SET NULL,
        outbox_event_id    BIGINT NULL
                               REFERENCES traffit_outbox_events(id) ON DELETE SET NULL,
        entity_type        VARCHAR(50) NOT NULL,
        nexus_entity_id    BIGINT NULL,
        traffit_entity_id  VARCHAR(255) NULL,
        candidate_id       INTEGER NULL
                               REFERENCES candidates(id) ON DELETE SET NULL,
        field_path         VARCHAR(255) NULL,
        conflict_type      VARCHAR(50) NOT NULL,
        idempotency_key    VARCHAR(128) NULL,
        base_value         JSONB NULL,
        nexus_value        JSONB NULL,
        traffit_value      JSONB NULL,
        status             VARCHAR(30) NOT NULL DEFAULT 'open',
        resolution         VARCHAR(30) NULL,
        resolved_value     JSONB NULL,
        resolution_note    TEXT NULL,
        detected_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
        resolved_at        TIMESTAMPTZ NULL,
        resolved_by        INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_traffit_conflicts_open "
    "ON traffit_sync_conflicts (detected_at, id) "
    "WHERE status IN ('open', 'manual_action_required')",
    "CREATE INDEX IF NOT EXISTS ix_traffit_conflicts_candidate "
    "ON traffit_sync_conflicts (candidate_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_traffit_conflicts_entity "
    "ON traffit_sync_conflicts (entity_type, nexus_entity_id, traffit_entity_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_traffit_conflicts_idempotency "
    "ON traffit_sync_conflicts (idempotency_key) "
    "WHERE idempotency_key IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS traffit_sync_runs (
        id             BIGSERIAL PRIMARY KEY,
        run_uuid       VARCHAR(36) NOT NULL UNIQUE,
        mode           VARCHAR(30) NOT NULL,
        trigger        VARCHAR(30) NOT NULL,
        scope          JSONB NOT NULL DEFAULT '{}'::jsonb,
        status         VARCHAR(30) NOT NULL DEFAULT 'queued',
        dry_run        BOOLEAN NOT NULL DEFAULT true,
        leader_id      VARCHAR(255) NULL,
        started_at     TIMESTAMPTZ NULL,
        finished_at    TIMESTAMPTZ NULL,
        cursor_before  JSONB NULL,
        cursor_after   JSONB NULL,
        stats          JSONB NOT NULL DEFAULT '{}'::jsonb,
        errors         JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_traffit_sync_runs_status_started "
    "ON traffit_sync_runs (status, started_at)",
    "CREATE INDEX IF NOT EXISTS ix_traffit_sync_runs_mode_created "
    "ON traffit_sync_runs (mode, created_at)",
    """
    CREATE TABLE IF NOT EXISTS traffit_sync_run_phases (
        id                 BIGSERIAL PRIMARY KEY,
        run_id             BIGINT NOT NULL
                               REFERENCES traffit_sync_runs(id) ON DELETE CASCADE,
        phase              VARCHAR(100) NOT NULL,
        status             VARCHAR(30) NOT NULL DEFAULT 'queued',
        started_at         TIMESTAMPTZ NULL,
        finished_at        TIMESTAMPTZ NULL,
        cursor_before      JSONB NULL,
        cursor_after       JSONB NULL,
        pages_processed    INTEGER NOT NULL DEFAULT 0,
        items_seen         INTEGER NOT NULL DEFAULT 0,
        items_applied      INTEGER NOT NULL DEFAULT 0,
        items_skipped      INTEGER NOT NULL DEFAULT 0,
        conflicts_created  INTEGER NOT NULL DEFAULT 0,
        complete           BOOLEAN NOT NULL DEFAULT false,
        stats              JSONB NOT NULL DEFAULT '{}'::jsonb,
        error              TEXT NULL,
        created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_traffit_sync_run_phase UNIQUE (run_id, phase)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_traffit_sync_run_phases_run_status "
    "ON traffit_sync_run_phases (run_id, status)",
    """
    CREATE TABLE IF NOT EXISTS integration_leases (
        name          VARCHAR(100) PRIMARY KEY,
        holder_id     VARCHAR(255) NOT NULL,
        acquired_at   TIMESTAMPTZ NOT NULL,
        heartbeat_at  TIMESTAMPTZ NOT NULL,
        expires_at    TIMESTAMPTZ NOT NULL,
        generation    BIGINT NOT NULL DEFAULT 1,
        metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_integration_leases_expires_at "
    "ON integration_leases (expires_at)",
    """
    CREATE TABLE IF NOT EXISTS traffit_integration_control (
        integration             VARCHAR(50) PRIMARY KEY,
        webhook_accept_enabled  BOOLEAN NOT NULL DEFAULT false,
        inbound_apply_enabled   BOOLEAN NOT NULL DEFAULT false,
        poll_enabled            BOOLEAN NOT NULL DEFAULT false,
        outbound_enabled        BOOLEAN NOT NULL DEFAULT false,
        dry_run                 BOOLEAN NOT NULL DEFAULT true,
        paused_reason           TEXT NULL,
        settings                JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_by              INTEGER NULL
                                    REFERENCES users(id) ON DELETE SET NULL,
        created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
]

_ENTITY_EXTENSIONS = [
    # candidates — edytowalny opis profilu (Traffit candidate_about) oddzielny
    # od ai_summary + tenantowe custom fields `_<SID>`.
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS profile_about TEXT",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS custom_fields JSONB "
    "NOT NULL DEFAULT '{}'::jsonb",
    # notes — strukturalna tożsamość źródła + append-only corrections.
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS external_source VARCHAR(50)",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS external_id VARCHAR(255)",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS source_created_at TIMESTAMPTZ",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS source_updated_at TIMESTAMPTZ",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS source_deleted_at TIMESTAMPTZ",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS supersedes_note_id INTEGER "
    "REFERENCES notes(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_notes_external_source ON notes (external_source)",
    "CREATE INDEX IF NOT EXISTS ix_notes_external_id ON notes (external_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_notes_external_source_id "
    "ON notes (external_source, external_id) WHERE external_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_notes_candidate_source_created "
    "ON notes (candidate_id, external_source, source_created_at)",
    # candidate_documents — tożsamość treści (SHA-256) + manifest źródła.
    "ALTER TABLE candidate_documents ADD COLUMN IF NOT EXISTS "
    "content_sha256 VARCHAR(64)",
    "ALTER TABLE candidate_documents ADD COLUMN IF NOT EXISTS "
    "source_manifest_fingerprint VARCHAR(64)",
    "ALTER TABLE candidate_documents ADD COLUMN IF NOT EXISTS "
    "source_deleted_at TIMESTAMPTZ",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_documents_candidate_sha "
    "ON candidate_documents (candidate_id, content_sha256) "
    "WHERE content_sha256 IS NOT NULL AND source_deleted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_candidate_documents_manifest "
    "ON candidate_documents (candidate_id, source_manifest_fingerprint)",
    # rejection_reasons — mapowanie remote rejection_id dla outbound reject.
    "ALTER TABLE rejection_reasons ADD COLUMN IF NOT EXISTS "
    "external_source VARCHAR(50)",
    "ALTER TABLE rejection_reasons ADD COLUMN IF NOT EXISTS external_id VARCHAR(100)",
    "UPDATE rejection_reasons SET external_source = 'manual' "
    "WHERE external_source IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_rejection_reasons_external_source "
    "ON rejection_reasons (external_source)",
    "CREATE INDEX IF NOT EXISTS ix_rejection_reasons_external_id "
    "ON rejection_reasons (external_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_rejection_reasons_external_source_id "
    "ON rejection_reasons (external_source, external_id) "
    "WHERE external_id IS NOT NULL",
    # traffit_sync_state — kursor per strumień/tryb (shadow/live) + telemetria.
    "ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS cursor_at TIMESTAMPTZ",
    "ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS "
    "cursor_external_id VARCHAR(255)",
    "ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS cursor_payload JSONB",
    "ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS "
    "last_attempt_at TIMESTAMPTZ",
    "ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS "
    "last_success_at TIMESTAMPTZ",
    "ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS "
    "consecutive_failures INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS last_error TEXT",
    "ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS next_due_at TIMESTAMPTZ",
]


def upgrade() -> None:
    for stmt in _NEW_TABLES:
        op.execute(stmt)
    for stmt in _ENTITY_EXTENSIONS:
        op.execute(stmt)


def downgrade() -> None:
    # Nowe tabele znikają w całości; kolumny dodane do istniejących encji
    # zostają (drop = utrata danych — usuwać tylko świadomą, osobną migracją).
    op.execute("DROP TABLE IF EXISTS traffit_sync_run_phases")
    op.execute("DROP TABLE IF EXISTS traffit_sync_runs")
    op.execute("DROP TABLE IF EXISTS traffit_sync_conflicts")
    op.execute("DROP TABLE IF EXISTS traffit_webhook_events")
    op.execute("DROP TABLE IF EXISTS traffit_outbox_events")
    op.execute("DROP TABLE IF EXISTS traffit_field_contracts")
    op.execute("DROP TABLE IF EXISTS traffit_entity_links")
    op.execute("DROP TABLE IF EXISTS integration_leases")
    op.execute("DROP TABLE IF EXISTS traffit_integration_control")
