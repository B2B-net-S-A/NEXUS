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
        /tmp/nexus/uploads/finance_imports \
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
import asyncio, json, os, re
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
    # Section RBAC (0268): Talent Community Manager persona.
    "ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'talent_community_manager'",
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
    # 0224: masowe uzupełnianie pól z CV (Fala 3) — osobny kubełek kwoty
    "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_backfill'",
    # 0230: cykliczna ekstrakcja faktów z notatek (notes_insights_sync)
    "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'notes_extraction'",
    "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'champion_profile_parse'",
    # 0240: generator CV B2B (`cv_generator`) i MINDY (`mindy_chat`) — dwie
    # powierzchnie Claude'a, które dotąd nie miały czym być ograniczone. Bez
    # tych wartości seed niżej ORAZ każdy INSERT do ai_usage_log przy generacji
    # CV / odpowiedzi MINDY lecą InvalidTextRepresentationError.
    "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_generator'",
    "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'mindy_chat'",
    # 0267: lint instrukcji klienta dla generatora CV (`cv_rule_lint`) —
    # osobny kubełek kwoty; bez wartości enuma seed niżej i INSERT do
    # ai_usage_log przy lincie => InvalidTextRepresentationError.
    "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_rule_lint'",
    # 0233: cotygodniowy digest dopasowań (match_digest_loop)
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'match_digest'",
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
    # Migracja 0241: stempel ostrzeżenia o zużyciu AI. Bez tych kolumn pętla
    # `ai_spend_alerts` pada na UndefinedColumnError przy KAŻDYM przebiegu —
    # a prod alembic bywa osierocony, więc lustro jest tu jedyną gwarancją.
    "ALTER TABLE ai_features ADD COLUMN IF NOT EXISTS spend_alert_period DATE NULL",
    "ALTER TABLE ai_features ADD COLUMN IF NOT EXISTS spend_alert_level INTEGER NULL",
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
    # 0224: usunięcie kandydata NIE kasuje umowy. Bez tego lustra hard delete
    # na prodzie z osieroconym alembicem poleciałby kaskadą przez `contracts`
    # i zabrał ze sobą `invoices`, `document_signatures` i `client_orders` —
    # dokumenty księgowe i dowodowe, które nie mają własnego FK na kandydata.
    """ALTER TABLE contracts
       ADD COLUMN IF NOT EXISTS candidate_subject_ref VARCHAR(64) NULL""",
    "ALTER TABLE contracts ALTER COLUMN candidate_id DROP NOT NULL",
    # DROP po INTROSPEKCJI, nie po nazwie: sweep 0146 nadał tym więzom nazwy
    # generowane, a starsze bazy mają nazwę z czasów `create_table`. Kasowanie
    # po zgadniętej nazwie zostawiłoby stary CASCADE i lustro byłoby bezczynne.
    """DO $$
        DECLARE con RECORD;
    BEGIN
        FOR con IN
            SELECT c.conname
              FROM pg_constraint c
              JOIN pg_attribute a
                ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
             WHERE c.conrelid = 'contracts'::regclass
               AND c.contype = 'f'
               AND c.confrelid = 'candidates'::regclass
               AND a.attname = 'candidate_id'
        LOOP
            EXECUTE format('ALTER TABLE contracts DROP CONSTRAINT %I', con.conname);
        END LOOP;
    END $$""",
    """DO $$ BEGIN
        ALTER TABLE contracts
            ADD CONSTRAINT contracts_candidate_id_candidates_fkey
            FOREIGN KEY (candidate_id) REFERENCES candidates (id)
            ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """CREATE INDEX IF NOT EXISTS ix_contracts_candidate_subject_ref
       ON contracts (candidate_subject_ref)""",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS legal_name VARCHAR(255)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS nip VARCHAR(32)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS regon VARCHAR(32)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS business_address TEXT",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS business_form VARCHAR(64)",
    # Nagrobek: Traffit odpowiedział, że tego rekordu u niego nie ma
    # (migracja 0221). Indeks CZĘŚCIOWY — nagrobki są rzadkie, więc pełny
    # kosztowałby tyle co skan 57 tys. wierszy.
    """ALTER TABLE candidates
        ADD COLUMN IF NOT EXISTS external_deleted_at TIMESTAMP WITH TIME ZONE NULL""",
    """CREATE INDEX IF NOT EXISTS ix_candidates_external_deleted_at
        ON candidates (external_deleted_at)
        WHERE external_deleted_at IS NOT NULL""",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS legal_name VARCHAR(255)",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS nip VARCHAR(32)",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS regon VARCHAR(32)",
    # Auto-assign TAC + Delivery Lead do projektów (migracje 0059/0060).
    # Bez tych kolumn prod backend crashuje na `SELECT jobs.tac_id` (ORM
    # deklaruje kolumnę w `app.models.job.Job` od commit c57c944).
    # Safety-net chroni prod gdyby alembic upgrade nie wszedł (multi-head).
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tac_id INTEGER NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS rate_budget_hourly NUMERIC(8,2) NULL",
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
    # 0269: configurable product-section RBAC. The tables are created here as
    # an idempotent recovery path when Alembic stopped before stamping head.
    """CREATE TABLE IF NOT EXISTS rbac_policy_state (
           id INTEGER PRIMARY KEY,
           revision BIGINT NOT NULL DEFAULT 1,
           updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           CONSTRAINT ck_rbac_policy_state_singleton CHECK (id = 1),
           CONSTRAINT ck_rbac_policy_state_revision_positive CHECK (revision > 0)
       )""",
    """CREATE TABLE IF NOT EXISTS rbac_role_section_permissions (
           role VARCHAR(64) NOT NULL,
           section VARCHAR(32) NOT NULL,
           access VARCHAR(16) NOT NULL,
           updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           PRIMARY KEY (role, section),
           CONSTRAINT ck_rbac_role_section_permissions_role CHECK (
               role IN ('admin','head_of_recruitment','delivery_lead','talent_community_manager','finance','tac','recruiter','sourcer','user')
           ),
           CONSTRAINT ck_rbac_role_section_permissions_section CHECK (
               section IN ('sourcing','pipeline','delivery','insights','finance','system_admin')
           ),
           CONSTRAINT ck_rbac_role_section_permissions_access CHECK (
               access IN ('none','read','write')
           )
       )""",
    """CREATE TABLE IF NOT EXISTS rbac_user_section_overrides (
           user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
           section VARCHAR(32) NOT NULL,
           access VARCHAR(16) NOT NULL,
           updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           PRIMARY KEY (user_id, section),
           CONSTRAINT ck_rbac_user_section_overrides_section CHECK (
               section IN ('sourcing','pipeline','delivery','insights','finance','system_admin')
           ),
           CONSTRAINT ck_rbac_user_section_overrides_access CHECK (
               access IN ('none','read','write')
           )
       )""",
    # 0273: granular action permissions. Section access remains the outer
    # ceiling; these rows distinguish register view, document generation and
    # management without granting the Finance section.
    """CREATE TABLE IF NOT EXISTS rbac_role_action_permissions (
           role VARCHAR(64) NOT NULL,
           action VARCHAR(64) NOT NULL,
           access VARCHAR(16) NOT NULL,
           updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           PRIMARY KEY (role, action),
           CONSTRAINT ck_rbac_role_action_permissions_role CHECK (
               role IN ('admin','head_of_recruitment','delivery_lead','talent_community_manager','finance','tac','recruiter','sourcer','user')
           ),
           CONSTRAINT ck_rbac_role_action_permissions_action CHECK (
               action IN ('b2b_contract_generator')
           ),
           CONSTRAINT ck_rbac_role_action_permissions_access CHECK (
               access IN ('none','view','generate','manage')
           )
       )""",
    """CREATE TABLE IF NOT EXISTS rbac_user_action_overrides (
           user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
           action VARCHAR(64) NOT NULL,
           access VARCHAR(16) NOT NULL,
           updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           PRIMARY KEY (user_id, action),
           CONSTRAINT ck_rbac_user_action_overrides_action CHECK (
               action IN ('b2b_contract_generator')
           ),
           CONSTRAINT ck_rbac_user_action_overrides_access CHECK (
               access IN ('none','view','generate','manage')
           )
       )""",
    """CREATE TABLE IF NOT EXISTS rbac_permission_audit (
           id BIGSERIAL PRIMARY KEY,
           actor_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           target_kind VARCHAR(16) NOT NULL,
           target_key VARCHAR(128) NOT NULL,
           revision BIGINT NOT NULL,
           before JSONB NOT NULL,
           after JSONB NOT NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           CONSTRAINT ck_rbac_permission_audit_target_kind CHECK (
               target_kind IN ('role','user')
           ),
           CONSTRAINT ck_rbac_permission_audit_revision_positive CHECK (revision > 0)
       )""",
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
    # Surowy payload `/render` (migracja 0132). Bez tego wpisu lustro nie tworzy
    # kolumny, a backfill w `_DATA_STATEMENTS` niżej czyta z niej dane Partnera —
    # milcząco spadłby do `backfill data skip: ... UndefinedColumn`.
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS render_payload JSONB NULL""",
    # Snapshot danych Partnera + data rozpoczęcia usług (migracja 0224).
    # Odnormalizowane z `render_payload`, bo lista „Wygenerowane umowy" pokazuje
    # te pola jako kolumny i filtruje po `start_date` po stronie SQL-a.
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS partner_legal_name VARCHAR(255) NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS partner_nip VARCHAR(32) NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS start_date DATE NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS partner_entity_type VARCHAR(16) NULL""",
    # Dziennik zmian statusu umowy (migracja 0226). CREATE TABLE leci TUTAJ,
    # a nie przez `Base.metadata.create_all` niżej: tamten blok jest jedną
    # transakcją i na produkcji potrafi paść w całości przez jedną złą tabelę
    # (incydent Cortex, PR #664), zostawiając „metadata create_all failed;
    # continuing" i UndefinedTable na żywym endpointcie.
    #
    # Powrót z „Zawieszonej" na „Aktywną" MUSI wyczyścić `closure_*` (wymusza to
    # ck_..._closure_coherence), więc bez tej tabeli data i powód zakończenia
    # poprzedniego projektu przepadają bezpowrotnie.
    """CREATE TABLE IF NOT EXISTS b2b_generated_contract_status_events (
           id SERIAL PRIMARY KEY,
           generated_contract_id INTEGER NOT NULL
               REFERENCES b2b_generated_contracts (id) ON DELETE CASCADE,
           from_status VARCHAR(16) NULL,
           to_status VARCHAR(16) NOT NULL,
           effective_date DATE NULL,
           reason VARCHAR(32) NULL,
           reason_other TEXT NULL,
           job_id INTEGER NULL REFERENCES jobs (id) ON DELETE SET NULL,
           client_id INTEGER NULL REFERENCES clients (id) ON DELETE SET NULL,
           changed_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now()
       )""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_gc_status_events_contract
       ON b2b_generated_contract_status_events (generated_contract_id)""",
    # ── Zamówienia wielo-konsultantowe (migracja 0227) ────────────────────
    # Grupa („Zamówienie nr 445") NAD istniejącymi client_orders. Kolejność ma
    # znaczenie: client_order_groups musi powstać przed kolumną FK w
    # client_orders, a client_orders przed tabelami, które go referencjonują.
    """CREATE TABLE IF NOT EXISTS client_order_groups (
           id SERIAL PRIMARY KEY,
           client_id INTEGER NOT NULL REFERENCES clients (id) ON DELETE CASCADE,
           order_number VARCHAR(64) NOT NULL,
           start_date DATE NOT NULL,
           end_date DATE NULL,
           notes TEXT NULL,
           created_by_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_client_order_groups_dates
               CHECK (end_date IS NULL OR end_date >= start_date)
       )""",
    """CREATE INDEX IF NOT EXISTS ix_client_order_groups_client
       ON client_order_groups (client_id)""",
    """ALTER TABLE client_orders
       ADD COLUMN IF NOT EXISTS order_group_id INTEGER NULL
       REFERENCES client_order_groups (id) ON DELETE SET NULL""",
    """CREATE INDEX IF NOT EXISTS ix_client_orders_order_group
       ON client_orders (order_group_id)""",
    """ALTER TABLE client_orders
       ADD COLUMN IF NOT EXISTS md_rate_cost NUMERIC(12, 2) NULL""",
    """ALTER TABLE client_orders
       ADD COLUMN IF NOT EXISTS md_rate_revenue NUMERIC(12, 2) NULL""",
    """ALTER TABLE client_orders
       ADD COLUMN IF NOT EXISTS md_input_mode VARCHAR(8) NULL""",
    """ALTER TABLE client_orders
       ADD COLUMN IF NOT EXISTS md_input_value NUMERIC(16, 6) NULL""",
    """ALTER TABLE client_orders
       ADD COLUMN IF NOT EXISTS md_total NUMERIC(16, 6) NULL""",
    """ALTER TABLE client_orders
       ADD COLUMN IF NOT EXISTS md_remaining NUMERIC(16, 6) NULL""",
    """ALTER TABLE client_orders
       ADD COLUMN IF NOT EXISTS md_manual_adjustment NUMERIC(16, 6)
       NOT NULL DEFAULT 0""",
    """ALTER TABLE client_orders
       ADD COLUMN IF NOT EXISTS predecessor_order_id INTEGER NULL
       REFERENCES client_orders (id) ON DELETE SET NULL""",
    # Linia MD jest albo kompletna, albo jej nie ma. `md_rate_revenue` jest
    # dzielnikiem przy przeliczaniu kwoty na MD i przy zamianie kontraktora,
    # więc zero/NULL przy wypełnionym budżecie musi odpaść w bazie, a nie
    # dopiero jako DivisionByZero w środku transakcji. NOT VALID — istniejące
    # wiersze mają same NULL-e, więc i tak spełniają pierwszą gałąź.
    """DO $$ BEGIN
        ALTER TABLE client_orders
            ADD CONSTRAINT ck_client_orders_md_coherence
            CHECK (
                (
                    md_total IS NULL
                    AND md_remaining IS NULL
                    AND md_input_mode IS NULL
                    AND md_input_value IS NULL
                    AND md_rate_revenue IS NULL
                )
                OR (
                    md_total IS NOT NULL
                    AND md_remaining IS NOT NULL
                    AND md_input_mode IN ('md', 'amount')
                    AND md_input_value IS NOT NULL
                    AND md_rate_revenue IS NOT NULL
                    AND md_rate_revenue > 0
                )
            )
            NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$""",
    """CREATE TABLE IF NOT EXISTS md_consumption_imports (
           id SERIAL PRIMARY KEY,
           period_month VARCHAR(7) NOT NULL,
           filename VARCHAR(255) NULL,
           rows_total INTEGER NOT NULL DEFAULT 0,
           rows_applied INTEGER NOT NULL DEFAULT 0,
           rows_ambiguous INTEGER NOT NULL DEFAULT 0,
           rows_unmatched INTEGER NOT NULL DEFAULT 0,
           uploaded_by_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_md_consumption_imports_period
               CHECK (period_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$')
       )""",
    """CREATE TABLE IF NOT EXISTS md_consumption_import_rows (
           id SERIAL PRIMARY KEY,
           import_id INTEGER NOT NULL
               REFERENCES md_consumption_imports (id) ON DELETE CASCADE,
           row_number INTEGER NOT NULL,
           consultant_name VARCHAR(255) NOT NULL,
           md_reported NUMERIC(16, 6) NOT NULL,
           status VARCHAR(24) NOT NULL,
           matched_order_id INTEGER NULL
               REFERENCES client_orders (id) ON DELETE SET NULL,
           candidate_order_ids JSONB NULL,
           resolved_by_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           resolved_at TIMESTAMPTZ NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_md_import_rows_status
               CHECK (status IN ('applied', 'needs_assignment', 'unmatched'))
       )""",
    """CREATE INDEX IF NOT EXISTS ix_md_import_rows_import
       ON md_consumption_import_rows (import_id)""",
    """CREATE INDEX IF NOT EXISTS ix_md_import_rows_status
       ON md_consumption_import_rows (status)""",
    """CREATE TABLE IF NOT EXISTS client_order_md_consumptions (
           id SERIAL PRIMARY KEY,
           order_id INTEGER NOT NULL
               REFERENCES client_orders (id) ON DELETE CASCADE,
           period_month VARCHAR(7) NOT NULL,
           md_reported NUMERIC(16, 6) NOT NULL,
           import_id INTEGER NULL
               REFERENCES md_consumption_imports (id) ON DELETE SET NULL,
           source VARCHAR(16) NOT NULL,
           created_by_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_md_consumptions_source
               CHECK (source IN ('import', 'manual')),
           CONSTRAINT ck_md_consumptions_period
               CHECK (period_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$')
       )""",
    # UNIQUE, nie zwykły indeks — to on czyni import idempotentnym. Bez niego
    # powtórka miesiąca dokłada drugi wiersz i MD odejmują się dwa razy.
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_md_consumptions_order_month
       ON client_order_md_consumptions (order_id, period_month)""",
    """CREATE TABLE IF NOT EXISTS client_order_group_events (
           id SERIAL PRIMARY KEY,
           group_id INTEGER NOT NULL
               REFERENCES client_order_groups (id) ON DELETE CASCADE,
           order_id INTEGER NULL REFERENCES client_orders (id) ON DELETE SET NULL,
           event_type VARCHAR(32) NOT NULL,
           description TEXT NOT NULL,
           payload JSONB NULL,
           created_by_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_client_order_group_events_type
               CHECK (event_type IN ('utworzenie', 'dodanie_konsultanta',
                                     'import_md', 'zamiana_kontraktora',
                                     'edycja_reczna', 'zakonczenie',
                                     'przywrocenie', 'wyczerpanie',
                                     'przedluzenie', 'import_faktur',
                                     'transfer_md',
                                     'zakonczenie_konsultanta',
                                     'decyzja_md_wymagana',
                                     'usuniecie_puli_md',
                                     'przeniesienie_puli_md'))
       )""",
    """CREATE INDEX IF NOT EXISTS ix_client_order_group_events_group
       ON client_order_group_events (group_id)""",
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
    # 0257: dni robocze uzytkownika w oknie czasu — mianownik wskaznikow
    # „na dzien" (D5). Do 2026-08-31 Power Calling dzielil przez sztywne 5
    # i publikowal imienna liste „ponizej progu", wiec osoba na urlopie
    # ladowala na niej pod nazwiskiem.
    #
    # Trzymamy WYLACZNIE liczby dni — nigdy typu nieobecnosci ani notatki
    # (dane o zdrowiu). Okno, nie miesiac: Power Calling raportuje tydzien ISO,
    # a wskazniki MD miesiac; przyblizanie jednego z drugiego byloby zgadywaniem.
    #
    # Po dodaniu tabeli TUTAJ dopisz ja tez do `core_checks` (/api/health/deep) —
    # prod alembic bywa osierocony, wiec to jest jedyny realny dowod wdrozenia.
    """CREATE TABLE IF NOT EXISTS user_workday_periods (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        period_start DATE NOT NULL,
        period_end DATE NOT NULL,
        business_days INTEGER NOT NULL,
        absence_days NUMERIC(5,1) NOT NULL,
        working_days NUMERIC(5,1) NOT NULL,
        basis VARCHAR(64) NOT NULL DEFAULT 'business_days_minus_approved_leave',
        source VARCHAR(32) NOT NULL DEFAULT 'compass',
        synced_at TIMESTAMPTZ DEFAULT now(),
        CONSTRAINT uq_user_workday_period UNIQUE (user_id, period_start, period_end)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_user_workday_periods_user_id "
    "ON user_workday_periods (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_user_workday_periods_window "
    "ON user_workday_periods (period_start, period_end)",
    # 0258: plakietki ostrzezen przy osobie („slabe wyniki", „procedury").
    # Wygaszamy, nie kasujemy — CHECK spojnosci jest tu, bo to on, a nie kod,
    # trzyma niezmiennik: aktywna plakietka NIE ma daty zdjecia, a zdjeta MA.
    # Bez tabeli caly panel plakietek zwracalby 500 na kazdym odczycie.
    """CREATE TABLE IF NOT EXISTS user_performance_flags (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        flag_type VARCHAR(32) NOT NULL,
        note TEXT,
        is_active BOOLEAN NOT NULL DEFAULT true,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        cleared_at TIMESTAMPTZ,
        cleared_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        CONSTRAINT ck_user_performance_flags_type
            CHECK (flag_type IN ('weak_results', 'procedures')),
        CONSTRAINT ck_user_performance_flags_clear_coherence
            CHECK ((is_active AND cleared_at IS NULL AND cleared_by IS NULL)
                   OR (NOT is_active AND cleared_at IS NOT NULL))
    )""",
    "CREATE INDEX IF NOT EXISTS ix_user_performance_flags_user_id "
    "ON user_performance_flags (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_user_performance_flags_active "
    "ON user_performance_flags (user_id, is_active)",
    # Unikalnosc CZESCIOWA: jedna AKTYWNA plakietka danego typu na osobe.
    # Pelny UNIQUE zablokowalby historie — druga plakietka po zdjeciu
    # pierwszej jest normalnym biegiem rzeczy.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_performance_flags_active_type "
    "ON user_performance_flags (user_id, flag_type) WHERE is_active",
    # 0259: baner kampanii rekrutacyjnej. CHECK na oknie, bo okno odwrocone
    # daje pusty przedzial — baner pokazalby „0 z N" i „0 dni do konca",
    # czyli liczby poprawne arytmetycznie, opisujace nieistniejaca kampanie.
    """CREATE TABLE IF NOT EXISTS recruitment_campaigns (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        emoji VARCHAR(16),
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        target_net INTEGER NOT NULL DEFAULT 0,
        is_active BOOLEAN NOT NULL DEFAULT false,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_recruitment_campaigns_window CHECK (end_date >= start_date)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_recruitment_campaigns_active "
    "ON recruitment_campaigns (is_active, start_date)",
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
    # 0248: osobne waluty przychodu i kosztu. Nullable zostają dla legacy
    # read fallbacku; trigger niżej synchronizuje zapisy starej wersji appki.
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS "
    "rate_client_currency VARCHAR(3) NULL",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS "
    "rate_candidate_currency VARCHAR(3) NULL",
    """CREATE OR REPLACE FUNCTION sync_contract_rate_currencies_from_legacy()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        normalized_currency VARCHAR(3) := COALESCE(
            NULLIF(UPPER(BTRIM(NEW.currency)), ''),
            'PLN'
        );
    BEGIN
        IF TG_OP = 'INSERT' THEN
            NEW.rate_client_currency := COALESCE(
                NEW.rate_client_currency,
                normalized_currency
            );
            NEW.rate_candidate_currency := COALESCE(
                NEW.rate_candidate_currency,
                normalized_currency
            );
        ELSIF NEW.currency IS DISTINCT FROM OLD.currency
           AND NEW.rate_client_currency IS NOT DISTINCT FROM OLD.rate_client_currency
           AND NEW.rate_candidate_currency IS NOT DISTINCT FROM OLD.rate_candidate_currency
        THEN
            NEW.rate_client_currency := normalized_currency;
            NEW.rate_candidate_currency := normalized_currency;
        END IF;
        IF COALESCE(
               NULLIF(UPPER(BTRIM(NEW.rate_client_currency)), ''),
               normalized_currency
           ) IS DISTINCT FROM COALESCE(
               NULLIF(UPPER(BTRIM(NEW.rate_candidate_currency)), ''),
               normalized_currency
           )
        THEN
            NEW.margin := NULL;
        END IF;
        RETURN NEW;
    END;
    $$""",
    # Nie rób DROP+CREATE w dwóch best-effort transakcjach: lock timeout między
    # nimi zostawiłby rolling deploy bez ochrony legacy writerów. Funkcja jest
    # już CREATE OR REPLACE; trigger tworzymy atomowo tylko, gdy go brak.
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_trigger
            WHERE tgname = 'trg_contract_rate_currencies_legacy_sync'
              AND tgrelid = 'contracts'::regclass
              AND NOT tgisinternal
        ) THEN
            CREATE TRIGGER trg_contract_rate_currencies_legacy_sync
            BEFORE INSERT OR UPDATE OF
                margin, currency, rate_client_currency, rate_candidate_currency
            ON contracts
            FOR EACH ROW
            EXECUTE FUNCTION sync_contract_rate_currencies_from_legacy();
        END IF;
    END
    $$""",
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
    # 0255: reguły CV per klient (nazwa pliku, język, blok zgody RODO).
    # CREATE TABLE idzie TU, a nie przez `Base.metadata.create_all` — tamten
    # blok to jedna transakcja i na prodzie potrafi paść w całości (incydent
    # Cortex, PR #664), zabierając ze sobą wszystkie pozostałe tabele.
    """CREATE TABLE IF NOT EXISTS client_cv_rules (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL
            REFERENCES clients(id) ON DELETE CASCADE,
        filename_pattern VARCHAR(300),
        spaces_to_underscores BOOLEAN NOT NULL DEFAULT FALSE,
        cv_language VARCHAR(8),
        requires_en_copy BOOLEAN NOT NULL DEFAULT FALSE,
        requires_rodo_consent_block BOOLEAN NOT NULL DEFAULT FALSE,
        notes TEXT,
        generator_instructions TEXT,
        seed_key VARCHAR(64),
        confirmed_at TIMESTAMPTZ,
        confirmed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    # 0266: instrukcje dla generatora AI — jedyne pole reguły, które trafia do
    # promptu. Istniejąca tabela (0255) nie ma tej kolumny, więc ALTER obok
    # CREATE TABLE wyżej.
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS generator_instructions TEXT",
    # 0267: reguła jako pełna recepta DL — blokady, polityka prezentacji
    # egzekwowana w kodzie, wersja + historia + CV próbne + stempel wersji
    # na wygenerowanym CV. Istniejąca tabela (0255) nie ma tych kolumn.
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS content_mode VARCHAR(16)",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS content_mode_locked "
    "BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS "
    "require_screening_notes_min_chars INTEGER",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS require_project_ref "
    "BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS require_position "
    "BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS require_champion "
    "BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS auto_second_language "
    "BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS omit_sections JSONB",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS max_roles INTEGER",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS max_bullets_per_role INTEGER",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS max_bullet_chars INTEGER",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS why_points_max INTEGER",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS date_format VARCHAR(16)",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS glossary JSONB",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS generator_instructions_en TEXT",
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS version "
    "INTEGER NOT NULL DEFAULT 1",
    """DO $$ BEGIN
        ALTER TABLE client_cv_rules
            ADD CONSTRAINT ck_client_cv_rules_content_mode
            CHECK (content_mode IS NULL
                   OR content_mode IN ('basic', 'polished', 'tailored'));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE client_cv_rules
            ADD CONSTRAINT ck_client_cv_rules_date_format
            CHECK (date_format IS NULL
                   OR date_format IN ('MM.YYYY', 'MM/YYYY', 'YYYY-MM', 'YYYY'));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE client_cv_rules
            ADD CONSTRAINT ck_client_cv_rules_limits_positive
            CHECK ((max_roles IS NULL OR max_roles > 0)
                   AND (max_bullets_per_role IS NULL OR max_bullets_per_role > 0)
                   AND (max_bullet_chars IS NULL OR max_bullet_chars >= 40)
                   AND (why_points_max IS NULL OR why_points_max > 0)
                   AND (require_screening_notes_min_chars IS NULL
                        OR require_screening_notes_min_chars >= 0));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """CREATE TABLE IF NOT EXISTS client_cv_rule_events (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        rule_version INTEGER NOT NULL,
        action VARCHAR(24) NOT NULL,
        changes JSONB,
        actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        actor_name VARCHAR(255),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_client_cv_rule_events_client_created "
    "ON client_cv_rule_events (client_id, created_at)",
    """CREATE TABLE IF NOT EXISTS client_cv_rule_previews (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        candidate_id INTEGER REFERENCES candidates(id) ON DELETE CASCADE,
        stage_id INTEGER,
        language VARCHAR(2) NOT NULL DEFAULT 'pl',
        status VARCHAR(20) NOT NULL DEFAULT 'processing',
        with_rule JSONB,
        without_rule JSONB,
        prompt_block TEXT,
        error_message VARCHAR(1000),
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_client_cv_rule_previews_client_created "
    "ON client_cv_rule_previews (client_id, created_at)",
    # 0272: karta klienta — standardy współpracy per klient (SLA, limity,
    # hold, onboarding, dokumenty). Sąsiad `client_cv_rules`: 1:1 z klientem,
    # wersja + historia. Lustro migracji 0272 — zmieniasz tu, zmień też tam.
    """CREATE TABLE IF NOT EXISTS client_playbooks (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        sla_business_days INTEGER,
        sla_min_candidates INTEGER,
        cv_limit_per_process INTEGER,
        hold_hours INTEGER,
        multi_project_cooldown_days INTEGER,
        rate_policy VARCHAR(500),
        about_for_candidate TEXT,
        priority_rules TEXT,
        process_rules_md TEXT,
        onboarding_md TEXT,
        documents JSONB,
        version INTEGER NOT NULL DEFAULT 1,
        seed_key VARCHAR(64),
        updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_client_playbooks_client "
    "ON client_playbooks (client_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_playbooks_seed_key "
    "ON client_playbooks (seed_key)",
    """DO $$ BEGIN
        ALTER TABLE client_playbooks
            ADD CONSTRAINT ck_client_playbooks_numbers
            CHECK ((sla_business_days IS NULL
                    OR (sla_business_days >= 0 AND sla_business_days <= 365))
                   AND (sla_min_candidates IS NULL OR sla_min_candidates > 0)
                   AND (cv_limit_per_process IS NULL OR cv_limit_per_process > 0)
                   AND (hold_hours IS NULL OR hold_hours > 0)
                   AND (multi_project_cooldown_days IS NULL
                        OR multi_project_cooldown_days > 0));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """CREATE TABLE IF NOT EXISTS client_playbook_events (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        playbook_version INTEGER NOT NULL,
        action VARCHAR(24) NOT NULL,
        changes JSONB,
        actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        actor_name VARCHAR(255),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_client_playbook_events_client_created "
    "ON client_playbook_events (client_id, created_at)",
    "ALTER TABLE cv_generated_documents ADD COLUMN IF NOT EXISTS "
    "client_rule_version INTEGER",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_client_cv_rules_client "
    "ON client_cv_rules (client_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_cv_rules_seed_key "
    "ON client_cv_rules (seed_key)",
    "CREATE INDEX IF NOT EXISTS ix_client_cv_rules_confirmed_at "
    "ON client_cv_rules (confirmed_at)",
    # Bez tego więzu ręczny UPDATE mógłby wpisać dowolny łańcuch jako język,
    # a walidacja generatora porównywałaby żądanie z wartością, której nie
    # umie wymusić — 422 na poprawnym żądaniu albo cicha zgoda na zły język.
    """DO $$ BEGIN
        ALTER TABLE client_cv_rules
            ADD CONSTRAINT ck_client_cv_rules_language
            CHECK (cv_language IS NULL OR cv_language IN ('pl', 'en'));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # 0256: konfigurowalna punktacja Insights (Liga Mistrzów + progi Ścieżki
    # rozwoju). CREATE TABLE idzie TU, a nie przez `Base.metadata.create_all` —
    # tamten blok to jedna transakcja i na prodzie potrafi paść w całości
    # (incydent Cortex, PR #664), zabierając ze sobą wszystkie pozostałe tabele.
    #
    # Brak tej tabeli nie wywraca Ligi: `get_scoring_config` degraduje się do
    # wartości domyślnych z kodu. Ale wtedy ekran ustawień przyjmuje zapis,
    # który znika — czyli awaria najgorszego rodzaju, bo cicha. Sondą jest
    # `insights_scoring_config` w `core_checks` (/api/health/deep).
    """CREATE TABLE IF NOT EXISTS insights_scoring_config (
        key VARCHAR(64) PRIMARY KEY,
        value INTEGER NOT NULL,
        updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    # 0255: klient wprost na wygenerowanym dokumencie. Tryb "upload" (99,9%
    # generacji) nie ma joba, więc bez tej kolumny klienta nie da się ani
    # zastosować, ani później odtworzyć.
    "ALTER TABLE cv_generated_documents ADD COLUMN IF NOT EXISTS "
    "client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_cv_generated_documents_client_id "
    "ON cv_generated_documents (client_id)",
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
    # 0237: liczniki dealbreakerów w snapshotcie ({"over_budget": N, ...}) —
    # budżet oferty działa z automatu jako twardy sufit (decyzja 19.08), a
    # ukrywanie nigdy nie jest ciche. ORM czyta kolumnę, brak =>
    # UndefinedColumnError na /proposals/latest.
    "ALTER TABLE proposal_snapshots ADD COLUMN IF NOT EXISTS hidden JSONB NULL",
    # 0238: trwały master PDF grupy zamówienia + źródło automatycznej kopii w
    # dokumentach kontraktu. Alembic bywa na prodzie osierocony, a metadata
    # create_all nie dodaje kolumn do istniejących tabel.
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS filename VARCHAR(255) NULL",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS file_path VARCHAR(512) NULL",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS content_type VARCHAR(128) NULL",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS size_bytes INTEGER NULL",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS file_uploaded_by INTEGER NULL",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS file_uploaded_at TIMESTAMPTZ NULL",
    "ALTER TABLE contract_documents ADD COLUMN IF NOT EXISTS source_order_group_id INTEGER NULL",
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
    # 0229: pozycja Pomocy może być SZABLONEM TREŚCI zamiast linku (zaproszenie
    # kalendarzowe nie jest plikiem w SharePoincie). `url` przestaje być
    # obowiązkowy, a treść trafia do `template_subject`/`template_body`.
    # DROP NOT NULL jest idempotentny — na kolumnie już nullable to no-op.
    # Kolejność ma znaczenie: `_DATA_STATEMENTS` niżej wstawia wiersz z
    # `url = NULL`, a `_CONSTRAINT_STATEMENTS` dokłada CHECK spójności.
    "ALTER TABLE help_materials ALTER COLUMN url DROP NOT NULL",
    "ALTER TABLE help_materials "
    "ADD COLUMN IF NOT EXISTS template_subject VARCHAR(255) NULL",
    "ALTER TABLE help_materials ADD COLUMN IF NOT EXISTS template_body TEXT NULL",
    # 0220: konta serwisowe + klucze API (nagłówek X-API-Key). Bez tych tabel
    # zależność ``require_service_scope`` wywala UndefinedTable na KAŻDYM
    # requeście z kluczem, a Ustawienia → API zwracają 500. Kolejność ma
    # znaczenie: klucze mają FK na konta.
    """CREATE TABLE IF NOT EXISTS service_accounts (
        id SERIAL PRIMARY KEY,
        slug VARCHAR(64) NOT NULL,
        name VARCHAR(120) NOT NULL,
        description TEXT,
        scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_service_accounts_scopes_array
            CHECK (jsonb_typeof(scopes) = 'array')
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_service_accounts_slug "
    "ON service_accounts (slug)",
    # PK = nie-sekretny revoke-key ``v2$<hex>``; sekret istnieje wyłącznie jako
    # SHA-256 w ``secret_sha256``. ``expires_at`` bez DEFAULT-u świadomie —
    # termin wylicza aplikacja, klucz bez terminu nie ma prawa powstać.
    """CREATE TABLE IF NOT EXISTS service_account_keys (
        key_id VARCHAR(64) PRIMARY KEY,
        service_account_id INTEGER NOT NULL
            REFERENCES service_accounts(id) ON DELETE CASCADE,
        secret_sha256 VARCHAR(64) NOT NULL,
        label VARCHAR(120) NOT NULL,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL,
        revoked_at TIMESTAMPTZ,
        revoked_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        revoke_reason VARCHAR(255),
        last_used_at TIMESTAMPTZ,
        last_used_ip VARCHAR(64)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_service_account_keys_service_account_id "
    "ON service_account_keys (service_account_id)",
    # 0227: moduł Finanse — import miesięcznych wyników kontraktorów.
    # `status` jako VARCHAR + CHECK (nie natywny enum PG): poszerzenie domeny
    # to wtedy DROP+ADD CHECK-a, a nie `ALTER TYPE ... ADD VALUE`, które
    # opakowane w `EXCEPTION WHEN duplicate_object` po pierwszym wykonaniu
    # nigdy więcej nie zadziała (lekcja z 0226).
    """CREATE TABLE IF NOT EXISTS finance_import_runs (
        id SERIAL PRIMARY KEY,
        period_year INTEGER NOT NULL,
        period_month INTEGER NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'current',
        source_filename VARCHAR(255) NOT NULL,
        file_path VARCHAR(512) NOT NULL,
        file_sha256 VARCHAR(64),
        size_bytes INTEGER,
        row_count INTEGER NOT NULL DEFAULT 0,
        needs_completion_count INTEGER NOT NULL DEFAULT 0,
        rejected_count INTEGER NOT NULL DEFAULT 0,
        rejected_details JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        superseded_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS finance_monthly_results (
        id SERIAL PRIMARY KEY,
        import_run_id INTEGER NOT NULL
            REFERENCES finance_import_runs(id) ON DELETE CASCADE,
        row_number INTEGER NOT NULL,
        consultant_name VARCHAR(255) NOT NULL,
        client_name VARCHAR(255),
        cost_rate_md NUMERIC(12,2),
        md_count NUMERIC(8,2),
        compensation NUMERIC(14,2),
        revenue_rate_md NUMERIC(12,2),
        invoice_amount NUMERIC(14,2),
        margin_pln NUMERIC(14,2),
        margin_pct NUMERIC(7,2),
        edited_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_finance_monthly_results_row UNIQUE (import_run_id, row_number)
    )""",
    # 0227: kto wgrał PDF zamówienia. Osobno od `created_by_user_id` — draft
    # zakłada automat z hooka „hired", plik dokłada człowiek później.
    "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS file_uploaded_by INTEGER NULL",
    "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS "
    "file_uploaded_at TIMESTAMPTZ NULL",
    """DO $$ BEGIN
        ALTER TABLE client_orders
            ADD CONSTRAINT fk_client_orders_file_uploaded_by_users
            FOREIGN KEY (file_uploaded_by) REFERENCES users(id) ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$""",
    # ── 0233: cykl życia zamówienia + zamówienie kosztowe ───────────────────
    # Kolumny NAJPIERW, bo referencje (dl_alerts, wiersze importu) muszą mieć
    # do czego wskazać; kolejność w tej liście jest wykonywana dosłownie.
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS "
    "status VARCHAR(16) NOT NULL DEFAULT 'active'",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS closure_date DATE NULL",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS closure_reason TEXT NULL",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS "
    "closed_at TIMESTAMPTZ NULL",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS "
    "closed_by_user_id INTEGER NULL",
    """DO $$ BEGIN
        ALTER TABLE client_order_groups
            ADD CONSTRAINT fk_client_order_groups_closed_by_users
            FOREIGN KEY (closed_by_user_id) REFERENCES users(id) ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$""",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS "
    "is_cost_based BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS "
    "budget_amount NUMERIC(16, 2) NULL",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS "
    "budget_remaining NUMERIC(16, 2) NULL",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS "
    "budget_manual_adjustment NUMERIC(16, 2) NOT NULL DEFAULT 0",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS "
    "predecessor_group_id INTEGER NULL",
    """DO $$ BEGIN
        ALTER TABLE client_order_groups
            ADD CONSTRAINT fk_client_order_groups_predecessor
            FOREIGN KEY (predecessor_group_id)
            REFERENCES client_order_groups(id) ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$""",
    # 0245: wspólna pula MD Cyfrowego Polsatu. Addytywne pola domyślnie
    # wyłączone nie zmieniają istniejącego wariantu MD per konsultant.
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS "
    "is_md_budget_based BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS "
    "md_budget_total NUMERIC(16, 6) NULL",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS "
    "md_budget_remaining NUMERIC(16, 6) NULL",
    "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS "
    "md_budget_manual_adjustment NUMERIC(16, 6) NOT NULL DEFAULT 0",
    """CREATE TABLE IF NOT EXISTS client_order_group_md_consumptions (
        id SERIAL PRIMARY KEY,
        group_id INTEGER NOT NULL
            REFERENCES client_order_groups(id) ON DELETE CASCADE,
        period_month VARCHAR(7) NOT NULL,
        md_reported NUMERIC(16, 6) NOT NULL,
        source VARCHAR(16) NOT NULL,
        created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_group_md_consumptions_period
            CHECK (period_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
        CONSTRAINT ck_group_md_consumptions_source
            CHECK (source IN ('import', 'manual')),
        CONSTRAINT ck_group_md_consumptions_nonnegative
            CHECK (md_reported >= 0)
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_group_md_consumptions_group_month "
    "ON client_order_group_md_consumptions (group_id, period_month)",
    # 0233: rozliczenie fakturami. Lustro client_order_md_consumptions —
    # UNIQUE na (order_id, period_month) jest tu KLUCZEM IDEMPOTENCJI, więc
    # tworzone razem z tabelą, nie w _INDEX_STATEMENTS (tabela bez niego przez
    # jeden boot przyjęłaby duplikaty, których potem nie da się już wstawić).
    """CREATE TABLE IF NOT EXISTS client_order_invoice_consumptions (
        id SERIAL PRIMARY KEY,
        order_id INTEGER NOT NULL REFERENCES client_orders(id) ON DELETE CASCADE,
        period_month VARCHAR(7) NOT NULL,
        invoice_amount NUMERIC(16, 2) NOT NULL,
        settled_amount NUMERIC(16, 2) NOT NULL DEFAULT 0,
        unsettled_amount NUMERIC(16, 2) NOT NULL DEFAULT 0,
        import_id INTEGER NULL
            REFERENCES md_consumption_imports(id) ON DELETE SET NULL,
        source VARCHAR(16) NOT NULL,
        created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_invoice_consumptions_source
            CHECK (source IN ('import', 'manual')),
        CONSTRAINT ck_invoice_consumptions_period
            CHECK (period_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$')
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_consumptions_order_month "
    "ON client_order_invoice_consumptions (order_id, period_month)",
    # 0233: „Uwagi" i „Faktura" z arkusza + wynik dopasowania kosztowego.
    "ALTER TABLE md_consumption_import_rows ADD COLUMN IF NOT EXISTS notes_raw TEXT NULL",
    "ALTER TABLE md_consumption_import_rows ADD COLUMN IF NOT EXISTS "
    "order_number_hint VARCHAR(64) NULL",
    "ALTER TABLE md_consumption_import_rows ADD COLUMN IF NOT EXISTS "
    "invoice_amount NUMERIC(16, 2) NULL",
    "ALTER TABLE md_consumption_import_rows ADD COLUMN IF NOT EXISTS "
    "matched_group_id INTEGER NULL",
    """DO $$ BEGIN
        ALTER TABLE md_consumption_import_rows
            ADD CONSTRAINT fk_md_import_rows_matched_group
            FOREIGN KEY (matched_group_id)
            REFERENCES client_order_groups(id) ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$""",
    "ALTER TABLE md_consumption_import_rows ADD COLUMN IF NOT EXISTS "
    "cost_status VARCHAR(24) NULL",
    "ALTER TABLE md_consumption_imports ADD COLUMN IF NOT EXISTS "
    "rows_cost_applied INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE md_consumption_imports ADD COLUMN IF NOT EXISTS "
    "rows_cost_unmatched INTEGER NOT NULL DEFAULT 0",
    # 0233: powiadomienia Delivery Leada. UNIQUE na dedupe_key tworzone razem
    # z tabelą — to on jest atomowym claimem (ON CONFLICT DO NOTHING), więc
    # tabela bez niego przez jeden boot rozmnożyłaby alerty przy każdym
    # przebiegu skanera.
    """CREATE TABLE IF NOT EXISTS dl_alerts (
        id SERIAL PRIMARY KEY,
        alert_type VARCHAR(48) NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        order_group_id INTEGER NULL
            REFERENCES client_order_groups(id) ON DELETE SET NULL,
        order_id INTEGER NULL REFERENCES client_orders(id) ON DELETE SET NULL,
        title VARCHAR(255) NOT NULL,
        message TEXT NOT NULL,
        link VARCHAR(1000) NULL,
        payload JSONB NULL,
        dedupe_key VARCHAR(255) NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'new',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        handled_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        handled_at TIMESTAMPTZ NULL,
        CONSTRAINT uq_dl_alerts_dedupe_key UNIQUE (dedupe_key),
        CONSTRAINT ck_dl_alerts_type CHECK (alert_type IN (
            'cost_order_exhausted', 'draft_consultant_unassigned',
            'md_budget_low', 'missing_revenue_rate',
            'md_consultant_ended', 'order_mail_review')),
        CONSTRAINT ck_dl_alerts_status CHECK (status IN ('new', 'handled')),
        CONSTRAINT ck_dl_alerts_handled_coherence
            CHECK (status <> 'handled' OR handled_at IS NOT NULL)
    )""",
    # 0249: order owns a finance snapshot. Add nullable first; the data phase
    # below deterministically fills every existing row before the constraint
    # phase installs defaults and NOT NULL on the two required columns.
    "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS "
    "rate_candidate NUMERIC(12, 3) NULL",
    "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS rate_unit rateunit NULL",
    "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS "
    "billing_hours_per_month INTEGER NULL",
    "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS "
    "rate_client_currency VARCHAR(3) NULL",
    "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS "
    "rate_candidate_currency VARCHAR(3) NULL",
    # Contract termination is a fact, but an MD pool needs a durable DL
    # decision. This table mirrors ClientOrderOffboardingCase exactly and is
    # intentionally created before dl_alerts receives its FK below.
    """CREATE TABLE IF NOT EXISTS client_order_offboarding_cases (
        id SERIAL PRIMARY KEY,
        contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
        order_id INTEGER NOT NULL REFERENCES client_orders(id) ON DELETE CASCADE,
        order_group_id INTEGER NULL
            REFERENCES client_order_groups(id) ON DELETE SET NULL,
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        effective_date DATE NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        version INTEGER NOT NULL DEFAULT 1,
        uses_shared_md_pool BOOLEAN NOT NULL DEFAULT FALSE,
        remaining_md_snapshot NUMERIC(16, 6) NOT NULL DEFAULT 0,
        rate_cost_snapshot NUMERIC(12, 2) NULL,
        rate_revenue_snapshot NUMERIC(12, 2) NULL,
        currency_snapshot VARCHAR(3) NULL,
        order_number_snapshot VARCHAR(64) NULL,
        resolution VARCHAR(16) NULL,
        target_order_id INTEGER NULL
            REFERENCES client_orders(id) ON DELETE SET NULL,
        rate_basis VARCHAR(16) NULL,
        resolution_payload JSONB NULL,
        resolved_at TIMESTAMPTZ NULL,
        resolved_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_client_order_offboarding_order_effective
            UNIQUE (order_id, effective_date),
        CONSTRAINT ck_client_order_offboarding_status
            CHECK (status IN ('pending', 'resolved')),
        CONSTRAINT ck_client_order_offboarding_resolution
            CHECK (resolution IS NULL
                   OR resolution IN ('remove', 'transfer', 'restore')),
        CONSTRAINT ck_client_order_offboarding_rate_basis
            CHECK (rate_basis IS NULL OR rate_basis IN ('departing', 'recipient')),
        CONSTRAINT ck_client_order_offboarding_resolution_state CHECK (
            (status = 'pending' AND resolution IS NULL AND resolved_at IS NULL
             AND target_order_id IS NULL AND rate_basis IS NULL)
            OR (status = 'resolved' AND resolution IS NOT NULL
                AND resolved_at IS NOT NULL)
        ),
        CONSTRAINT ck_client_order_offboarding_transfer_target CHECK (
            resolution IS DISTINCT FROM 'transfer'
            OR rate_basis IS NOT NULL
        ),
        CONSTRAINT ck_client_order_offboarding_remove_target CHECK (
            resolution IS DISTINCT FROM 'remove'
            OR (target_order_id IS NULL AND rate_basis IS NULL)
        ),
        CONSTRAINT ck_client_order_offboarding_restore_target CHECK (
            resolution IS DISTINCT FROM 'restore'
            OR (target_order_id IS NULL AND rate_basis IS NULL)
        ),
        CONSTRAINT ck_client_order_offboarding_version CHECK (version >= 1),
        CONSTRAINT ck_client_order_offboarding_remaining_nonnegative
            CHECK (remaining_md_snapshot >= 0)
    )""",
    "ALTER TABLE dl_alerts ADD COLUMN IF NOT EXISTS "
    "offboarding_case_id INTEGER NULL",
    # Dziennik obserwacji poziomu seniority (0261). Lustro DDL, bo alembic na
    # prodzie bywa osierocony — bez tego pętla dobowa wywalałaby się na
    # nieistniejącej tabeli, a `/api/insights/seniority` oddawałby 500.
    """CREATE TABLE IF NOT EXISTS insights_seniority_snapshots (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        level VARCHAR(16) NOT NULL,
        previous_level VARCHAR(16) NULL,
        total_placements INTEGER NOT NULL,
        previous_total_placements INTEGER NULL,
        senior_since VARCHAR(7) NULL,
        expert_since VARCHAR(7) NULL,
        thresholds_fingerprint VARCHAR(64) NOT NULL,
        is_regression BOOLEAN NOT NULL DEFAULT FALSE,
        CONSTRAINT ck_insights_seniority_snapshots_level
            CHECK (level IN ('junior', 'senior', 'expert')),
        CONSTRAINT ck_insights_seniority_snapshots_previous_level
            CHECK (previous_level IS NULL
                   OR previous_level IN ('junior', 'senior', 'expert'))
    )""",
    "CREATE INDEX IF NOT EXISTS ix_insights_seniority_snapshots_user_observed "
    "ON insights_seniority_snapshots (user_id, observed_at DESC)",
    # 0264: zamówienia z maila. Przeznaczenie połączenia M365 (skrzynka kopii
    # zamówień pomijana przez sync osobisty), dziennik załączników z drabiną
    # wyniku i jednowierszowy watermark pętli. Prod alembic bywa osierocony —
    # lustro DDL jest jedyną gwarancją, że tabele powstaną.
    "ALTER TABLE m365_connections ADD COLUMN IF NOT EXISTS purpose "
    "VARCHAR(16) NOT NULL DEFAULT 'personal'",
    """DO $$ BEGIN
        ALTER TABLE m365_connections ADD CONSTRAINT ck_m365_connections_purpose
            CHECK (purpose IN ('personal', 'orders'));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """CREATE TABLE IF NOT EXISTS order_mail_documents (
        id SERIAL PRIMARY KEY,
        connection_id INTEGER NULL REFERENCES m365_connections(id) ON DELETE SET NULL,
        internet_message_id VARCHAR(998) NOT NULL,
        m365_message_id VARCHAR(512) NULL,
        received_at TIMESTAMPTZ NULL,
        sender_email VARCHAR(320) NULL,
        sender_domain VARCHAR(255) NULL,
        subject VARCHAR(1000) NULL,
        attachment_name VARCHAR(255) NULL,
        attachment_sha256 VARCHAR(64) NULL,
        attachment_size INTEGER NULL,
        storage_path VARCHAR(512) NULL,
        duplicate_of_id INTEGER NULL REFERENCES order_mail_documents(id) ON DELETE SET NULL,
        outcome VARCHAR(32) NOT NULL DEFAULT 'received',
        client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
        client_key VARCHAR(64) NULL,
        identification_method VARCHAR(16) NULL,
        identification_reason TEXT NULL,
        client_policy VARCHAR(128) NULL,
        extraction JSONB NULL,
        document_meta JSONB NULL,
        gate_verdict VARCHAR(16) NULL,
        gate_reasons JSONB NULL,
        proposal JSONB NULL,
        applied_order_id INTEGER NULL REFERENCES client_orders(id) ON DELETE SET NULL,
        applied_group_id INTEGER NULL REFERENCES client_order_groups(id) ON DELETE SET NULL,
        applied_at TIMESTAMPTZ NULL,
        applied_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        reviewed_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        reviewed_at TIMESTAMPTZ NULL,
        error TEXT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_order_mail_documents_outcome CHECK (outcome IN (
            'received','ignored_no_pdf','ignored_sender','duplicate_attachment',
            'unrecognized_client','needs_review','auto_applied','applied',
            'dismissed','failed')),
        CONSTRAINT ck_order_mail_documents_gate_verdict
            CHECK (gate_verdict IS NULL OR gate_verdict IN ('auto','review'))
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_order_mail_documents_message_attachment "
    "ON order_mail_documents (internet_message_id, attachment_sha256) "
    "WHERE attachment_sha256 IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_order_mail_documents_message_no_attachment "
    "ON order_mail_documents (internet_message_id) WHERE attachment_sha256 IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_order_mail_documents_sha ON order_mail_documents (attachment_sha256)",
    "CREATE INDEX IF NOT EXISTS ix_order_mail_documents_outcome ON order_mail_documents (outcome)",
    "CREATE INDEX IF NOT EXISTS ix_order_mail_documents_client ON order_mail_documents (client_id)",
    "CREATE INDEX IF NOT EXISTS ix_order_mail_documents_received ON order_mail_documents (received_at)",
    "CREATE INDEX IF NOT EXISTS ix_order_mail_documents_connection_id ON order_mail_documents (connection_id)",
    """CREATE TABLE IF NOT EXISTS order_mail_sync_state (
        id INTEGER PRIMARY KEY,
        last_run_started_at TIMESTAMPTZ NULL,
        last_run_finished_at TIMESTAMPTZ NULL,
        last_status VARCHAR(20) NULL,
        last_error TEXT NULL,
        last_seen_received_at TIMESTAMPTZ NULL,
        stats JSONB NULL,
        updated_at TIMESTAMPTZ NULL
    )""",
    # 0270: rekrutacje — data otwarcia ze źródła + własna „otwartość" NEXUSA.
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS opened_at TIMESTAMPTZ",
    """ALTER TABLE jobs
        ADD COLUMN IF NOT EXISTS is_open BOOLEAN NOT NULL DEFAULT false""",
    "CREATE INDEX IF NOT EXISTS ix_jobs_opened_at ON jobs (opened_at)",
    "CREATE INDEX IF NOT EXISTS ix_jobs_is_open ON jobs (is_open) WHERE is_open",
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
                                'talent_community_manager', 'tac', 'recruiter',
                                'sourcer'
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
    # 0269: bootstrap only. Defaults are inserted only for an entirely empty
    # matrix. A partial matrix is an operational fault and must stay fail-closed;
    # filling a single missing row on restart could silently restore a broader
    # default after an administrator deliberately selected `none`.
    """INSERT INTO rbac_policy_state (id, revision)
       VALUES (1, 1)
       ON CONFLICT (id) DO NOTHING""",
    """INSERT INTO rbac_role_section_permissions (role, section, access)
       SELECT defaults.role, defaults.section, defaults.access
       FROM (VALUES
           ('admin', 'sourcing', 'write'),
           ('admin', 'pipeline', 'write'),
           ('admin', 'delivery', 'write'),
           ('admin', 'insights', 'write'),
           ('admin', 'finance', 'write'),
           ('admin', 'system_admin', 'write'),
           ('finance', 'sourcing', 'write'),
           ('finance', 'pipeline', 'write'),
           ('finance', 'delivery', 'write'),
           ('finance', 'insights', 'read'),
           ('finance', 'finance', 'write'),
           ('finance', 'system_admin', 'none'),
           ('head_of_recruitment', 'sourcing', 'write'),
           ('head_of_recruitment', 'pipeline', 'write'),
           ('head_of_recruitment', 'delivery', 'none'),
           ('head_of_recruitment', 'insights', 'write'),
           ('head_of_recruitment', 'finance', 'none'),
           ('head_of_recruitment', 'system_admin', 'none'),
           ('delivery_lead', 'sourcing', 'write'),
           ('delivery_lead', 'pipeline', 'write'),
           ('delivery_lead', 'delivery', 'write'),
           ('delivery_lead', 'insights', 'read'),
           ('delivery_lead', 'finance', 'none'),
           ('delivery_lead', 'system_admin', 'none'),
           ('talent_community_manager', 'sourcing', 'write'),
           ('talent_community_manager', 'pipeline', 'write'),
           ('talent_community_manager', 'delivery', 'read'),
           ('talent_community_manager', 'insights', 'read'),
           ('talent_community_manager', 'finance', 'none'),
           ('talent_community_manager', 'system_admin', 'none'),
           ('tac', 'sourcing', 'write'),
           ('tac', 'pipeline', 'write'),
           ('tac', 'delivery', 'none'),
           ('tac', 'insights', 'read'),
           ('tac', 'finance', 'none'),
           ('tac', 'system_admin', 'none'),
           ('recruiter', 'sourcing', 'write'),
           ('recruiter', 'pipeline', 'write'),
           ('recruiter', 'delivery', 'none'),
           ('recruiter', 'insights', 'read'),
           ('recruiter', 'finance', 'none'),
           ('recruiter', 'system_admin', 'none'),
           ('sourcer', 'sourcing', 'write'),
           ('sourcer', 'pipeline', 'write'),
           ('sourcer', 'delivery', 'none'),
           ('sourcer', 'insights', 'read'),
           ('sourcer', 'finance', 'none'),
           ('sourcer', 'system_admin', 'none'),
           ('user', 'sourcing', 'read'),
           ('user', 'pipeline', 'read'),
           ('user', 'delivery', 'none'),
           ('user', 'insights', 'read'),
           ('user', 'finance', 'none'),
           ('user', 'system_admin', 'none')
       ) AS defaults(role, section, access)
       WHERE NOT EXISTS (
           SELECT 1 FROM rbac_role_section_permissions
       )
       ON CONFLICT (role, section) DO NOTHING""",
    # 0271: domyślny szablon dostaje kolumnę dla legacy `interview`.
    #
    # Bez niej karty z tego etapu (1 633 na produkcji) nie miały gdzie się
    # wyrenderować. Mapowanie wyrównane do szablonu importowanego z Traffita,
    # który kolumnę o TEJ SAMEJ nazwie mapuje na `interview`.
    #
    # Warunkowo (`IS NULL`) — ręczna korekta wygrywa; oraz `NOT EXISTS`, bo
    # `get_kanban` buduje `enum_to_def` jako słownik i druga kolumna z tą samą
    # wartością wygrywałaby zależnie od kolejności.
    """UPDATE pipeline_stage_defs AS sd
          SET legacy_enum_value = 'interview', updated_at = NOW()
         FROM pipeline_templates AS t
        WHERE t.id = sd.template_id
          AND t.is_default IS TRUE
          AND sd.name = 'Przepuszczony przez DZ'
          AND sd.legacy_enum_value IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM pipeline_stage_defs other
               WHERE other.template_id = sd.template_id
                 AND other.legacy_enum_value = 'interview'
          )""",
    # 0273: mirror the migration defaults. These values preserve the existing
    # generator behavior; only TCM and the legacy viewer start view-only.
    """INSERT INTO rbac_role_action_permissions (role, action, access)
       SELECT defaults.role, defaults.action, defaults.access
       FROM (VALUES
           ('admin', 'b2b_contract_generator', 'manage'),
           ('finance', 'b2b_contract_generator', 'manage'),
           ('head_of_recruitment', 'b2b_contract_generator', 'manage'),
           ('delivery_lead', 'b2b_contract_generator', 'manage'),
           ('talent_community_manager', 'b2b_contract_generator', 'view'),
           ('tac', 'b2b_contract_generator', 'manage'),
           ('recruiter', 'b2b_contract_generator', 'manage'),
           ('sourcer', 'b2b_contract_generator', 'manage'),
           ('user', 'b2b_contract_generator', 'view')
       ) AS defaults(role, action, access)
       WHERE NOT EXISTS (
           SELECT 1 FROM rbac_role_action_permissions
       )
       ON CONFLICT (role, action) DO NOTHING""",
    # 0256: seed domyślnej punktacji Insights. `ON CONFLICT DO NOTHING`, więc
    # wartości ustawione wcześniej przez admina zostają nietknięte — ten blok
    # biegnie przy KAŻDYM starcie kontenera, a nadpisanie cofałoby strojenie
    # wag do domyślnych na każdym deployu.
    """INSERT INTO insights_scoring_config (key, value) VALUES
           ('league_points_placement', 150),
           ('league_points_interview', 15),
           ('league_points_recommendation', 5),
           ('league_min_placements_month1', 1),
           ('league_min_placements_month2', 2),
           ('league_min_placements_month3', 3),
           ('seniority_senior_placements', 6),
           ('seniority_senior_window_months', 6),
           ('seniority_expert_placements', 12),
           ('seniority_expert_window_months', 6),
           ('seniority_senior_alt_placements', 12),
           ('seniority_senior_alt_window_months', 12),
           ('seniority_expert_alt_placements', 24),
           ('seniority_expert_alt_window_months', 12)
       ON CONFLICT (key) DO NOTHING""",
    # 0260: korekta okna Eksperta 12 -> 6 miesięcy. Seed wyżej NIE naprawi
    # istniejącej instalacji (`DO NOTHING` omija wiersz zasiany przez 0256),
    # a ten blok biegnie przy każdym starcie, więc warunek musi odróżnić
    # „nasza stara wartość domyślna" od strojenia człowieka — stąd
    # `updated_by IS NULL` obok porównania wartości. Bez tego każdy deploy
    # cofałby świadomą zmianę admina.
    """UPDATE insights_scoring_config
          SET value = 6
        WHERE key = 'seniority_expert_window_months'
          AND value = 12
          AND updated_by IS NULL""",
    # 0248: stare kontrakty miały jedną walutę dla obu stawek. Nie
    # nadpisujemy już uzupełnionej strony, więc safety-net jest idempotentny
    # także po utworzeniu kontraktu mieszanego.
    """UPDATE contracts
       SET rate_client_currency = COALESCE(
               rate_client_currency,
               NULLIF(UPPER(BTRIM(currency)), ''),
               'PLN'
           ),
           rate_candidate_currency = COALESCE(
               rate_candidate_currency,
               NULLIF(UPPER(BTRIM(currency)), ''),
               'PLN'
           )
       WHERE rate_client_currency IS NULL
          OR rate_candidate_currency IS NULL""",
    # 0249: the new nullable metadata fields are also the resumability guard.
    # Historical amounts stay untouched: contracts.rate_* is only a cache and
    # can lag a progressive schedule, so copying it would freeze a wrong rate
    # and margin on the order. Null amounts keep the existing dated fallback.
    """UPDATE client_orders AS order_row
       SET rate_unit = COALESCE(contract.rate_unit, 'monthly'::rateunit),
           billing_hours_per_month = COALESCE(
               contract.billing_hours_per_month, 160
           ),
           rate_client_currency = COALESCE(
               NULLIF(UPPER(BTRIM(contract.rate_client_currency)), ''),
               NULLIF(UPPER(BTRIM(contract.currency)), ''),
               'PLN'
           ),
           rate_candidate_currency = COALESCE(
               NULLIF(UPPER(BTRIM(contract.rate_candidate_currency)), ''),
               NULLIF(UPPER(BTRIM(contract.currency)), ''),
               'PLN'
           ),
           currency = COALESCE(
               NULLIF(UPPER(BTRIM(contract.rate_client_currency)), ''),
               NULLIF(UPPER(BTRIM(contract.currency)), ''),
               'PLN'
           )
       FROM contracts AS contract
       WHERE order_row.contract_id = contract.id
         AND order_row.order_group_id IS NULL
         AND (
             order_row.rate_unit IS NULL
             OR order_row.billing_hours_per_month IS NULL
             OR order_row.rate_client_currency IS NULL
             OR order_row.rate_candidate_currency IS NULL
         )""",
    # Multi-consultant lines are deliberately canonical PLN/MD, independent of
    # the linked contract's display unit/currency. Their authoritative rates
    # already live in md_rate_cost/md_rate_revenue.
    """UPDATE client_orders AS order_row
       SET rate_candidate = order_row.md_rate_cost,
           rate_client = order_row.md_rate_revenue,
           rate_unit = 'daily'::rateunit,
           billing_hours_per_month = 160,
           rate_client_currency = 'PLN',
           rate_candidate_currency = 'PLN',
           currency = 'PLN'
       WHERE order_row.order_group_id IS NOT NULL
         AND (
             order_row.rate_unit IS NULL
             OR order_row.billing_hours_per_month IS NULL
             OR order_row.rate_client_currency IS NULL
             OR order_row.rate_candidate_currency IS NULL
         )""",
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
    # 0224: seed feature'a AI `cv_backfill` (masowe uzupełnianie pól z CV).
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    "SELECT 'cv_backfill', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'cv_backfill')",
    # 0230: seed feature'a AI `notes_extraction` (cykliczna ekstrakcja notatek).
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    "SELECT 'notes_extraction', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS "
    "(SELECT 1 FROM ai_features WHERE feature = 'notes_extraction')",
    # 0236: seed feature'a AI `champion_profile_parse` (ingest profili Championa).
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    "SELECT 'champion_profile_parse', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS "
    "(SELECT 1 FROM ai_features WHERE feature = 'champion_profile_parse')",
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    "SELECT 'cv_interactive_chat', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS "
    "(SELECT 1 FROM ai_features WHERE feature = 'cv_interactive_chat')",
    # 0240: seedy `cv_generator` i `mindy_chat`. Brak wiersza w ai_features nie
    # blokuje wywołania (quota jest fail-open), ale czyni funkcję NIEWIDOCZNĄ
    # w Ustawieniach → AI — czyli nie do ograniczenia przez administratora.
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    "SELECT 'cv_generator', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS "
    "(SELECT 1 FROM ai_features WHERE feature = 'cv_generator')",
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    "SELECT 'mindy_chat', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS "
    "(SELECT 1 FROM ai_features WHERE feature = 'mindy_chat')",
    # 0267: seed feature'a AI `cv_rule_lint` (lint instrukcji reguły CV).
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    "SELECT 'cv_rule_lint', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'cv_rule_lint')",
    # 0238: jednorazowa korekta dziewięciu kontraktów BIK. Marker i UPDATE są
    # jednym statementem: entrypoint leci przy każdym starcie, więc bez guardu
    # ponownie aktywowałby kontrakt świadomie zakończony później przez admina.
    """WITH marker AS (
           INSERT INTO app_settings (key, value)
           VALUES (
               '0238_bik_contract_status_correction',
               jsonb_build_object(
                   'revision', '0238_contract_order_workflows',
                   'completed_at', clock_timestamp(),
                   'source', 'entrypoint_safety_net'
               )
           )
           ON CONFLICT (key) DO NOTHING
           RETURNING key
       ), ranked AS (
           SELECT
               co.id,
               row_number() OVER (
                   PARTITION BY co.candidate_id, co.client_id
                   ORDER BY co.end_date DESC NULLS FIRST, co.id DESC
               ) AS position
           FROM contracts co
           JOIN candidates ca ON ca.id = co.candidate_id
           JOIN clients cl ON cl.id = co.client_id
           WHERE co.status <> 'void'::contractstatus
             AND lower(concat_ws(' ', cl.name, cl.display_name, cl.legal_name))
                   LIKE '%biuro informacji kredytowej%'
             -- `normalize(..., NFC)` jak w migracji 0238. Bez tego
             -- porównanie CAŁEGO napisu nie trafia w rekord zapisany
             -- w NFD („ń" jako "n" + U+0301) — tak zgubiony został
             -- kontrakt #571 (Robert Łuszczyński), doaktywowany osobną
             -- rewizją 0239. To lustro jest WAŻNIEJSZE od samej migracji:
             -- prod alembic bywa osierocony, więc na produkcji chodzi
             -- właśnie ten SQL. Pudło jest CICHE — nie raportujemy, ilu
             -- z dziewięciu ludzi trafiliśmy, więc częściowe trafienie
             -- wygląda w logach jak pełne.
             AND lower(normalize(trim(ca.name) || ' ' || trim(ca.lastname), NFC)) IN (
                   'aleksander wojdyła',
                   'daniel madejski',
                   'maciej koc',
                   'robert łuszczyński',
                   'paweł łaski',
                   'konrad teper',
                   'michał leśniak',
                   'wojciech wojtak',
                   'grzegorz wadecki'
             )
             AND EXISTS (SELECT 1 FROM marker)
       )
       UPDATE contracts co
       SET status = 'active'::contractstatus,
           updated_at = now()
       FROM ranked
       WHERE co.id = ranked.id
         AND ranked.position = 1""",
    # 0239: precyzyjne domknięcie dwóch legacy rekordów wykrytych podczas
    # produkcyjnej weryfikacji 0238. Jeden marker obejmuje całą transakcję;
    # kolejne restarty nie nadpiszą późniejszych decyzji operatora.
    """DO $contract_order_backfill$
       DECLARE
           target_group_id INTEGER;
           target_group_count BIGINT := 0;
           contract_rows BIGINT := 0;
           order_line_rows BIGINT := 0;
       BEGIN
           IF EXISTS (
               SELECT 1
               FROM app_settings
               WHERE key = '0239_bik_contract_order_backfill'
           ) THEN
               RETURN;
           END IF;

           UPDATE contracts AS contract
              SET status = 'active'::contractstatus,
                  updated_at = now()
             FROM candidates AS candidate,
                  clients AS client
            WHERE contract.id = 571
              AND contract.client_id = 18
              AND contract.status = 'draft'::contractstatus
              AND candidate.id = contract.candidate_id
              AND btrim(candidate.name) = 'Robert'
              AND btrim(candidate.lastname) LIKE 'Łuszcz%'
              AND client.id = contract.client_id
              AND lower(concat_ws(
                      ' ', client.name, client.display_name, client.legal_name
                  )) LIKE '%biuro informacji kredytowej%';
           GET DIAGNOSTICS contract_rows = ROW_COUNT;

           -- Lustro poszerzonego CHECK-a z 0238 MUSI stać TUTAJ, a nie tylko
           -- w `_CONSTRAINT_STATEMENTS`: pętla w `backfill()` wykonuje
           -- `_DATA_STATEMENTS` PRZED więzami, więc na deployu, na którym
           -- poszerzenie jeszcze nie weszło (świeża baza — tabele powstają
           -- dopiero w `Base.metadata.create_all` PO backfillu — albo
           -- osierocony alembic, czyli dokładnie tryb awarii, pod który ten
           -- safety-net powstał), UPDATE na 'scheduled' łamałby wąski CHECK
           -- z 0233. Wyjątek wywraca CAŁY ten blok DO, razem z aktywacją
           -- kontraktu i markerem, a jedynym śladem jest jedna linijka
           -- „backfill data skip" w logu kontenera — `/api/health` zostaje
           -- zielony. Że na prodzie nie ugryzło, wynika wyłącznie z tego, że
           -- 0238 i 0239 wjechały dwoma osobnymi deployami.
           --
           -- Sprawdzamy DEFINICJĘ więzu, nie samą nazwę: wąski i szeroki
           -- wariant nazywają się tak samo, więc test na obecność nazwy
           -- przepuściłby stary CHECK i nic by nie naprawił.
           IF NOT EXISTS (
               SELECT 1
               FROM pg_constraint
               WHERE conrelid = 'client_order_groups'::regclass
                 AND conname = 'ck_client_order_groups_status'
                 AND pg_get_constraintdef(oid) LIKE '%scheduled%'
           ) THEN
               ALTER TABLE client_order_groups
                   DROP CONSTRAINT IF EXISTS ck_client_order_groups_status;
               ALTER TABLE client_order_groups
                   ADD CONSTRAINT ck_client_order_groups_status
                   CHECK (
                       status IN ('active', 'scheduled', 'completed', 'exhausted')
                   ) NOT VALID;
           END IF;

           SELECT count(*), max(order_group.id)
             INTO target_group_count, target_group_id
             FROM client_order_groups AS order_group
             JOIN clients AS client ON client.id = order_group.client_id
            WHERE order_group.client_id = 18
              AND order_group.order_number = '4500030684'
              AND order_group.status = 'active'
              AND order_group.predecessor_group_id IS NOT NULL
              AND order_group.start_date = DATE '2026-09-11'
              AND order_group.start_date > CURRENT_DATE
              AND lower(concat_ws(
                      ' ', client.name, client.display_name, client.legal_name
                  )) LIKE '%biuro informacji kredytowej%';

           IF target_group_count > 1 THEN
               RAISE EXCEPTION
                   '0239 expected at most one BIK order group 4500030684, found %',
                   target_group_count;
           END IF;

           IF target_group_count = 1 THEN
               UPDATE client_order_groups
                  SET status = 'scheduled',
                      updated_at = now()
                WHERE id = target_group_id;

               UPDATE client_orders
                  SET status = 'draft'::clientorderstatus,
                      filled_at = NULL,
                      updated_at = now()
                WHERE order_group_id = target_group_id
                  AND status = 'active'::clientorderstatus;
               GET DIAGNOSTICS order_line_rows = ROW_COUNT;
           END IF;

           INSERT INTO app_settings (key, value)
           VALUES (
               '0239_bik_contract_order_backfill',
               jsonb_build_object(
                   'revision', '0239_bik_contract_order_backfill',
                   'completed_at', clock_timestamp(),
                   'source', 'entrypoint_safety_net',
                   'contract_rows', contract_rows,
                   'order_group_rows', target_group_count,
                   'order_line_rows', order_line_rows,
                   'rollback', 'manual_only'
               )
           );
       END
       $contract_order_backfill$;""",
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
    # USUNIĘTE w 0270: `UPDATE jobs SET closed_at = updated_at ...`.
    # Ta linia leciała przy KAŻDYM starcie kontenera, a `_UPSERT_JOB` stempluje
    # `updated_at = NOW()` przy każdym dotknięciu wiersza — więc `closed_at`
    # wychodził znacznikiem syncu, nie datą zamknięcia (3584 zamknięcia
    # wylądowały w maju 2026, mediana czasu realizacji = 0 dni). Komentarz
    # „safe because only touches NULL rows" był prawdziwy co do bezpieczeństwa
    # zapisu i mylący co do skutku: każdy świeżo zamknięty wiersz JEST NULL-em.
    # Datę zamknięcia mapuje teraz importer z `closing_date` ze źródła.
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
             -- `normalize(..., NFC)` jak przy korekcie BIK. „ś" (U+015B) w NFD
             -- rozkłada się na „s" + U+0301, więc porównanie surowego napisu
             -- nie trafia w rekord zapisany w tej formie — a wtedy wyróżnienie
             -- klienta po prostu się nie zakłada, CICHO. Ta sama klasa co #315.
             AND lower(normalize(btrim(name), NFC)) = lower(normalize('Ministerstwo Sprawiedliwości', NFC))
           ORDER BY id
           LIMIT 1
       )
       AND NOT EXISTS (
           SELECT 1 FROM clients
           WHERE normalize(display_name, NFC) = normalize('Ministerstwo Sprawiedliwości', NFC)
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
           WHERE normalize(display_name, NFC) = normalize('Ministerstwo Sprawiedliwości', NFC)
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
    # 0272 (decyzja produktowa 03.09.2026): 14 wzorów Championa per klient
    # schodzi z Pomocy; ich treść przejęła karta klienta, a wzór jest jeden,
    # ogólny. Wiersze ZOSTAJĄ (przegląd reguł CV linkuje `template_url` po
    # slugu) — zmienia się tylko `is_published`. Marker w app_settings jest
    # wstawiany TYM SAMYM statementem, więc ponowna publikacja przez admina
    # nie jest cofana przy każdym starcie kontenera.
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    "VALUES ('0272_champion_client_templates_unpublished', 'true'::jsonb) "
    "ON CONFLICT (key) DO NOTHING RETURNING key) "
    "UPDATE help_materials SET is_published = false, updated_at = now() "
    "WHERE slug IN ("
    "'profil-championa-wzor-alior-docx', 'profil-championa-wzor-bank-pocztowy-docx', "
    "'profil-championa-wzor-bik-docx', 'profil-championa-wzor-bnp-paribas-docx', "
    "'profil-championa-wzor-credit-agricole-docx', 'profil-championa-wzor-energa-docx', "
    "'profil-championa-wzor-kir-docx', 'profil-championa-wzor-nordea-docx', "
    "'profil-championa-wzor-orlen-docx', 'profil-championa-wzor-pansa-docx', "
    "'profil-championa-wzor-pfron-docx', 'profil-championa-wzor-pko-bp-docx', "
    "'profil-championa-wzor-santander-docx', 'profil-championa-wzor-tauron-docx') "
    "AND EXISTS (SELECT 1 FROM marker)",
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
    # 0255: propozycje reguł CV per klient, wyprowadzone z sekcji „7. STANDARDY
    # REKRUTACJI KLIENTA" szablonów zasianych wyżej. Lustro seeda z migracji
    # 0255 — zmieniasz tu, zmień też tam.
    #
    # `confirmed_at` zostaje NULL, bo dopasowanie szablonu do wiersza w
    # `clients` NIE jest 1:1 (samych bytów „BNP" jest siedem). Wiersz powstaje
    # wyłącznie przy DOKŁADNIE JEDNYM żywym trafieniu nazwy, a i tak nie
    # obowiązuje, dopóki człowiek go nie zatwierdzi w Ustawieniach. Dlatego
    # dopasowanie po nazwie jest tu dopuszczalne mimo reguły „bramki idą po
    # client_id" — nic z niego nie wchodzi w życie samo z siebie.
    """INSERT INTO client_cv_rules
           (client_id, filename_pattern, spaces_to_underscores, cv_language,
            requires_en_copy, requires_rodo_consent_block, seed_key,
            confirmed_at, created_at, updated_at)
       SELECT c.id, s.filename_pattern, s.spaces_to_underscores, s.cv_language,
              s.requires_en_copy, s.requires_rodo, s.seed_key,
              NULL, now(), now()
       FROM (VALUES
           ('profil-championa-wzor-alior-docx', '%alior%',
            'B2B_{STANOWISKO}_{IMIE_NAZWISKO}', FALSE, NULL::varchar, TRUE, FALSE),
           ('profil-championa-wzor-bik-docx', '%informacji kredytowej%',
            'B2B_{STANOWISKO}_{IMIE_NAZWISKO}', FALSE, NULL::varchar, TRUE, FALSE),
           ('profil-championa-wzor-bnp-paribas-docx', '%bnp%',
            'B2B_{STANOWISKO}_{IMIE_NAZWISKO}', FALSE, NULL::varchar, TRUE, FALSE),
           ('profil-championa-wzor-santander-docx', '%santander%',
            'B2B_{STANOWISKO}_{IMIE_NAZWISKO}', FALSE, NULL::varchar, TRUE, FALSE),
           ('profil-championa-wzor-nordea-docx', '%nordea%',
            'B2B_{STANOWISKO}_{IMIE_NAZWISKO}', FALSE, 'en', FALSE, FALSE),
           ('profil-championa-wzor-pfron-docx', '%pfron%',
            'B2B_{STANOWISKO}_{IMIE_NAZWISKO}', FALSE, 'pl', FALSE, FALSE),
           ('profil-championa-wzor-kir-docx', '%krajowa izba rozliczeniowa%',
            'B2B_{STANOWISKO}_{IMIE_NAZWISKO}', TRUE, 'pl', FALSE, FALSE),
           ('profil-championa-wzor-bank-pocztowy-docx', '%pocztow%',
            'Bank_Pocztowy_{STANOWISKO}_{IMIE_NAZWISKO}', TRUE, 'pl', FALSE, FALSE),
           ('profil-championa-wzor-credit-agricole-docx', '%credit agricole%',
            'B2B.NET_{STANOWISKO}_{IMIE_NAZWISKO}_{DATA}', TRUE, 'pl', FALSE, FALSE),
           ('profil-championa-wzor-pansa-docx', '%pansa%',
            'B2B_PANSA_{STANOWISKO}_{IMIE_NAZWISKO}', TRUE, 'pl', FALSE, FALSE),
           ('profil-championa-wzor-tauron-docx', '%tauron%',
            'B2B_Tauron_{STANOWISKO}_{IMIE_NAZWISKO}', TRUE, 'pl', FALSE, FALSE),
           ('profil-championa-wzor-energa-docx', '%energa%',
            'ENERGA_{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}', FALSE, 'pl', FALSE, FALSE),
           ('profil-championa-wzor-orlen-docx', '%orlen%',
            'ORLEN_{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}', FALSE, 'pl', FALSE, FALSE),
           ('profil-championa-wzor-pko-bp-docx', '%pko%',
            'ZOB-{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}', FALSE, 'pl', FALSE, TRUE)
       ) AS s(seed_key, name_pattern, filename_pattern, spaces_to_underscores,
              cv_language, requires_en_copy, requires_rodo)
       JOIN clients c
         ON lower(c.name) LIKE s.name_pattern
        AND c.hidden = FALSE
        AND c.merged_into_client_id IS NULL
       WHERE (SELECT count(*) FROM clients c2
               WHERE lower(c2.name) LIKE s.name_pattern
                 AND c2.hidden = FALSE
                 AND c2.merged_into_client_id IS NULL) = 1
       ON CONFLICT (client_id) DO NOTHING""",
    # 0255: klient na historycznych generacjach z trybu "new" — wyprowadzalny
    # z oferty. Bez tego lista „Wygenerowane CV" pokazałaby „—" przy
    # dokumentach, które klienta miały od zawsze.
    """UPDATE cv_generated_documents d
          SET client_id = j.client_id
         FROM jobs j
        WHERE d.job_id = j.id
          AND d.client_id IS NULL
          AND j.client_id IS NOT NULL""",
    # 0229 — szablon zaproszenia na spotkanie przygotowujące. Jedyny wiersz bez
    # `url`: to nie plik w SharePoincie, tylko TREŚĆ, którą rekruter wkleja do
    # Outlooka. `\n` rozwija Python (nie-raw string), więc do SQL-a trafiają
    # prawdziwe znaki nowej linii — puste linie są częścią układu wiadomości.
    #
    # Zdania „UWAGA! Do zaproszenia załączamy CV…" CELOWO tu NIE MA: to
    # instrukcja dla rekrutera, a nie treść wysyłana kandydatowi. Jej miejsce
    # jest w UI obok przycisku.
    """INSERT INTO help_materials
           (slug, category, title, url, description,
            template_subject, template_body,
            is_editable_template, sort_order, is_published,
            created_at, updated_at)
       VALUES (
           'zaproszenie-prep-spotkanie',
           'Szablony i wzory',
           'Zaproszenie na spotkanie przygotowujące (prep)',
           NULL,
           'Zaproszenie kalendarzowe wysyłane kandydatowi przed rozmową z klientem.',
           'Przygotowanie do interview z (nazwa Klienta) – (imię i nazwisko kandydata)',
           'Dzień dobry (bądź per „Ty”),\n\nZapraszam na spotkanie przygotowujące do interview z (nazwa Klienta) na stanowisko (nazwa stanowiska).\nTermin spotkania przygotowującego: (data prepa)\n\nTermin interview z (nazwa klienta): (data interview)\nLink do opisu stanowiska: (link do pracuj / rocketjobs / JJIT)\n\nW razie pytań pozostaję do dyspozycji.\n\nPozdrawiam',
           FALSE, 35, TRUE, now(), now()
       )
       ON CONFLICT (slug) DO NOTHING""",
    # 0224 — snapshot danych Partnera z `render_payload` do kolumn. Klucze są
    # 1:1 nazwami pól `B2BRenderRequest` (bez aliasów, bez `exclude_none`).
    #
    # `WHERE <kolumna> IS NULL` to nie optymalizacja, a poprawność: te
    # instrukcje lecą przy KAŻDYM starcie kontenera, więc bez tego warunku
    # ręcznie poprawiona nazwa firmy byłaby cyklicznie nadpisywana starym
    # payloadem. `jsonb_typeof(...) = 'object'` chroni przed payloadem
    # skalarnym, a `left(..., N)` przed `value too long`, które wywala CAŁY
    # start kontenera, nie jeden wiersz.
    """UPDATE b2b_generated_contracts
          SET partner_legal_name =
              left(NULLIF(TRIM(render_payload ->> 'partner_legal_name'), ''), 255)
        WHERE partner_legal_name IS NULL
          AND render_payload IS NOT NULL
          AND jsonb_typeof(render_payload) = 'object'
          AND NULLIF(TRIM(render_payload ->> 'partner_legal_name'), '') IS NOT NULL""",
    # NIP kanonicznie do samych cyfr — surowe formatowanie („123-456-32-18")
    # zostaje w `render_payload`, żeby dokument renderował się bez zmian.
    r"""UPDATE b2b_generated_contracts
          SET partner_nip = left(
                  NULLIF(
                      regexp_replace(
                          COALESCE(render_payload ->> 'partner_nip', ''), '\D', '', 'g'
                      ),
                      ''
                  ),
                  32
              )
        WHERE partner_nip IS NULL
          AND render_payload IS NOT NULL
          AND jsonb_typeof(render_payload) = 'object'
          AND NULLIF(
                  regexp_replace(
                      COALESCE(render_payload ->> 'partner_nip', ''), '\D', '', 'g'
                  ),
                  ''
              ) IS NOT NULL""",
    # Regex-guard zamiast `NULLIF(..., '')::date`: CI-sentinel sieje payload
    # bez klucza `start_date`, a formularz umie zapisać pusty string — `::date`
    # na jednym i drugim wywala instrukcję.
    """UPDATE b2b_generated_contracts
          SET start_date = (render_payload ->> 'start_date')::date
        WHERE start_date IS NULL
          AND render_payload IS NOT NULL
          AND jsonb_typeof(render_payload) = 'object'
          AND render_payload ->> 'start_date' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'""",
    # ── 0242: trzy punktowe korekty (BIK: struktura + status linii MD; BP: ──
    # przepięcie podpisanej umowy B2B na właściwy projekt).
    #
    # Lustro migracji `0242_order_md_transfer_and_bp_bik_backfill`. Prod ma
    # `alembic_version` osierocony na 0152, więc sama migracja jest tam NO-OPEM
    # — realnym mechanizmem wdrożenia jest ta lista.
    #
    # Różnica wobec migracji: tam „zero dopasowań" przerywa RAISE-em, tutaj
    # NIE MOŻE. Wyjątek wywraca cały blok DO razem z markerem, a jedynym śladem
    # jest jedna linijka „backfill data skip" w logu kontenera (`/api/health`
    # zostaje zielony) — czyli głośna asercja zamieniłaby się w cichą pętlę
    # powtarzaną przy każdym starcie. Zamiast tego każdy krok jest warunkowy
    # i idempotentny, a marker zapisuje LICZBY, po których widać, co realnie
    # zadziałało.
    r"""DO $bp_bik_backfill$
    DECLARE
        scheduled_group_id INTEGER;
        scheduled_line_rows BIGINT := 0;
        reactivated_line_rows BIGINT := 0;
        generated_rows BIGINT := 0;
        md_line_id INTEGER;
        target_contract_id INTEGER;
    BEGIN
        IF EXISTS (
            SELECT 1 FROM app_settings
             WHERE key = '0242_bp_bik_order_and_contract_backfill'
        ) THEN
            RETURN;
        END IF;

        -- 1. Grupa 4500029903 (BIK) ma poprawnego poprzednika, ale status
        --    `active`, więc renderuje się jako równorzędna karta zamiast
        --    zagnieździć się pod 4500030067. Zagnieżdżenie wymaga `scheduled`.
        SELECT g.id INTO scheduled_group_id
          FROM client_order_groups AS g
         WHERE g.client_id = 18
           AND g.order_number = '4500029903'
           AND g.status = 'active'
           AND g.predecessor_group_id IS NOT NULL
         ORDER BY g.id
         LIMIT 1;

        IF scheduled_group_id IS NOT NULL THEN
            UPDATE client_order_groups
               SET status = 'scheduled', updated_at = now()
             WHERE id = scheduled_group_id;

            UPDATE client_orders
               SET status = 'draft'::clientorderstatus,
                   filled_at = NULL,
                   updated_at = now()
             WHERE order_group_id = scheduled_group_id
               AND status = 'active'::clientorderstatus;
            GET DIAGNOSTICS scheduled_line_rows = ROW_COUNT;
        END IF;

        -- 2. Linia 4500030067 jest `completed` mimo NIEWYCZERPANYCH MD.
        --    Po tej rewizji o zamknięciu linii MD decyduje wyłącznie budżet.
        SELECT o.id INTO md_line_id
          FROM client_orders AS o
          JOIN client_order_groups AS g ON g.id = o.order_group_id
         WHERE g.client_id = 18
           AND g.order_number = '4500030067'
           AND o.status = 'completed'::clientorderstatus
           AND o.md_total IS NOT NULL
           AND o.md_remaining > 0
         ORDER BY o.id
         LIMIT 1;

        IF md_line_id IS NOT NULL THEN
            UPDATE client_orders
               SET status = 'active'::clientorderstatus, updated_at = now()
             WHERE id = md_line_id;
            GET DIAGNOSTICS reactivated_line_rows = ROW_COUNT;
        END IF;

        -- 3. Umowa 1476/2026 wskazuje projekt Energa, a dokument drukuje
        --    stronę „Bank Pocztowy S.A.". Kontrakt docelowy potwierdzamy
        --    kandydatem i klientem, nie samym id ze zrzutu produkcji.
        SELECT c.id INTO target_contract_id
          FROM contracts AS c
         WHERE c.candidate_id = 154325
           AND c.client_id = 16
           AND c.status <> 'void'
         ORDER BY c.id
         LIMIT 1;

        IF target_contract_id IS NOT NULL THEN
            UPDATE b2b_generated_contracts
               SET contract_id = target_contract_id,
                   client_id = 16,
                   job_id = (
                       SELECT c.job_id FROM contracts AS c
                        WHERE c.id = target_contract_id
                   ),
                   updated_at = now()
             WHERE contract_number = '1476/2026'
               AND candidate_id = 154325
               AND signature_status = 'signed_both'
               AND contract_id IS DISTINCT FROM target_contract_id;
            GET DIAGNOSTICS generated_rows = ROW_COUNT;
        END IF;

        INSERT INTO app_settings (key, value)
        VALUES (
            '0242_bp_bik_order_and_contract_backfill',
            jsonb_build_object(
                'revision', '0242_order_md_transfer_and_bp_bik_backfill',
                'completed_at', clock_timestamp(),
                'source', 'entrypoint',
                'scheduled_group_rows', CASE WHEN scheduled_group_id IS NULL THEN 0 ELSE 1 END,
                'scheduled_line_rows', scheduled_line_rows,
                'reactivated_line_rows', reactivated_line_rows,
                'generated_contract_rows', generated_rows,
                'rollback', 'manual_only'
            )
        )
        ON CONFLICT (key) DO NOTHING;
    END
    $bp_bik_backfill$""",
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
    # 0249: data phase above has filled every existing row. Defaults protect
    # rolling legacy writers; NOT NULL matches the ORM snapshot invariant.
    "ALTER TABLE client_orders ALTER COLUMN rate_unit SET DEFAULT 'monthly'",
    "ALTER TABLE client_orders ALTER COLUMN rate_unit SET NOT NULL",
    "ALTER TABLE client_orders ALTER COLUMN billing_hours_per_month SET DEFAULT 160",
    "ALTER TABLE client_orders ALTER COLUMN billing_hours_per_month SET NOT NULL",
    # Atomic closed-domain rewrite. If lock_timeout fires, the DROP rolls back
    # with the ADD and the next container start retries safely.
    #
    # JEDYNA definicja tej domeny w safety-necie (lustro `DlAlert.__table_args__`
    # i migracji 0265). Do 03.09.2026 lustro 0265 stało WYŻEJ w tej liście
    # i dodawało `order_mail_review`, a ten blok — starszy, z wąską listą —
    # wykonywał się PO nim i przy każdym deployu ZWĘŻAŁ więz z powrotem.
    # Skutek na prodzie: żaden alert „zamówienie z maila do weryfikacji"
    # nie dał się zapisać (CheckViolationError w `notify_review`), a do #1355
    # ten sam błąd zatruwał sesję i zostawiał stan biegu na „running".
    # Pilnuje tego `tests/test_entrypoint_dl_alerts_check_mirror.py`.
    """DO $$ BEGIN
        ALTER TABLE dl_alerts DROP CONSTRAINT IF EXISTS ck_dl_alerts_type;
        ALTER TABLE dl_alerts
            ADD CONSTRAINT ck_dl_alerts_type CHECK (alert_type IN (
                'cost_order_exhausted', 'draft_consultant_unassigned',
                'md_budget_low', 'missing_revenue_rate',
                'md_consultant_ended', 'order_mail_review'
            ));
    END $$""",
    # Detect the FK structurally rather than by name: metadata.create_all may
    # have installed an automatically named equivalent after an earlier boot.
    """DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint AS constraint_row
            JOIN pg_attribute AS source_column
              ON source_column.attrelid = constraint_row.conrelid
             AND source_column.attnum = ANY(constraint_row.conkey)
            WHERE constraint_row.contype = 'f'
              AND constraint_row.conrelid = 'dl_alerts'::regclass
              AND constraint_row.confrelid =
                  'client_order_offboarding_cases'::regclass
              AND source_column.attname = 'offboarding_case_id'
        ) THEN
            ALTER TABLE dl_alerts
                ADD CONSTRAINT fk_dl_alerts_offboarding_case
                FOREIGN KEY (offboarding_case_id)
                REFERENCES client_order_offboarding_cases(id)
                ON DELETE SET NULL NOT VALID;
        END IF;
    END $$""",
    # 0229 — pozycja Pomocy musi być ALBO linkiem, ALBO szablonem treści.
    # Wiersz bez `url` i bez `template_body` wyrenderowałby się w zakładce jako
    # martwa pozycja bez żadnej akcji — czyta się jak awaria, nie jak pustka.
    #
    # IF NOT EXISTS zamiast gołego ADD CONSTRAINT: te instrukcje lecą przy
    # KAŻDYM starcie kontenera, więc drugi boot musi być no-opem.
    """DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_help_materials_link_or_template'
              AND conrelid = 'help_materials'::regclass
        ) THEN
            ALTER TABLE help_materials
                ADD CONSTRAINT ck_help_materials_link_or_template
                CHECK (url IS NOT NULL OR template_body IS NOT NULL);
        END IF;
    END $$""",
    # 0227 — moduł Finanse. DROP przed ADD, nie samo `EXCEPTION WHEN
    # duplicate_object`: gdy kiedyś dojdzie trzeci status wersji, sam wyjątek
    # zostawiłby na prodzie stary, węższy CHECK i nowa wartość leciałaby
    # IntegrityError (dokładnie ten błąd naprawiała migracja 0226).
    "ALTER TABLE finance_import_runs DROP CONSTRAINT IF EXISTS ck_finance_import_runs_status",
    """DO $$ BEGIN
        ALTER TABLE finance_import_runs
            ADD CONSTRAINT ck_finance_import_runs_status
            CHECK (status IN ('current', 'superseded'));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "ALTER TABLE finance_import_runs DROP CONSTRAINT IF EXISTS ck_finance_import_runs_period_month",
    """DO $$ BEGIN
        ALTER TABLE finance_import_runs
            ADD CONSTRAINT ck_finance_import_runs_period_month
            CHECK (period_month BETWEEN 1 AND 12);
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "ALTER TABLE finance_import_runs DROP CONSTRAINT IF EXISTS ck_finance_import_runs_period_year",
    """DO $$ BEGIN
        ALTER TABLE finance_import_runs
            ADD CONSTRAINT ck_finance_import_runs_period_year
            CHECK (period_year BETWEEN 2000 AND 2100);
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # 0233 — cykl życia grupy zamówień i zamówienie kosztowe. DROP przed ADD:
    # domena statusu i domena zdarzeń będą jeszcze rosły, a samo `EXCEPTION
    # WHEN duplicate_object` zostawiłoby wtedy na prodzie stary, węższy CHECK
    # i pierwsza nowa wartość leciałaby IntegrityError (błąd z 0226).
    #
    # NOT VALID: istniejące wiersze spełniają te warunki z definicji (same
    # defaulty), więc skan całej tabeli pod ACCESS EXCLUSIVE nic by nie wniósł.
    # 0233 — linia zamówienia kosztowego ma obie stawki i NIE ma budżetu MD.
    # CHECK z 0227 wymagał `md_rate_revenue IS NULL` przy pustym budżecie, więc
    # bez tego rozluźnienia dodanie konsultanta do zamówienia kosztowego pada
    # na IntegrityError. Gwarancja „budżet wymaga dodatniej stawki" zostaje.
    "ALTER TABLE client_orders DROP CONSTRAINT IF EXISTS ck_client_orders_md_coherence",
    """DO $$ BEGIN
        ALTER TABLE client_orders
            ADD CONSTRAINT ck_client_orders_md_coherence
            CHECK (
                (
                    (
                        md_total IS NULL
                        AND md_remaining IS NULL
                        AND md_input_mode IS NULL
                        AND md_input_value IS NULL
                    )
                    OR (
                        md_total IS NOT NULL
                        AND md_remaining IS NOT NULL
                        AND md_input_mode IN ('md', 'amount')
                        AND md_input_value IS NOT NULL
                        AND md_rate_revenue IS NOT NULL
                        AND md_rate_revenue > 0
                    )
                )
                AND (md_rate_revenue IS NULL OR md_rate_revenue > 0)
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "ALTER TABLE client_order_groups DROP CONSTRAINT IF EXISTS ck_client_order_groups_status",
    """DO $$ BEGIN
        ALTER TABLE client_order_groups
            ADD CONSTRAINT ck_client_order_groups_status
            CHECK (status IN ('active', 'scheduled', 'completed', 'exhausted')) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # 0238 — master PDF grupy i automatyczna kopia na kontrakcie. Sprawdzamy
    # semantycznie po kolumnie/target table, nie wyłącznie po nazwie więzu.
    """DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint c
            JOIN pg_attribute a
              ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            WHERE c.contype = 'f'
              AND c.conrelid = 'client_order_groups'::regclass
              AND c.confrelid = 'users'::regclass
              AND a.attname = 'file_uploaded_by'
        ) THEN
            ALTER TABLE client_order_groups
                ADD CONSTRAINT fk_client_order_groups_file_uploaded_by_users
                FOREIGN KEY (file_uploaded_by) REFERENCES users(id)
                ON DELETE SET NULL NOT VALID;
        END IF;
    END $$""",
    """DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint c
            JOIN pg_attribute a
              ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            WHERE c.contype = 'f'
              AND c.conrelid = 'contract_documents'::regclass
              AND c.confrelid = 'client_order_groups'::regclass
              AND a.attname = 'source_order_group_id'
        ) THEN
            ALTER TABLE contract_documents
                ADD CONSTRAINT fk_contract_documents_source_order_group
                FOREIGN KEY (source_order_group_id)
                REFERENCES client_order_groups(id)
                ON DELETE SET NULL NOT VALID;
        END IF;
    END $$""",
    "ALTER TABLE client_order_groups "
    "DROP CONSTRAINT IF EXISTS ck_client_order_groups_cost_coherence",
    """DO $$ BEGIN
        ALTER TABLE client_order_groups
            ADD CONSTRAINT ck_client_order_groups_cost_coherence
            CHECK (
                (
                    is_cost_based = FALSE
                    AND budget_amount IS NULL
                    AND budget_remaining IS NULL
                )
                OR (
                    is_cost_based = TRUE
                    AND budget_amount IS NOT NULL
                    AND budget_amount > 0
                    AND budget_remaining IS NOT NULL
                )
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # 0245 — koszt i wspólna pula MD są rozłącznymi typami, a pola MD są
    # kompletne albo nieobecne. DROP+ADD naprawia także starszy, węższy CHECK.
    "ALTER TABLE client_order_groups "
    "DROP CONSTRAINT IF EXISTS ck_client_order_groups_settlement_exclusive",
    """DO $$ BEGIN
        ALTER TABLE client_order_groups
            ADD CONSTRAINT ck_client_order_groups_settlement_exclusive
            CHECK (NOT (is_cost_based = TRUE AND is_md_budget_based = TRUE))
            NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "ALTER TABLE client_order_groups "
    "DROP CONSTRAINT IF EXISTS ck_client_order_groups_md_budget_coherence",
    """DO $$ BEGIN
        ALTER TABLE client_order_groups
            ADD CONSTRAINT ck_client_order_groups_md_budget_coherence
            CHECK (
                (
                    is_md_budget_based = FALSE
                    AND md_budget_total IS NULL
                    AND md_budget_remaining IS NULL
                    AND md_budget_manual_adjustment = 0
                )
                OR (
                    is_md_budget_based = TRUE
                    AND md_budget_total IS NOT NULL
                    AND md_budget_total > 0
                    AND md_budget_remaining IS NOT NULL
                    AND md_budget_remaining >= 0
                )
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # 0263 — spójność typu z flagami, BEZ zaszytych ID klientów. Do 0263 więz
    # kodował `client_id IN (155, 38339)`, czyli rozstrzygał w bazie, kto jest
    # Lotte Wedel i Cyfrowym Polsatem; aplikacja traktuje tę tożsamość jako
    # podmienialną, więc oba źródła prawdy się rozjeżdżały (500 w środku
    # aktywacji szkicu). DROP przed ADD jest tu obowiązkowy: sam
    # `EXCEPTION WHEN duplicate_object` zostawiłby stary, węższy kształt.
    "ALTER TABLE client_order_groups "
    "DROP CONSTRAINT IF EXISTS ck_client_order_groups_explicit_type_coherence",
    """DO $$ BEGIN
        ALTER TABLE client_order_groups
            ADD CONSTRAINT ck_client_order_groups_explicit_type_coherence
            CHECK (
                order_type IS NULL
                OR (
                    order_type = 'cost'
                    AND is_cost_based = TRUE
                    AND is_md_budget_based = FALSE
                )
                OR (order_type = 'md' AND is_cost_based = FALSE)
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "ALTER TABLE client_order_group_md_consumptions "
    "DROP CONSTRAINT IF EXISTS ck_group_md_consumptions_period",
    """DO $$ BEGIN
        ALTER TABLE client_order_group_md_consumptions
            ADD CONSTRAINT ck_group_md_consumptions_period
            CHECK (period_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$') NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "ALTER TABLE client_order_group_md_consumptions "
    "DROP CONSTRAINT IF EXISTS ck_group_md_consumptions_source",
    """DO $$ BEGIN
        ALTER TABLE client_order_group_md_consumptions
            ADD CONSTRAINT ck_group_md_consumptions_source
            CHECK (source IN ('import', 'manual')) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "ALTER TABLE client_order_group_md_consumptions "
    "DROP CONSTRAINT IF EXISTS ck_group_md_consumptions_nonnegative",
    """DO $$ BEGIN
        ALTER TABLE client_order_group_md_consumptions
            ADD CONSTRAINT ck_group_md_consumptions_nonnegative
            CHECK (md_reported >= 0) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint c
            JOIN pg_attribute a
              ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            WHERE c.contype = 'f'
              AND c.conrelid = 'client_order_group_md_consumptions'::regclass
              AND c.confrelid = 'client_order_groups'::regclass
              AND a.attname = 'group_id'
        ) THEN
            ALTER TABLE client_order_group_md_consumptions
                ADD CONSTRAINT fk_group_md_consumptions_group
                FOREIGN KEY (group_id) REFERENCES client_order_groups(id)
                ON DELETE CASCADE NOT VALID;
        END IF;
    END $$""",
    """DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint c
            JOIN pg_attribute a
              ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            WHERE c.contype = 'f'
              AND c.conrelid = 'client_order_group_md_consumptions'::regclass
              AND c.confrelid = 'users'::regclass
              AND a.attname = 'created_by_user_id'
        ) THEN
            ALTER TABLE client_order_group_md_consumptions
                ADD CONSTRAINT fk_group_md_consumptions_created_by
                FOREIGN KEY (created_by_user_id) REFERENCES users(id)
                ON DELETE SET NULL NOT VALID;
        END IF;
    END $$""",
    "ALTER TABLE client_order_groups DROP CONSTRAINT IF EXISTS ck_client_order_groups_closure",
    """DO $$ BEGIN
        ALTER TABLE client_order_groups
            ADD CONSTRAINT ck_client_order_groups_closure
            CHECK (status <> 'completed' OR closure_date IS NOT NULL) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # 0233 — pięć nowych typów zdarzeń cyklu życia. Ten CHECK jest dokładnie
    # tym, który migracja 0227 zapisała jako zamkniętą listę; poszerzenie MUSI
    # przejść przez DROP, inaczej prod odrzuci „zakonczenie" i zamknięcie
    # zamówienia wywali się w połowie transakcji.
    #
    # 0242 dokłada „transfer_md" — wpis o podziale MD między zamówieniem
    # bieżącym a przyszłym. Bez tego pierwszy import z Finansów, który przeleje
    # nadwyżkę na następcę, wywróci się IntegrityError-em w ŚRODKU transakcji
    # importu, czyli zabierze ze sobą także poprawnie dopasowane wiersze.
    # 0249 dodaje cztery zdarzenia offboardingu. DROP i ADD są teraz jednym
    # atomowym DO: timeout między dwiema transakcjami nie zostawia tabeli bez
    # ochrony domeny.
    # 0250 dokłada „przywrocenie_konsultanta" — trzecią decyzję DL po
    # zakończeniu współpracy (linia wraca na aktywną obsadę z nietkniętą pulą).
    # Świadomie OSOBNY slug od „przywrocenie", które opisuje przywrócenie
    # CAŁEGO zamówienia; wspólna wartość zlałaby w historii dwie różne
    # operacje na dwóch różnych poziomach.
    """DO $$ BEGIN
        ALTER TABLE client_order_group_events
            DROP CONSTRAINT IF EXISTS ck_client_order_group_events_type;
        ALTER TABLE client_order_group_events
            ADD CONSTRAINT ck_client_order_group_events_type
            CHECK (event_type IN (
                'utworzenie', 'dodanie_konsultanta', 'import_md',
                'zamiana_kontraktora', 'edycja_reczna', 'zakonczenie',
                'przywrocenie', 'wyczerpanie', 'przedluzenie', 'import_faktur',
                'transfer_md', 'zakonczenie_konsultanta',
                'decyzja_md_wymagana', 'usuniecie_puli_md',
                'przeniesienie_puli_md', 'przywrocenie_konsultanta'
            ));
    END $$""",
    # 0250 — trzecia decyzja offboardingowa („restore"). Poszerzenie MUSI
    # iść przez DROP: CREATE TABLE wyżej dotyczy WYŁĄCZNIE instalacji od zera,
    # a na produkcji tabela istnieje od 0249 z węższą domeną. Bez tego bloku
    # pierwsze „Przywróć jako aktywne" na prodzie kończy się naruszeniem
    # CHECK-a w środku transakcji decyzji.
    """DO $$ BEGIN
        ALTER TABLE client_order_offboarding_cases
            DROP CONSTRAINT IF EXISTS ck_client_order_offboarding_resolution;
        ALTER TABLE client_order_offboarding_cases
            ADD CONSTRAINT ck_client_order_offboarding_resolution
            CHECK (resolution IS NULL
                   OR resolution IN ('remove', 'transfer', 'restore'));
        ALTER TABLE client_order_offboarding_cases
            DROP CONSTRAINT IF EXISTS ck_client_order_offboarding_restore_target;
        ALTER TABLE client_order_offboarding_cases
            ADD CONSTRAINT ck_client_order_offboarding_restore_target
            CHECK (resolution IS DISTINCT FROM 'restore'
                   OR (target_order_id IS NULL AND rate_basis IS NULL));
    END $$""",
    "ALTER TABLE md_consumption_import_rows "
    "DROP CONSTRAINT IF EXISTS ck_md_import_rows_cost_status",
    """DO $$ BEGIN
        ALTER TABLE md_consumption_import_rows
            ADD CONSTRAINT ck_md_import_rows_cost_status
            CHECK (cost_status IS NULL OR cost_status IN (
                'applied', 'unmatched_number', 'unmatched_consultant'
            )) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "ALTER TABLE finance_monthly_results DROP CONSTRAINT IF EXISTS ck_finance_monthly_results_row_number",
    """DO $$ BEGIN
        ALTER TABLE finance_monthly_results
            ADD CONSTRAINT ck_finance_monthly_results_row_number
            CHECK (row_number >= 1);
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # 0222 — Talent Radar: nazwa przechodzi na moduł wyszukiwania, a źródło
    # importu dostaje `tr_legacy`. Oba CHECK-i przyjmują starą I nową wartość,
    # żeby rollback (redeploy poprzedniego obrazu, który wciąż pisze
    # `talent_radar`) nie wywalał się na naruszeniu constraintu.
    "ALTER TABLE candidate_languages DROP CONSTRAINT IF EXISTS ck_candidate_languages_provenance",
    """DO $$ BEGIN
        ALTER TABLE candidate_languages
            ADD CONSTRAINT ck_candidate_languages_provenance
            CHECK (provenance IN ('manual', 'cv', 'traffit', 'talent_radar',
                                  'tr_legacy', 'csv', 'legacy', 'unknown'));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "ALTER TABLE candidate_source_identity_reviews DROP CONSTRAINT IF EXISTS ck_candidate_source_identity_review_kind",
    """DO $$ BEGIN
        ALTER TABLE candidate_source_identity_reviews
            ADD CONSTRAINT ck_candidate_source_identity_review_kind
            CHECK (source_kind IN ('note', 'document', 'legacy_cv',
                                   'talent_radar_cv', 'tr_legacy_cv'));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
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
    # 0224/0226: 'in_progress' i 'suspended' jako trzeci i czwarty status.
    # DROP PRZED ADD, bo `EXCEPTION WHEN duplicate_object THEN NULL` po cichu
    # zostawiłby STARY, wąski constraint z 0203 — a wtedy INSERT z 'in_progress'
    # wywalałby CheckViolation przy każdym generowaniu umowy, a entrypoint
    # wypisałby tylko „backfill constraint skip".
    """ALTER TABLE b2b_generated_contracts
       DROP CONSTRAINT IF EXISTS ck_b2b_generated_contracts_contract_status""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_contract_status
            CHECK (
                contract_status IN ('active', 'in_progress', 'suspended', 'closed')
            )
            NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # 0226: katalog powodów opisuje teraz KONIEC PROJEKTU, nie rozstanie
    # z Partnerem. Trzy wartości z 0203 zostają mimo zniknięcia z pickera —
    # produkcja ma wiersze `closed`, które je niosą, a CHECK jest domeną
    # dopuszczalnych wartości, nie listą podpowiedzi w UI.
    #
    # DROP przed ADD dołożony w 0226: do tej pory ten wpis miał wyłącznie
    # `EXCEPTION WHEN duplicate_object`, więc poszerzenie katalogu nigdy by na
    # produkcji nie zadziałało — stary constraint zostałby nietknięty, a
    # pierwsze zamknięcie umowy nowym powodem poleciałoby CheckViolation.
    """ALTER TABLE b2b_generated_contracts
       DROP CONSTRAINT IF EXISTS ck_b2b_generated_contracts_closure_reason""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_closure_reason
            CHECK (
                closure_reason IS NULL OR
                closure_reason IN (
                    'no_client_budget',
                    'contractor_found_other_project',
                    'contractor_health_reasons',
                    'contractor_underperformance',
                    'project_completed',
                    'internalization',
                    'other',
                    'resignation_before_signing',
                    'termination',
                    'mutual_agreement'
                )
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # 0224: 'in_progress' traktowany jak 'active' — umowa w drodze do podpisu
    # nie ma pól zamknięcia. 0226: 'suspended' traktowany jak 'closed' — umowa
    # bez projektu MUSI powiedzieć, co i kiedy się skończyło. Bez tego
    # przepisania wiersz 'suspended' łamie OBIE gałęzie tego CHECK-a, więc samo
    # poszerzenie ck_..._contract_status wyżej NIE wystarczy. DROP przed ADD.
    """ALTER TABLE b2b_generated_contracts
       DROP CONSTRAINT IF EXISTS ck_b2b_generated_contracts_closure_coherence""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_closure_coherence
            CHECK (
                (
                    contract_status IN ('active', 'in_progress')
                    AND closure_reason IS NULL
                    AND closure_date IS NULL
                    AND closure_reason_other IS NULL
                ) OR (
                    contract_status IN ('closed', 'suspended')
                    AND closure_reason IS NOT NULL
                    AND closure_date IS NOT NULL
                    AND (
                        (closure_reason = 'other')
                        = (closure_reason_other IS NOT NULL)
                    )
                )
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    # 0224: domena typu podmiotu Partnera. NULL dozwolony = wiersz historyczny
    # bez sygnału z rejestru (heurystyka po nazwie działa w serializacji).
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_partner_entity_type
            CHECK (
                partner_entity_type IS NULL
                OR partner_entity_type IN ('sole_trader', 'company')
            ) NOT VALID;
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
]

# ── Indeksy zadeklarowane w ORM (index=True), których nie tworzy żadna migracja ──
# Zmierzone na produkcji 2026-07-20. Wtedy wszystkie były NIEUNIKALNE, więc
# nieudany build był stratą wydajności, nie integralności — i to uzasadniało
# połykanie porażek do samego `print()`. TO JUŻ NIEPRAWDA: lista urosła od
# 2026-07-24 o cztery pozycje UNIQUE (jedno główne CV na kandydata, jeden
# bieżący miesiąc importu finansowego, jeden pierwszy priorytet TAC na klienta,
# jedna główna kategoria kompetencji użytkownika). Nieprawidłowy indeks unikalny
# NIE wymusza niczego, więc porażka buildu to dziś także utrata inwariantu —
# stąd `_drop_invalid_indexes` przed pętlą.
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
    # 0249: pending MD decisions and their durable DL alerts.
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
    "ix_client_order_offboarding_cases_id "
    "ON client_order_offboarding_cases (id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
    "ix_client_order_offboarding_cases_contract_id "
    "ON client_order_offboarding_cases (contract_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
    "ix_client_order_offboarding_pending "
    "ON client_order_offboarding_cases (client_id, effective_date) "
    "WHERE status = 'pending'",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
    "ix_client_order_offboarding_contract_effective "
    "ON client_order_offboarding_cases (contract_id, effective_date)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
    "ix_client_order_offboarding_group "
    "ON client_order_offboarding_cases (order_group_id, status)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_dl_alerts_offboarding_case "
    "ON dl_alerts (offboarding_case_id)",
    # 0227 — moduł Finanse. Indeks CZĘŚCIOWY, nie zwykły UNIQUE: aktualna
    # wersja miesiąca musi być dokładnie jedna, ale zastąpionych wolno mieć
    # dowolnie wiele (to cała treść Archiwum). Pełny UNIQUE zabroniłby
    # drugiego importu tego samego miesiąca, czyli funkcji z ticketu.
    "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
    "uq_finance_import_runs_current_period "
    "ON finance_import_runs (period_year, period_month) "
    "WHERE status = 'current'",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_finance_import_runs_period "
    "ON finance_import_runs (period_year, period_month)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_finance_import_runs_status "
    "ON finance_import_runs (status)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_finance_monthly_results_import_run_id "
    "ON finance_monthly_results (import_run_id)",
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
    # 0233 — pigułka „Zakończeni"/„Wyczerpane" filtruje po statusie w obrębie
    # jednego klienta; skaner alertów pyta o otwarte wpisy per DL przy KAŻDYM
    # przebiegu, a log rośnie w nieskończoność (nie jest kasowany).
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_client_order_groups_status "
    "ON client_order_groups (client_id, status)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
    "ix_contract_documents_source_order_group_id "
    "ON contract_documents (source_order_group_id)",
    "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
    "uq_contract_documents_contract_order_group "
    "ON contract_documents (contract_id, source_order_group_id) "
    "WHERE source_order_group_id IS NOT NULL",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_dl_alerts_open "
    "ON dl_alerts (user_id, created_at) WHERE status = 'new'",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_dl_alerts_rule_scope "
    "ON dl_alerts (alert_type, user_id, client_id, created_at)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_dl_alerts_user_status "
    "ON dl_alerts (user_id, status, created_at)",
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


async def _apply_limits(conn, lock, statement):
    """Ustaw ``lock_timeout``/``statement_timeout`` na tym połączeniu.

    Wartości podajemy już jako literały SQL (``"'3s'"`` albo ``"0"``) — to
    parametry sesji, których nie da się związać placeholderem, a jedynym
    źródłem są stałe w tym pliku.
    """
    for name, value in (("lock_timeout", lock), ("statement_timeout", statement)):
        try:
            await conn.execute(f"SET {name} = {value}")
        except Exception as e:
            print(f"backfill: nie udało się ustawić {name}={value} -> {e!r}")


# ── Procedury utrzymywane w repozytorium ────────────────────────────────────
# Instrukcja obsługi zamówień (Pomoc → Procedury) opisuje ZACHOWANIE SYSTEMU,
# więc jej źródłem jest plik w repo, a nie wpis, który ktoś kiedyś wkleił do
# bazy. Migracja 0250 sieje ją tak samo — ten blok jest safety-netem na
# wypadek osieroconego alembica, dokładnie jak reszta tego pliku.
#
# Treści NIE ma tutaj dosłownie: to kilkadziesiąt kilobajtów Markdownu, a druga
# kopia rozjeżdża się z pierwszą przy pierwszej poprawce. Czytamy ten sam plik,
# który czyta migracja, i wysyłamy go PARAMETREM — sklejanie literału SQL z
# tekstu zawierającego apostrofy, dolary i backslashe to sposób na zepsucie
# startu kontenera cudzysłowem w zdaniu.
_REPO_PROCEDURES = [
    {
        "slug": "zamowienia-instrukcja-delivery-lead",
        "title": "Zamówienia — instrukcja dla Delivery Leada",
        "sort_order": 100,
        "filename": "zamowienia-instrukcja-delivery-lead.md",
    },
]

_PROCEDURE_UPSERT = """
    INSERT INTO procedures
        (title, slug, content, sort_order, is_published, created_at, updated_at)
    VALUES ($1, $2, $3, $4, TRUE, now(), now())
    ON CONFLICT (slug) DO UPDATE
        SET title = EXCLUDED.title,
            content = EXCLUDED.content,
            sort_order = EXCLUDED.sort_order,
            is_published = EXCLUDED.is_published,
            updated_at = now()
        WHERE procedures.updated_by IS NULL
"""


def _read_procedure(filename):
    """Treść procedury z obrazu. ``None`` = brak pliku, pomijamy zasiew.

    Dwie ścieżki, bo obraz ma WORKDIR ``/app`` i PYTHONPATH ``/app``, ale ten
    skrypt bywa uruchamiany też lokalnie z katalogu ``backend/``.
    """
    for base in ("/app/app/data/procedures", os.path.join(os.getcwd(), "app", "data", "procedures")):
        path = os.path.join(base, filename)
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            continue
    return None


async def _seed_repo_procedures(conn):
    """Wgraj procedury utrzymywane w repo.

    ``updated_by IS NULL`` w klauzuli ON CONFLICT: wiersz poprawiony ręcznie
    przez admina w aplikacji przestaje być nadpisywany przy wdrożeniu. Zasiew
    zostawia to pole puste, a ``PUT /api/procedures/{id}`` je stempluje, więc
    rozróżnienie „nasz tekst" / „czyjaś praca" nie wymaga dodatkowej kolumny.
    """
    for procedure in _REPO_PROCEDURES:
        content = _read_procedure(procedure["filename"])
        if not content:
            print(f"procedure seed skip: brak pliku {procedure['filename']}")
            continue
        try:
            await conn.execute(
                _PROCEDURE_UPSERT,
                procedure["title"],
                procedure["slug"],
                content,
                procedure["sort_order"],
            )
            print(f"procedure seed ok: {procedure['slug']}")
        except Exception as e:
            print(f"procedure seed skip: {procedure['slug']} -> {e!r}")


# ── Karta klienta: seed z pliku w repo ──────────────────────────────────────
# Lustro seeda migracji 0272. Źródło prawdy: `app/data/client_playbooks/
# seed.json` (treść dawnych 14 wzorów Championa per klient). Wiersz powstaje
# wyłącznie przy DOKŁADNIE JEDNYM żywym kliencie pasującym do wzorca nazwy
# i NIGDY nie nadpisuje istniejącego (ON CONFLICT DO NOTHING) — edycja
# Delivery Leada wygrywa z seedem na każdym kolejnym starcie.
#
# Wszystkie parametry rzutowane jawnie: w `INSERT … SELECT` Postgres nie
# wywnioskuje typu NULL-a. `documents` idzie jako string JSON → `::jsonb`.
_PLAYBOOK_SEED_SQL = """
    INSERT INTO client_playbooks
        (client_id, sla_business_days, sla_min_candidates, cv_limit_per_process,
         hold_hours, multi_project_cooldown_days, rate_policy, about_for_candidate,
         priority_rules, process_rules_md, onboarding_md, documents,
         version, seed_key, created_at, updated_at)
    SELECT c.id, $2::integer, $3::integer, $4::integer, $5::integer, $6::integer,
           $7::varchar, $8::text, $9::text, $10::text, $11::text, $12::jsonb,
           1, $13::varchar, now(), now()
    FROM clients c
    WHERE lower(c.name) LIKE $1
      AND c.hidden = FALSE
      AND c.merged_into_client_id IS NULL
      AND (SELECT count(*) FROM clients c2
            WHERE lower(c2.name) LIKE $1
              AND c2.hidden = FALSE
              AND c2.merged_into_client_id IS NULL) = 1
    ON CONFLICT (client_id) DO NOTHING
"""


def _read_playbook_seed():
    """Wpisy z seed.json albo None. Dwie ścieżki jak `_read_procedure`.

    Łapiemy też ValueError (zepsuty JSON): ta funkcja biegnie MIĘDZY
    `_DATA_STATEMENTS` a `_CONSTRAINT_STATEMENTS` i wyjątek urwałby
    constraints + indeksy całego startu.
    """
    for base in (
        "/app/app/data/client_playbooks",
        os.path.join(os.getcwd(), "app", "data", "client_playbooks"),
    ):
        path = os.path.join(base, "seed.json")
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            continue
    return None


async def _seed_client_playbooks(conn):
    entries = _read_playbook_seed()
    if not entries:
        print("client playbook seed skip: brak app/data/client_playbooks/seed.json")
        return
    for entry in entries:
        try:
            await conn.execute(
                _PLAYBOOK_SEED_SQL,
                entry["name_pattern"],
                entry.get("sla_business_days"),
                entry.get("sla_min_candidates"),
                entry.get("cv_limit_per_process"),
                entry.get("hold_hours"),
                entry.get("multi_project_cooldown_days"),
                entry.get("rate_policy"),
                entry.get("about_for_candidate"),
                entry.get("priority_rules"),
                entry.get("process_rules_md"),
                entry.get("onboarding_md"),
                json.dumps(entry.get("documents") or [], ensure_ascii=False),
                entry["seed_key"],
            )
            print(f"client playbook seed ok: {entry['seed_key']}")
        except Exception as e:
            print(f"client playbook seed skip: {entry.get('seed_key')} -> {e!r}")


_INDEX_NAME_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def _declared_index_names(statements):
    names = set()
    for stmt in statements:
        m = _INDEX_NAME_RE.search(stmt)
        if m:
            names.add(m.group(1).lower())
    return names


async def _drop_invalid_indexes(conn, statements):
    """Usuń NIEPRAWIDŁOWE indeksy z naszej listy, żeby dały się zbudować ponownie.

    Komentarz nad fazą indeksów obiecuje, że „nieudany indeks powtórzy się przy
    następnym starcie" — i dla CONCURRENTLY to nieprawda. Anulowany albo padnięty
    build zostawia w katalogu indeks z ``indisvalid = false``, a ``IF NOT EXISTS``
    widzi wtedy samą NAZWĘ relacji i pomija instrukcję już na zawsze. Czyli jedyny
    tryb awarii, przed którym broni statement_timeout, jest dokładnie tym, który
    staje się trwały.

    To nie jest wyłącznie strata wydajności: cztery pozycje z tej listy są UNIQUE
    i niosą inwarianty biznesowe (jedno główne CV na kandydata, jeden bieżący
    miesiąc importu finansowego). Nieprawidłowy indeks unikalny NIE wymusza
    niczego, więc duplikaty narastają w ciszy.

    Kasujemy wyłącznie nazwy, które sami deklarujemy tuż niżej — cudzego
    nieprawidłowego indeksu (np. z ręcznej operacji DBA) nie ruszamy.
    """
    declared = _declared_index_names(statements)
    if not declared:
        return
    try:
        rows = await conn.fetch(
            "SELECT c.relname FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE NOT i.indisvalid AND n.nspname = current_schema()"
        )
    except Exception as e:
        print(f"backfill: nie udało się odpytać o nieprawidłowe indeksy -> {e!r}")
        return
    for row in rows:
        name = row["relname"]
        if name.lower() not in declared:
            print(f"backfill: nieprawidłowy indeks spoza listy, pomijam: {name}")
            continue
        try:
            await conn.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"')
            print(f"backfill: usunięto nieprawidłowy indeks {name} (zbuduje się ponownie)")
        except Exception as e:
            print(f"backfill: DROP nieprawidłowego indeksu {name} nie powiódł się -> {e!r}")


async def backfill():
    url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://nexus:nexus@postgres:5432/nexus")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    # Enum ADD VALUE must run in autocommit mode.
    conn = await asyncpg.connect(url)
    try:
        # Limit CZEKANIA NA ZAMEK dla faz DDL biorących ACCESS EXCLUSIVE
        # (ALTER TABLE, ADD CONSTRAINT, zwykłe CREATE INDEX). Bez niego jedno
        # długie zapytanie na `candidates` ustawia ALTER-a w kolejce, a za nim
        # KAŻDEGO kolejnego czytelnika tabeli — żądania ACCESS EXCLUSIVE nie są
        # wyprzedzane. To nie jest awaria, tylko zwis: DDL nic nie zwraca, więc
        # `|| echo ... continuing` nigdy nie zadziała, a rekruterzy widzą po
        # prostu zawieszony ATS. Instrukcja, która trafi na kontencję, poddaje
        # się z LockNotAvailable, per-instrukcyjny `except` już to toleruje,
        # a przy następnym boocie spróbuje ponownie — to model odzyskiwania
        # zakładany w tym pliku wszędzie indziej.
        await _apply_limits(conn, lock="'3s'", statement="'60s'")
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
        # `_DATA_STATEMENTS` to backfille i seedy, nie DDL — wolno im trwać
        # (przerankowanie `candidate_documents` idzie po ~136 tys. wierszy).
        # Limit czasu zdejmujemy, limit CZEKANIA NA ZAMEK zostaje: instrukcja
        # ma się poddać, a nie ustawiać kolejki przed gorącą tabelą.
        await _apply_limits(conn, lock="'3s'", statement="0")
        for stmt in _DATA_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception as e:
                print(f"backfill data skip: {stmt!r} -> {e!r}")
        await _seed_repo_procedures(conn)
        await _seed_client_playbooks(conn)
        await _apply_limits(conn, lock="'3s'", statement="'60s'")
        for stmt in _CONSTRAINT_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception as e:
                print(f"backfill constraint skip: {stmt!r} -> {e!r}")
        # Indeksy na końcu: najwolniejsze i najmniej krytyczne. Limit czasu na
        # instrukcję, żeby jeden wolny CREATE INDEX nie zawiesił startu
        # kontenera — nieudany indeks powtórzy się przy następnym starcie
        # (patrz `_drop_invalid_indexes`, bez którego ta obietnica była pusta),
        # zablokowany deploy trzeba ratować ręcznie.
        #
        # `lock_timeout = 0` z powrotem: CREATE INDEX CONCURRENTLY z założenia
        # CZEKA na wydrenowanie transakcji widzących tabelę i robi to nie
        # blokując zapisów, więc trzysekundowy limit z faz wyżej byłby tu
        # przeciwskuteczny — zamieniałby normalne oczekiwanie w porażkę.
        await _apply_limits(conn, lock="0", statement="'120s'")
        await _drop_invalid_indexes(conn, _INDEX_STATEMENTS)
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
            try:
                await conn.execute("SET lock_timeout = 0")
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

# Rozdzielenie zamówień MD i okresowych — jednorazowa naprawa danych
# (safety-net dla migracji 0262, gdy alembic na prodzie stoi na starszej
# rewizji). Blok SQL jest ten sam co w migracji — jedno źródło w
# `app/services/order_separation_repair.py` — i jest idempotentny: advisory
# lock serializuje równoległe deploye, a marker w `app_settings` sprawia, że
# drugie wywołanie kończy się natychmiast.
echo "Separating MD and periodic client orders (one-shot, idempotent)..."
python - <<'PY' || echo "md/periodic order separation skipped; continuing"
import asyncio
from sqlalchemy import text
from app.core.database import engine
from app.services.order_separation_repair import (
    SEPARATE_MD_PERIODIC_MARKER,
    SEPARATE_MD_PERIODIC_SQL,
)

async def repair():
    async with engine.begin() as conn:
        await conn.execute(text(SEPARATE_MD_PERIODIC_SQL))
        receipt = await conn.scalar(
            text("SELECT value::text FROM app_settings WHERE key = :key"),
            {"key": SEPARATE_MD_PERIODIC_MARKER},
        )
    print(f"md/periodic separation: {receipt}")

asyncio.run(repair())
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
