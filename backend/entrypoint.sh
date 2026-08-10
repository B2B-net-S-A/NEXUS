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
    # Role dashboards/RBAC cutover (0210): exclusive Finance persona.
    "ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'finance'",
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
    # 0214: nowa wartość aifeaturekey dla odczytu PDF zamówienia
    # ("Zczytaj dane z dokumentu" w przedłużeniu). Bez niej seed ai_features
    # poniżej ORAZ INSERT do ai_usage_log przy odczycie wywalają się
    # InvalidTextRepresentationError. _ENUM_STATEMENTS leci przed
    # _DATA_STATEMENTS (patrz pętla w main()), więc wartość jest zacommitowana,
    # zanim seed jej użyje.
    "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'order_parser'",
    # 0217: interaktywne CV — kafelki wymagań (cv_requirement_map) + chat
    # hiring managera (cv_interactive_chat). Bez wartości enuma seed ai_features
    # niżej i INSERT do ai_usage_log przy generacji mapy/odpowiedzi chatu
    # => InvalidTextRepresentationError.
    "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_requirement_map'",
    "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_interactive_chat'",
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
        is_first_priority_for_tac BOOLEAN NULL,
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
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_client_tac_one_first_priority_client "
    "ON client_tac_assignments (tac_user_id) "
    "WHERE is_first_priority_for_tac IS TRUE",
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
    # Job deadline alerts (migracja 0211_job_deadline_alerts). Daily scanner
    # app/tasks/job_deadline_alerts.py wstawia Notification z tymi typami dla
    # progów 7/3/1 dni przed Job.deadline. Bez tych wartości w DB enum insert
    # crashuje (InvalidTextRepresentationError), gdyby alembic upgrade nie
    # wszedł na prod — ten sam failure mode co kpi_coach/saved_search incident.
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_deadline_7d'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_deadline_3d'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_deadline_1d'",
    # Nowy typ dokumentu „Zamówienie" na kontrakcie (migracja
    # 0160_contract_document_type_order). Bez tej wartości upload dokumentu
    # doc_type='order' wywala się InvalidTextRepresentationError (DB enum nie
    # zna wartości), gdyby alembic upgrade nie wszedł na prod (multi-head).
    "ALTER TYPE contractdocumenttype ADD VALUE IF NOT EXISTS 'order'",
    # ── Rozjazd zmierzony na produkcji 2026-07-20 przez /api/admin/schema-drift ──
    # Wszystkie cztery: ORM deklaruje etykietę, której typ w bazie nie ma, więc
    # SQLAlchemy wysyła wartość, a Postgres odrzuca ją jako invalid input value.
    #
    # rejection_email_*: migracja 0045 je dodaje, ale zakładka alembica prod stoi
    # na 0152 i te ALTER-y nigdy się nie wykonały. rejection_email_scheduler.py
    # zapisuje je w liniach 171/296/332 — to ŻYWY błąd, cicho psujący
    # powiadomienia o mailach odmownych.
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'rejection_email_scheduled'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'rejection_email_sent'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'rejection_email_failed'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'rejection_email_cancelled'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'rejection_email_skipped'",
    # callstatus: zapisywane przez POST /api/cloudtalk/initiate-call. Uśpione,
    # bo CLOUDTALK_ENABLED=false — ale leży dokładnie na ścieżce aktywacji.
    "ALTER TYPE callstatus ADD VALUE IF NOT EXISTS 'initiated'",
    # contracttype: typ powstał z literówką 'uzlecenie' (0001_initial), a ORM
    # wysyła 'zlecenie'. Dodajemy poprawną; literówki NIE ruszamy, bo mogą na
    # niej wisieć istniejące wiersze, a DROP wartości enuma w Postgresie nie
    # istnieje. Przeniesienie wierszy to osobna, świadoma decyzja.
    "ALTER TYPE contracttype ADD VALUE IF NOT EXISTS 'zlecenie'",
    # nextsteppreference: baza ma 'pass' (poprawnie), ORM wysyła 'pass_', bo
    # pass to keyword Pythona. Dokładamy 'pass_' jako natychmiastowe rozbrojenie;
    # docelowo właściwą naprawą jest values_callable na kolumnie, żeby ORM
    # wysyłał wartość zamiast nazwy — ale to zmiana kodu, nie schematu.
    "ALTER TYPE nextsteppreference ADD VALUE IF NOT EXISTS 'pass_'",
    # Contract lifecycle invariant (migracja 0190_contract_lifecycle_invariant):
    # dwie nowe wartości contractstatus. Bez nich guarded lifecycle
    # (app/services/contract_lifecycle.py) crashuje na INSERT/UPDATE contracts z
    # tymi statusami (InvalidTextRepresentationError):
    #   ready_for_signature — sfinalizowany, niepodpisany draft (NIE 'active'),
    #   void                — soft-delete/annulacja zamiast hard DELETE.
    "ALTER TYPE contractstatus ADD VALUE IF NOT EXISTS 'ready_for_signature'",
    "ALTER TYPE contractstatus ADD VALUE IF NOT EXISTS 'void'",
    # Recruitment Priority Lock (0200). `origin_kind` is added to the existing
    # recruitment_processes table before metadata.create_all runs, therefore
    # its enum must exist here. Enums used only by new tables are created by
    # SQLAlchemy together with those tables in the second safety net.
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'priorityoriginkind'
        ) THEN
            CREATE TYPE priorityoriginkind AS ENUM (
                'legacy', 'assigned', 'shadow_violation', 'external_inbound',
                'external_observed', 'manager_inbound', 'approved_exception'
            );
        END IF;
    END $$""",
    "ALTER TYPE priorityoriginkind ADD VALUE IF NOT EXISTS 'legacy'",
    "ALTER TYPE priorityoriginkind ADD VALUE IF NOT EXISTS 'assigned'",
    "ALTER TYPE priorityoriginkind ADD VALUE IF NOT EXISTS 'shadow_violation'",
    "ALTER TYPE priorityoriginkind ADD VALUE IF NOT EXISTS 'external_inbound'",
    "ALTER TYPE priorityoriginkind ADD VALUE IF NOT EXISTS 'external_observed'",
    "ALTER TYPE priorityoriginkind ADD VALUE IF NOT EXISTS 'manager_inbound'",
    "ALTER TYPE priorityoriginkind ADD VALUE IF NOT EXISTS 'approved_exception'",
    # 0205: lokalna klasyfikacja katalogu klientów. Tworzymy typ przed
    # kolumnami/tabelami safety-netu; ADD VALUE naprawia też częściowy typ po
    # przerwanym ręcznym wdrożeniu.
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'clientportfoliocategory'
        ) THEN
            CREATE TYPE clientportfoliocategory AS ENUM (
                'active', 'relationship', 'inactive'
            );
        END IF;
    END $$""",
    "ALTER TYPE clientportfoliocategory ADD VALUE IF NOT EXISTS 'active'",
    "ALTER TYPE clientportfoliocategory ADD VALUE IF NOT EXISTS 'relationship'",
    "ALTER TYPE clientportfoliocategory ADD VALUE IF NOT EXISTS 'inactive'",
    # 0087 zwykle już utworzyło ten enum. Guard zabezpiecza odtworzoną /
    # osieroconą bazę, a legacy_import oznacza zakres MSA z Excela bez PDF-a.
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'frameworkcontractsignedvia'
        ) THEN
            CREATE TYPE frameworkcontractsignedvia AS ENUM (
                'upload', 'autenti', 'legacy_import'
            );
        END IF;
    END $$""",
    "ALTER TYPE frameworkcontractsignedvia ADD VALUE IF NOT EXISTS 'upload'",
    "ALTER TYPE frameworkcontractsignedvia ADD VALUE IF NOT EXISTS 'autenti'",
    "ALTER TYPE frameworkcontractsignedvia ADD VALUE IF NOT EXISTS 'legacy_import'",
]

_PROFILE_RATE_TARGET_TYPE = "numeric(10,2)"
_PROFILE_RATE_TABLE_QUERY = "SELECT to_regclass('candidates') IS NOT NULL"
_PROFILE_RATE_TYPE_QUERY = """
    SELECT format_type(attribute.atttypid, attribute.atttypmod)
    FROM pg_attribute AS attribute
    WHERE attribute.attrelid = to_regclass('candidates')
      AND attribute.attname = 'expected_rate_hourly'
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
"""
_PROFILE_RATE_ALTER_SQL = (
    "ALTER TABLE candidates ALTER COLUMN expected_rate_hourly "
    "TYPE NUMERIC(10,2) USING expected_rate_hourly::numeric(10,2)"
)

_COLUMN_STATEMENTS = [
    # Role dashboards/RBAC cutover (0210).  These tables keep the pre-cutover
    # role snapshot and explicit work queue for ambiguous relationship data.
    """CREATE TABLE IF NOT EXISTS role_session_migration_audit (
           id BIGSERIAL PRIMARY KEY,
           migration_key VARCHAR(80) NOT NULL,
           user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
           original_state JSONB NOT NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           CONSTRAINT uq_role_session_migration_audit
               UNIQUE (migration_key, user_id)
       )""",
    """CREATE TABLE IF NOT EXISTS rbac_relationship_reconciliation (
           id BIGSERIAL PRIMARY KEY,
           migration_key VARCHAR(80) NOT NULL,
           issue_kind VARCHAR(80) NOT NULL,
           user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           details JSONB NOT NULL DEFAULT '{}'::jsonb,
           resolved_at TIMESTAMPTZ NULL,
           resolved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
       )""",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
    "authorization_version BIGINT NOT NULL DEFAULT 1",
    "ALTER TABLE auth_exchange_codes ADD COLUMN IF NOT EXISTS "
    "issued_authorization_version BIGINT NOT NULL DEFAULT 1",
    "ALTER TABLE client_tac_assignments ADD COLUMN IF NOT EXISTS "
    "is_first_priority_for_tac BOOLEAN NULL",
    # 0215: manualne nakładki placementu katalogu klientów. Czytane przez
    # katalog (COALESCE), niewidoczne dla inwariantu manifestu — ręczne
    # przeniesienie między zakładkami nie rozjeżdża /api/health/deep.
    "ALTER TABLE client_portfolio_scopes ADD COLUMN IF NOT EXISTS category_override clientportfoliocategory NULL",
    "ALTER TABLE client_portfolio_scopes ADD COLUMN IF NOT EXISTS contract_start_override DATE NULL",
    "ALTER TABLE client_portfolio_scopes ADD COLUMN IF NOT EXISTS contract_end_override DATE NULL",
    """DO $$ BEGIN
        ALTER TABLE client_portfolio_scopes
            ADD CONSTRAINT ck_client_portfolio_scopes_override_dates
            CHECK (
                contract_start_override IS NULL
                OR contract_end_override IS NULL
                OR contract_end_override >= contract_start_override
            );
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$""",
    # 0216: „część umowy" Centrum e-Zdrowia (ticket #3). Nullable — wymagane
    # tylko w walidacji API/UI dla client_id=115; cz.3 celowo nie istnieje.
    "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS project_part VARCHAR(8) NULL",
    """DO $$ BEGIN
        ALTER TABLE client_orders
            ADD CONSTRAINT ck_client_orders_project_part
            CHECK (
                project_part IS NULL
                OR project_part IN ('cz1', 'cz2', 'cz4', 'cz5', 'cz6')
            );
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$""",
    # Recruitment Priority Lock (0200) — provenance/eligibility is added to the
    # existing canonical aggregate. New priority-work tables are created by the
    # metadata safety net below; post-create FKs are installed after it.
    """ALTER TABLE recruitment_processes
       ADD COLUMN IF NOT EXISTS origin_assignment_id INTEGER NULL""",
    """ALTER TABLE recruitment_processes
       ADD COLUMN IF NOT EXISTS eligibility_assignment_id INTEGER NULL""",
    """ALTER TABLE recruitment_processes
       ADD COLUMN IF NOT EXISTS opened_by_user_id INTEGER NULL""",
    """ALTER TABLE recruitment_processes
       ADD COLUMN IF NOT EXISTS credit_user_id INTEGER NULL""",
    """ALTER TABLE recruitment_processes
       ADD COLUMN IF NOT EXISTS origin_kind priorityoriginkind NULL""",
    """ALTER TABLE recruitment_processes
       ADD COLUMN IF NOT EXISTS priority_compliant_at_open BOOLEAN NULL""",
    """ALTER TABLE recruitment_processes
       ADD COLUMN IF NOT EXISTS kpi_eligible BOOLEAN NULL""",
    """ALTER TABLE recruitment_processes
       ADD COLUMN IF NOT EXISTS kpi_eligibility_reason VARCHAR(255) NULL""",
    """ALTER TABLE recruitment_processes
       ADD COLUMN IF NOT EXISTS kpi_eligibility_decided_at TIMESTAMPTZ NULL""",
    """ALTER TABLE recruitment_processes
       ADD COLUMN IF NOT EXISTS ownership_confirmed_at TIMESTAMPTZ NULL""",
    """ALTER TABLE recruitment_processes
       ADD COLUMN IF NOT EXISTS ownership_confirmed_by_user_id INTEGER NULL""",
    """ALTER TABLE candidate_invite_links
       ADD COLUMN IF NOT EXISTS origin_assignment_id INTEGER NULL""",
    """ALTER TABLE candidate_invite_links
       ADD COLUMN IF NOT EXISTS priority_compliant_at_create BOOLEAN NULL""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_processes_credit_user_id
       ON recruitment_processes (credit_user_id)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_processes_origin_kind
       ON recruitment_processes (origin_kind)""",
    # Restart-safe background loops (migracja 0186, audyt P1/P2). Durable dedup
    # markers dla pętli tła — bez nich pętla po restarcie (Coolify rebuild na
    # każdym pushu) i przy >1 workerze duplikuje wysyłki:
    #   calendar_reminder_loop  → reminder_sent_at (NULL = nie przypomniano)
    #   slack_sla_alerts_loop   → sla_alerted_at   (NULL = nie zaalarmowano)
    # linkedin_sync NIE wymaga kolumny (reużywa candidates.linkedin_synced_at
    # + FOR UPDATE SKIP LOCKED).
    """ALTER TABLE calendar_events
       ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ NULL""",
    """ALTER TABLE candidate_stages
       ADD COLUMN IF NOT EXISTS sla_alerted_at TIMESTAMPTZ NULL""",
    # Generated B2B contract signature automation (migration 0196). Historical
    # rows remain unsigned; entity links are filled explicitly, never guessed
    # from partner/client names.
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS signature_status VARCHAR(32)
       NOT NULL DEFAULT 'unsigned'""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS signature_source VARCHAR(32) NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS candidate_id INTEGER NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS job_id INTEGER NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS client_id INTEGER NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS contract_id INTEGER NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS signed_at TIMESTAMPTZ NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS signed_by_user_id INTEGER NULL""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_generated_contracts_candidate_id
       ON b2b_generated_contracts (candidate_id)""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_generated_contracts_job_id
       ON b2b_generated_contracts (job_id)""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_generated_contracts_client_id
       ON b2b_generated_contracts (client_id)""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_generated_contracts_contract_id
       ON b2b_generated_contracts (contract_id)""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_generated_contracts_signed_by_user_id
       ON b2b_generated_contracts (signed_by_user_id)""",
    # Status handlowy wygenerowanej umowy (migracja 0203). Wszystkie istniejące
    # wiersze stają się 'active' z defaultu — zamknięcie jest zawsze decyzją
    # użytkownika, nigdy backfillem.
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS contract_status VARCHAR(16)
       NOT NULL DEFAULT 'active'""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS closure_reason VARCHAR(32) NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS closure_reason_other TEXT NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS closure_date DATE NULL""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_generated_contracts_contract_status
       ON b2b_generated_contracts (contract_status)""",
    # candidate_invite_links: token_sha256 + token_ct — hash+encrypt v2
    # (migracja 0183). Bez nich mint v2 wywala UndefinedColumn.
    """ALTER TABLE candidate_invite_links
       ADD COLUMN IF NOT EXISTS token_sha256 VARCHAR(64)""",
    """ALTER TABLE candidate_invite_links
       ADD COLUMN IF NOT EXISTS token_ct TEXT""",
    """CREATE INDEX IF NOT EXISTS ix_candidate_invite_links_token_sha256
       ON candidate_invite_links (token_sha256)""",
    # signature_links.token_sha256 + engagement_declaration_tokens.token_sha256
    # — hash-at-rest v2 (migracja 0182). Bez tego mint v2 wywala UndefinedColumn.
    """ALTER TABLE signature_links
       ADD COLUMN IF NOT EXISTS token_sha256 VARCHAR(64)""",
    """CREATE INDEX IF NOT EXISTS ix_signature_links_token_sha256
       ON signature_links (token_sha256)""",
    """ALTER TABLE engagement_declaration_tokens
       ADD COLUMN IF NOT EXISTS token_sha256 VARCHAR(64)""",
    """CREATE INDEX IF NOT EXISTS ix_engagement_declaration_tokens_token_sha256
       ON engagement_declaration_tokens (token_sha256)""",
    # champion_card_share_tokens.token_sha256 — hash-at-rest v2 (migracja 0181).
    # Bez tej kolumny mint v2 (token_sha256=digest) wywala UndefinedColumn i cały
    # generator linku do karty champion pada. Idempotentne.
    """ALTER TABLE champion_card_share_tokens
       ADD COLUMN IF NOT EXISTS token_sha256 VARCHAR(64)""",
    """CREATE INDEX IF NOT EXISTS ix_champion_card_share_tokens_token_sha256
       ON champion_card_share_tokens (token_sha256)""",
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
    # 0199: archiwum historii rekrutacji usuniętej korekcyjnie. Musi istnieć
    # ZANIM ktokolwiek wywoła DELETE /candidates/{id}/recruitments/{job_id} —
    # brak tabeli zamieniłby archiwizację w błąd, a alternatywą byłby powrót do
    # kasowania bez śladu.
    """CREATE TABLE IF NOT EXISTS candidate_stage_removals (
        id BIGSERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        removed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        removed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        reason TEXT,
        last_stage VARCHAR(64),
        stage_count INTEGER NOT NULL DEFAULT 0,
        stages_snapshot JSONB NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_candidate_stage_removals_pair "
    "ON candidate_stage_removals (candidate_id, job_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_stage_removals_removed_at "
    "ON candidate_stage_removals (removed_at)",
    # 0200: candidate-global contact coordination.  Feature flags are OFF by
    # default, but the complete additive schema must exist before a reviewed
    # activation.  This mirrors migration 0200 because prod's alembic lineage
    # may be orphaned and fall through to this idempotent safety net.
    """CREATE TABLE IF NOT EXISTS candidate_contact_cases (
        id SERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL
            REFERENCES candidates(id) ON DELETE CASCADE,
        owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        previous_owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        primary_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
        state VARCHAR(32) NOT NULL DEFAULT 'unassigned',
        due_at TIMESTAMPTZ,
        cooldown_until TIMESTAMPTZ,
        attempt_count SMALLINT NOT NULL DEFAULT 0,
        cycle INTEGER NOT NULL DEFAULT 1,
        version INTEGER NOT NULL DEFAULT 1,
        queue_slot SMALLINT,
        assigned_at TIMESTAMPTZ,
        last_attempt_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        blocked_phone_value VARCHAR(30),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_candidate_contact_cases_candidate_id UNIQUE (candidate_id),
        CONSTRAINT ck_candidate_contact_cases_state CHECK (
            state IN (
                'unassigned', 'awaiting_capacity', 'queued', 'callback_due',
                'cooldown', 'handoff_pending', 'blocked_no_phone',
                'suppressed', 'completed', 'cancelled'
            )
        ),
        CONSTRAINT ck_candidate_contact_cases_queue_slot CHECK (
            queue_slot IS NULL OR queue_slot BETWEEN 1 AND 20
        ),
        CONSTRAINT ck_candidate_contact_cases_slot_owner CHECK (
            queue_slot IS NULL OR owner_user_id IS NOT NULL
        ),
        CONSTRAINT ck_candidate_contact_cases_actionable_slot CHECK (
            (state IN ('queued', 'callback_due')) =
            (queue_slot IS NOT NULL)
        ),
        CONSTRAINT ck_candidate_contact_cases_attempt_count
            CHECK (attempt_count >= 0),
        CONSTRAINT ck_candidate_contact_cases_cycle CHECK (cycle >= 1),
        CONSTRAINT ck_candidate_contact_cases_version CHECK (version >= 1)
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_contact_cases_owner_slot "
    "ON candidate_contact_cases (owner_user_id, queue_slot) "
    "WHERE queue_slot IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_candidate_contact_cases_state_due "
    "ON candidate_contact_cases (state, due_at)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_contact_cases_owner_state "
    "ON candidate_contact_cases (owner_user_id, state)",
    """CREATE TABLE IF NOT EXISTS candidate_contact_opportunities (
        id SERIAL PRIMARY KEY,
        case_id INTEGER NOT NULL
            REFERENCES candidate_contact_cases(id) ON DELETE CASCADE,
        candidate_id INTEGER NOT NULL
            REFERENCES candidates(id) ON DELETE CASCADE,
        -- Durable tombstone: the job-delete hook closes the opportunity,
        -- while this denormalized id preserves its recruitment identity.
        job_id INTEGER NOT NULL,
        source VARCHAR(32) NOT NULL DEFAULT 'manual',
        source_external_ref VARCHAR(255),
        linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        source_cursor_created_at TIMESTAMPTZ,
        source_cursor_external_id VARCHAR(255),
        outcome VARCHAR(32),
        presented_at TIMESTAMPTZ,
        meeting_event_id INTEGER
            REFERENCES calendar_events(id) ON DELETE SET NULL,
        meeting_scheduled_at TIMESTAMPTZ,
        closed_at TIMESTAMPTZ,
        closed_reason VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_candidate_contact_opportunities_candidate_job
            UNIQUE (candidate_id, job_id),
        CONSTRAINT uq_candidate_contact_opportunities_case_job
            UNIQUE (case_id, job_id),
        CONSTRAINT ck_candidate_contact_opportunities_source CHECK (
            source IN ('pipeline', 'shortlist', 'traffit', 'manual')
        ),
        CONSTRAINT ck_candidate_contact_opportunities_outcome CHECK (
            outcome IS NULL OR outcome IN (
                'interested', 'maybe', 'not_interested', 'not_presented'
            )
        )
    )""",
    "ALTER TABLE candidate_contact_opportunities "
    "ADD COLUMN IF NOT EXISTS linked_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    "ALTER TABLE candidate_contact_opportunities "
    "ADD COLUMN IF NOT EXISTS source_cursor_created_at TIMESTAMPTZ",
    "ALTER TABLE candidate_contact_opportunities "
    "ADD COLUMN IF NOT EXISTS source_cursor_external_id VARCHAR(255)",
    "ALTER TABLE candidate_contact_opportunities "
    "DROP CONSTRAINT IF EXISTS "
    "candidate_contact_opportunities_job_id_fkey",
    "CREATE INDEX IF NOT EXISTS ix_candidate_contact_opportunities_candidate_id "
    "ON candidate_contact_opportunities (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_contact_opportunities_job_id "
    "ON candidate_contact_opportunities (job_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_contact_opportunities_case_open "
    "ON candidate_contact_opportunities (case_id, closed_at)",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS contact_case_id INTEGER",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS contact_outcome VARCHAR(32)",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS contact_source VARCHAR(32)",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS contact_idempotency_key VARCHAR(160)",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS contact_request_hash VARCHAR(64)",
    "ALTER TABLE calls ADD COLUMN IF NOT EXISTS callback_at TIMESTAMPTZ",
    """DO $$ BEGIN
        ALTER TABLE calls
            ADD CONSTRAINT fk_calls_contact_case_id
            FOREIGN KEY (contact_case_id)
            REFERENCES candidate_contact_cases(id) ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE calls
            ADD CONSTRAINT ck_calls_contact_outcome CHECK (
                contact_outcome IS NULL OR contact_outcome IN (
                    'connected', 'no_answer', 'callback_requested',
                    'wrong_number', 'do_not_contact'
                )
            );
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "CREATE INDEX IF NOT EXISTS ix_calls_contact_case_id "
    "ON calls (contact_case_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_calls_contact_idempotency_key "
    "ON calls (contact_idempotency_key) "
    "WHERE contact_idempotency_key IS NOT NULL",
    """CREATE TABLE IF NOT EXISTS candidate_contact_events (
        id BIGSERIAL PRIMARY KEY,
        case_id INTEGER NOT NULL,
        candidate_id INTEGER NOT NULL,
        opportunity_id INTEGER,
        job_id INTEGER,
        actor_user_id INTEGER,
        call_id INTEGER,
        event_type VARCHAR(64) NOT NULL,
        from_state VARCHAR(32),
        to_state VARCHAR(32),
        idempotency_key VARCHAR(160),
        details JSONB NOT NULL DEFAULT '{}'::jsonb,
        occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_candidate_contact_events_candidate_id "
    "ON candidate_contact_events (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_contact_events_case_occurred "
    "ON candidate_contact_events (case_id, occurred_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_contact_events_idempotency "
    "ON candidate_contact_events (idempotency_key) "
    "WHERE idempotency_key IS NOT NULL",
    """CREATE OR REPLACE FUNCTION reject_candidate_contact_event_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RAISE EXCEPTION
            'candidate_contact_events is append-only; append a correction event'
            USING ERRCODE = '55000';
    END;
    $$""",
    "DROP TRIGGER IF EXISTS trg_candidate_contact_events_immutable "
    "ON candidate_contact_events",
    """CREATE TRIGGER trg_candidate_contact_events_immutable
    BEFORE UPDATE OR DELETE ON candidate_contact_events
    FOR EACH ROW EXECUTE FUNCTION reject_candidate_contact_event_mutation()""",
    """CREATE TABLE IF NOT EXISTS candidate_contact_traffit_cursors (
        stream VARCHAR(64) PRIMARY KEY,
        cursor_created_at TIMESTAMPTZ,
        cursor_external_id VARCHAR(255),
        last_attempt_at TIMESTAMPTZ,
        last_success_at TIMESTAMPTZ,
        status VARCHAR(32),
        last_error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS candidate_contact_traffit_ledger (
        id BIGSERIAL PRIMARY KEY,
        external_event_id VARCHAR(255) NOT NULL,
        source_created_at TIMESTAMPTZ NOT NULL,
        candidate_external_id VARCHAR(255),
        job_external_id VARCHAR(255),
        candidate_id INTEGER REFERENCES candidates(id) ON DELETE SET NULL,
        job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
        case_id INTEGER
            REFERENCES candidate_contact_cases(id) ON DELETE SET NULL,
        opportunity_id INTEGER
            REFERENCES candidate_contact_opportunities(id) ON DELETE SET NULL,
        status VARCHAR(32) NOT NULL,
        payload_hash VARCHAR(64) NOT NULL,
        raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_attempt_at TIMESTAMPTZ,
        error TEXT,
        processed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_candidate_contact_traffit_ledger_external_event
            UNIQUE (external_event_id),
        CONSTRAINT ck_candidate_contact_traffit_ledger_status
            CHECK (status IN ('processed', 'exception')),
        CONSTRAINT ck_candidate_contact_traffit_ledger_attempts
            CHECK (attempts >= 0)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_candidate_contact_traffit_ledger_candidate_id "
    "ON candidate_contact_traffit_ledger (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_contact_traffit_ledger_job_id "
    "ON candidate_contact_traffit_ledger (job_id)",
    "CREATE INDEX IF NOT EXISTS ix_match_index_outbox_pending ON match_index_outbox (status, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_match_index_outbox_entity ON match_index_outbox (entity_type, entity_id)",
    "CREATE INDEX IF NOT EXISTS ix_match_index_outbox_status ON match_index_outbox (status)",
    # candidate_job_match_scores.scoring_algorithm_version (migration 0170) —
    # versioned score cache. A row whose version != the running
    # scoring_service.SCORING_ALGORITHM_VERSION is a cache miss, so flipping
    # AI_SCORING_CONTRACT_V2 auto-invalidates. Backfill to 'score-v1-legacy'
    # (== the flag-off version) so nothing recomputes on deploy. Without the
    # column the recommendations read 500s (UndefinedColumn) under multi-head.
    "ALTER TABLE candidate_job_match_scores ADD COLUMN IF NOT EXISTS scoring_algorithm_version VARCHAR(64) NOT NULL DEFAULT 'score-v1-legacy'",
    # Widen 32→64: the version now folds in the embedding model name (AI-P0-06,
    # migration 0185). At 32 every cache INSERT failed silently (value too long)
    # → the match-score cache stopped persisting. Idempotent — no-op once wide.
    "ALTER TABLE candidate_job_match_scores ALTER COLUMN scoring_algorithm_version TYPE VARCHAR(64)",
    # candidate_job_match_scores.invalidated_at (migration 0189_match_score_cache_cas,
    # audyt P1-MATCH-02) — compare-and-swap fence so a score compute that started
    # before a mark_stale_* cannot resurrect stale=False on write-back. NULL =
    # never invalidated since last fresh compute. Without the column the write-back
    # 500s (UndefinedColumn) under multi-head. Nullable, idempotent.
    "ALTER TABLE candidate_job_match_scores ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ NULL",
    # match_score_invalidations (migration 0194_match_score_invalidations, audyt F-28)
    # — persistent invalidation ledger. The invalidated_at column above only fences
    # the CONFLICT (row-exists) write-back; the MISS path has no row to stamp, so
    # mark_stale_* UPSERTs a watermark here and the miss-path INSERT reads it to
    # decide stale. Without the table mark_stale_*/write-back 500s (UndefinedTable)
    # under prod's chronic alembic multi-head drift. Idempotent.
    """CREATE TABLE IF NOT EXISTS match_score_invalidations (
        entity_type VARCHAR(16) NOT NULL,
        entity_id INTEGER NOT NULL,
        last_invalidated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_match_score_invalidations PRIMARY KEY (entity_type, entity_id)
    )""",
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
    # contract_alerts atomic dedup (migration 0186_contract_alert_dedup) —
    # contract_alerts_loop claimuje (kategoria, próg, encja) przez INSERT ...
    # ON CONFLICT DO NOTHING, więc nakładające się / równoległe przebiegi pętli
    # nie duplikują notyfikacji. Tabela musi istnieć zanim loop wystartuje,
    # inaczej claim 500s pod chronicznym multi-head driftem alembica na prod.
    """CREATE TABLE IF NOT EXISTS contract_alert_dedup (
        id SERIAL PRIMARY KEY,
        dedup_key VARCHAR(128) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_contract_alert_dedup_key UNIQUE (dedup_key)
    )""",
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
    # calls.candidate_id NULL — unassigned inbound CloudTalk calls (F-12,
    # migracja 0192). Ambiguous inbound (dwóch+ kandydatów o tych samych
    # ostatnich 9 cyfrach telefonu) NIE jest przypisywany na ślepo do
    # najnowszego kandydata — wiersz Call powstaje z candidate_id NULL do
    # ręcznej atrybucji. Bez tego INSERT unassigned-a padnie na NOT NULL.
    # DROP NOT NULL jest idempotentny (no-op gdy kolumna już nullable).
    "ALTER TABLE calls ALTER COLUMN candidate_id DROP NOT NULL",
    # Atomic dedup dla notatek Fireflies (migracja 0186). services/fireflies_sync.py
    # robił nieatomowy SELECT-then-INSERT po nie-unikalnym source_ref
    # ('fireflies:<id>') → dwa równoległe syncy wstawiały duplikaty. Kod używa
    # teraz INSERT ... ON CONFLICT DO NOTHING, który potrzebuje unikalnego indeksu
    # arbitra. Indeks jest CZĘŚCIOWY (tylko fireflies:) więc NIE dotyka Traffita
    # ('traffit:activity:<id>') ani NULL-owych source_ref. Dedup MUSI iść przed
    # CREATE (inaczej padnie na istniejących duplikatach); note_mentions.note_id
    # to ON DELETE CASCADE, więc kasowanie duplikatu sprząta ewentualne dzieci.
    """DELETE FROM notes a
        USING notes b
        WHERE a.source_ref LIKE 'fireflies:%'
          AND b.source_ref = a.source_ref
          AND b.id < a.id""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_notes_source_ref_fireflies "
    "ON notes (source_ref) WHERE source_ref LIKE 'fireflies:%'",
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
    "ALTER TABLE user_competence_categories ADD COLUMN IF NOT EXISTS "
    "priority SMALLINT DEFAULT 2",
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
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'candidatedocumentkind'
        ) THEN
            CREATE TYPE candidatedocumentkind AS ENUM (
                'cv', 'cover_letter', 'certificate', 'other'
            );
        END IF;
    END $$""",
    "ALTER TABLE candidate_documents ADD COLUMN IF NOT EXISTS document_kind candidatedocumentkind NOT NULL DEFAULT 'other'",
    'CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_documents_candidate_sha ON candidate_documents (candidate_id, content_sha256) WHERE content_sha256 IS NOT NULL AND source_deleted_at IS NULL',
    'CREATE INDEX IF NOT EXISTS ix_candidate_documents_manifest ON candidate_documents (candidate_id, source_manifest_fingerprint)',
    # 0207: durable, PII-minimized identity quarantine for candidate sources.
    """CREATE TABLE IF NOT EXISTS candidate_source_identity_reviews (
        id                  SERIAL PRIMARY KEY,
        candidate_id        INTEGER NOT NULL
                                REFERENCES candidates(id) ON DELETE CASCADE,
        source_kind         VARCHAR(24) NOT NULL,
        source_id           BIGINT NOT NULL,
        decision            VARCHAR(32) NOT NULL,
        provenance          VARCHAR(80) NOT NULL,
        detector_version    VARCHAR(64) NOT NULL,
        evidence            JSONB NOT NULL DEFAULT '{}'::jsonb,
        reviewed_by_id      INTEGER NULL
                                REFERENCES users(id) ON DELETE SET NULL,
        reviewed_at         TIMESTAMPTZ NOT NULL,
        override_reason     TEXT NULL,
        override_by_id      INTEGER NULL
                                REFERENCES users(id) ON DELETE SET NULL,
        override_at         TIMESTAMPTZ NULL,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_candidate_source_identity_review
            UNIQUE (candidate_id, source_kind, source_id),
        CONSTRAINT ck_candidate_source_identity_review_kind
            CHECK (
                source_kind IN (
                    'note', 'document', 'legacy_cv', 'talent_radar_cv'
                )
            ),
        CONSTRAINT ck_candidate_source_identity_review_decision
            CHECK (
                decision IN (
                    'confirmed_match', 'confirmed_mismatch', 'inconclusive'
                )
            ),
        CONSTRAINT ck_candidate_source_identity_review_override
            CHECK (
                (
                    override_at IS NULL
                    AND override_by_id IS NULL
                    AND override_reason IS NULL
                )
                OR
                (
                    override_at IS NOT NULL
                    AND override_by_id IS NOT NULL
                    AND override_reason IS NOT NULL
                    AND length(btrim(override_reason)) >= 3
                )
            )
    )""",
    'CREATE INDEX IF NOT EXISTS ix_candidate_source_identity_reviews_candidate ON candidate_source_identity_reviews (candidate_id)',
    "CREATE INDEX IF NOT EXISTS ix_candidate_source_identity_reviews_quarantine ON candidate_source_identity_reviews (candidate_id, source_kind, source_id) WHERE decision = 'confirmed_mismatch' AND override_at IS NULL",
    'ALTER TABLE rejection_reasons ADD COLUMN IF NOT EXISTS external_source VARCHAR(50)',
    'ALTER TABLE rejection_reasons ADD COLUMN IF NOT EXISTS external_id VARCHAR(100)',
    'CREATE INDEX IF NOT EXISTS ix_rejection_reasons_external_source ON rejection_reasons (external_source)',
    'CREATE INDEX IF NOT EXISTS ix_rejection_reasons_external_id ON rejection_reasons (external_id)',
    'CREATE UNIQUE INDEX IF NOT EXISTS ux_rejection_reasons_external_source_id ON rejection_reasons (external_source, external_id) WHERE external_id IS NOT NULL',
    # 0197: bez tej kolumny każdy SELECT z rejection_reasons po dodaniu pola do
    # ORM leci UndefinedColumn — a to ścieżka KAŻDEGO terminalnego ruchu w pipeline.
    'ALTER TABLE rejection_reasons ADD COLUMN IF NOT EXISTS disqualifies_person BOOLEAN NOT NULL DEFAULT false',
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
            -- Odrzucone/oczekujące weryfikacje NIE liczą się jako kamień
            -- milowy ani nie kotwiczą kredytu (M7-P0.8). Liczy się tylko
            -- zaakceptowana ('active') weryfikacja. Pozostałe stage'y mają
            -- default verification_status='active', więc filtr ich nie dotyka.
            AND (cs.stage <> 'verified' OR cs.verification_status = 'active')
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
    # 0177 (M4 PR-05): wersjonowane workflow — shadow tabele (runtime nic z
    # nich nie czyta do PR-06/07). Wszystko idempotentne.
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'workflowrevisionstatus'
        ) THEN
            CREATE TYPE workflowrevisionstatus AS ENUM (
                'draft', 'published', 'archived'
            );
        END IF;
    END $$""",
    """CREATE TABLE IF NOT EXISTS workflow_definitions (
        id SERIAL PRIMARY KEY,
        template_id INTEGER NULL UNIQUE
            REFERENCES pipeline_templates(id) ON DELETE SET NULL,
        name VARCHAR(100) NOT NULL,
        description TEXT NULL,
        client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
        archived BOOLEAN NOT NULL DEFAULT FALSE,
        created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_workflow_defs_client "
    "ON workflow_definitions (client_id)",
    """CREATE TABLE IF NOT EXISTS workflow_revisions (
        id SERIAL PRIMARY KEY,
        workflow_id INTEGER NOT NULL
            REFERENCES workflow_definitions(id) ON DELETE CASCADE,
        revision_no INTEGER NOT NULL,
        status workflowrevisionstatus NOT NULL DEFAULT 'draft',
        source VARCHAR(50) NULL,
        registry_version VARCHAR(30) NULL,
        published_at TIMESTAMPTZ NULL,
        published_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_workflow_rev_no UNIQUE (workflow_id, revision_no)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_workflow_revs_workflow "
    "ON workflow_revisions (workflow_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_workflow_one_published "
    "ON workflow_revisions (workflow_id) WHERE status = 'published'",
    """CREATE TABLE IF NOT EXISTS stage_revisions (
        id SERIAL PRIMARY KEY,
        workflow_revision_id INTEGER NOT NULL
            REFERENCES workflow_revisions(id) ON DELETE CASCADE,
        source_stage_def_id INTEGER NULL
            REFERENCES pipeline_stage_defs(id) ON DELETE SET NULL,
        name VARCHAR(100) NOT NULL,
        "order" INTEGER NOT NULL,
        category VARCHAR(20) NOT NULL,
        semantic_key VARCHAR(50) NOT NULL,
        is_terminal BOOLEAN NOT NULL DEFAULT FALSE,
        terminal_type VARCHAR(20) NULL,
        tracker_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        tracker_public_name VARCHAR(100) NULL,
        sla_max_days INTEGER NULL,
        scorecard_schema JSONB NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_stage_rev_order UNIQUE (workflow_revision_id, "order"),
        CONSTRAINT uq_stage_rev_name UNIQUE (workflow_revision_id, name)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_stage_revs_revision "
    "ON stage_revisions (workflow_revision_id)",
    "CREATE INDEX IF NOT EXISTS ix_stage_revs_semantic "
    "ON stage_revisions (semantic_key)",
    "CREATE INDEX IF NOT EXISTS ix_stage_revs_source "
    "ON stage_revisions (source_stage_def_id)",
    """CREATE TABLE IF NOT EXISTS workflow_edges (
        id SERIAL PRIMARY KEY,
        workflow_revision_id INTEGER NOT NULL
            REFERENCES workflow_revisions(id) ON DELETE CASCADE,
        from_stage_revision_id INTEGER NULL
            REFERENCES stage_revisions(id) ON DELETE CASCADE,
        to_stage_revision_id INTEGER NOT NULL
            REFERENCES stage_revisions(id) ON DELETE CASCADE,
        CONSTRAINT uq_workflow_edge UNIQUE (
            workflow_revision_id, from_stage_revision_id, to_stage_revision_id
        )
    )""",
    "CREATE INDEX IF NOT EXISTS ix_workflow_edges_revision "
    "ON workflow_edges (workflow_revision_id)",
    # 0178 (M4 PR-06): RecruitmentProcess — kanoniczny agregat w shadow mode.
    # Partial unique = jeden otwarty proces pary; unique attempt. Idempotentne.
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'processstatus'
        ) THEN
            CREATE TYPE processstatus AS ENUM ('open', 'closed', 'voided');
        END IF;
    END $$""",
    """CREATE TABLE IF NOT EXISTS recruitment_processes (
        id SERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL
            REFERENCES candidates(id) ON DELETE CASCADE,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
        attempt_no INTEGER NOT NULL DEFAULT 1,
        previous_process_id INTEGER NULL
            REFERENCES recruitment_processes(id) ON DELETE SET NULL,
        workflow_revision_id INTEGER NULL
            REFERENCES workflow_revisions(id) ON DELETE SET NULL,
        current_stage_revision_id INTEGER NULL
            REFERENCES stage_revisions(id) ON DELETE SET NULL,
        current_semantic_state VARCHAR(50) NULL,
        legacy_current_candidate_stage_id INTEGER NULL
            REFERENCES candidate_stages(id) ON DELETE SET NULL,
        state_version INTEGER NOT NULL DEFAULT 1,
        status processstatus NOT NULL DEFAULT 'open',
        owner_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        source_authority VARCHAR(30) NOT NULL DEFAULT 'backfill',
        opened_at TIMESTAMPTZ NULL,
        closed_at TIMESTAMPTZ NULL,
        voided_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_process_attempt UNIQUE (candidate_id, job_id, attempt_no)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_processes_candidate "
    "ON recruitment_processes (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_processes_job "
    "ON recruitment_processes (job_id)",
    "CREATE INDEX IF NOT EXISTS ix_processes_client "
    "ON recruitment_processes (client_id)",
    "CREATE INDEX IF NOT EXISTS ix_processes_status "
    "ON recruitment_processes (status)",
    "CREATE INDEX IF NOT EXISTS ix_processes_semantic "
    "ON recruitment_processes (current_semantic_state)",
    "CREATE INDEX IF NOT EXISTS ix_processes_job_status "
    "ON recruitment_processes (job_id, status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_process_one_open "
    "ON recruitment_processes (candidate_id, job_id) WHERE status = 'open'",
    # application_submissions (migration 0189, P0-CAND-01) — parks public
    # /apply/{token} submissions that matched an existing candidate, instead of
    # OVERWRITING that candidate. Table must exist before submit_public_apply's
    # INSERT runs or a duplicate-email apply 500s under prod's chronic alembic
    # multi-head drift. DDL 1:1 with 0189.
    """CREATE TABLE IF NOT EXISTS application_submissions (
        id SERIAL PRIMARY KEY,
        invite_link_token_sha256 VARCHAR(64),
        job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending_review',
        submitted_first_name VARCHAR(100) NOT NULL,
        submitted_last_name VARCHAR(100) NOT NULL,
        submitted_email VARCHAR(255) NOT NULL,
        submitted_phone VARCHAR(30),
        submitted_linkedin VARCHAR(500),
        submitted_message TEXT,
        matched_candidate_id INTEGER REFERENCES candidates(id) ON DELETE SET NULL,
        cv_object_key VARCHAR(500),
        cv_filename VARCHAR(500),
        cv_content_type VARCHAR(100),
        cv_size_bytes INTEGER,
        cv_file_content BYTEA,
        raw_cv_text TEXT,
        raw_payload JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        reviewed_at TIMESTAMPTZ,
        CONSTRAINT ck_application_submissions_status CHECK (
            status IN ('pending_review','linked','merged','created','rejected')
        )
    )""",
    "CREATE INDEX IF NOT EXISTS ix_application_submissions_status "
    "ON application_submissions (status)",
    "CREATE INDEX IF NOT EXISTS ix_application_submissions_matched_candidate_id "
    "ON application_submissions (matched_candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_application_submissions_link "
    "ON application_submissions (invite_link_token_sha256)",
    "CREATE INDEX IF NOT EXISTS ix_application_submissions_submitted_email "
    "ON application_submissions (submitted_email)",
    "CREATE INDEX IF NOT EXISTS ix_application_submissions_job_id "
    "ON application_submissions (job_id)",
    # Contract lifecycle invariant (migracja 0190_contract_lifecycle_invariant):
    # void metadata na contracts. Ustawiane przez POST /api/contracts/{id}/void
    # (soft-delete). Bez kolumn UPDATE/INSERT contracts z voided_* => UndefinedColumn.
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS voided_at TIMESTAMPTZ NULL",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS voided_by INTEGER NULL",
    # F-01: idempotent guarded ADD instead of DROP+ADD on every boot. The old
    # DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT recreated the FK on every
    # restart (Coolify rebuilds each push) — pointless churn, plus a window
    # where the FK is briefly absent under concurrent writes. Add only if
    # missing; identical semantics (voided_by → users(id) ON DELETE SET NULL).
    """DO $$ BEGIN
        ALTER TABLE contracts ADD CONSTRAINT fk_contracts_voided_by
            FOREIGN KEY (voided_by) REFERENCES users(id) ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # Session-revocation floor (migracja 0192_user_tokens_valid_after, F-05):
    # po zmianie/resecie hasła backend ustawia tokens_valid_after=now() i odrzuca
    # (401) tokeny z wcześniejszym iat. Bez tej kolumny UPDATE users z
    # tokens_valid_after => UndefinedColumn i każda zmiana hasła zwraca 500.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS tokens_valid_after TIMESTAMPTZ",
    # Chat email fallback reservation (migracja
    # 0198_notification_email_send_started_at): background task rezerwuje
    # wiersz TUTAJ przed wysyłką SMTP, a `email_sent_at` stempluje dopiero po
    # potwierdzonej wysyłce. Bez tej kolumny UPDATE notifications z
    # email_send_started_at => UndefinedColumn i cała pętla fallbacku pada
    # w każdej iteracji (zero maili do offline'owych userów).
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS "
    "email_send_started_at TIMESTAMPTZ NULL",
    # Tryb obróbki treści CV (migracja 0202_cv_content_mode). Pipeline zapisuje
    # content_mode przy KAŻDEJ generacji, więc bez tej kolumny INSERT do
    # cv_generated_documents => UndefinedColumn i generator CV pada w całości.
    # DEFAULT 'tailored' jest prawdziwościowym backfillem historii — wiersze
    # sprzed tej funkcji powstały z pełnym pozycjonowaniem pod ofertę klienta.
    "ALTER TABLE cv_generated_documents ADD COLUMN IF NOT EXISTS "
    "content_mode VARCHAR(16) NOT NULL DEFAULT 'tailored'",
    # Sufit trybu per klient (NULL = bez ograniczenia). Czytany przy każdej
    # generacji z profilu kandydata; bez kolumny SELECT clients => UndefinedColumn.
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS cv_content_mode_cap VARCHAR(16)",
    # CHECK-i z migracji 0202. Na prodzie alembic jest osierocony, więc to
    # entrypoint JEST realną ścieżką tworzenia schematu — bez tych dwóch
    # ograniczeń baza przyjęłaby dowolny łańcuch jako tryb (np. z ręcznego
    # UPDATE ustawiającego sufit), a wtedy `apply_content_mode_cap` cicho
    # zdegradowałoby żądanie do domyślnego zamiast wymusić zamierzony sufit.
    """DO $$ BEGIN
        ALTER TABLE cv_generated_documents
            ADD CONSTRAINT ck_cv_generated_documents_content_mode
            CHECK (content_mode IN ('basic', 'polished', 'tailored'));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE clients
            ADD CONSTRAINT ck_clients_cv_content_mode_cap
            CHECK (cv_content_mode_cap IS NULL
                   OR cv_content_mode_cap IN ('basic', 'polished', 'tailored'));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # 0217: interaktywne CV. Mapa „wymaganie → dowody" zapisywana po generacji
    # (mode="new"); bez kolumn UPDATE cv_generated_documents => UndefinedColumn
    # i generacja mapy pada przy każdym CV.
    "ALTER TABLE cv_generated_documents ADD COLUMN IF NOT EXISTS "
    "requirement_map JSONB",
    "ALTER TABLE cv_generated_documents ADD COLUMN IF NOT EXISTS "
    "requirement_map_input_hash VARCHAR(64)",
    "ALTER TABLE cv_generated_documents ADD COLUMN IF NOT EXISTS "
    "requirement_map_model VARCHAR(64)",
    "ALTER TABLE cv_generated_documents ADD COLUMN IF NOT EXISTS "
    "requirement_map_generated_at TIMESTAMPTZ",
    # 0217: per-klientowy włącznik wersji interaktywnej na publicznym linku.
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS "
    "cv_interactive_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    # 0217: tokeny publicznych linków do WYGENEROWANYCH CV (Generator B2B).
    # Wyłącznie token v2 (hash-at-rest): PK = revoke-key v2$<hex>, sekret tylko
    # jako SHA-256. Bez tej tabeli POST /generated/{id}/share-token => 500.
    """CREATE TABLE IF NOT EXISTS cv_generated_share_tokens (
        token VARCHAR(64) PRIMARY KEY,
        token_sha256 VARCHAR(64) NOT NULL,
        generated_document_id INTEGER NOT NULL
            REFERENCES cv_generated_documents(id) ON DELETE CASCADE,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ,
        revoked BOOLEAN NOT NULL DEFAULT FALSE,
        revoked_at TIMESTAMPTZ,
        revoked_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        revoke_reason VARCHAR(255),
        max_views INTEGER,
        view_count INTEGER NOT NULL DEFAULT 0,
        last_viewed_at TIMESTAMPTZ
    )""",
    "CREATE INDEX IF NOT EXISTS ix_cv_generated_share_tokens_token_sha256 "
    "ON cv_generated_share_tokens (token_sha256)",
    "CREATE INDEX IF NOT EXISTS ix_cv_generated_share_tokens_generated_document_id "
    "ON cv_generated_share_tokens (generated_document_id)",
    # 0217: chat hiring managera na publicznym linku (dzienny limit + log pytań).
    """CREATE TABLE IF NOT EXISTS cv_share_chat_messages (
        id BIGSERIAL PRIMARY KEY,
        share_token VARCHAR(64) NOT NULL
            REFERENCES cv_generated_share_tokens(token) ON DELETE CASCADE,
        role VARCHAR(12) NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_cv_share_chat_token_created "
    "ON cv_share_chat_messages (share_token, created_at)",
    # 0206: typed candidate profile facts. Existing candidate rows need OCC
    # counters even when orphaned Alembic skipped the migration; create_all
    # cannot add columns to an existing table.
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS "
    "languages_version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS "
    "profile_rate_version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS "
    "profile_rate_updated_at TIMESTAMPTZ NULL",
    """CREATE TABLE IF NOT EXISTS candidate_languages (
        id SERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        language_code VARCHAR(16) NOT NULL,
        language_name VARCHAR(100) NOT NULL,
        cefr_level VARCHAR(2) NULL,
        is_native BOOLEAN NOT NULL DEFAULT FALSE,
        is_level_unknown BOOLEAN NOT NULL DEFAULT TRUE,
        provenance VARCHAR(32) NOT NULL DEFAULT 'unknown',
        manual_lock BOOLEAN NOT NULL DEFAULT FALSE,
        source_ref VARCHAR(255) NULL,
        version INTEGER NOT NULL DEFAULT 1,
        deleted_at TIMESTAMPTZ NULL,
        created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_candidate_languages_candidate_code
            UNIQUE (candidate_id, language_code),
        CONSTRAINT ck_candidate_languages_code
            CHECK (language_code ~ '^[a-z][a-z0-9-]{1,15}$'),
        CONSTRAINT ck_candidate_languages_cefr
            CHECK (cefr_level IS NULL
                   OR cefr_level IN ('A1', 'A2', 'B1', 'B2', 'C1', 'C2')),
        CONSTRAINT ck_candidate_languages_proficiency_state CHECK (
            (is_native IS TRUE AND is_level_unknown IS FALSE AND cefr_level IS NULL)
            OR
            (is_native IS FALSE AND is_level_unknown IS TRUE AND cefr_level IS NULL)
            OR
            (is_native IS FALSE AND is_level_unknown IS FALSE AND cefr_level IS NOT NULL)
        ),
        CONSTRAINT ck_candidate_languages_provenance CHECK (
            provenance IN (
                'manual', 'cv', 'traffit', 'talent_radar',
                'csv', 'legacy', 'unknown'
            )
        ),
        CONSTRAINT ck_candidate_languages_version_positive CHECK (version > 0)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_candidate_languages_candidate_id "
    "ON candidate_languages (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_languages_candidate_active "
    "ON candidate_languages (candidate_id, language_code) "
    "WHERE deleted_at IS NULL",
    # 0208: the monthly candidate-rate columns stay physically present, but
    # no new row may silently repopulate the deprecated currency. The saved
    # search flag is schema-only here; data rewriting remains in Alembic and
    # the runtime scanner fails closed if that migration was skipped.
    "ALTER TABLE candidates ALTER COLUMN salary_currency DROP DEFAULT",
    "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS "
    "requires_reapproval BOOLEAN NOT NULL DEFAULT FALSE",
    # 0204 + 0207: scope-aware, no-finance activity-summary cache.  The
    # nullable output fields also represent a short committed generation lease.
    # mirrora tutaj (precedens: cortex_skill_facts, incident 2026-07-12),
    # inaczej /api/candidates/{id}/activity-summary 500-tkuje przy
    # orphaned/multi-head alembicu mimo zielonego deployu.
    """CREATE TABLE IF NOT EXISTS candidate_activity_summaries (
        id SERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        summary TEXT NULL,
        model VARCHAR(64) NULL,
        input_hash VARCHAR(64) NOT NULL,
        source_version VARCHAR(64) NULL,
        visibility_scope_hash VARCHAR(64) NOT NULL DEFAULT 'legacy-unscoped',
        content_policy_version VARCHAR(64) NOT NULL DEFAULT 'legacy-unscoped',
        source_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
        generated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        generated_at TIMESTAMPTZ NULL,
        generation_lease_token VARCHAR(36) NULL,
        generation_lease_expires_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_candidate_activity_summary_scope_policy
            UNIQUE (
                candidate_id,
                visibility_scope_hash,
                content_policy_version
            ),
        CONSTRAINT ck_candidate_activity_summary_lease_pair CHECK (
            (generation_lease_token IS NULL
             AND generation_lease_expires_at IS NULL)
            OR
            (generation_lease_token IS NOT NULL
             AND generation_lease_expires_at IS NOT NULL)
        )
    )""",
    """ALTER TABLE candidate_activity_summaries
        ALTER COLUMN summary DROP NOT NULL,
        ALTER COLUMN generated_at DROP NOT NULL,
        ADD COLUMN IF NOT EXISTS source_version VARCHAR(64) NULL,
        ADD COLUMN IF NOT EXISTS visibility_scope_hash VARCHAR(64)
            NOT NULL DEFAULT 'legacy-unscoped',
        ADD COLUMN IF NOT EXISTS content_policy_version VARCHAR(64)
            NOT NULL DEFAULT 'legacy-unscoped',
        ADD COLUMN IF NOT EXISTS source_manifest JSONB
            NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN IF NOT EXISTS generation_lease_token VARCHAR(36) NULL,
        ADD COLUMN IF NOT EXISTS generation_lease_expires_at TIMESTAMPTZ NULL""",
    """DO $$ BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_candidate_activity_summary'
              AND conrelid = 'candidate_activity_summaries'::regclass
        ) THEN
            ALTER TABLE candidate_activity_summaries
                DROP CONSTRAINT uq_candidate_activity_summary;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_candidate_activity_summary_scope_policy'
              AND conrelid = 'candidate_activity_summaries'::regclass
        ) THEN
            ALTER TABLE candidate_activity_summaries
                ADD CONSTRAINT uq_candidate_activity_summary_scope_policy
                UNIQUE (
                    candidate_id,
                    visibility_scope_hash,
                    content_policy_version
                );
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_candidate_activity_summary_lease_pair'
              AND conrelid = 'candidate_activity_summaries'::regclass
        ) THEN
            ALTER TABLE candidate_activity_summaries
                ADD CONSTRAINT ck_candidate_activity_summary_lease_pair
                CHECK (
                    (generation_lease_token IS NULL
                     AND generation_lease_expires_at IS NULL)
                    OR
                    (generation_lease_token IS NOT NULL
                     AND generation_lease_expires_at IS NOT NULL)
                );
        END IF;
    END $$""",
    "CREATE INDEX IF NOT EXISTS ix_candidate_activity_summaries_candidate_id "
    "ON candidate_activity_summaries (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_activity_summaries_input_hash "
    "ON candidate_activity_summaries (input_hash)",
    # 0205: katalog klientów jest addytywny i niezależny od legacy
    # clients.status / integracji Traffit. Soft-merge zachowuje rekord źródłowy
    # i jego historię; ten blok jest wyłącznie DDL i nie mutuje danych klienta.
    """ALTER TABLE clients
       ADD COLUMN IF NOT EXISTS merged_into_client_id INTEGER NULL,
       ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NULL,
       ADD COLUMN IF NOT EXISTS archived_by INTEGER NULL""",
    """DO $$ BEGIN
        ALTER TABLE clients
            ADD CONSTRAINT fk_clients_merged_into_client_id
            FOREIGN KEY (merged_into_client_id) REFERENCES clients(id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE clients
            ADD CONSTRAINT fk_clients_archived_by
            FOREIGN KEY (archived_by) REFERENCES users(id) ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE clients
            ADD CONSTRAINT ck_clients_not_merged_into_self
            CHECK (
                merged_into_client_id IS NULL OR merged_into_client_id <> id
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "CREATE INDEX IF NOT EXISTS ix_clients_merged_into_client_id "
    "ON clients (merged_into_client_id)",
    "CREATE INDEX IF NOT EXISTS ix_clients_archived_at ON clients (archived_at)",
    "CREATE INDEX IF NOT EXISTS ix_clients_archived_by ON clients (archived_by)",
    # Audyt importu istnieje przed FK z MSA. Hash pliku daje retry-safe
    # identyfikację runu, a rolled_back zostawia czytelny ślad odwrócenia.
    """CREATE TABLE IF NOT EXISTS client_import_runs (
        id SERIAL PRIMARY KEY,
        source_system VARCHAR(32) NOT NULL DEFAULT 'client_excel',
        source_filename VARCHAR(255) NOT NULL,
        source_sha256 VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
        summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        error_message TEXT NULL,
        created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        approved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        approved_at TIMESTAMPTZ NULL,
        applied_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_client_import_runs_status CHECK (
            status IN (
                'uploaded', 'reviewed', 'applying', 'applied',
                'rolled_back', 'failed'
            )
        ),
        CONSTRAINT ck_client_import_runs_source_system_nonempty
            CHECK (char_length(btrim(source_system)) > 0),
        CONSTRAINT ck_client_import_runs_source_sha256
            CHECK (char_length(source_sha256) = 64)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_client_import_runs_status "
    "ON client_import_runs (status)",
    "ALTER TABLE client_import_runs "
    "DROP CONSTRAINT IF EXISTS uq_client_import_runs_source_sha256",
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    "ux_client_import_runs_applied_source_sha256 "
    "ON client_import_runs (source_system, source_sha256) "
    "WHERE status = 'applied'",
    # MSA jest źródłem Start/Koniec umowy. source_system/source_key zapewniają
    # idempotentne ponowienie zatwierdzonego wiersza importu.
    """ALTER TABLE client_framework_contracts
       ADD COLUMN IF NOT EXISTS source_system VARCHAR(32)
           NOT NULL DEFAULT 'manual',
       ADD COLUMN IF NOT EXISTS source_key VARCHAR(255) NULL,
       ADD COLUMN IF NOT EXISTS import_run_id INTEGER NULL""",
    """DO $$ BEGIN
        ALTER TABLE client_framework_contracts
            ADD CONSTRAINT fk_client_framework_contracts_import_run_id
            FOREIGN KEY (import_run_id) REFERENCES client_import_runs(id)
            ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE client_framework_contracts
            ADD CONSTRAINT ck_client_framework_contracts_dates
            CHECK (
                effective_date IS NULL OR expiry_date IS NULL
                OR expiry_date >= effective_date
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE client_framework_contracts
            ADD CONSTRAINT ck_client_framework_contracts_source_system_nonempty
            CHECK (char_length(btrim(source_system)) > 0) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE client_framework_contracts
            ADD CONSTRAINT ck_client_framework_contracts_source_key_nonempty
            CHECK (
                source_key IS NULL OR char_length(btrim(source_key)) > 0
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "CREATE INDEX IF NOT EXISTS ix_client_framework_contracts_import_run_id "
    "ON client_framework_contracts (import_run_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    "ux_client_framework_contracts_source_key "
    "ON client_framework_contracts (source_system, source_key) "
    "WHERE source_key IS NOT NULL",
    """CREATE TABLE IF NOT EXISTS client_portfolio_scopes (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        framework_contract_id INTEGER NULL
            REFERENCES client_framework_contracts(id) ON DELETE SET NULL,
        category clientportfoliocategory NOT NULL DEFAULT 'inactive',
        label VARCHAR(255) NULL,
        source_system VARCHAR(32) NOT NULL DEFAULT 'manual',
        source_key VARCHAR(255) NULL,
        archived_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_client_portfolio_scopes_label_nonempty
            CHECK (label IS NULL OR char_length(btrim(label)) > 0),
        CONSTRAINT ck_client_portfolio_scopes_source_system_nonempty
            CHECK (char_length(btrim(source_system)) > 0),
        CONSTRAINT ck_client_portfolio_scopes_source_key_nonempty
            CHECK (source_key IS NULL OR char_length(btrim(source_key)) > 0)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_client_portfolio_scopes_client_id "
    "ON client_portfolio_scopes (client_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    "ux_client_portfolio_scopes_framework_contract_active "
    "ON client_portfolio_scopes (framework_contract_id) "
    "WHERE framework_contract_id IS NOT NULL AND archived_at IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    "ux_client_portfolio_scopes_source_key_active "
    "ON client_portfolio_scopes (source_system, source_key) "
    "WHERE source_key IS NOT NULL AND archived_at IS NULL",
    "CREATE INDEX IF NOT EXISTS "
    "ix_client_portfolio_scopes_category_label_active "
    "ON client_portfolio_scopes (category, label) WHERE archived_at IS NULL",
    """CREATE TABLE IF NOT EXISTS client_aliases (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        alias VARCHAR(255) NOT NULL,
        normalized_alias VARCHAR(255) NOT NULL,
        source_system VARCHAR(32) NOT NULL DEFAULT 'manual',
        source_key VARCHAR(255) NULL,
        import_run_id INTEGER NULL,
        archived_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_client_aliases_client_normalized
            UNIQUE (client_id, normalized_alias),
        CONSTRAINT ck_client_aliases_alias_nonempty
            CHECK (char_length(btrim(alias)) > 0),
        CONSTRAINT ck_client_aliases_normalized_nonempty
            CHECK (char_length(btrim(normalized_alias)) > 0),
        CONSTRAINT ck_client_aliases_source_system_nonempty
            CHECK (char_length(btrim(source_system)) > 0),
        CONSTRAINT ck_client_aliases_source_key_nonempty
            CHECK (source_key IS NULL OR char_length(btrim(source_key)) > 0)
    )""",
    # 0209: aliasy utworzone przez import są podczas rollbacku archiwizowane,
    # nie usuwane. Pochodzenie runu pozwala odtworzyć/re-aktywować ten sam
    # rekord bez łamania unikalności aliasu lub source_key.
    """ALTER TABLE client_aliases
       ADD COLUMN IF NOT EXISTS import_run_id INTEGER NULL,
       ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NULL""",
    """DO $$ BEGIN
        ALTER TABLE client_aliases
            ADD CONSTRAINT fk_client_aliases_import_run_id
            FOREIGN KEY (import_run_id) REFERENCES client_import_runs(id)
            ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "CREATE INDEX IF NOT EXISTS ix_client_aliases_client_id "
    "ON client_aliases (client_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_aliases_normalized_alias "
    "ON client_aliases (normalized_alias)",
    "CREATE INDEX IF NOT EXISTS ix_client_aliases_import_run_id "
    "ON client_aliases (import_run_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_aliases_archived_at "
    "ON client_aliases (archived_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_client_aliases_source_key "
    "ON client_aliases (source_system, source_key) WHERE source_key IS NOT NULL",
    """CREATE TABLE IF NOT EXISTS client_import_rows (
        id SERIAL PRIMARY KEY,
        import_run_id INTEGER NOT NULL
            REFERENCES client_import_runs(id) ON DELETE CASCADE,
        sheet_name VARCHAR(255) NOT NULL,
        row_number INTEGER NOT NULL,
        source_key VARCHAR(255) NULL,
        source_name VARCHAR(255) NOT NULL,
        normalized_name VARCHAR(255) NULL,
        proposed_display_name VARCHAR(255) NULL,
        proposed_legal_name VARCHAR(255) NULL,
        category clientportfoliocategory NOT NULL,
        start_date DATE NULL,
        end_date DATE NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        match_confidence NUMERIC(5, 4) NULL,
        raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        error_message TEXT NULL,
        matched_client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
        portfolio_scope_id INTEGER NULL
            REFERENCES client_portfolio_scopes(id) ON DELETE SET NULL,
        framework_contract_id INTEGER NULL
            REFERENCES client_framework_contracts(id) ON DELETE SET NULL,
        resolved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        resolved_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_client_import_rows_sheet_row
            UNIQUE (import_run_id, sheet_name, row_number),
        CONSTRAINT ck_client_import_rows_row_number_positive
            CHECK (row_number >= 1),
        CONSTRAINT ck_client_import_rows_source_name_nonempty
            CHECK (char_length(btrim(source_name)) > 0),
        CONSTRAINT ck_client_import_rows_status CHECK (
            status IN (
                'pending', 'matched', 'create', 'ambiguous',
                'ignored', 'applied', 'failed'
            )
        ),
        CONSTRAINT ck_client_import_rows_match_confidence CHECK (
            match_confidence IS NULL
            OR (match_confidence >= 0 AND match_confidence <= 1)
        ),
        CONSTRAINT ck_client_import_rows_dates CHECK (
            start_date IS NULL OR end_date IS NULL OR end_date >= start_date
        )
    )""",
    "CREATE INDEX IF NOT EXISTS ix_client_import_rows_import_run_id "
    "ON client_import_rows (import_run_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_import_rows_matched_client_id "
    "ON client_import_rows (matched_client_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_import_rows_status "
    "ON client_import_rows (status)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_activity_summaries_scope_policy "
    "ON candidate_activity_summaries "
    "(candidate_id, visibility_scope_hash, content_policy_version)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_activity_summaries_lease_expires_at "
    "ON candidate_activity_summaries (generation_lease_expires_at) "
    "WHERE generation_lease_expires_at IS NOT NULL",
    # P0-A (migration 0211_proposal_snapshot_degraded): flag na snapshotach
    # rankingu, że semantyka leciała w trybie awaryjnym (Qdrant/Voyage down lub
    # job niezaindeksowany). ORM (`ProposalSnapshot.degraded`) + proposals API to
    # czytają — brak kolumny => UndefinedColumnError na GET /proposals/latest.
    "ALTER TABLE proposal_snapshots "
    "ADD COLUMN IF NOT EXISTS degraded BOOLEAN NOT NULL DEFAULT FALSE",
    # P0-A (migration 0212_proposal_snapshot_source_handoff): ranking powstaje
    # teraz przez handoff „Przekaż do searchu", nie przy create. Poszerz CHECK na
    # `source`, bo INSERT z source='handoff' inaczej rzuca CheckViolationError.
    "ALTER TABLE proposal_snapshots "
    "DROP CONSTRAINT IF EXISTS ck_proposal_snapshots_source",
    "ALTER TABLE proposal_snapshots ADD CONSTRAINT ck_proposal_snapshots_source "
    "CHECK (source IN ('create', 'manual_regenerate', 'job_updated', 'handoff'))",
    # P0-B (migration 0213_proposal_snapshot_freshness): run_id / fingerprint /
    # stale — ORM je czyta, brak => UndefinedColumnError na /proposals/latest.
    "ALTER TABLE proposal_snapshots "
    "ADD COLUMN IF NOT EXISTS run_id TEXT NULL",
    "ALTER TABLE proposal_snapshots "
    "ADD COLUMN IF NOT EXISTS input_fingerprint TEXT NULL",
    "ALTER TABLE proposal_snapshots "
    "ADD COLUMN IF NOT EXISTS stale BOOLEAN NOT NULL DEFAULT FALSE",
    # 0218: materiały w zakładce Pomoc — biblioteka LINKÓW do dokumentów w
    # SharePoincie (NEXUS ich nie hostuje). Bez tej tabeli GET
    # /api/help-materials => UndefinedTableError (500).
    """CREATE TABLE IF NOT EXISTS help_materials (
        id SERIAL PRIMARY KEY,
        slug VARCHAR(255) NOT NULL UNIQUE,
        category VARCHAR(255) NOT NULL,
        title VARCHAR(255) NOT NULL,
        url TEXT NOT NULL,
        description TEXT,
        is_editable_template BOOLEAN NOT NULL DEFAULT FALSE,
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_published BOOLEAN NOT NULL DEFAULT TRUE,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_help_materials_slug "
    "ON help_materials (slug)",
    "CREATE INDEX IF NOT EXISTS ix_help_materials_category "
    "ON help_materials (category)",
    "CREATE INDEX IF NOT EXISTS ix_help_materials_sort_order "
    "ON help_materials (sort_order)",
    "CREATE INDEX IF NOT EXISTS ix_help_materials_id ON help_materials (id)",
]

_ROLE_DASHBOARD_CUTOVER_SQL = r"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM app_settings
        WHERE key = '0210_role_dashboard_rbac_cutover'
    ) THEN
        INSERT INTO role_session_migration_audit (
            migration_key, user_id, original_state
        )
        SELECT
            '0210_role_dashboard_rbac_cutover',
            id,
            jsonb_build_object(
                'role', role::text,
                'roles', roles,
                'profile_completed', profile_completed,
                'profile_completed_at', profile_completed_at,
                'allowed_sections', allowed_sections,
                'kpi_coach_enabled', kpi_coach_enabled,
                'cloudtalk_agent_id', cloudtalk_agent_id,
                'authorization_version', authorization_version,
                'tokens_valid_after', tokens_valid_after,
                'finance_requested',
                    role::text = 'finance'
                    OR (jsonb_typeof(roles) = 'array' AND roles ? 'finance')
            )
        FROM users
        ON CONFLICT (migration_key, user_id) DO NOTHING;

        UPDATE users
        SET roles = jsonb_build_array(role::text)
        WHERE roles IS NULL OR jsonb_typeof(roles) <> 'array';

        UPDATE users
        SET role = 'finance'::userrole,
            roles = '["finance"]'::jsonb,
            allowed_sections = '[]'::jsonb,
            profile_completed = TRUE,
            profile_completed_at = COALESCE(profile_completed_at, clock_timestamp()),
            kpi_coach_enabled = FALSE,
            cloudtalk_agent_id = NULL
        WHERE role::text = 'finance' OR roles ? 'finance';

        UPDATE users
        SET role = 'recruiter'::userrole,
            roles = '["recruiter"]'::jsonb,
            allowed_sections = '[]'::jsonb,
            profile_completed = FALSE,
            profile_completed_at = NULL
        WHERE role::text = 'user';

        WITH cleaned AS (
            SELECT
                u.id,
                COALESCE(
                    jsonb_agg(e.value ORDER BY e.ordinality)
                        FILTER (
                            WHERE e.value IN (
                                'admin', 'head_of_recruitment', 'delivery_lead',
                                'tac', 'recruiter', 'sourcer'
                            )
                        ),
                    '[]'::jsonb
                ) AS roles
            FROM users AS u
            LEFT JOIN LATERAL jsonb_array_elements_text(u.roles)
                WITH ORDINALITY AS e(value, ordinality) ON TRUE
            WHERE u.role::text <> 'finance'
            GROUP BY u.id
        )
        UPDATE users AS u SET roles = cleaned.roles
        FROM cleaned WHERE u.id = cleaned.id;

        UPDATE users
        SET roles = jsonb_build_array(role::text) || roles
        WHERE role::text <> 'finance' AND NOT (roles ? role::text);

        INSERT INTO rbac_relationship_reconciliation (
            migration_key, issue_kind, user_id, details
        )
        SELECT
            '0210_role_dashboard_rbac_cutover',
            'finance_relationships_sanitised',
            u.id,
            jsonb_build_object(
                'delivery_lead_client_assignment_ids', COALESCE((
                    SELECT jsonb_agg(a.id ORDER BY a.id)
                    FROM delivery_lead_client_assignments a
                    WHERE a.delivery_lead_user_id = u.id
                ), '[]'::jsonb),
                'client_tac_assignment_ids', COALESCE((
                    SELECT jsonb_agg(a.id ORDER BY a.id)
                    FROM client_tac_assignments a
                    WHERE a.tac_user_id = u.id
                ), '[]'::jsonb),
                'tac_delivery_lead_assignment_ids', COALESCE((
                    SELECT jsonb_agg(a.id ORDER BY a.id)
                    FROM tac_delivery_lead_assignments a
                    WHERE a.tac_user_id = u.id OR a.delivery_lead_user_id = u.id
                ), '[]'::jsonb),
                'competence_assignment_ids', COALESCE((
                    SELECT jsonb_agg(a.id ORDER BY a.id)
                    FROM user_competence_categories a
                    WHERE a.user_id = u.id
                ), '[]'::jsonb)
            )
        FROM users u
        WHERE u.role::text = 'finance'
          AND NOT EXISTS (
              SELECT 1
              FROM rbac_relationship_reconciliation r
              WHERE r.migration_key = '0210_role_dashboard_rbac_cutover'
                AND r.issue_kind = 'finance_relationships_sanitised'
                AND r.user_id = u.id
          );

        DELETE FROM delivery_lead_client_assignments a USING users u
        WHERE a.delivery_lead_user_id = u.id AND u.role::text = 'finance';
        DELETE FROM client_tac_assignments a USING users u
        WHERE a.tac_user_id = u.id AND u.role::text = 'finance';
        DELETE FROM tac_delivery_lead_assignments a USING users u
        WHERE u.role::text = 'finance'
          AND (a.tac_user_id = u.id OR a.delivery_lead_user_id = u.id);
        DELETE FROM tac_linkedin_farming a USING users u
        WHERE a.tac_user_id = u.id AND u.role::text = 'finance';
        DELETE FROM user_competence_categories a USING users u
        WHERE a.user_id = u.id AND u.role::text = 'finance';
        DELETE FROM job_collaborators a USING users u
        WHERE a.user_id = u.id AND u.role::text = 'finance';

        IF to_regclass('public.dr_tac_delivery_lead_assignments') IS NOT NULL THEN
            DELETE FROM dr_tac_delivery_lead_assignments a USING users u
            WHERE u.role::text = 'finance'
              AND (a.tac_user_id = u.id OR a.delivery_lead_user_id = u.id);
        END IF;
        IF to_regclass('public.dr_sourcer_category_assignments') IS NOT NULL THEN
            DELETE FROM dr_sourcer_category_assignments a USING users u
            WHERE a.user_id = u.id AND u.role::text = 'finance';
        END IF;

        UPDATE jobs j SET recruiter_id = NULL
        FROM users u WHERE j.recruiter_id = u.id AND u.role::text = 'finance';
        UPDATE jobs j SET delivery_lead_id = NULL
        FROM users u WHERE j.delivery_lead_id = u.id AND u.role::text = 'finance';
        UPDATE jobs j SET tac_id = NULL
        FROM users u WHERE j.tac_id = u.id AND u.role::text = 'finance';
        UPDATE contacts c SET key_relationship_owner_id = NULL
        FROM users u
        WHERE c.key_relationship_owner_id = u.id AND u.role::text = 'finance';
        UPDATE saved_searches s
        SET notify_new_matches = FALSE, unseen_count = 0
        FROM users u
        WHERE s.user_id = u.id AND u.role::text = 'finance';
        DELETE FROM notifications n USING users u
        WHERE n.user_id = u.id
          AND u.role::text = 'finance'
          AND n.notification_type::text NOT IN (
              'password_reset_requested', 'password_changed_by_admin'
          );
        UPDATE notifications n
        SET link = NULL,
            related_entity_type = NULL,
            related_entity_id = NULL,
            email_send_started_at = NULL
        FROM users u
        WHERE n.user_id = u.id AND u.role::text = 'finance';

        INSERT INTO rbac_relationship_reconciliation (
            migration_key, issue_kind, user_id, details
        )
        SELECT
            '0210_role_dashboard_rbac_cutover',
            'client_tac_first_priority_required',
            tac_user_id,
            jsonb_build_object(
                'assignment_count', count(*),
                'client_ids', jsonb_agg(client_id ORDER BY client_id),
                'legacy_primary_client_ids',
                    COALESCE(
                        jsonb_agg(client_id ORDER BY client_id)
                            FILTER (WHERE is_primary IS TRUE),
                        '[]'::jsonb
                    )
            )
        FROM client_tac_assignments AS assignment
        GROUP BY assignment.tac_user_id
        HAVING count(*) > 1
           AND count(*) FILTER (
                   WHERE assignment.is_first_priority_for_tac IS TRUE
               ) <> 1
           AND NOT EXISTS (
               SELECT 1
               FROM rbac_relationship_reconciliation AS existing
               WHERE existing.migration_key = '0210_role_dashboard_rbac_cutover'
                 AND existing.issue_kind = 'client_tac_first_priority_required'
                 AND existing.user_id = assignment.tac_user_id
           );

        WITH single_client_tacs AS (
            SELECT tac_user_id FROM client_tac_assignments
            GROUP BY tac_user_id HAVING count(*) = 1
        )
        UPDATE client_tac_assignments a
        SET is_first_priority_for_tac = TRUE
        FROM single_client_tacs s
        WHERE a.tac_user_id = s.tac_user_id
          AND a.is_first_priority_for_tac IS NULL;

        INSERT INTO rbac_relationship_reconciliation (
            migration_key, issue_kind, user_id, details
        )
        SELECT
            '0210_role_dashboard_rbac_cutover',
            'competence_primary_required',
            user_id,
            jsonb_build_object(
                'signalled_assignment_ids',
                    jsonb_agg(id ORDER BY id)
                        FILTER (WHERE is_primary IS TRUE OR priority = 1),
                'all_assignment_ids', jsonb_agg(id ORDER BY id)
            )
        FROM user_competence_categories AS assignment
        GROUP BY assignment.user_id
        HAVING count(*) FILTER (
                   WHERE assignment.is_primary IS TRUE OR assignment.priority = 1
               ) > 1
           AND NOT EXISTS (
               SELECT 1
               FROM rbac_relationship_reconciliation AS existing
               WHERE existing.migration_key = '0210_role_dashboard_rbac_cutover'
                 AND existing.issue_kind = 'competence_primary_required'
                 AND existing.user_id = assignment.user_id
           );

        WITH ambiguous AS (
            SELECT user_id FROM user_competence_categories
            GROUP BY user_id
            HAVING count(*) FILTER (WHERE is_primary IS TRUE OR priority = 1) > 1
        )
        UPDATE user_competence_categories a
        SET priority = 2, is_primary = FALSE
        FROM ambiguous x WHERE a.user_id = x.user_id;

        WITH signal AS (
            SELECT user_id, min(id) AS assignment_id
            FROM user_competence_categories
            WHERE is_primary IS TRUE OR priority = 1
            GROUP BY user_id HAVING count(*) = 1
        )
        UPDATE user_competence_categories a
        SET priority = CASE WHEN a.id = signal.assignment_id THEN 1 ELSE 2 END,
            is_primary = (a.id = signal.assignment_id)
        FROM signal WHERE a.user_id = signal.user_id;

        UPDATE user_competence_categories
        SET priority = COALESCE(priority, 2),
            is_primary = (COALESCE(priority, 2) = 1);

        UPDATE users
        SET authorization_version = GREATEST(authorization_version, 1) + 1,
            tokens_valid_after = clock_timestamp();
        DELETE FROM auth_exchange_codes;

        INSERT INTO app_settings (key, value)
        VALUES (
            '0210_role_dashboard_rbac_cutover',
            jsonb_build_object(
                'revision', '0210_role_dashboard_rbac_cutover',
                'completed_at', clock_timestamp(),
                'source', 'entrypoint_safety_net'
            )
        );
    END IF;
END $$
"""


_DATA_STATEMENTS = [
    # 0204: seed zarezerwowanego feature'a AI `candidate_summary` (widoczność
    # + licznik w Ustawieniach → AI). Idempotentny: WHERE NOT EXISTS.
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    "SELECT 'candidate_summary', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'candidate_summary')",
    # 0214: seed feature'a AI `order_parser` (odczyt PDF zamówienia w przedłużeniu).
    # Enabled + unlimited, idempotentny WHERE NOT EXISTS. Wymaga wartości enuma
    # dodanej w _ENUM_STATEMENTS (leci wcześniej).
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    "SELECT 'order_parser', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'order_parser')",
    # 0217: seedy feature'ów interaktywnego CV (kafelki + chat). Brak wiersza w
    # ai_features = feature milcząco zablokowany (get_feature_config -> None).
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    "SELECT 'cv_requirement_map', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'cv_requirement_map')",
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    "SELECT 'cv_interactive_chat', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS "
    "(SELECT 1 FROM ai_features WHERE feature = 'cv_interactive_chat')",
    # 0173: rejection_reasons.external_source backfill (integracja Traffit).
    "UPDATE rejection_reasons SET external_source = 'manual' "
    "WHERE external_source IS NULL",
    # 0197: jednorazowy seed „powód dyskwalifikuje osobę". Ta lista leci przy
    # KAŻDYM starcie kontenera, więc bez guardu przywracałaby flagi po każdym
    # deployu i kasowała świadome zmiany admina w panelu. Marker w app_settings
    # jest wstawiany TYM SAMYM statementem, co seed — więc seed odpala się
    # wyłącznie na runie, który ten marker zajął.
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    "VALUES ('rejection_reason_disqualifies_seeded', 'true'::jsonb) "
    "ON CONFLICT (key) DO NOTHING RETURNING key) "
    "UPDATE rejection_reasons SET disqualifies_person = true "
    "WHERE category = 'rejected' "
    "AND name IN ('Brak doświadczenia', 'Nie spełnia wymagań technicznych', "
    "'Nie pasuje kulturowo') "
    "AND EXISTS (SELECT 1 FROM marker)",
    """UPDATE candidate_documents AS document
       SET document_kind = 'cv'
       FROM candidates AS candidate
       WHERE document.candidate_id = candidate.id
         AND document.source_deleted_at IS NULL
         AND (
             document.is_primary IS TRUE
             OR document.external_source = 'apply_submission'
             OR (
                 candidate.cv_filename IS NOT NULL
                 AND lower(document.filename) = lower(candidate.cv_filename)
             )
             OR document.filename ~* '(^|[^a-z])(cv|resume|curriculum)([^a-z]|$)'
         )""",
    """INSERT INTO candidate_documents (
           candidate_id, filename, file_content, storage_key, size_bytes,
           document_kind, is_primary, uploaded_at, external_source,
           created_at, updated_at
       )
       SELECT candidate.id,
              candidate.cv_filename,
              CASE WHEN candidate.cv_storage_key IS NULL
                   THEN candidate.cv_file_content ELSE NULL END,
              candidate.cv_storage_key,
              CASE WHEN candidate.cv_storage_key IS NULL
                   THEN octet_length(candidate.cv_file_content) ELSE NULL END,
              'cv',
              TRUE,
              COALESCE(candidate.cv_parsed_at, candidate.updated_at),
              'legacy_backfill',
              NOW(),
              NOW()
       FROM candidates AS candidate
       WHERE candidate.cv_filename IS NOT NULL
         AND btrim(candidate.cv_filename) <> ''
         AND (
             candidate.cv_storage_key IS NOT NULL
             OR candidate.cv_file_content IS NOT NULL
         )
         AND NOT EXISTS (
             SELECT 1
             FROM candidate_documents AS document
             WHERE document.candidate_id = candidate.id
               AND document.source_deleted_at IS NULL
               AND (
                   document.is_primary IS TRUE
                   OR lower(document.filename) = lower(candidate.cv_filename)
               )
         )""",
    """WITH ranked AS (
           SELECT id,
                  row_number() OVER (
                      PARTITION BY candidate_id
                      ORDER BY uploaded_at DESC NULLS LAST, created_at DESC, id DESC
                  ) AS position
           FROM candidate_documents
           WHERE document_kind = 'cv'
             AND is_primary IS TRUE
             AND source_deleted_at IS NULL
       )
       UPDATE candidate_documents AS document
       SET is_primary = FALSE
       FROM ranked
       WHERE document.id = ranked.id
         AND ranked.position > 1""",
    # Backfill closed_at for historical closed rows so reports sort by "real
    # close date" instead of NULL. Safe because only touches NULL rows.
    "UPDATE jobs SET closed_at = updated_at WHERE status = 'closed' AND closed_at IS NULL",
    # Pre-flag roles that don't need onboarding (mirrors migration 0035 step)
    """UPDATE users
          SET profile_completed = TRUE,
              profile_completed_at = COALESCE(profile_completed_at, NOW())
        WHERE profile_completed = FALSE
          AND role::text NOT IN ('delivery_lead', 'recruiter')""",
    # Must run after the legacy onboarding preflag above so viewer→Recruiter
    # remains profile_completed=false.  The marker makes it one-shot.
    _ROLE_DASHBOARD_CUTOVER_SQL,
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
    # 0153: wyróżniony klient „Ministerstwo Sprawiedliwości" w dropdownie
    # generatora umów B2B. Migracja 0153 nigdy nie skomitowała się na prodzie
    # (INSERT bez nda_signed vs NOT NULL bez defaultu → rollback, bookmark
    # utknął na 0152) — lustro tutaj, jak dla pozostałych migracji >=0153.
    # Oba kroki strażowane „nie ma jeszcze wyróżnionej pozycji" → no-op po
    # pierwszym udanym runie i odporne na ręczne zmiany admina.
    """UPDATE clients
       SET display_name = 'Ministerstwo Sprawiedliwości'
       WHERE id = (
           SELECT id FROM clients
           WHERE display_name IS NULL
             AND hidden = false
             AND lower(btrim(name)) = lower('Ministerstwo Sprawiedliwości')
           ORDER BY id
           LIMIT 1
       )
       AND NOT EXISTS (
           SELECT 1 FROM clients
           WHERE display_name = 'Ministerstwo Sprawiedliwości'
             AND hidden = false
       )""",
    """INSERT INTO clients
           (name, display_name, status, hidden, nda_signed,
            external_source, created_at, updated_at)
       SELECT
           'Ministerstwo Sprawiedliwości', 'Ministerstwo Sprawiedliwości',
           'prospect', false, false, 'manual', now(), now()
       WHERE NOT EXISTS (
           SELECT 1 FROM clients
           WHERE display_name = 'Ministerstwo Sprawiedliwości'
             AND hidden = false
       )""",
    # ─────────────────────────────────────────────────────────────────────
    # 0218: seed materiałów w zakładce Pomoc (26 pozycji — lustro _SEED_ROWS
    # z migracji 0218). To EFEKTYWNY kanał seedowania proda: leci przy każdym
    # boocie i jest rerun-safe (ON CONFLICT (slug) DO NOTHING), w odróżnieniu
    # od migracji, której alembic nie powtórzy po zastosowaniu. Zmieniasz tu —
    # zmień też w migracji, żeby oba kanały nie rozjechały się.
    #
    # is_editable_template = TRUE mają DOKŁADNIE 3 wiersze (nasze wzory:
    # szablon umowy, profil Championa, notatka po screeningu) — FE dokłada im
    # skrót „Edytuj w Word Online". Formularze klientów zawsze FALSE.
    # ─────────────────────────────────────────────────────────────────────
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'szablon-umowy-b2b-2026',
           'Szablony i wzory',
           'Nowy szablon do Umowy B2B 2026.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBYCLTZTfqoQIw5DkZA-cO9AVTZkGhqkY4tfhq5AGXgv3E?e=HmRSwm',
           'Szablon do umowy', TRUE, 10, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor',
           'Szablony i wzory',
           'Profil_Championa_WZÓR.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQAXQ2XHDxDdTY-sIuR1URcmASEIat4mo1UbzjlPGtowpF4?e=gY6p9K',
           'Profil championa', TRUE, 20, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'notatka-po-screeningu-wzor',
           'Szablony i wzory',
           'Notatka po screeningu_WZÓR.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQAH82MUIw8NQIA_awLVQa-OAa3Sp9NH3uuJ2--0Zh2w_Yk?e=B4d1Ee',
           'Notatka po screeningu', TRUE, 30, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'nordea-appendix-3-confidentiality',
           'Onboarding — NORDEA',
           'Appendix 3 (Confidentiality undertaking template).docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQCNrQioV9HRW5Cg2hPDrkvmAaoRkll4bOvCRtM9DVrguJY?e=hWCrNJ',
           NULL, FALSE, 100, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'nordea-oswiadczenie-krk-2026',
           'Onboarding — NORDEA',
           'OŚWIADCZENIE o niekaralności KRK_2026.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQDkqOfMK4lFQLBAP5nReg_xATO6ea46CcWlOG28H2GjoOo?e=AeHgut',
           NULL, FALSE, 110, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'bnp-cardif-zgoda-dane-osobowe',
           'Onboarding — BNP CARDIF',
           'Zgoda na przetwarzanie danych osobowych przez BNP_CPL (1).doc',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBQzJjtYMnlTo61T78myddsAcbI62g1FlkFgO2weFZ-acc?e=kLgtvU',
           NULL, FALSE, 200, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'bnp-paribas-oswiadczenie-zdalny-dostep',
           'Onboarding — BNP Paribas Bank Polska',
           'Oświadczenie_zdalny dostęp_Kontraktor BNP.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBYka4c_dUyXrtKfSyBKh3tARHMTWrB_E_j7LCY3O2I2iE?e=DROMA9',
           NULL, FALSE, 300, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'bank-pocztowy-oswiadczenie-niekaralnosci',
           'Onboarding — Bank Pocztowy',
           'Oświadczenie o niekaralności Bank Pocztowy.doc',
           'https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQDGbFJOOMiEWJl6Q5mRjahnAf4P_hvVBiHxAhgDkn4jt8M?e=hSNYsc',
           NULL, FALSE, 400, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'bank-pocztowy-oswiadczenie-poufnosci',
           'Onboarding — Bank Pocztowy',
           'Oświadczenie o zachowaniu poufności.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQC5Pk2IFiJmVJYq8Wbe3snAAUibIPmUIMhXdS4ITVMhVGo?e=Jpm70p',
           NULL, FALSE, 410, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'ergo-oswiadczenia-folder',
           'Onboarding — ERGO',
           'Oświadczenia (folder)',
           'https://b2bnetsa.sharepoint.com/:f:/s/B2B_ALL/IgB4aG8FiGNCWIkwKfKEfFRQAalrkypJlOnZx5nf1QI9-_s?e=7DoJ7E',
           NULL, FALSE, 500, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'ergo-opis-dokumentow-onboarding',
           'Onboarding — ERGO',
           'ERGO_opis dokumentów do podpisania przed onboardingiem.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQDlucxDIrS-Wo2W4VxrFLqUARzxom-pr3tedyLsaOd7Jw0?e=cfUxnJ',
           NULL, FALSE, 510, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'pfron-oswiadczenie-bhp',
           'Onboarding — PFRON',
           'oswiadczenie bhp.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBh6_04XLdNQKGgyoztq3nuAVscjlXYUdX3rtDDzHY08Ag?e=SuVP2a',
           NULL, FALSE, 600, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'pfron-oswiadczenie-wzor',
           'Onboarding — PFRON',
           'oświadczenie_wzór.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQCSIrWRj3NfSr6qJqvUsosyARbm-LGN9VFG2ShtUpCx7fs?e=6ERa0W',
           NULL, FALSE, 610, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'pfron-zalacznik-polityka-oswiadczenie',
           'Onboarding — PFRON',
           'załącznik do Polityki - oświadczenie.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBh8IMyyPqGT5jG1rWpqPr-AdOkcdtDAhQRaFbz5pHsYqo?e=PYyXZi',
           NULL, FALSE, 620, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'polkomtel-informacja-przetwarzanie-danych',
           'Onboarding — POLKOMTEL',
           'Informacja o przetwarzaniu danych osobowych.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQDoSxX3OKNiU7MK4E8bzIWfAfn7Fe6YDFBmo1NBesju4AY?e=8bGTaA',
           NULL, FALSE, 700, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'tauron-zalacznik-1-zakres-uslug',
           'Onboarding — TAURON',
           'ZAŁĄCZNIK NR 1 Zakres usług.pdf',
           'https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQBTNdLh2w4ISZoJmXNOee50AfWL8fNj-R9pBWsSANPbZL4?e=8xgiVe',
           NULL, FALSE, 800, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'tauron-draft-umowy',
           'Onboarding — TAURON',
           'draft umowy Tauron.pdf',
           'https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQCsLARwCnQ5Qbp0xKlhZRDJAUvCkm6RxKF7oc1ubBfOKOc?e=id9xUp',
           NULL, FALSE, 810, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'tauron-zalacznik-2-raport-miesieczny',
           'Onboarding — TAURON',
           'ZAŁĄCZNIK NR 2 Raport Miesięczny — uproszczony.pdf',
           'https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQDxLFIyvELvTajgG7nVN0HcAfWrBK2oS6ce460XAA00RMY?e=LYdn9h',
           NULL, FALSE, 820, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'tauron-zalacznik-3-upowaznienie-dane-osobowe',
           'Onboarding — TAURON',
           'ZAŁĄCZNIK NR 3 Upoważnienie szczególne do Przetwarzania Danych Osobowych.pdf',
           'https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQCrCdKO5SFZQqGZ9Sm861fmAXSv0DJeI3a8BtcOVv-CxsA?e=jizscN',
           NULL, FALSE, 830, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'tauron-zalacznik-4-vpn',
           'Onboarding — TAURON',
           'ZAŁĄCZNIK NR 4 Zasady Zdalnego Dostępu VPN dla Wykonawcy.pdf',
           'https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQAigsT1LENsQIk3IZ-AH79kAccTfb7jIJa4MTrODwKv0vc?e=cimF4u',
           NULL, FALSE, 840, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'tauron-zalacznik-5a-porozumienie-przesylanie-dokumentow',
           'Onboarding — TAURON',
           'ZAŁĄCZNIK NR 5a Porozumienie przesyłanie dokumentów (1).pdf',
           'https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQC4sflP6q8eSabZNsID3c_mAeq-_iwcTWpnWEk65cGTsd8?e=DNhDsP',
           NULL, FALSE, 850, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'tauron-zalacznik-5b-ksef',
           'Onboarding — TAURON',
           'ZAŁĄCZNIK NR 5b Zasady przesyłania faktur i załączników za pośrednictwem Krajowego Systemu e-Faktur (KSeF).pdf',
           'https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQCc79RRqqAPRLt0h8St_5OtAfVBGgrWjhNTdNLqqZA1-B0?e=FtKyx8',
           NULL, FALSE, 860, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'tauron-zalacznik-6-incydenty-bezpieczenstwa',
           'Onboarding — TAURON',
           'ZAŁĄCZNIK NR 6 Wymagania dot. zgłaszania i obsługi incydentów bezpieczeństwa.pdf',
           'https://b2bnetsa.sharepoint.com/:b:/s/B2B_ALL/IQCwHFWV-XG6RpjNCDW6_ebmAeG4-jyaM9YSknnsjjNqp_A?e=bOhHjT',
           NULL, FALSE, 870, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'velobank-dokumenty-etat-umowa-ramowa',
           'Onboarding — VeloBank',
           'Dokumenty_Etat_VeloBank_umowa ramowa.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQCj4OMyTYoIQKqTu5r0GlsTAfAVb6np3ZmEDei0lQhCzew?e=DX5iEM',
           NULL, FALSE, 900, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'velobank-dokumenty-podwykonawcy-nowy',
           'Onboarding — VeloBank',
           'Dokumenty_Podwykonawcy_VeloBank NOWY.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQAiRlr-0uFzVp_uqPTdh724AX5H89ZunbnOxy-5w_zrLAU?e=heH4fX',
           NULL, FALSE, 910, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'velobank-dokumenty-podwykonawcy-instrukcja',
           'Onboarding — VeloBank',
           'Dokumenty_Podwykonawcy_VeloBank+Instrukcja.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBQwWFCXgP-QJhd4B43CxucAfoTp9f5T6MGOkJWA_nr-M8?e=IpwtCU',
           NULL, FALSE, 920, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    # ─────────────────────────────────────────────────────────────────────
    # 0219: profile Championa per klient (14) + angielskie KRK dla NORDEI.
    # Lustro _SEED_ROWS z migracji 0219 — zmieniasz tu, zmień też tam.
    # Slugi są dosłownie te, które wygenerowało API przy dodaniu pozycji
    # przez panel admina, więc ON CONFLICT czyni to no-opem na żywej bazie.
    # ─────────────────────────────────────────────────────────────────────
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-alior-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_ALIOR.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQAqhBG2TeC-Rq5iZvv0eCIdAaU9wTC4GQsNeOQEIW6-pHU?e=gAcy15',
           NULL, TRUE, 40, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-bank-pocztowy-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_Bank_Pocztowy.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQDOeFoZ9jXlRZOOZS64x3jPATePmoyCq6n3Ey24KdM28wI?e=FRB6AY',
           NULL, TRUE, 41, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-bik-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_BIK.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQCGKeFvsfRdSJZQfx6ic3MIAd7ORch-9xFOn9SmTcYP9zQ?e=8TMS7l',
           NULL, TRUE, 42, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-bnp-paribas-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_BNP PARIBAS.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQCnzsRBh_jjRazf6E99DnujAfvlUPIlfS-il0gO7kARwWY?e=qi2sJ7',
           NULL, TRUE, 43, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-credit-agricole-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_Credit_Agricole.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQD2UQIpNGWNQazOxiiAzBwSAagOFte6eTs3bjTz1yVS6k0?e=O5obFf',
           NULL, TRUE, 44, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-energa-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_ENERGA.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBuaj9FoVuqQ4kWjRWO-Q48AaREJPRIkwtkLuWktaoBWm4?e=y7aI5u',
           NULL, TRUE, 45, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-kir-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_KIR.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQCP1Cycr_nlSaamMIP9D3y0AX6qWLEcZ3g9VgXKMb0tgnc?e=a96UJd',
           NULL, TRUE, 46, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-nordea-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_Nordea.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQAdW75s9FA6T4ZtUzvWLQGvAYYmpHA-Ls7yqEDaCJhFe0I?e=e1WeCi',
           NULL, TRUE, 47, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-orlen-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_ORLEN.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQAtwxfeHg5ER69jFBwnZq-QAVmOsogbnKKDZBbzNu8gFjg?e=Q9DFPz',
           NULL, TRUE, 48, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-pansa-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_PANSA.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBM19BRQcwNTqiKVYAhXRDZAXCJpfKjsFssyoRYyoW3dhQ?e=TvMegW',
           NULL, TRUE, 49, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-pfron-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_PFRON.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQDL2kX71z-0QYdvJzqjM93sAXPvO1Zll5DZEeX8M3oBJXI?e=ybfUNL',
           NULL, TRUE, 50, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-pko-bp-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_PKO_BP.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQD9_8XJmO59RK88a60JBHvrAewQThXykcP8aQ4zgjpJ9C0?e=BcPEVd',
           NULL, TRUE, 51, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-santander-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_SANTANDER.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBiuBrkrRtWQ5tExRVDuDvgAXjxgxZOcFKOXPhrAvIii9k?e=CpPLwh',
           NULL, TRUE, 52, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'profil-championa-wzor-tauron-docx',
           'Profile Championa — per klient',
           'Profil_Championa_WZÓR_Tauron.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQBO8uaqIOaRTaCUnHvJ8KlHAdz0kAdvjQdC9bWFSK1VYas?e=1smhiG',
           NULL, TRUE, 53, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'oswiadczenie-o-niekaralnosci-eng-krk-2024-docx',
           'Onboarding — NORDEA',
           'Oświadczenie o niekaralnośći_ENG_KRK_2024.docx',
           'https://b2bnetsa.sharepoint.com/:w:/s/B2B_ALL/IQANFFmetXfmS4PuZKyAAdTJAUlFelWJl0wN9bZVd4Gw1UE?e=itWxtg',
           'Wersja angielska oświadczenia o niekaralności (KRK 2024)', FALSE, 120, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
]


# ── Klucze obce zmierzone jako brakujące na produkcji (2026-07-20) ───────────
# Safety-net dodaje KOLUMNY, ale nigdy ich OGRANICZEŃ — dlatego competence_
# category_id istnieje na candidates i jobs, a więzy referencyjne nie. Skutek:
# nic nie broni przed osieroconym id kategorii.
#
# NOT VALID świadomie: egzekwuje więz dla NOWYCH zapisów, nie skanując przy tym
# całej tabeli i nie wywracając się na ewentualnych sierotach z przeszłości.
# Bez tego jedna zabłąkana wartość zablokowałaby start kontenera. VALIDATE
# CONSTRAINT można uruchomić później, świadomie, po policzeniu sierot.
_CONSTRAINT_STATEMENTS = [
    "ALTER TABLE user_competence_categories ALTER COLUMN priority SET DEFAULT 2",
    "ALTER TABLE user_competence_categories ALTER COLUMN priority SET NOT NULL",
    "ALTER TABLE user_competence_categories DROP CONSTRAINT IF EXISTS ck_user_cc_priority",
    "ALTER TABLE user_competence_categories DROP CONSTRAINT IF EXISTS ck_user_cc_primary_priority",
    """DO $$ BEGIN
        ALTER TABLE user_competence_categories
            ADD CONSTRAINT ck_user_cc_priority
            CHECK (priority IN (1, 2)) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE user_competence_categories
            ADD CONSTRAINT ck_user_cc_primary_priority
            CHECK (is_primary = (priority = 1)) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE users
            ADD CONSTRAINT ck_users_authorization_version_positive
            CHECK (authorization_version > 0) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE users
            ADD CONSTRAINT ck_users_roles_array
            CHECK (jsonb_typeof(roles) = 'array') NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE users
            ADD CONSTRAINT ck_users_exclusive_finance_viewer_roles
            CHECK (
                CASE
                    WHEN role::text IN ('finance', 'user')
                        THEN roles = jsonb_build_array(role::text)
                    ELSE NOT (roles ?| ARRAY['finance', 'user']::text[])
                END
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "ALTER TABLE user_competence_categories VALIDATE CONSTRAINT ck_user_cc_priority",
    "ALTER TABLE user_competence_categories VALIDATE CONSTRAINT ck_user_cc_primary_priority",
    "ALTER TABLE users VALIDATE CONSTRAINT ck_users_authorization_version_positive",
    "ALTER TABLE users VALIDATE CONSTRAINT ck_users_roles_array",
    "ALTER TABLE users VALIDATE CONSTRAINT ck_users_exclusive_finance_viewer_roles",
    """DO $$ BEGIN
        ALTER TABLE candidates
            ADD CONSTRAINT fk_candidates_competence_category
            FOREIGN KEY (competence_category_id)
            REFERENCES competence_categories (id) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE jobs
            ADD CONSTRAINT fk_jobs_competence_category
            FOREIGN KEY (competence_category_id)
            REFERENCES competence_categories (id) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_signature_status
            CHECK (signature_status IN ('unsigned', 'signed_both')) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_signature_source
            CHECK (
                signature_source IS NULL OR
                signature_source IN ('manual_confirmation', 'validated_upload')
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT fk_b2b_generated_contracts_candidate_id
            FOREIGN KEY (candidate_id) REFERENCES candidates (id)
            ON DELETE SET NULL NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT fk_b2b_generated_contracts_job_id
            FOREIGN KEY (job_id) REFERENCES jobs (id)
            ON DELETE SET NULL NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT fk_b2b_generated_contracts_client_id
            FOREIGN KEY (client_id) REFERENCES clients (id)
            ON DELETE SET NULL NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT fk_b2b_generated_contracts_contract_id
            FOREIGN KEY (contract_id) REFERENCES contracts (id)
            ON DELETE RESTRICT NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT fk_b2b_generated_contracts_signed_by_user_id
            FOREIGN KEY (signed_by_user_id) REFERENCES users (id)
            ON DELETE SET NULL NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_contract_status
            CHECK (contract_status IN ('active', 'closed')) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_closure_reason
            CHECK (
                closure_reason IS NULL OR
                closure_reason IN (
                    'resignation_before_signing',
                    'termination',
                    'mutual_agreement',
                    'other'
                )
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_closure_coherence
            CHECK (
                (
                    contract_status = 'active'
                    AND closure_reason IS NULL
                    AND closure_date IS NULL
                    AND closure_reason_other IS NULL
                ) OR (
                    contract_status = 'closed'
                    AND closure_reason IS NOT NULL
                    AND closure_date IS NOT NULL
                    AND (
                        (closure_reason = 'other')
                        = (closure_reason_other IS NOT NULL)
                    )
                )
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
]

# ── Indeksy zadeklarowane w ORM (index=True), których nie tworzy żadna migracja ──
# Zmierzone na produkcji 2026-07-20. Wszystkie NIEUNIKALNE, więc to strata
# wydajności, nie integralności (brakujących UNIQUE jest zero).
#
# Najlepiej udokumentowany koszt: calendar_events.external_id odpytywane przez
# ical_import.py:255,281 RAZ NA KAŻDE wydarzenie — bez indeksu każdy import
# kalendarza skanuje tabelę tyle razy, ile ma VEVENT-ów. Dziesięć pozycji to
# kolumny external_id, czyli klucze, po których integracje odnajdują rekordy.
#
# CONCURRENTLY, bo stary kontener może jeszcze obsługiwać ruch podczas startu
# nowego — zwykły CREATE INDEX brałby ACCESS EXCLUSIVE i blokował zapisy.
# IF NOT EXISTS sprawia, że kolejne starty są natychmiastowe.
#
# UWAGA: ta lista jest KRÓTSZA niż _INDEXES w migracji 0180 i tak ma być.
# Tu są 30 indeksów zmierzonych jako brakujące NA PRODUKCJI; migracja tworzy
# unię 36 z pomiarem CI, żeby świeża baza (odtworzenie, nowe środowisko)
# dostała komplet. Sześć różnicy produkcja już ma — m.in.
# ix_champion_profile_suggestions_job_id, ix_proposal_snapshots_job_id,
# ix_rate_benchmarks_role/_seniority,
# ix_delivery_lead_client_assignments_delivery_lead_user_id. Dopisywanie ich
# tutaj byłoby martwym kodem: CREATE INDEX IF NOT EXISTS i tak by je pominął.
_INDEX_STATEMENTS = [
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_rbac_reconciliation_open "
    "ON rbac_relationship_reconciliation (issue_kind, created_at) "
    "WHERE resolved_at IS NULL",
    "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
    "ux_client_tac_one_first_priority_client "
    "ON client_tac_assignments (tac_user_id) "
    "WHERE is_first_priority_for_tac IS TRUE",
    "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_user_cc_one_primary "
    "ON user_competence_categories (user_id) WHERE priority = 1",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_activities_external_id ON activities (external_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_analytics_metric_snapshots_module ON analytics_metric_snapshots (module)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_analytics_metric_snapshots_period_label ON analytics_metric_snapshots (period_label)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_calendar_events_external_id ON calendar_events (external_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_calendar_events_external_source ON calendar_events (external_source)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_calls_contract_id ON calls (contract_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_candidate_stages_external_id ON candidate_stages (external_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_candidate_stages_rejection_reason_id ON candidate_stages (rejection_reason_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_candidate_documents_document_kind ON candidate_documents (document_kind)",
    "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_candidate_documents_active_primary_cv "
    "ON candidate_documents (candidate_id) WHERE is_primary IS TRUE "
    "AND source_deleted_at IS NULL AND document_kind = 'cv'",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_candidates_availability_status ON candidates (availability_status)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_candidates_competence_category_id ON candidates (competence_category_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_candidates_created_by ON candidates (created_by)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_candidates_external_id ON candidates (external_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_clients_external_id ON clients (external_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_contacts_external_id ON contacts (external_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_contracts_client_order_end_date ON contracts (client_order_end_date)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_contracts_termination_reason ON contracts (termination_reason)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_dr_client_mrr_client_id ON dr_client_mrr (client_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_dr_sales_leads_user_id ON dr_sales_leads (user_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_dr_sales_offers_user_id ON dr_sales_offers (user_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_competence_category_id ON jobs (competence_category_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_delivery_lead_id ON jobs (delivery_lead_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_external_id ON jobs (external_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_needs_sourcing ON jobs (needs_sourcing)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_train_name ON jobs (train_name)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notes_contract_id ON notes (contract_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notifications_related_entity_id ON notifications (related_entity_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_pipeline_stage_defs_external_id ON pipeline_stage_defs (external_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_pipeline_templates_external_id ON pipeline_templates (external_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_talent_pools_competence_category_id ON talent_pools (competence_category_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_talent_pools_external_id ON talent_pools (external_id)",
]


async def _ensure_profile_rate_numeric(conn):
    """Run the hot-table ALTER only when needed and never wait indefinitely."""

    table_exists = await conn.fetchval(_PROFILE_RATE_TABLE_QUERY)
    if not table_exists:
        # A fresh/debug database is completed by metadata.create_all below.
        print("backfill profile rate type: candidates table not present; skipped")
        return True
    current_type = await conn.fetchval(_PROFILE_RATE_TYPE_QUERY)
    if current_type is None:
        # create_all does not add columns to an existing table. The application
        # lifespan performs the final fail-closed assertion and refuses traffic.
        print("backfill profile rate type: required column is missing")
        return False
    if current_type == _PROFILE_RATE_TARGET_TYPE:
        return True

    try:
        async with conn.transaction():
            await conn.execute("SET LOCAL lock_timeout = '5s'")
            await conn.execute("SET LOCAL statement_timeout = '30s'")
            # Another starting container may have completed the conversion
            # between the catalog probe and this bounded transaction.
            current_type = await conn.fetchval(_PROFILE_RATE_TYPE_QUERY)
            if current_type != _PROFILE_RATE_TARGET_TYPE:
                await conn.execute(_PROFILE_RATE_ALTER_SQL)
    except Exception as exc:
        print(f"backfill profile rate type skipped safely -> {exc!r}")
        return False

    verified_type = await conn.fetchval(_PROFILE_RATE_TYPE_QUERY)
    if verified_type != _PROFILE_RATE_TARGET_TYPE:
        print(
            "backfill profile rate type verification failed: "
            f"observed={verified_type!r}"
        )
        return False
    return True


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
        await _ensure_profile_rate_numeric(conn)
        for stmt in _DATA_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception as e:
                print(f"backfill data skip: {stmt!r} -> {e!r}")
        for stmt in _CONSTRAINT_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception as e:
                print(f"backfill constraint skip: {stmt!r} -> {e!r}")
        # Indeksy na końcu: najwolniejsze i najmniej krytyczne. Limit czasu na
        # instrukcję, żeby jeden wolny CREATE INDEX nie zawiesił startu
        # kontenera — nieudany indeks powtórzy się przy następnym starcie,
        # zablokowany deploy trzeba ratować ręcznie.
        try:
            await conn.execute("SET statement_timeout = '120s'")
        except Exception as e:
            print(f"backfill: nie udało się ustawić statement_timeout -> {e!r}")
        try:
            for stmt in _INDEX_STATEMENTS:
                try:
                    await conn.execute(stmt)
                except Exception as e:
                    print(f"backfill index skip: {stmt!r} -> {e!r}")
        finally:
            # W finally, nie po pętli: wyjątki w środku są łykane, więc w
            # praktyce reset zawsze się wykonywał — ale gdyby cokolwiek
            # wypropagowało (np. zerwane połączenie), limit zostałby ustawiony
            # na tym połączeniu. Ta ścieżka biegnie przy każdym deployu.
            try:
                await conn.execute("SET statement_timeout = 0")
            except Exception:
                pass
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

# Recruitment Priority Lock: metadata.create_all creates the new tables, but
# cannot add foreign keys to the already-existing recruitment_processes table.
# Install those links only after both sides exist. Every statement is rerun-safe
# and mirrors migration 0200.
echo "Finalizing Recruitment Priority Work schema (idempotent)..."
python - <<'PY' || echo "priority work schema finalization failed; continuing"
import asyncio
from sqlalchemy import text
from app.core.database import engine

_FKS = (
    (
        "fk_process_origin_priority_assignment",
        "origin_assignment_id",
        "recruitment_priority_assignments",
    ),
    (
        "fk_process_eligibility_priority_assignment",
        "eligibility_assignment_id",
        "recruitment_priority_assignments",
    ),
    ("fk_process_opened_by_user", "opened_by_user_id", "users"),
    ("fk_process_credit_user", "credit_user_id", "users"),
    (
        "fk_process_ownership_confirmed_by_user",
        "ownership_confirmed_by_user_id",
        "users",
    ),
)

# Każdy krok idzie w OSOBNEJ, ograniczonej czasowo transakcji.
#
# Wcześniej całość leciała w jednej transakcji bez lock_timeout, a ALTER TABLE
# ... ADD CONSTRAINT bierze ACCESS EXCLUSIVE na gorącym recruitment_processes.
# Na obciążonej produkcji potrafił więc czekać bez końca — a czekając w kolejce
# po ten zamek blokował KAŻDEGO czytelnika tabeli. To nie jest awaria, tylko
# zwis, więc `|| echo ... continuing` na dole nigdy by go nie złapał.
# Przy okazji jedna wywrotka kasowała też INSERT singletona i trzy CREATE INDEX
# z tej samej transakcji.
#
# NOT VALID świadomie, tak jak w _CONSTRAINT_STATEMENTS wyżej: więz działa dla
# nowych zapisów (łącznie z ON DELETE SET NULL) bez skanowania całej tabeli pod
# ACCESS EXCLUSIVE. VALIDATE CONSTRAINT można odpalić później, świadomie.
#
# Awaria każdego kroku jest MIĘKKA: logujemy i idziemy dalej, następny deploy
# ponowi. Ten skrypt nigdy nie może zatrzymać startu kontenera.
_LOCK_TIMEOUT = "5s"
_STATEMENT_TIMEOUT = "120s"


def _process_fk_sql(name, column, target):
    return f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint AS constraint_row
                JOIN pg_attribute AS source_column
                  ON source_column.attrelid = constraint_row.conrelid
                 AND source_column.attnum = ANY(constraint_row.conkey)
                WHERE constraint_row.contype = 'f'
                  AND constraint_row.conrelid =
                      'recruitment_processes'::regclass
                  AND constraint_row.confrelid = '{target}'::regclass
                  AND source_column.attname = '{column}'
            ) THEN
                ALTER TABLE recruitment_processes
                    ADD CONSTRAINT {name}
                    FOREIGN KEY ({column}) REFERENCES {target}(id)
                    ON DELETE SET NULL NOT VALID;
            END IF;
        END $$
    """


_INVITE_FK_SQL = """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint AS constraint_row
            JOIN pg_attribute AS source_column
              ON source_column.attrelid = constraint_row.conrelid
             AND source_column.attnum = ANY(constraint_row.conkey)
            WHERE constraint_row.contype = 'f'
              AND constraint_row.conrelid =
                  'candidate_invite_links'::regclass
              AND constraint_row.confrelid =
                  'recruitment_priority_assignments'::regclass
              AND source_column.attname = 'origin_assignment_id'
        ) THEN
            ALTER TABLE candidate_invite_links
                ADD CONSTRAINT fk_invite_link_origin_priority_assignment
                FOREIGN KEY (origin_assignment_id)
                REFERENCES recruitment_priority_assignments(id)
                ON DELETE SET NULL NOT VALID;
        END IF;
    END $$
"""

_INDEXES = (
    (
        "ix_candidate_invite_links_origin_assignment_id",
        "CREATE INDEX IF NOT EXISTS "
        "ix_candidate_invite_links_origin_assignment_id "
        "ON candidate_invite_links (origin_assignment_id)",
    ),
    (
        "ix_recruitment_processes_origin_assignment_id",
        "CREATE INDEX IF NOT EXISTS "
        "ix_recruitment_processes_origin_assignment_id "
        "ON recruitment_processes (origin_assignment_id)",
    ),
    (
        "ix_recruitment_processes_eligibility_assignment_id",
        "CREATE INDEX IF NOT EXISTS "
        "ix_recruitment_processes_eligibility_assignment_id "
        "ON recruitment_processes (eligibility_assignment_id)",
    ),
)


async def _guarded(label, statement):
    """Jeden krok schematu. Nigdy nie podnosi wyjątku — zwraca True/False."""
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
            await conn.execute(
                text(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT}'")
            )
            await conn.execute(text(statement))
    except Exception as exc:  # noqa: BLE001 - start kontenera jest ważniejszy
        print(f"priority work schema finalization: {label} pominięte -> {exc!r}")
        return False
    return True

async def finalize():
    steps = [
        (name, _process_fk_sql(name, column, target))
        for name, column, target in _FKS
    ]
    steps.append((
        "recruitment_priority_state singleton",
        "INSERT INTO recruitment_priority_state (id) VALUES (1) "
        "ON CONFLICT (id) DO NOTHING",
    ))
    steps.append(("fk_invite_link_origin_priority_assignment", _INVITE_FK_SQL))
    steps.extend(_INDEXES)

    results = [await _guarded(label, statement) for label, statement in steps]
    if all(results):
        print("priority work schema finalization: ok")
    else:
        print(
            "priority work schema finalization: częściowa "
            f"({sum(results)}/{len(results)}) — następny deploy ponowi"
        )

asyncio.run(finalize())
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

# Apply the checked-in client-portfolio manifest exactly once per source hash.
# This command is intentionally fail-closed on first apply and has no
# ``|| ... continuing``: the importer validates the complete plan under a
# transaction-scoped advisory lock, commits only a successful all-or-nothing
# apply, and exits non-zero after rolling back on any first-apply blocker,
# manifest digest mismatch, or exception.  A previously applied hash is a
# read-only no-op, so ordinary container restarts remain safe.
#
# One deliberate exception keeps a healthy import from taking prod down: when
# the manifest is already applied and the ONLY blocker is post-apply live drift
# (a scope archived/edited in the app after import), the command exits 0 and
# startup continues.  That drift is reported by /api/health/deep as degraded
# instead of crash-looping the whole backend on every restart.
echo "Applying client portfolio manifest (transactional apply-once)..."
python -m app.cli.client_portfolio_import --apply-once

# Start the application
echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
