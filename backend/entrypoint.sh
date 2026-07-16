#!/bin/bash
set -e

# Privilege handoff (root → appuser). The Dockerfile leaves ENTRYPOINT as
# root specifically so this block can heal volume ownership. Named Docker
# volumes (e.g. `uploads_data` mounted at /tmp/nexus/uploads) created under
# earlier images that ran as root retain root ownership on first mount, and
# the unprivileged appuser cannot create subdirectories there. Without this
# heal, `POST /api/clients/{id}/framework-contracts` 500'd in prod on
# 2026-05-25 with `PermissionError: '/tmp/nexus/uploads/client_framework_contracts'`
# because the volume from before commit 2b465d6 (P0/P1 security review,
# which introduced the non-root user) was still root-owned. We chown the
# entire `/tmp/nexus` tree as root, then `exec gosu appuser:appgroup` to
# re-execute this same script as the unprivileged user — meaning the
# Python process below still runs with the privilege drop intended by the
# security hardening, just with writable uploads.
if [ "$(id -u)" = "0" ]; then
    echo "=== Nexus ATS Backend Privilege Handoff (root -> appuser) ==="
    # Pre-create upload subdirs so the chown -R below cascades into them.
    # The Docker named volume `uploads_data` mounts on top of
    # /tmp/nexus/uploads and clobbers the Dockerfile's `RUN mkdir`, so
    # any subdir the app writes at runtime has to be materialised at boot
    # while we are still root. Without this, attachment_handler._persist_bytes
    # failed with PermissionError on /tmp/nexus/uploads/microsoft365 (Sentry
    # NEXUS-BE-D — 303 events, ongoing 2026-05-25): the M365 sync loop tried
    # mkdir-as-appuser on the volume root and never recovered.
    mkdir -p \
        /tmp/nexus/uploads/microsoft365 \
        /tmp/nexus/uploads/client_framework_contracts \
        /tmp/nexus/uploads/candidate_documents \
        || echo "WARN: mkdir /tmp/nexus/uploads/* failed"
    if chown -R appuser:appgroup /tmp/nexus; then
        echo "chown /tmp/nexus ok"
    else
        echo "WARN: chown /tmp/nexus failed (volume read-only?); appuser may not be able to upload"
    fi
    exec gosu appuser:appgroup "$0" "$@"
fi

export PYTHONPATH=/app:${PYTHONPATH}

echo "=== Nexus ATS Backend Starting (as $(id -un)) ==="

# Wait for postgres to be ready
echo "Waiting for database..."
until python -c "
import asyncio, asyncpg, os

async def check():
    url = os.environ.get('DATABASE_URL', 'postgresql+asyncpg://nexus:nexus@postgres:5432/nexus')
    url = url.replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    await conn.close()
    print('Database ready!')

asyncio.run(check())
" 2>/dev/null; do
    echo "Database not ready, retrying in 2s..."
    sleep 2
done

# Run migrations
# The alembic.ini lives in /app/alembic/ but script_location=alembic points to /app/alembic
# Run from /app so that 'alembic' dir is found correctly
echo "Running database migrations..."
cd /app
# Tolerate alembic failures in dev: multiple in-flight feature branches can
# produce duplicate-revision or multi-head states. In DEBUG mode the app
# falls back to Base.metadata.create_all() on startup, so tables still exist.
# Production should never hit this path (clean single-head chain on main).
alembic -c alembic/alembic.ini upgrade heads 2>&1 || echo "alembic upgrade failed (likely multi-head in dev); continuing via Base.metadata.create_all"

# Safety net: alembic upgrade sometimes bails halfway through the Phase 8
# multi-head graph (see project_alembic_state memory). The ORM expects
# several columns that those migrations ship; backfill them idempotently
# so ORM queries don't crash with UndefinedColumnError. Non-fatal — bail
# back to alembic-only behavior if anything unexpected happens.
echo "Backfilling critical Phase 8 columns (idempotent)..."
python - <<'PY' || echo "column backfill failed; continuing"
import asyncio, os
import asyncpg

# Every statement here is idempotent. Order matters for enum ADD VALUE
# (must run outside transaction) vs column adds (can run in tx).
_ENUM_STATEMENTS = [
    # Plan analytics PR 6 — status korekt finansowych.
    """DO $$ BEGIN
        CREATE TYPE adjustmentstatus AS ENUM ('draft', 'approved');
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # userrole: head_of_recruitment (migration 0029_notifications_triggers)
    "ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'head_of_recruitment'",
    # notificationtype: 5 trigger types + champion_profile_updated
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'dl_stage_stale_6h'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'client_feedback_eobd'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'powercalling_kpi'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'candidate_feedback_1h'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'stage_stuck_7d'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'champion_profile_updated'",
    # Migration 0029 ALSO creates the partial UNIQUE index `ix_notif_dedup_daily`
    # — the ONLY thing enforcing 1-alert-per-(user,type,entity,Warsaw-day).
    # `emit()` relies on "INSERT → IntegrityError → skip" for dedup. On prod the
    # raw-SQL index from 0029 never applied (create_all builds the table from the
    # ORM model, which does NOT declare this expression index, and alembic was
    # stamped past 0029), so dedup silently no-op'd and triggers_loop re-inserted
    # every stale-stage alert every 5 min → ~137M rows / 45GB by 2026-05-22, the
    # per-user notifications query saturated the DB pool and took the whole API
    # down. This safety-net guarantees the index exists so dedup actually works.
    """CREATE UNIQUE INDEX IF NOT EXISTS ix_notif_dedup_daily
        ON notifications
        (user_id, notification_type, related_entity_id,
         (date_trunc('day', created_at AT TIME ZONE 'Europe/Warsaw')))
        WHERE related_entity_id IS NOT NULL""",
    # Covering index for the per-user notifications poll
    # (GET /api/notifications: WHERE user_id=? ORDER BY is_read, created_at DESC
    # LIMIT ?). Lets Postgres return the top-N straight from the index instead
    # of sorting a user's whole history — insurance so a large notifications
    # table can never again exhaust the connection pool (incident 2026-05-22).
    "CREATE INDEX IF NOT EXISTS ix_notifications_user_read_created "
    "ON notifications (user_id, is_read, created_at DESC)",
    # Kontrakty expansion (migration 0037) notificationtype extensions
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'contract_ending_90d'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'equipment_return_due_14d'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'client_order_ending_30d'",
    # Phase 14 (migration 0043_interview_feedback) post-interview reminders
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'post_interview_t15'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'post_interview_t45'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'post_interview_t2h_escalation'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'suggest_next_step'",
    # KPI Coach (migration 0034_kpi_coach): dodaje value 'kpi_coach' do enum
    # notificationtype. Bez tego insert Notification(notification_type='kpi_coach')
    # crashuje z InvalidTextRepresentationError (DB enum nie zna wartości).
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'kpi_coach'",
    # Contractor module (migration 0046_backfill_contractor_drafts): auto-draft
    # + POST /api/contracts/{id}/activate oba używają 'contract_activated' jako
    # notification_type. Safety-net chroni prod przed crash-loopem gdyby alembic
    # head był wolniejszy niż restart aplikacji.
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'contract_activated'",
    # Phase 15 (migration 0051_champion_historical_source): nowe źródło
    # sugestii Profilu Championa — podobne historyczne role jako baza pre-fill.
    # Safety-net: /api/jobs/{id}/champion-profile/generate-from-history używa
    # tej wartości w INSERT, więc brak w enum => InvalidTextRepresentationError
    # i crash-loop feature'a dla DL-i.
    "ALTER TYPE champion_suggestion_source ADD VALUE IF NOT EXISTS 'historical_jobs'",
    # Autenti e-signature (migration 0079_autenti_signatures): 4 nowe wartości
    # notificationtype + dedykowany enum signaturestatus. Bez tego safety-netu
    # POST /api/autenti/contracts/{id}/send wywala się na insercie Notification
    # (notification_type='signature_sent') gdy alembic upgrade nie wszedł na
    # prod (np. multi-head w dev gałęziach 0036).
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'signature_sent'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'signature_signed'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'signature_rejected'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'signature_failed'",
    # signaturestatus enum (CREATE TYPE wymaga DO $$ bo PG nie ma IF NOT EXISTS).
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'signaturestatus') THEN
            CREATE TYPE signaturestatus AS ENUM (
                'draft', 'sending', 'sent', 'in_progress',
                'completed', 'rejected', 'withdrawn', 'failed', 'expired'
            );
        END IF;
    END $$""",
    # Phase 15 / Phase D (migration 0055_job_train_name): train_name column
    # na jobs + partial index. Safety-net: /api/jobs create/update oraz
    # /champion-profile/historical-matches czytają/piszą tę kolumnę; brak
    # kolumny => UndefinedColumnError przy INSERT/UPDATE jobs.
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS train_name VARCHAR(128) NULL",
    "CREATE INDEX IF NOT EXISTS ix_jobs_train_name_partial "
    "ON jobs (client_id, train_name) WHERE train_name IS NOT NULL",
    # Poszerzenie alembic_version.version_num — nowsze nazwy rewizji (np.
    # 0054_marketplace_notification_type, 34 znaki) nie mieściły się w
    # pierwotnym VARCHAR(32) i blokowały upgrade na prod. VARCHAR(128) jest
    # bezpiecznym górnym limitem dla nazewnictwa w tym repo.
    "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)",
    # FX rates updated_at (migration 0027_fx_rates): TimestampMixin daje
    # created_at + updated_at, ale prod ma tylko created_at — defensive ALTER
    # w 0027 nigdy nie odpalił (multi-head drift między 0091 i 0097 zatrzymał
    # alembic_version). Bez kolumny każda kwerenda na fx_rates wywala
    # `column fx_rates.updated_at does not exist` (postgres ERROR, blokuje
    # /api/contracts forecast + NBP refresh cron).
    "ALTER TABLE fx_rates ADD COLUMN IF NOT EXISTS updated_at "
    "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()",
    # Phase 15 / Phase C (migration 0057_champion_suggestion_rating):
    # kolumny rating + rating_comment na champion_profile_suggestions.
    # Safety-net: POST /champion-suggestions/{id}/rate pisze te kolumny —
    # brak => UndefinedColumnError.
    "ALTER TABLE champion_profile_suggestions "
    "ADD COLUMN IF NOT EXISTS rating SMALLINT NULL",
    "ALTER TABLE champion_profile_suggestions "
    "ADD COLUMN IF NOT EXISTS rating_comment TEXT NULL",
    "ALTER TABLE champion_profile_suggestions "
    "DROP CONSTRAINT IF EXISTS chk_champion_suggestion_rating_range",
    "ALTER TABLE champion_profile_suggestions "
    "ADD CONSTRAINT chk_champion_suggestion_rating_range "
    "CHECK (rating IS NULL OR rating IN (-1, 0, 1))",
    # Phase 16 (migration 0058_editable_draft_contract): edytowalna treść
    # draftu umowy + JDG/firma na kandydatach i klientach. Safety-net chroni
    # prod przed crash-loopem `GET /api/contracts → UndefinedColumnError`
    # gdyby alembic upgrade nie wszedł (np. multi-head dev gałęzi 0036).
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS draft_content_html TEXT",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS draft_template_id INTEGER",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS draft_updated_at TIMESTAMPTZ",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS draft_updated_by INTEGER",
    "ALTER TABLE contracts DROP CONSTRAINT IF EXISTS fk_contracts_draft_template_id",
    "ALTER TABLE contracts ADD CONSTRAINT fk_contracts_draft_template_id "
    "FOREIGN KEY (draft_template_id) REFERENCES contract_templates(id) "
    "ON DELETE SET NULL",
    "ALTER TABLE contracts DROP CONSTRAINT IF EXISTS fk_contracts_draft_updated_by",
    "ALTER TABLE contracts ADD CONSTRAINT fk_contracts_draft_updated_by "
    "FOREIGN KEY (draft_updated_by) REFERENCES users(id) "
    "ON DELETE SET NULL",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS legal_name VARCHAR(255)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS nip VARCHAR(32)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS regon VARCHAR(32)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS business_address TEXT",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS business_form VARCHAR(64)",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS legal_name VARCHAR(255)",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS nip VARCHAR(32)",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS regon VARCHAR(32)",
    # Auto-assign TAC + Delivery Lead do projektów (migracje 0059/0060).
    # Bez tych kolumn prod backend crashuje na `SELECT jobs.tac_id` (ORM
    # deklaruje kolumnę w `app.models.job.Job` od commit c57c944).
    # Safety-net chroni prod gdyby alembic upgrade nie wszedł (multi-head).
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tac_id INTEGER NULL",
    "ALTER TABLE jobs DROP CONSTRAINT IF EXISTS fk_jobs_tac_id",
    "ALTER TABLE jobs ADD CONSTRAINT fk_jobs_tac_id "
    "FOREIGN KEY (tac_id) REFERENCES users(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_jobs_tac_id ON jobs (tac_id)",
    """
    CREATE TABLE IF NOT EXISTS client_tac_assignments (
        id SERIAL PRIMARY KEY,
        tac_user_id INTEGER NOT NULL
            REFERENCES users(id) ON DELETE CASCADE,
        client_id INTEGER NOT NULL
            REFERENCES clients(id) ON DELETE CASCADE,
        is_primary BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_client_tac UNIQUE (tac_user_id, client_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_client_tac_assignments_client_id "
    "ON client_tac_assignments (client_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_tac_assignments_tac_user_id "
    "ON client_tac_assignments (tac_user_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_primary_tac "
    "ON client_tac_assignments (client_id) WHERE is_primary = TRUE",
    # Targ kandydatów (migracja 0054_marketplace_notification_type): nowy typ
    # powiadomień dla dopasowań z puli marketplace. Bez tego insert
    # Notification(notification_type='marketplace_match') crashuje z
    # InvalidTextRepresentationError podczas scan_job_for_marketplace_matches.
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'marketplace_match'",
    # Szybkie przepinanie: notyfikacja "podobny request — gotowi kandydaci"
    # emitowana po POST /jobs (services/similar_job_notify.py). Bez tej
    # wartości insert Notification(notification_type='similar_job_candidates')
    # crashuje z InvalidTextRepresentationError w background tasku.
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'similar_job_candidates'",
    # Job Chat (migracja 0063_job_chat): per-rekrutacja team chat. Prod
    # alembic upgrade pada na 0029 duplicate revision id (pre-existing
    # multi-head bug), wpada w fallback create_all — tabele powstają, ALE
    # ALTER TYPE i CREATE TRIGGER nie. POST /api/jobs/{id}/chat/messages
    # crashował z 500 bo notificationtype/useractiontype enums nie miały
    # nowych wartości. Bez tego safety-netu Job Chat nie działa w prod.
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_chat_message'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_chat_mention'",
    "ALTER TYPE useractiontype ADD VALUE IF NOT EXISTS 'chat_message_added'",
    # Phase 14 dedicated enums for interview_feedback table
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'feedbacksource') THEN
            CREATE TYPE feedbacksource AS ENUM ('candidate_side', 'client_side');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'interestlevel') THEN
            CREATE TYPE interestlevel AS ENUM ('hot', 'warm', 'cold', 'dead');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'nextsteppreference') THEN
            CREATE TYPE nextsteppreference AS ENUM ('ready_for_next', 'need_info', 'pass');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'interviewdecision') THEN
            CREATE TYPE interviewdecision AS ENUM ('advance', 'reject', 'on_hold');
        END IF;
    END $$""",
    # availabilitystatus (migration wyroznienia_availability) — CREATE TYPE
    # must be gated with DO $$ because PG lacks CREATE TYPE IF NOT EXISTS.
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'availabilitystatus') THEN
            CREATE TYPE availabilitystatus AS ENUM (
                'actively_looking', 'open_to_offers', 'not_looking', 'unknown'
            );
        END IF;
    END $$""",
    # Kontrakty expansion (migration 0037) enum types
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'contractterminationreason') THEN
            CREATE TYPE contractterminationreason AS ENUM (
                'poached_by_client', 'project_ended', 'client_budget_cut',
                'performance_issue', 'consultant_resigned', 'better_offer',
                'personal_reasons', 'contract_breach', 'mutual_agreement', 'other'
            );
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'equipmentitemtype') THEN
            CREATE TYPE equipmentitemtype AS ENUM (
                'laptop', 'phone', 'monitor', 'headset', 'docking_station',
                'security_token', 'keycard', 'sim_card', 'other'
            );
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'equipmentowner') THEN
            CREATE TYPE equipmentowner AS ENUM ('ours', 'client');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'equipmentreturnstatus') THEN
            CREATE TYPE equipmentreturnstatus AS ENUM (
                'pending', 'returned', 'lost', 'written_off'
            );
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'seniorityleveltype') THEN
            CREATE TYPE seniorityleveltype AS ENUM (
                'junior', 'mid', 'senior', 'expert', 'principal'
            );
        END IF;
    END $$""",
    # AI CC matching (migration 0041_ai_cc_matching): enum for candidate→CC source
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'candidatecccategorysource') THEN
            CREATE TYPE candidatecccategorysource AS ENUM (
                'ai_auto', 'ai_suggested', 'manual'
            );
        END IF;
    END $$""",
    # Client Profile tab (migration 0048_job_close_reason): structured close
    # reason for "Przegrane rekrutacje". Safety-net bo prod może wyjść na live
    # przed ukończeniem upgrade'u alembica, a POST /jobs/{id}/close crashuje
    # bez tego enum + kolumny.
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'jobclosereason') THEN
            CREATE TYPE jobclosereason AS ENUM (
                'budget', 'internal_hire', 'competitor', 'paused',
                'filled_by_us', 'client_ghosted', 'other'
            );
        END IF;
    END $$""",
    # LinkedIn employment tracking (migracja 0049_linkedin_employment).
    # Candidate model odwołuje się do 7 nowych kolumn + enum — bez nich KAŻDY
    # SELECT kandydata wywala UndefinedColumnError (łącznie z /api/candidates
    # i /api/marketplace/candidates przez JOIN).
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'linkedinsyncstatus') THEN
            CREATE TYPE linkedinsyncstatus AS ENUM (
                'ok', 'not_found', 'error', 'rate_limited', 'disabled'
            );
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'linkedinchangekind') THEN
            CREATE TYPE linkedinchangekind AS ENUM (
                'first_snapshot', 'no_change',
                'new_company', 'new_title_same_company'
            );
        END IF;
    END $$""",
    # Pending verification flow (migracja 0056_pending_verification).
    # Dodaje stage 'verified' + VerificationStatus enum + 9 kolumn audit na
    # candidate_stages. Bez tego ORM CandidateStage wywala UndefinedColumnError
    # przy każdym select'cie (GET /pipeline/kanban/{id} — crash-loop backendu).
    "ALTER TYPE pipelinestage ADD VALUE IF NOT EXISTS 'verified'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'pending_verification'",
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'verificationstatus') THEN
            CREATE TYPE verificationstatus AS ENUM ('active', 'pending', 'rejected');
        END IF;
    END $$""",
    """ALTER TABLE candidate_stages
        ADD COLUMN IF NOT EXISTS verification_status verificationstatus
            NOT NULL DEFAULT 'active'""",
    "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS expected_rate_value NUMERIC(10, 2) NULL",
    "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS expected_rate_unit rateunit NULL",
    "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS expected_rate_currency VARCHAR(3) NULL",
    "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS budget_max_at_move INTEGER NULL",
    """ALTER TABLE candidate_stages
        ADD COLUMN IF NOT EXISTS approved_by INTEGER NULL REFERENCES users(id)""",
    "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE NULL",
    """ALTER TABLE candidate_stages
        ADD COLUMN IF NOT EXISTS rejected_by INTEGER NULL REFERENCES users(id)""",
    "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP WITH TIME ZONE NULL",
    "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS rejection_note TEXT NULL",
    """CREATE INDEX IF NOT EXISTS ix_candidate_stages_pending_verification
        ON candidate_stages (job_id, verification_status)
        WHERE verification_status = 'pending'""",
    # Seed 'verified' do wszystkich istniejących pipeline_templates —
    # bez tego kanban template-driven nie ma kolumny "Zweryfikowany".
    # 2-step shift trick bo uq_stage_order_in_template jest UNIQUE (nie DEFERRABLE).
    """DO $$
    DECLARE
        tpl_id INTEGER;
    BEGIN
        FOR tpl_id IN SELECT id FROM pipeline_templates LOOP
            IF NOT EXISTS (
                SELECT 1 FROM pipeline_stage_defs
                WHERE template_id = tpl_id AND legacy_enum_value = 'verified'
            ) THEN
                UPDATE pipeline_stage_defs
                   SET "order" = "order" + 1000
                 WHERE template_id = tpl_id AND "order" >= 3;
                INSERT INTO pipeline_stage_defs (
                    template_id, name, "order", category,
                    is_terminal, terminal_type, legacy_enum_value
                ) VALUES (
                    tpl_id, 'Zweryfikowany', 3, 'internal',
                    FALSE, NULL, 'verified'
                );
                UPDATE pipeline_stage_defs
                   SET "order" = "order" - 999
                 WHERE template_id = tpl_id AND "order" >= 1003;
            END IF;
        END LOOP;
    END $$""",
    # Saved-search alerts (migration 0129_saved_search_alerts). Scanner task
    # inserts Notification(notification_type='saved_search_match') — bez tej
    # wartości w DB enum insert crashuje (InvalidTextRepresentationError),
    # ten sam failure mode co kpi_coach incident.
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'saved_search_match'",
    # Nowy typ dokumentu „Zamówienie" na kontrakcie (migracja
    # 0160_contract_document_type_order). Bez tej wartości upload dokumentu
    # doc_type='order' wywala się InvalidTextRepresentationError (DB enum nie
    # zna wartości), gdyby alembic upgrade nie wszedł na prod (multi-head).
    "ALTER TYPE contractdocumenttype ADD VALUE IF NOT EXISTS 'order'",
]

_COLUMN_STATEMENTS = [
    # saved_searches (migration 0129_saved_search_alerts) — ORM SavedSearch
    # selectuje te kolumny przy każdym GET /api/saved-searches; bez nich
    # UndefinedColumnError gdyby app wystartował przed alembic upgrade.
    # match_index_outbox (migration 0171) — durable reindex queue drained by the
    # flag-gated index_outbox worker. Table must exist before the worker/enqueue
    # paths run under prod's multi-head alembic drift.
    """CREATE TABLE IF NOT EXISTS match_index_outbox (
        id BIGSERIAL PRIMARY KEY,
        entity_type VARCHAR(16) NOT NULL,
        entity_id INTEGER NOT NULL,
        entity_revision BIGINT NOT NULL,
        desired_hash VARCHAR(64) NOT NULL,
        operation VARCHAR(16) NOT NULL DEFAULT 'upsert',
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error VARCHAR(500),
        indexed_hash VARCHAR(64),
        indexed_revision BIGINT,
        heartbeat_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_match_index_outbox_pending ON match_index_outbox (status, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_match_index_outbox_entity ON match_index_outbox (entity_type, entity_id)",
    "CREATE INDEX IF NOT EXISTS ix_match_index_outbox_status ON match_index_outbox (status)",
    # candidate_job_match_scores.scoring_algorithm_version (migration 0170) —
    # versioned score cache. A row whose version != the running
    # scoring_service.SCORING_ALGORITHM_VERSION is a cache miss, so flipping
    # AI_SCORING_CONTRACT_V2 auto-invalidates. Backfill to 'score-v1-legacy'
    # (== the flag-off version) so nothing recomputes on deploy. Without the
    # column the recommendations read 500s (UndefinedColumn) under multi-head.
    "ALTER TABLE candidate_job_match_scores ADD COLUMN IF NOT EXISTS scoring_algorithm_version VARCHAR(32) NOT NULL DEFAULT 'score-v1-legacy'",
    "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS notify_new_matches BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS last_seen_candidate_id INTEGER",
    "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS unseen_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS last_viewed_at TIMESTAMPTZ",
    # saved_searches V2 (migration 0131_saved_search_match_log) — watermark
    # po updated_at + tabela dedup + indeks. ORM SavedSearch selectuje
    # last_scanned_at; scanner SELECT-uje saved_search_alert_log.
    "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS last_scanned_at TIMESTAMPTZ",
    """CREATE TABLE IF NOT EXISTS saved_search_alert_log (
        id SERIAL PRIMARY KEY,
        saved_search_id INTEGER NOT NULL REFERENCES saved_searches(id) ON DELETE CASCADE,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        notified_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_saved_search_alert_pair UNIQUE (saved_search_id, candidate_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_saved_search_alert_log_saved_search_id ON saved_search_alert_log (saved_search_id)",
    "CREATE INDEX IF NOT EXISTS ix_saved_search_alert_log_candidate_id ON saved_search_alert_log (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidates_updated_at ON candidates (updated_at)",
    # match telemetry (migration 0169_match_telemetry) — append-only impression
    # + outcome logs. No FKs (analytics survive candidate hard-delete; purged by
    # retention/DSAR). Writer is flag-gated (AI_MATCH_TELEMETRY_ENABLED) so these
    # stay empty until switched on, but the tables must exist first or the
    # writer's INSERT 500s under prod's chronic alembic multi-head drift.
    """CREATE TABLE IF NOT EXISTS match_impressions (
        id BIGSERIAL PRIMARY KEY,
        run_id VARCHAR(64) NOT NULL,
        surface VARCHAR(64) NOT NULL,
        job_id INTEGER,
        request_id INTEGER,
        user_ref VARCHAR(64),
        client_ref VARCHAR(64),
        candidate_id INTEGER NOT NULL,
        rank INTEGER NOT NULL,
        eligible BOOLEAN NOT NULL DEFAULT true,
        retrieval_sources JSONB,
        retrieval_score DOUBLE PRECISION,
        rerank_score DOUBLE PRECISION,
        fit_score DOUBLE PRECISION,
        fit_breakdown JSONB,
        ranker_version VARCHAR(64) NOT NULL DEFAULT 'scoring-v1-legacy',
        index_version VARCHAR(64) NOT NULL DEFAULT 'index-legacy-v1',
        text_schema_version VARCHAR(64) NOT NULL DEFAULT 'text-v1-legacy',
        taxonomy_version VARCHAR(64) NOT NULL DEFAULT 'taxonomy-legacy-v1',
        degraded BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_match_impression_run_cand UNIQUE (run_id, candidate_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_match_impressions_run_id ON match_impressions (run_id)",
    "CREATE INDEX IF NOT EXISTS ix_match_impressions_job_id ON match_impressions (job_id)",
    "CREATE INDEX IF NOT EXISTS ix_match_impressions_candidate_id ON match_impressions (candidate_id)",
    """CREATE TABLE IF NOT EXISTS match_outcomes (
        id BIGSERIAL PRIMARY KEY,
        event_id VARCHAR(128) NOT NULL,
        run_id VARCHAR(64),
        candidate_id INTEGER,
        job_id INTEGER,
        event_type VARCHAR(32) NOT NULL,
        reason_code VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_match_outcome_event_id UNIQUE (event_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_match_outcomes_run_id ON match_outcomes (run_id)",
    "CREATE INDEX IF NOT EXISTS ix_match_outcomes_candidate_id ON match_outcomes (candidate_id)",
    # candidates.search_doc_unaccented (migration 0159) — diacritic-folded mirror
    # of search_doc so `?q=lukasz gradzki` matches „Łukasz Grądzki".
    # advanced_candidate_search references it in the search UNION; without the
    # column the candidates list 500s (UndefinedColumn) on prod's chronic alembic
    # multi-head drift. GENERATED so it self-maintains. Fold map + field list MUST
    # match migration 0159 / advanced_candidate_search._POLISH_FOLD_SRC/_DST.
    # Non-CONCURRENT here (startup, one-shot via IF NOT EXISTS); index failure is
    # non-fatal (per-statement try/except) — the column is what prevents the 500.
    """ALTER TABLE candidates ADD COLUMN IF NOT EXISTS search_doc_unaccented text
        GENERATED ALWAYS AS (lower(translate(
            coalesce(name, '') || ' ' ||
            coalesce(lastname, '') || ' ' ||
            coalesce(email, '') || ' ' ||
            coalesce(phone, '') || ' ' ||
            coalesce(location, '') || ' ' ||
            coalesce(city, '') || ' ' ||
            coalesce(linkedin_current_title, '') || ' ' ||
            coalesce(linkedin_current_company, '') || ' ' ||
            coalesce(ai_summary, '') || ' ' ||
            coalesce(competence_category, '') || ' ' ||
            coalesce(engagement_notes, '') || ' ' ||
            coalesce(experience::text, '') || ' ' ||
            coalesce(skills::text, '') || ' ' ||
            coalesce(tags::text, '') || ' ' ||
            coalesce(education::text, '') || ' ' ||
            coalesce(languages::text, ''),
            'ąćęłńóśźżĄĆĘŁŃÓŚŹŻ', 'acelnoszzACELNOSZZ'))) STORED""",
    "CREATE INDEX IF NOT EXISTS ix_candidates_search_doc_unaccent_trgm ON candidates USING GIN (search_doc_unaccented gin_trgm_ops)",
    # users (migration 0035_onboarding_and_job_sourcing)
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_completed BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_completed_at TIMESTAMPTZ",
    # jobs (migration 0035_onboarding_and_job_sourcing + 0029_notifications_triggers)
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS needs_sourcing BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS delivery_lead_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS competence_category_id INTEGER",
    # candidates (migration 0030_candidate_created_by + 0033_cc_entities +
    # wyroznienia_availability)
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS competence_category_id INTEGER",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS availability_status availabilitystatus NOT NULL DEFAULT 'unknown'",
    # notifications (migration 0029_notifications_triggers)
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS related_entity_type VARCHAR(50)",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS related_entity_id INTEGER",
    # contracts (migration 0037_contracts_expansion)
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS termination_reason contractterminationreason",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS termination_lessons TEXT",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS terminated_at DATE",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS target_rate_min INTEGER",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS target_rate_max INTEGER",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS client_order_end_date DATE",
    # candidates engagement flags (migration 0037_contracts_expansion)
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS is_ambassador BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS wants_to_verify_candidates BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS open_to_side_projects BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS open_to_sales_support BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS open_to_expert_consult BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS engagement_notes TEXT",
    # candidates open_to_* timestamps (migration 0061_open_to_timestamps)
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS open_to_side_projects_updated_at TIMESTAMPTZ",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS open_to_sales_support_updated_at TIMESTAMPTZ",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS open_to_expert_consult_updated_at TIMESTAMPTZ",
    # engagement_declaration_tokens (migration 0062_engagement_declaration_tokens)
    """CREATE TABLE IF NOT EXISTS engagement_declaration_tokens (
        id SERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        token VARCHAR(48) UNIQUE NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_engagement_decl_tokens_token ON engagement_declaration_tokens (token)",
    "CREATE INDEX IF NOT EXISTS ix_engagement_decl_tokens_candidate ON engagement_declaration_tokens (candidate_id)",
    # candidates structured location (migration 0037_contracts_expansion)
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS city VARCHAR(120)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS country VARCHAR(2)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS region VARCHAR(120)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS hub_city VARCHAR(120)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS latitude NUMERIC(9,6)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS longitude NUMERIC(9,6)",
    # notes + calls contract_id FK (migration 0037_contracts_expansion)
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS contract_id INTEGER REFERENCES contracts(id) ON DELETE SET NULL",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS contract_id INTEGER REFERENCES contracts(id) ON DELETE SET NULL",
    # talent_pools centroid cache (pre-existing model fields — no dedicated migration)
    "ALTER TABLE talent_pools ADD COLUMN IF NOT EXISTS centroid_vector_id VARCHAR(100)",
    "ALTER TABLE talent_pools ADD COLUMN IF NOT EXISTS centroid_updated_at TIMESTAMPTZ",
    # talent_pool_memberships source tracking (migration 0040_talent_pool_source_event)
    "ALTER TABLE talent_pool_memberships ADD COLUMN IF NOT EXISTS source_event VARCHAR(50)",
    "ALTER TABLE talent_pool_memberships ADD COLUMN IF NOT EXISTS source_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_tpm_source_job_id ON talent_pool_memberships (source_job_id)",
    # AI CC matching (migration 0041_ai_cc_matching): columns on existing tables
    "ALTER TABLE talent_pools ADD COLUMN IF NOT EXISTS competence_category_id INTEGER REFERENCES competence_categories(id) ON DELETE SET NULL",
    "ALTER TABLE job_collaborators ADD COLUMN IF NOT EXISTS removed_from_auto_cc BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE job_collaborators ADD COLUMN IF NOT EXISTS removed_at TIMESTAMPTZ",
    # KPI coach (bundled WIP, migration 0043_kpi_coach_nudger): bez tej kolumny
    # users.kpi_coach_enabled crashuje login query (ORM leci na nią).
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS kpi_coach_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    # Sourcer priority per CC (introduced by team_structure model for Head of
    # Recruitment matrix). Legacy deployments may be missing it.
    "ALTER TABLE user_competence_categories ADD COLUMN IF NOT EXISTS priority SMALLINT",
    "ALTER TABLE user_competence_categories DROP CONSTRAINT IF EXISTS ck_user_cc_priority",
    "ALTER TABLE user_competence_categories ADD CONSTRAINT ck_user_cc_priority CHECK (priority IS NULL OR priority IN (1, 2))",
    # Phase 14 (migration 0043_interview_feedback) needs_attention flag
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS needs_attention BOOLEAN NOT NULL DEFAULT false",
    "CREATE INDEX IF NOT EXISTS ix_calendar_events_needs_attention ON calendar_events (needs_attention) WHERE needs_attention = true",
    # Phase 14 interview_feedback table (migration 0043_interview_feedback).
    # Prod DEBUG=false → Base.metadata.create_all nie leci, alembic multi-head
    # często pada w dev → tabela musi być stworzona explicite idempotent tutaj.
    """CREATE TABLE IF NOT EXISTS interview_feedback (
        id SERIAL PRIMARY KEY,
        calendar_event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
        author_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        feedback_source feedbacksource NOT NULL,
        overall_impression SMALLINT CHECK (overall_impression IS NULL OR overall_impression BETWEEN 1 AND 5),
        interest_level interestlevel,
        candidate_questions TEXT,
        concerns TEXT,
        next_step_preference nextsteppreference,
        technical_fit SMALLINT CHECK (technical_fit IS NULL OR technical_fit BETWEEN 1 AND 5),
        soft_fit SMALLINT CHECK (soft_fit IS NULL OR soft_fit BETWEEN 1 AND 5),
        overall_fit SMALLINT CHECK (overall_fit IS NULL OR overall_fit BETWEEN 1 AND 5),
        decision interviewdecision,
        client_questions TEXT,
        feedback_summary TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_interview_feedback_event_source UNIQUE (calendar_event_id, feedback_source)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_interview_feedback_calendar_event_id ON interview_feedback (calendar_event_id)",
    "CREATE INDEX IF NOT EXISTS ix_interview_feedback_candidate_id ON interview_feedback (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_interview_feedback_job_id ON interview_feedback (job_id)",
    # Phase M365.1 drift: model ma kolumny od migracji 0036_microsoft365 ale
    # multi-head w dev skasowało ich auto-tworzenie. Bez tego SQLAlchemy fetche
    # eventów leci z UndefinedColumnError.
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS m365_series_master_id VARCHAR(255)",
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS m365_change_key VARCHAR(100)",
    "CREATE INDEX IF NOT EXISTS ix_calendar_events_m365_series_master_id ON calendar_events (m365_series_master_id)",
    # Client Profile tab + hit-ratio (migrations 0047_job_closed_at +
    # 0048_job_close_reason). Alembic was bailing on multi-head in prod, so
    # these never landed — safety-net avoids UndefinedColumnError on the
    # jobs SELECT and backend crash-loop.
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS ix_jobs_closed_at ON jobs(closed_at)",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS close_reason jobclosereason",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS close_notes TEXT",
    # LinkedIn tracking (migracja 0049_linkedin_employment): 7 kolumn na
    # candidates + tabela candidate_linkedin_snapshots. Bez nich Candidate
    # ORM SELECT pada — blokuje /api/candidates i /api/marketplace/candidates.
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS linkedin_current_company VARCHAR(255)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS linkedin_current_title VARCHAR(255)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS linkedin_current_started_at DATE",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS linkedin_employment_changed_at TIMESTAMPTZ",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS linkedin_synced_at TIMESTAMPTZ",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS linkedin_sync_status linkedinsyncstatus NOT NULL DEFAULT 'disabled'",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS linkedin_sync_error TEXT",
    "CREATE INDEX IF NOT EXISTS ix_candidates_linkedin_current_company ON candidates (linkedin_current_company)",
    "CREATE INDEX IF NOT EXISTS ix_candidates_linkedin_employment_changed_at ON candidates (linkedin_employment_changed_at)",
    "CREATE INDEX IF NOT EXISTS ix_candidates_linkedin_synced_at ON candidates (linkedin_synced_at)",
    """CREATE TABLE IF NOT EXISTS candidate_linkedin_snapshots (
        id SERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        fetched_at TIMESTAMPTZ NOT NULL,
        profile_json JSONB DEFAULT '{}'::jsonb,
        current_company VARCHAR(255),
        current_title VARCHAR(255),
        current_started_at DATE,
        changed_from_previous BOOLEAN NOT NULL DEFAULT false,
        change_kind linkedinchangekind NOT NULL DEFAULT 'first_snapshot',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_candidate_linkedin_snapshots_candidate_id ON candidate_linkedin_snapshots (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_linkedin_snapshots_fetched_at ON candidate_linkedin_snapshots (fetched_at)",
    "CREATE INDEX IF NOT EXISTS ix_linkedin_snap_candidate_fetched ON candidate_linkedin_snapshots (candidate_id, fetched_at)",
    # Targ kandydatów (migracja 0052_marketplace_pool_flag): is_marketplace
    # flag na talent_pools + marketplace_until na membership. ORM leci na
    # te kolumny z każdego listowania pul (łącznie z /api/talent-pools),
    # więc brak w schemacie = crash-loop wszystkich endpointów TalentPool.
    "ALTER TABLE talent_pools ADD COLUMN IF NOT EXISTS is_marketplace BOOLEAN NOT NULL DEFAULT FALSE",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_talent_pools_marketplace_singleton ON talent_pools ((1)) WHERE is_marketplace = TRUE",
    "CREATE INDEX IF NOT EXISTS ix_talent_pools_is_marketplace ON talent_pools (is_marketplace)",
    "ALTER TABLE talent_pool_memberships ADD COLUMN IF NOT EXISTS marketplace_until DATE",
    "CREATE INDEX IF NOT EXISTS ix_tpm_marketplace_until ON talent_pool_memberships (marketplace_until) WHERE marketplace_until IS NOT NULL",
    # Targ kandydatów (migracja 0053_marketplace_alert_log): append-only log
    # dedupujący powiadomienia. Bez tabeli scan_job_for_marketplace_matches
    # wywala się na ON CONFLICT INSERT → 500 na PATCH /api/jobs/{id}.
    """CREATE TABLE IF NOT EXISTS marketplace_alert_log (
        id SERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        score NUMERIC(5,2) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        notified_candidate_owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        notified_job_owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        CONSTRAINT uq_marketplace_alert_pair UNIQUE (candidate_id, job_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_mal_candidate ON marketplace_alert_log (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_mal_job ON marketplace_alert_log (job_id)",
    "CREATE INDEX IF NOT EXISTS ix_mal_created ON marketplace_alert_log (created_at DESC)",
    # Job Chat (migracja 0063_job_chat): trzy tabele + FTS trigger + GIN
    # index. Tabele tworzone przez metadata.create_all w drugim safety-net,
    # ale FTS trigger i GIN index — nie. Idempotentne.
    """CREATE TABLE IF NOT EXISTS job_chat_messages (
        id SERIAL PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        author_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        content TEXT NOT NULL,
        reply_to_message_id INTEGER NULL
            REFERENCES job_chat_messages(id) ON DELETE SET NULL,
        is_edited BOOLEAN NOT NULL DEFAULT FALSE,
        edited_at TIMESTAMP WITH TIME ZONE NULL,
        is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        deleted_at TIMESTAMP WITH TIME ZONE NULL,
        pinned BOOLEAN NOT NULL DEFAULT FALSE,
        pinned_at TIMESTAMP WITH TIME ZONE NULL,
        pinned_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        external_platform VARCHAR(32) NULL,
        external_message_id VARCHAR(255) NULL,
        search_vector tsvector NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_job_chat_messages_job_id ON job_chat_messages (job_id)",
    "CREATE INDEX IF NOT EXISTS ix_job_chat_messages_author_id ON job_chat_messages (author_id)",
    "CREATE INDEX IF NOT EXISTS ix_job_chat_messages_is_deleted ON job_chat_messages (is_deleted)",
    "CREATE INDEX IF NOT EXISTS ix_job_chat_messages_job_created ON job_chat_messages (job_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_job_chat_messages_search ON job_chat_messages USING gin (search_vector)",
    "CREATE INDEX IF NOT EXISTS ix_job_chat_messages_pinned ON job_chat_messages (job_id, pinned_at) WHERE pinned = TRUE AND is_deleted = FALSE",
    """CREATE OR REPLACE FUNCTION job_chat_messages_search_trigger()
       RETURNS trigger AS $$
       BEGIN
           NEW.search_vector := to_tsvector('simple', COALESCE(NEW.content, ''));
           RETURN NEW;
       END
       $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS job_chat_messages_search_update ON job_chat_messages",
    """CREATE TRIGGER job_chat_messages_search_update
       BEFORE INSERT OR UPDATE OF content
       ON job_chat_messages
       FOR EACH ROW EXECUTE FUNCTION job_chat_messages_search_trigger()""",
    """CREATE OR REPLACE FUNCTION job_chat_messages_touch_updated_at()
       RETURNS trigger AS $$
       BEGIN
           NEW.updated_at := NOW();
           RETURN NEW;
       END
       $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS job_chat_messages_touch_updated_at ON job_chat_messages",
    """CREATE TRIGGER job_chat_messages_touch_updated_at
       BEFORE UPDATE ON job_chat_messages
       FOR EACH ROW EXECUTE FUNCTION job_chat_messages_touch_updated_at()""",
    """CREATE TABLE IF NOT EXISTS job_chat_mentions (
        id SERIAL PRIMARY KEY,
        message_id INTEGER NOT NULL
            REFERENCES job_chat_messages(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_job_chat_mentions_msg_user UNIQUE (message_id, user_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_job_chat_mentions_message_id ON job_chat_mentions (message_id)",
    "CREATE INDEX IF NOT EXISTS ix_job_chat_mentions_user ON job_chat_mentions (user_id)",
    """CREATE TABLE IF NOT EXISTS job_chat_read_state (
        id SERIAL PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        last_read_message_id INTEGER NULL
            REFERENCES job_chat_messages(id) ON DELETE SET NULL,
        last_read_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_job_chat_read_state_job_user UNIQUE (job_id, user_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_job_chat_read_state_job_id ON job_chat_read_state (job_id)",
    "CREATE INDEX IF NOT EXISTS ix_job_chat_read_state_user_id ON job_chat_read_state (user_id)",
    # Chat Phase 2 (migracja 0065): per-candidate chat (3 tabele) + reactions
    # (2 tabele) + email-fallback kolumny. Idempotent dla prod gdy alembic
    # upgrade pada na multi-head i wpada w fallback create_all.
    """CREATE TABLE IF NOT EXISTS candidate_chat_messages (
        id SERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        author_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        content TEXT NOT NULL,
        reply_to_message_id INTEGER NULL
            REFERENCES candidate_chat_messages(id) ON DELETE SET NULL,
        is_edited BOOLEAN NOT NULL DEFAULT FALSE,
        edited_at TIMESTAMP WITH TIME ZONE NULL,
        is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        deleted_at TIMESTAMP WITH TIME ZONE NULL,
        pinned BOOLEAN NOT NULL DEFAULT FALSE,
        pinned_at TIMESTAMP WITH TIME ZONE NULL,
        pinned_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        external_platform VARCHAR(32) NULL,
        external_message_id VARCHAR(255) NULL,
        search_vector tsvector NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_candidate_chat_messages_candidate_id ON candidate_chat_messages (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_chat_messages_author_id ON candidate_chat_messages (author_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_chat_messages_is_deleted ON candidate_chat_messages (is_deleted)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_chat_messages_candidate_created ON candidate_chat_messages (candidate_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_chat_messages_search ON candidate_chat_messages USING gin (search_vector)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_chat_messages_pinned ON candidate_chat_messages (candidate_id, pinned_at) WHERE pinned = TRUE AND is_deleted = FALSE",
    """CREATE OR REPLACE FUNCTION candidate_chat_messages_search_trigger()
       RETURNS trigger AS $$
       BEGIN
           NEW.search_vector := to_tsvector('simple', COALESCE(NEW.content, ''));
           RETURN NEW;
       END
       $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS candidate_chat_messages_search_update ON candidate_chat_messages",
    """CREATE TRIGGER candidate_chat_messages_search_update
       BEFORE INSERT OR UPDATE OF content
       ON candidate_chat_messages
       FOR EACH ROW EXECUTE FUNCTION candidate_chat_messages_search_trigger()""",
    """CREATE OR REPLACE FUNCTION candidate_chat_messages_touch_updated_at()
       RETURNS trigger AS $$
       BEGIN
           NEW.updated_at := NOW();
           RETURN NEW;
       END
       $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS candidate_chat_messages_touch_updated_at ON candidate_chat_messages",
    """CREATE TRIGGER candidate_chat_messages_touch_updated_at
       BEFORE UPDATE ON candidate_chat_messages
       FOR EACH ROW EXECUTE FUNCTION candidate_chat_messages_touch_updated_at()""",
    """CREATE TABLE IF NOT EXISTS candidate_chat_mentions (
        id SERIAL PRIMARY KEY,
        message_id INTEGER NOT NULL
            REFERENCES candidate_chat_messages(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_candidate_chat_mentions_msg_user UNIQUE (message_id, user_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_candidate_chat_mentions_message_id ON candidate_chat_mentions (message_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_chat_mentions_user ON candidate_chat_mentions (user_id)",
    """CREATE TABLE IF NOT EXISTS candidate_chat_read_state (
        id SERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        last_read_message_id INTEGER NULL
            REFERENCES candidate_chat_messages(id) ON DELETE SET NULL,
        last_read_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_candidate_chat_read_state_candidate_user UNIQUE (candidate_id, user_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_candidate_chat_read_state_candidate_id ON candidate_chat_read_state (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_chat_read_state_user_id ON candidate_chat_read_state (user_id)",
    """CREATE TABLE IF NOT EXISTS job_chat_message_reactions (
        id SERIAL PRIMARY KEY,
        message_id INTEGER NOT NULL REFERENCES job_chat_messages(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        emoji VARCHAR(16) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_job_chat_msg_reaction UNIQUE (message_id, user_id, emoji)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_job_chat_msg_reactions_message ON job_chat_message_reactions (message_id)",
    "CREATE INDEX IF NOT EXISTS ix_job_chat_msg_reactions_user_id ON job_chat_message_reactions (user_id)",
    """CREATE TABLE IF NOT EXISTS candidate_chat_message_reactions (
        id SERIAL PRIMARY KEY,
        message_id INTEGER NOT NULL REFERENCES candidate_chat_messages(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        emoji VARCHAR(16) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_candidate_chat_msg_reaction UNIQUE (message_id, user_id, emoji)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_candidate_chat_msg_reactions_message ON candidate_chat_message_reactions (message_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_chat_msg_reactions_user_id ON candidate_chat_message_reactions (user_id)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NULL",
    "CREATE INDEX IF NOT EXISTS ix_users_last_seen_at ON users (last_seen_at)",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_sent_at TIMESTAMPTZ NULL",
    # Autenti e-signature (migracja 0079_autenti_signatures): document_signatures
    # + document_signature_events. Idempotent CREATE TABLE z all FK + indexes.
    # Bez tego prod safety-net (DEBUG=false → brak Base.metadata.create_all)
    # nie utworzy tabel jeśli alembic upgrade pada na multi-head.
    """CREATE TABLE IF NOT EXISTS document_signatures (
        id SERIAL PRIMARY KEY,
        contract_id INTEGER NOT NULL
            REFERENCES contracts(id) ON DELETE CASCADE,
        contract_document_id INTEGER NOT NULL
            REFERENCES contract_documents(id) ON DELETE RESTRICT,
        autenti_process_id VARCHAR(64) UNIQUE,
        autenti_signature_type VARCHAR(16) NOT NULL DEFAULT 'SES',
        status signaturestatus NOT NULL DEFAULT 'draft',
        sent_at TIMESTAMPTZ NULL,
        completed_at TIMESTAMPTZ NULL,
        expires_at TIMESTAMPTZ NULL,
        sender_user_id INTEGER NOT NULL REFERENCES users(id),
        signer_email VARCHAR(255) NOT NULL,
        signer_first_name VARCHAR(120) NOT NULL,
        signer_last_name VARCHAR(120) NOT NULL,
        signer_phone VARCHAR(30) NULL,
        signed_document_id INTEGER NULL
            REFERENCES contract_documents(id) ON DELETE SET NULL,
        signed_document_url VARCHAR(1000) NULL,
        last_error TEXT NULL,
        retry_count SMALLINT NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_doc_sig_contract ON document_signatures(contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_doc_sig_status ON document_signatures(status)",
    "CREATE INDEX IF NOT EXISTS ix_doc_sig_autenti_process "
    "ON document_signatures(autenti_process_id) WHERE autenti_process_id IS NOT NULL",
    """CREATE TABLE IF NOT EXISTS document_signature_events (
        id SERIAL PRIMARY KEY,
        signature_id INTEGER NOT NULL
            REFERENCES document_signatures(id) ON DELETE CASCADE,
        event_id VARCHAR(128) NOT NULL,
        event_type VARCHAR(64) NOT NULL,
        status VARCHAR(32) NULL,
        payload JSONB NOT NULL,
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        processed_at TIMESTAMPTZ NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_doc_sig_event_unique "
    "ON document_signature_events(event_id)",
    "CREATE INDEX IF NOT EXISTS ix_doc_sig_event_signature "
    "ON document_signature_events(signature_id)",
    # Pule osobiste (migracja 0137_talent_pool_is_personal). /api/talent-pools
    # czyta/pisze talent_pools.is_personal — bez kolumny SELECT/INSERT crashuje
    # (UndefinedColumnError) gdyby alembic upgrade nie wszedł (multi-head dev).
    "ALTER TABLE talent_pools ADD COLUMN IF NOT EXISTS is_personal "
    "BOOLEAN NOT NULL DEFAULT false",
    "CREATE INDEX IF NOT EXISTS ix_talent_pools_is_personal "
    "ON talent_pools (is_personal, created_by)",
    # Progresywne stawki kontraktów (migracje 0151 + 0154). KAŻDE zapytanie o
    # kontrakty (list/expiring/detail) robi selectinload OBU harmonogramów
    # stawek, a selectinload SELECT-uje wszystkie mapowane kolumny modelu.
    #
    # `effective_to` (0154, PR #644) to nowa kolumna na ISTNIEJĄCEJ tabeli
    # `contract_candidate_rates` (0144). Drugi safety-net poniżej
    # (Base.metadata.create_all) tworzy tylko brakujące TABELE — nie dokłada
    # kolumn do istniejących — więc gdy `alembic upgrade heads` pada na
    # multi-head drift ta kolumna nigdy nie powstaje. Efekt na prod 2026-07-06
    # po deployu #644: `SELECT ... effective_to ... FROM contract_candidate_rates`
    # → UndefinedColumnError → request ginie jako non-CORS 503 (patrz
    # app/core/database.py) → CAŁY moduł Kontrakty pokazuje 0 (`/api/candidates`
    # i reszta działają, bo nie dotykają tego schematu). Ten ALTER to właściwa
    # naprawa. Idempotentny.
    "ALTER TABLE contract_candidate_rates ADD COLUMN IF NOT EXISTS effective_to DATE",
    # `contract_client_rates` (0151) to NOWA tabela — create_all zwykle ją
    # utworzy, ale trzymamy DDL tu dla kompletności feature'u i na wypadek gdyby
    # create_all był wyłączony/padł. Bliźniacza do contract_candidate_rates,
    # DDL 1:1 z migracją 0151. Idempotentne (CREATE TABLE/INDEX IF NOT EXISTS).
    """CREATE TABLE IF NOT EXISTS contract_client_rates (
        id              SERIAL PRIMARY KEY,
        contract_id     INTEGER NOT NULL
                            REFERENCES contracts(id) ON DELETE CASCADE,
        rate            NUMERIC(12, 3) NOT NULL,
        effective_from  DATE NOT NULL,
        note            TEXT NULL,
        created_by      INTEGER NULL
                            REFERENCES users(id) ON DELETE SET NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_contract_client_rates_contract_id "
    "ON contract_client_rates (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_contract_client_rates_effective_from "
    "ON contract_client_rates (effective_from)",
    "CREATE INDEX IF NOT EXISTS ix_contract_client_rates_id "
    "ON contract_client_rates (id)",
    # `contract_framework_rates` (0165) to NOWA tabela — harmonogram stawki z
    # umowy ramowej, bliźniacza do contract_candidate_rates (ma `effective_to`).
    # create_all zwykle ją utworzy, ale trzymamy DDL tu na wypadek multi-head
    # driftu (patrz precedens contract_client_rates). Idempotentne.
    """CREATE TABLE IF NOT EXISTS contract_framework_rates (
        id              SERIAL PRIMARY KEY,
        contract_id     INTEGER NOT NULL
                            REFERENCES contracts(id) ON DELETE CASCADE,
        rate            NUMERIC(12, 2) NOT NULL,
        effective_from  DATE NOT NULL,
        effective_to    DATE NULL,
        note            TEXT NULL,
        created_by      INTEGER NULL
                            REFERENCES users(id) ON DELETE SET NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_contract_framework_rates_contract_id "
    "ON contract_framework_rates (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_contract_framework_rates_effective_from "
    "ON contract_framework_rates (effective_from)",
    "CREATE INDEX IF NOT EXISTS ix_contract_framework_rates_id "
    "ON contract_framework_rates (id)",
    # Stawka ramowa + widełki docelowe z groszami (0157): INTEGER → NUMERIC(12,2)
    # na ISTNIEJĄCYCH kolumnach `contracts`. Gdy alembic padnie na multi-head,
    # model już mapuje Decimal — zapis 215,60 w INTEGER kończy się DataError
    # (asyncpg nie rzutuje float→int). Zmiana typu NUMERIC→NUMERIC przy kolejnych
    # startach to no-op semantyczny (tabela mała), więc statement jest bezpiecznie
    # re-runowalny.
    "ALTER TABLE contracts ALTER COLUMN framework_rate TYPE NUMERIC(12, 2) "
    "USING framework_rate::numeric",
    "ALTER TABLE contracts ALTER COLUMN target_rate_min TYPE NUMERIC(12, 2) "
    "USING target_rate_min::numeric",
    "ALTER TABLE contracts ALTER COLUMN target_rate_max TYPE NUMERIC(12, 2) "
    "USING target_rate_max::numeric",
    # Cortex fact store (0158): na prod `Base.metadata.create_all` potrafi
    # cicho paść (failure-tolerant echo), a alembic bywa multi-head — nowe
    # TABELE też wymagają mirrora tutaj (precedens: saved_search_alert_log).
    # Bez nich /api/cortex/* 500-tkuje UndefinedTableError mimo zielonego
    # deployu (incident 2026-07-12).
    """CREATE TABLE IF NOT EXISTS cortex_skill_facts (
        id BIGSERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
        source VARCHAR(20) NOT NULL,
        level VARCHAR(20) NULL,
        years INTEGER NULL,
        confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8,
        evidence TEXT NULL,
        observed_at TIMESTAMPTZ NULL,
        extracted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_cortex_fact_cand_skill_source
            UNIQUE (candidate_id, skill_id, source)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_cortex_skill_facts_candidate_id "
    "ON cortex_skill_facts (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_cortex_skill_facts_skill_id "
    "ON cortex_skill_facts (skill_id)",
    "CREATE INDEX IF NOT EXISTS ix_cortex_facts_skill_source "
    "ON cortex_skill_facts (skill_id, source)",
    """CREATE TABLE IF NOT EXISTS cortex_unmatched_terms (
        id SERIAL PRIMARY KEY,
        term TEXT NOT NULL,
        occurrences INTEGER NOT NULL DEFAULT 1,
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        status VARCHAR(12) NOT NULL DEFAULT 'new',
        CONSTRAINT uq_cortex_unmatched_term UNIQUE (term)
    )""",
    # Cortex Trust Foundation (0160): nowe TABELE/KOLUMNY/INDEXY muszą być
    # mirrorowane tu, inaczej `select(CortexSkillFact/…)` 500-kuje na prod przy
    # multi-head/skipniętym alembicu (ta sama reguła co wyżej, incident 2026-07-12).
    "ALTER TABLE cortex_skill_facts ADD COLUMN IF NOT EXISTS extractor_version VARCHAR(40)",
    "ALTER TABLE cortex_skill_facts ADD COLUMN IF NOT EXISTS run_id BIGINT",
    "ALTER TABLE cortex_skill_facts ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",
    "ALTER TABLE cortex_skill_facts ADD COLUMN IF NOT EXISTS source_ref VARCHAR(120)",
    "ALTER TABLE cortex_unmatched_terms ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ",
    "ALTER TABLE cortex_unmatched_terms ADD COLUMN IF NOT EXISTS curated_by VARCHAR(120)",
    "ALTER TABLE cortex_unmatched_terms ADD COLUMN IF NOT EXISTS curated_at TIMESTAMPTZ",
    """CREATE TABLE IF NOT EXISTS cortex_extraction_runs (
        id BIGSERIAL PRIMARY KEY,
        run_type VARCHAR(10) NOT NULL,
        source VARCHAR(20) NOT NULL DEFAULT 'traffit',
        status VARCHAR(12) NOT NULL DEFAULT 'running',
        triggered_by VARCHAR(120) NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at TIMESTAMPTZ NULL,
        heartbeat_at TIMESTAMPTZ NULL,
        cursor_candidate_id INTEGER NULL,
        stats JSONB NULL,
        last_error TEXT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_cortex_runs_status_started "
    "ON cortex_extraction_runs (status, started_at)",
    "CREATE INDEX IF NOT EXISTS ix_cortex_runs_started "
    "ON cortex_extraction_runs (started_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cortex_single_running "
    "ON cortex_extraction_runs (source) WHERE status = 'running'",
    """CREATE TABLE IF NOT EXISTS cortex_unmatched_observations (
        id BIGSERIAL PRIMARY KEY,
        term TEXT NOT NULL,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        source VARCHAR(20) NOT NULL DEFAULT 'traffit',
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_cortex_unmatched_obs UNIQUE (term, candidate_id, source)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_cortex_unmatched_obs_term "
    "ON cortex_unmatched_observations (term)",
    "CREATE INDEX IF NOT EXISTS ix_cortex_unmatched_obs_candidate "
    "ON cortex_unmatched_observations (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_cortex_unmatched_status "
    "ON cortex_unmatched_terms (status)",
    # Guard po dedupie taksonomii (0160). Jeśli alembic nie zdążył scalić
    # duplikatów, te CREATE UNIQUE INDEX padną i zostaną pominięte (try/except
    # w backfill()) — wrócą przy następnym deployu po udanym alembicu.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_canonical_lower "
    "ON skills (lower(canonical_name))",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_aliases_alias_lower "
    "ON skill_aliases (lower(alias))",
    # ── Traffit bidirectional integration (0173, plan PR2) ──────────────
    # Nowe TABELE lustrzane tutaj mimo create_all (precedens cortex
    # 2026-07-12: create_all potrafi cicho paść), a nowe KOLUMNY na
    # istniejących tabelach create_all nigdy nie dołoży. DDL 1:1 z 0173.
    """CREATE TABLE IF NOT EXISTS traffit_entity_links (
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
    )""",
    'CREATE UNIQUE INDEX IF NOT EXISTS ux_traffit_entity_links_nexus ON traffit_entity_links (entity_type, nexus_entity_id) WHERE nexus_entity_id IS NOT NULL',
    'CREATE UNIQUE INDEX IF NOT EXISTS ux_traffit_entity_links_remote ON traffit_entity_links (entity_type, traffit_entity_id) WHERE traffit_entity_id IS NOT NULL',
    'CREATE INDEX IF NOT EXISTS ix_traffit_entity_links_candidate_status ON traffit_entity_links (candidate_id, status)',
    'CREATE INDEX IF NOT EXISTS ix_traffit_entity_links_last_seen ON traffit_entity_links (entity_type, last_seen_at)',
    """CREATE TABLE IF NOT EXISTS traffit_field_contracts (
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
    )""",
    'CREATE INDEX IF NOT EXISTS ix_traffit_field_contracts_status ON traffit_field_contracts (status)',
    """CREATE TABLE IF NOT EXISTS traffit_outbox_events (
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
    )""",
    "CREATE INDEX IF NOT EXISTS ix_traffit_outbox_due ON traffit_outbox_events (priority, next_attempt_at, id) WHERE status IN ('pending', 'retry')",
    'CREATE INDEX IF NOT EXISTS ix_traffit_outbox_aggregate_order ON traffit_outbox_events (aggregate_type, aggregate_id, sequence, id)',
    'CREATE INDEX IF NOT EXISTS ix_traffit_outbox_candidate_status ON traffit_outbox_events (candidate_id, status)',
    """CREATE TABLE IF NOT EXISTS traffit_webhook_events (
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
    )""",
    "CREATE INDEX IF NOT EXISTS ix_traffit_webhook_due ON traffit_webhook_events (next_attempt_at, id) WHERE status IN ('pending', 'retry')",
    'CREATE INDEX IF NOT EXISTS ix_traffit_webhook_remote_entity ON traffit_webhook_events (remote_entity_type, remote_entity_id)',
    """CREATE TABLE IF NOT EXISTS traffit_sync_conflicts (
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
    )""",
    "CREATE INDEX IF NOT EXISTS ix_traffit_conflicts_open ON traffit_sync_conflicts (detected_at, id) WHERE status IN ('open', 'manual_action_required')",
    'CREATE INDEX IF NOT EXISTS ix_traffit_conflicts_candidate ON traffit_sync_conflicts (candidate_id, status)',
    'CREATE INDEX IF NOT EXISTS ix_traffit_conflicts_entity ON traffit_sync_conflicts (entity_type, nexus_entity_id, traffit_entity_id)',
    'CREATE UNIQUE INDEX IF NOT EXISTS ux_traffit_conflicts_idempotency ON traffit_sync_conflicts (idempotency_key) WHERE idempotency_key IS NOT NULL',
    """CREATE TABLE IF NOT EXISTS traffit_sync_runs (
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
    )""",
    'CREATE INDEX IF NOT EXISTS ix_traffit_sync_runs_status_started ON traffit_sync_runs (status, started_at)',
    'CREATE INDEX IF NOT EXISTS ix_traffit_sync_runs_mode_created ON traffit_sync_runs (mode, created_at)',
    """CREATE TABLE IF NOT EXISTS traffit_sync_run_phases (
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
    )""",
    'CREATE INDEX IF NOT EXISTS ix_traffit_sync_run_phases_run_status ON traffit_sync_run_phases (run_id, status)',
    """CREATE TABLE IF NOT EXISTS integration_leases (
        name          VARCHAR(100) PRIMARY KEY,
        holder_id     VARCHAR(255) NOT NULL,
        acquired_at   TIMESTAMPTZ NOT NULL,
        heartbeat_at  TIMESTAMPTZ NOT NULL,
        expires_at    TIMESTAMPTZ NOT NULL,
        generation    BIGINT NOT NULL DEFAULT 1,
        metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    'CREATE INDEX IF NOT EXISTS ix_integration_leases_expires_at ON integration_leases (expires_at)',
    """CREATE TABLE IF NOT EXISTS traffit_integration_control (
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
    )""",
    # Rozszerzenia istniejących encji (0173) — bez UPDATE (ten w _DATA_).
    'ALTER TABLE candidates ADD COLUMN IF NOT EXISTS profile_about TEXT',
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS custom_fields JSONB NOT NULL DEFAULT '{}'::jsonb",
    'ALTER TABLE notes ADD COLUMN IF NOT EXISTS external_source VARCHAR(50)',
    'ALTER TABLE notes ADD COLUMN IF NOT EXISTS external_id VARCHAR(255)',
    'ALTER TABLE notes ADD COLUMN IF NOT EXISTS source_created_at TIMESTAMPTZ',
    'ALTER TABLE notes ADD COLUMN IF NOT EXISTS source_updated_at TIMESTAMPTZ',
    'ALTER TABLE notes ADD COLUMN IF NOT EXISTS source_deleted_at TIMESTAMPTZ',
    'ALTER TABLE notes ADD COLUMN IF NOT EXISTS supersedes_note_id INTEGER REFERENCES notes(id) ON DELETE SET NULL',
    'CREATE INDEX IF NOT EXISTS ix_notes_external_source ON notes (external_source)',
    'CREATE INDEX IF NOT EXISTS ix_notes_external_id ON notes (external_id)',
    'CREATE UNIQUE INDEX IF NOT EXISTS ux_notes_external_source_id ON notes (external_source, external_id) WHERE external_id IS NOT NULL',
    'CREATE INDEX IF NOT EXISTS ix_notes_candidate_source_created ON notes (candidate_id, external_source, source_created_at)',
    'ALTER TABLE candidate_documents ADD COLUMN IF NOT EXISTS content_sha256 VARCHAR(64)',
    'ALTER TABLE candidate_documents ADD COLUMN IF NOT EXISTS source_manifest_fingerprint VARCHAR(64)',
    'ALTER TABLE candidate_documents ADD COLUMN IF NOT EXISTS source_deleted_at TIMESTAMPTZ',
    'CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_documents_candidate_sha ON candidate_documents (candidate_id, content_sha256) WHERE content_sha256 IS NOT NULL AND source_deleted_at IS NULL',
    'CREATE INDEX IF NOT EXISTS ix_candidate_documents_manifest ON candidate_documents (candidate_id, source_manifest_fingerprint)',
    'ALTER TABLE rejection_reasons ADD COLUMN IF NOT EXISTS external_source VARCHAR(50)',
    'ALTER TABLE rejection_reasons ADD COLUMN IF NOT EXISTS external_id VARCHAR(100)',
    'CREATE INDEX IF NOT EXISTS ix_rejection_reasons_external_source ON rejection_reasons (external_source)',
    'CREATE INDEX IF NOT EXISTS ix_rejection_reasons_external_id ON rejection_reasons (external_id)',
    'CREATE UNIQUE INDEX IF NOT EXISTS ux_rejection_reasons_external_source_id ON rejection_reasons (external_source, external_id) WHERE external_id IS NOT NULL',
    'ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS cursor_at TIMESTAMPTZ',
    'ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS cursor_external_id VARCHAR(255)',
    'ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS cursor_payload JSONB',
    'ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ',
    'ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS last_success_at TIMESTAMPTZ',
    'ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0',
    'ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS last_error TEXT',
    'ALTER TABLE traffit_sync_state ADD COLUMN IF NOT EXISTS next_due_at TIMESTAMPTZ',
    # ── Analytics v1 foundation (0174, plan analytics PR 2) ──────────────
    # Indeksy + kanoniczne views. DDL 1:1 z 0174_analytics_v1_foundation —
    # przy zmianie definicji view bump metryki (app/analytics/cache.py
    # METRIC_VERSION) i aktualizacja OBU miejsc.
    "CREATE INDEX IF NOT EXISTS ix_analytics_cs_cand_job_moved "
    "ON candidate_stages (candidate_id, job_id, moved_at DESC, id DESC)",
    "DROP INDEX IF EXISTS ix_analytics_cs_stage_first",
    "CREATE INDEX IF NOT EXISTS ix_analytics_cs_stage_first_v2 "
    "ON candidate_stages (stage, candidate_id, job_id, moved_at ASC, id ASC) "
    "WHERE stage IN "
    "('verified', 'cv_sent', 'interview', 'client_interview', 'acceptance', 'hired')",
    "CREATE INDEX IF NOT EXISTS ix_analytics_calls_user_effective "
    "ON calls (user_id, status, (COALESCE(started_at, created_at)))",
    "CREATE INDEX IF NOT EXISTS ix_analytics_cse_first_touch "
    "ON candidate_source_events (candidate_id, captured_at ASC, id ASC)",
    "CREATE INDEX IF NOT EXISTS ix_analytics_contracts_dates "
    "ON contracts (start_date, end_date)",
    "CREATE INDEX IF NOT EXISTS ix_analytics_jobs_close_reason "
    "ON jobs (close_reason) WHERE close_reason IS NOT NULL",
    """CREATE OR REPLACE VIEW analytics_current_pipeline AS
        SELECT DISTINCT ON (candidate_id, job_id)
            candidate_id,
            job_id,
            stage,
            moved_at,
            moved_by,
            id AS candidate_stage_id
        FROM candidate_stages
        ORDER BY candidate_id, job_id, moved_at DESC, id DESC""",
    """CREATE OR REPLACE VIEW analytics_first_milestones AS
        SELECT
            candidate_id,
            job_id,
            stage,
            moved_at AS first_reached_at,
            moved_by AS first_moved_by,
            id AS candidate_stage_id
        FROM (
            SELECT
                cs.candidate_id,
                cs.job_id,
                cs.stage,
                cs.moved_at,
                cs.moved_by,
                cs.id,
                ROW_NUMBER() OVER (
                    PARTITION BY cs.candidate_id, cs.job_id, cs.stage
                    ORDER BY cs.moved_at ASC, cs.id ASC
                ) AS rn
            FROM candidate_stages cs
            WHERE cs.stage IN (
                'verified', 'cv_sent', 'interview', 'client_interview',
                'acceptance', 'hired'
            )
        ) ranked
        WHERE rn = 1""",
    # ── Snapshoty + cutover (0177, plan analytics PR 7) ─────────────────
    """CREATE TABLE IF NOT EXISTS analytics_metric_snapshots (
        id           SERIAL PRIMARY KEY,
        module       VARCHAR(50) NOT NULL,
        metric       VARCHAR(80) NOT NULL,
        period_label VARCHAR(20) NOT NULL,
        value        JSONB NOT NULL,
        source       VARCHAR(40) NOT NULL DEFAULT 'dynareporter',
        checksum     VARCHAR(64) NOT NULL,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_analytics_snapshot
            UNIQUE (module, metric, period_label, source)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_analytics_snapshots_module "
    "ON analytics_metric_snapshots (module, period_label)",
    """CREATE TABLE IF NOT EXISTS analytics_cutovers (
        id            SERIAL PRIMARY KEY,
        module        VARCHAR(50) NOT NULL UNIQUE,
        cutover_date  DATE NOT NULL,
        legacy_source VARCHAR(40) NOT NULL DEFAULT 'dynareporter',
        notes         TEXT,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    # ── Finanse (0176, plan analytics PR 6) ─────────────────────────────
    "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS filled_at TIMESTAMPTZ",
    """CREATE TABLE IF NOT EXISTS financial_adjustments (
        id              SERIAL PRIMARY KEY,
        effective_month DATE NOT NULL,
        kind            VARCHAR(50) NOT NULL,
        amount          NUMERIC(14, 2) NOT NULL,
        currency        VARCHAR(3) NOT NULL DEFAULT 'PLN',
        description     TEXT NOT NULL,
        client_id       INTEGER REFERENCES clients(id) ON DELETE SET NULL,
        status          adjustmentstatus NOT NULL DEFAULT 'draft',
        created_by      INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        approved_by     INTEGER REFERENCES users(id) ON DELETE RESTRICT,
        approved_at     TIMESTAMPTZ
    )""",
    "CREATE INDEX IF NOT EXISTS ix_financial_adjustments_month "
    "ON financial_adjustments (effective_month)",
    "CREATE INDEX IF NOT EXISTS ix_financial_adjustments_status "
    "ON financial_adjustments (status)",
    "CREATE INDEX IF NOT EXISTS ix_financial_adjustments_client "
    "ON financial_adjustments (client_id)",
    """CREATE OR REPLACE VIEW analytics_candidate_first_sources AS
        SELECT DISTINCT ON (candidate_id)
            candidate_id,
            channel,
            job_id,
            utm_source,
            utm_medium,
            utm_campaign,
            captured_at,
            id AS source_event_id
        FROM candidate_source_events
        ORDER BY candidate_id, captured_at ASC, id ASC""",
    # 0175 (M4 PR-01): stage_notification_rules.specific_user_id — FK
    # ON DELETE SET NULL kolidowało z CHECK ck_stage_notif_specific_user
    # (wymaga non-NULL dla recipient_type='specific_user'), więc DELETE
    # użytkownika wywalał się na CHECK. CASCADE usuwa regułę razem z userem
    # (reguła wskazująca nieistniejącego odbiorcę jest bezprzedmiotowa).
    # Para DROP+ADD jest rerun-safe (safety net wykonuje statementy 1:1).
    "ALTER TABLE stage_notification_rules "
    "DROP CONSTRAINT IF EXISTS stage_notification_rules_specific_user_id_fkey",
    "ALTER TABLE stage_notification_rules "
    "ADD CONSTRAINT stage_notification_rules_specific_user_id_fkey "
    "FOREIGN KEY (specific_user_id) REFERENCES users(id) ON DELETE CASCADE",
    "ALTER TABLE client_stage_notification_overrides "
    "DROP CONSTRAINT IF EXISTS "
    "client_stage_notification_overrides_specific_user_id_fkey",
    "ALTER TABLE client_stage_notification_overrides "
    "ADD CONSTRAINT client_stage_notification_overrides_specific_user_id_fkey "
    "FOREIGN KEY (specific_user_id) REFERENCES users(id) ON DELETE CASCADE",
    # 0176 (M4 PR-04): CV share token v2 — hash zamiast sekretu, limity
    # wyświetleń, audyt odwołań. Wszystko idempotentne (IF NOT EXISTS).
    "ALTER TABLE cv_share_tokens ADD COLUMN IF NOT EXISTS token_sha256 VARCHAR(64)",
    "ALTER TABLE cv_share_tokens ADD COLUMN IF NOT EXISTS max_views INTEGER",
    "ALTER TABLE cv_share_tokens "
    "ADD COLUMN IF NOT EXISTS view_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE cv_share_tokens ADD COLUMN IF NOT EXISTS last_viewed_at TIMESTAMPTZ",
    "ALTER TABLE cv_share_tokens ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ",
    "ALTER TABLE cv_share_tokens ADD COLUMN IF NOT EXISTS revoked_by INTEGER "
    "REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE cv_share_tokens ADD COLUMN IF NOT EXISTS revoke_reason VARCHAR(255)",
    "ALTER TABLE cv_share_tokens ADD COLUMN IF NOT EXISTS purpose VARCHAR(120)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_cv_share_tokens_sha256 "
    "ON cv_share_tokens (token_sha256) WHERE token_sha256 IS NOT NULL",
]

_DATA_STATEMENTS = [
    # 0173: rejection_reasons.external_source backfill (integracja Traffit).
    "UPDATE rejection_reasons SET external_source = 'manual' "
    "WHERE external_source IS NULL",
    # Backfill closed_at for historical closed rows so reports sort by "real
    # close date" instead of NULL. Safe because only touches NULL rows.
    "UPDATE jobs SET closed_at = updated_at WHERE status = 'closed' AND closed_at IS NULL",
    # Pre-flag roles that don't need onboarding (mirrors migration 0035 step)
    """UPDATE users
          SET profile_completed = TRUE,
              profile_completed_at = COALESCE(profile_completed_at, NOW())
        WHERE profile_completed = FALSE
          AND role::text NOT IN ('delivery_lead', 'recruiter')""",
    # Seed 5 Competence Categories (migration 0033_cc_entities). Idempotent:
    # ON CONFLICT (slug) pomija duplikaty. Nie re-update'uje, bo Head of
    # Recruitment mógł zmodyfikować opis/keywords w UI.
    """INSERT INTO competence_categories (slug, name_pl, name_en, description, keywords, display_order, is_active)
       VALUES
         ('infrastructure_operations', 'Infrastruktura i Operacje', 'Infrastructure & Operations',
          'Zespoły odpowiedzialne za infrastrukturę, cloud, DevOps, SRE, platformę, sieć, bezpieczeństwo systemów, CI/CD oraz niezawodność.',
          '["devops","sre","site reliability","kubernetes","k8s","docker","terraform","ansible","jenkins","gitlab ci","github actions","aws","azure","gcp","cloud","linux","sysadmin","platform","networking","ci/cd","helm","prometheus","grafana","istio","observability","infrastructure"]'::jsonb,
          1, true),
         ('software_development', 'Rozwój Oprogramowania', 'Software Development',
          'Rozwój aplikacji frontend, backend, mobile, embedded. Frameworki webowe, języki programowania, architektura aplikacyjna.',
          '["frontend","backend","fullstack","full stack","full-stack","react","vue","angular","typescript","javascript","nextjs","next.js","nuxt","java","spring","spring boot","python","django","fastapi","flask","node","nodejs","node.js","go","golang","rust",".net","dotnet","c#","csharp","php","laravel","symfony","ruby","rails","mobile","ios","swift","android","kotlin","flutter","react native","embedded"]'::jsonb,
          2, true),
         ('data_ai', 'Dane i AI', 'Data & AI',
          'Inżynieria danych, data science, machine learning, analityka, BI.',
          '["data engineer","data scientist","ml engineer","machine learning","deep learning","ai","nlp","computer vision","llm","gpt","tensorflow","pytorch","spark","airflow","dbt","snowflake","bigquery","redshift","databricks","kafka","analytics","bi","tableau","power bi","looker","etl","elt","mlops","feature store","vector database"]'::jsonb,
          3, true),
         ('security_quality', 'Bezpieczeństwo i Jakość', 'Security & Quality',
          'Zapewnienie jakości, automatyzacja testów, cyberbezpieczeństwo, pentesting, compliance.',
          '["qa","quality assurance","tester","test automation","selenium","cypress","playwright","junit","pytest","security","pentester","appsec","application security","owasp","soc","siem","iso 27001","sast","dast","red team","blue team","penetration testing","vulnerability","cybersecurity","security engineer"]'::jsonb,
          4, true),
         ('management_delivery', 'Zarządzanie i Dostarczanie', 'Management & Delivery',
          'Zarządzanie produktem, projektami, zespołami, delivery.',
          '["pm","product manager","project manager","delivery lead","delivery manager","scrum master","agile coach","product owner","po","business analyst","ba","engineering manager","tech lead","team lead","cto","director","head of"]'::jsonb,
          5, true)
       ON CONFLICT (slug) DO NOTHING""",
    # ── Sprzątanie reliktu "[zatrudniony]" w nazwiskach (mirror migracji 0165) ──
    # Traffit nie miał statusu zatrudnienia, więc zatrudnionych oznaczano
    # wpisując "[zatrudniony]" w imię/nazwisko. Nexus wyprowadza zatrudnienie z
    # sygnałów (aktywny kontrakt / konflikt current_employment / etap hired), więc
    # marker jest zbędny (psuje wyszukiwanie po nazwisku + nagłówki CV). Prod ma
    # chroniczny multi-head alembic (DB przed kodem), więc migracja 0165 może nie
    # wejść — dublujemy ją tu, żeby czyszczenie NA PEWNO się wykonało. Idempotentne:
    # po pierwszym przebiegu ILIKE nie łapie już żadnego wiersza. Kolejność ważna —
    # PARK przed STRIP (park wykrywa grupę B po markerze, który strip usuwa).
    #
    # 1) Parkuj trwały tag dla oznaczonych BEZ realnego sygnału zatrudnienia
    #    (grupa B). Mapper stripuje marker z nazwiska przy imporcie, więc bez tego
    #    ich jedyny ślad zniknąłby po cichu; tags nie jest nadpisywany przez sync.
    #    Guard: tylko array-owe tags + brak duplikatu.
    r"""
    UPDATE candidates cand
    SET tags = COALESCE(cand.tags, '[]'::jsonb)
               || '["Traffit: oznaczony jako zatrudniony (do weryfikacji)"]'::jsonb
    WHERE (cand.name ILIKE '%zatrudnion%' OR cand.lastname ILIKE '%zatrudnion%')
      AND jsonb_typeof(COALESCE(cand.tags, '[]'::jsonb)) = 'array'
      AND NOT (COALESCE(cand.tags, '[]'::jsonb)
               @> '["Traffit: oznaczony jako zatrudniony (do weryfikacji)"]'::jsonb)
      AND NOT (
          EXISTS (SELECT 1 FROM contracts c
                  WHERE c.candidate_id = cand.id AND c.status::text = 'active')
          OR EXISTS (SELECT 1 FROM candidate_conflicts cc
                     WHERE cc.candidate_id = cand.id
                       AND cc.type::text = 'current_employment' AND cc.active)
          OR EXISTS (SELECT 1 FROM candidate_stages cs
                     WHERE cs.candidate_id = cand.id AND cs.stage::text = 'hired'
                       AND NOT EXISTS (
                           SELECT 1 FROM candidate_stages later
                           WHERE later.candidate_id = cs.candidate_id
                             AND later.job_id = cs.job_id
                             AND (later.moved_at, later.id) > (cs.moved_at, cs.id)))
      )""",
    # 2) Wyczyść marker z name/lastname wszystkich oznaczonych. Osoby z realnym
    #    sygnałem dalej mają badge "U klienta" (przez _derive_employment). Fallback
    #    '?' gdy pole było samym markerem (jak w mapperze). Capturing group (...) —
    #    NIE (?:...) — spójne z migracją 0165. asyncpg nie parsuje bind-paramów,
    #    więc dwukropek nie jest problemem, ale trzymamy jeden wzorzec.
    r"""
    UPDATE candidates cand
    SET name = COALESCE(NULLIF(btrim(regexp_replace(
                   regexp_replace(cand.name, '[[(]?\s*zatrudnion(ego|ej|ych|ymi|[yaieą])?\s*[])]?', ' ', 'gi'),
                   '\s+', ' ', 'g'), ' -–,;'), ''), '?'),
        lastname = COALESCE(NULLIF(btrim(regexp_replace(
                   regexp_replace(cand.lastname, '[[(]?\s*zatrudnion(ego|ej|ych|ymi|[yaieą])?\s*[])]?', ' ', 'gi'),
                   '\s+', ' ', 'g'), ' -–,;'), ''), '?')
    WHERE cand.name ILIKE '%zatrudnion%' OR cand.lastname ILIKE '%zatrudnion%'""",
]


async def backfill():
    url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://nexus:nexus@postgres:5432/nexus")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    # Enum ADD VALUE must run in autocommit mode.
    conn = await asyncpg.connect(url)
    try:
        for stmt in _ENUM_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception as e:
                print(f"backfill enum skip: {stmt!r} -> {e!r}")
        for stmt in _COLUMN_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception as e:
                print(f"backfill column skip: {stmt!r} -> {e!r}")
        for stmt in _DATA_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception as e:
                print(f"backfill data skip: {stmt!r} -> {e!r}")
        print("backfill: ok")
    finally:
        await conn.close()

asyncio.run(backfill())
PY

# Second safety net: create any tables that alembic failed to create.
# Uses SQLAlchemy Base.metadata.create_all — idempotent, skips existing
# tables. Handles the Phase 8 tables (competence_categories,
# user_competence_categories, candidate_invite_links, procedures,
# proposal_snapshots, champion_profile_suggestions, app_settings, etc.)
# that migrations 0029_*/0031_*/0032_*/0033_* would have created.
echo "Creating missing tables from SQLAlchemy metadata..."
python - <<'PY' || echo "metadata create_all failed; continuing"
import asyncio
from app.core.database import engine, Base
# Import all model modules so Base.metadata is fully populated.
import app.models  # noqa: F401

async def create_all():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("metadata create_all: ok")

asyncio.run(create_all())
PY

# Cortex: dedup taksonomii (safety-net gdy alembic nie dobija do 0167).
# Idempotentne + transakcyjne (rollback przy błędzie → worst case brak zmiany);
# scala tylko faktyczne duplikaty case + 5 par semantycznych, repin-before-delete.
# Bez tego prod (zaklinowany alembic na starej rewizji) miałby zdublowaną
# taksonomię (python/Python) mimo działającego modułu Cortex.
echo "Cortex: dedup taxonomy (idempotent safety-net)..."
python - <<'PY' || echo "cortex dedup skipped; continuing"
import asyncio
from app.core.database import AsyncSessionLocal
from app.services.cortex.taxonomy_dedup import dedup_taxonomy

async def run():
    async with AsyncSessionLocal() as db:
        try:
            res = await dedup_taxonomy(db)
            await db.commit()
            print(f"cortex dedup: {res}")
        except Exception as e:
            await db.rollback()
            print(f"cortex dedup rolled back (no change): {e!r}")

asyncio.run(run())
PY

# Reset any m365_connections stuck in 'running' from a killed sync task.
# Without this, a container OOM/SIGTERM during backfill leaves last_sync_status
# pinned at 'running' and the sync loop keeps re-entering mid-flow instead of
# starting clean.
echo "Resetting stuck m365 sync state (idempotent)..."
python - <<'PY' || echo "m365 reset skipped (table may not exist yet); continuing"
import asyncio
from sqlalchemy import text
from app.core.database import engine

async def reset():
    async with engine.begin() as conn:
        # Cheap existence check so this stays a no-op before migration 0036.
        exists = await conn.scalar(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name='m365_connections' LIMIT 1"
        ))
        if not exists:
            print("m365_connections: table missing, skipping reset")
            return
        result = await conn.execute(text(
            "UPDATE m365_connections "
            "SET last_sync_status='idle', "
            "    last_error=COALESCE(last_error, 'reset after container restart') "
            "WHERE last_sync_status='running'"
        ))
        print(f"m365 reset: rowcount={result.rowcount}")

asyncio.run(reset())
PY

# Run seed (idempotent - skips if already seeded)
echo "Running seed data..."
python seed.py || echo "seed.py failed (likely pre-existing schema drift from unmerged branches); continuing"

# Ensure the dedicated Claude E2E admin account exists on every startup.
# Idempotent upsert — rotates password to the bootstrap value each boot unless
# CLAUDE_ADMIN_BOOTSTRAP_PWD is set in env. Non-fatal.
echo "Ensuring Claude admin account..."
python scripts/ensure_claude_admin.py || echo "ensure_claude_admin failed; continuing"

# Start the application
echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
