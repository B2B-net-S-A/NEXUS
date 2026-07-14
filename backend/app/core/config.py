import logging
import os
import re
import warnings
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Nexus ATS"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    # Browser auth rollout. Production/staging use `.nexus.dynaminds.pl` so the
    # HttpOnly cookie is visible to both the Next.js middleware and API host.
    # Localhost deliberately leaves this empty (cookies are shared by hostname,
    # independent of port). Secure defaults to true and must only be disabled
    # for local HTTP development.
    SESSION_COOKIE_PREFIX: str = "nexus"
    SESSION_COOKIE_DOMAIN: str = ""
    SESSION_COOKIE_SECURE: bool = True
    # Temporary compatibility gate for JWTs minted before token_version was
    # deployed. Missing-version tokens are accepted only while the DB version
    # is still zero; any logout/password reset revokes them immediately. Flip
    # false after the maximum legacy refresh-token lifetime (30 days).
    JWT_ALLOW_LEGACY_VERSIONLESS: bool = True
    # Query-string WS JWTs are retained only for the transition. The web client
    # no longer creates them; flip false after existing browser sessions expire.
    JWT_ALLOW_LEGACY_WS_QUERY_TOKEN: bool = True

    # Database (PostgreSQL)
    DATABASE_URL: str = "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus"

    # Qdrant (vector store for semantic search)
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION: str = "nexus_candidates"

    # Voyage AI (embeddings)
    VOYAGE_API_KEY: str = ""
    # voyage-3-large: MTEB 65.1 (#1, +9.74% over OpenAI v3-large). Matryoshka
    # learning keeps 1024-dim outputs compatible with existing Qdrant collection.
    VOYAGE_MODEL: str = "voyage-3-large"
    EMBEDDING_DIMENSION: int = 1024
    # Voyage Rerank 2.5 — best balance accuracy/latency (~595ms p95).
    # Enabled by default — has graceful passthrough on API failure (rerank
    # service returns identity ordering, never breaks retrieval).
    VOYAGE_RERANK_MODEL: str = "rerank-2.5"
    RERANKER_ENABLED: bool = True

    # ── AI matching: "pokaż wszystkich kandydatów, którzy pasują" ─────────────
    # Zastępuje stary twardy cap top-10. Oba silniki (legacy /ai-matches oraz
    # hybrydowe /recommendations + proposals) zwracają TERAZ wszystkich
    # kandydatów ze score >= próg, przycięte do MATCH_MAX_RESULTS jako bezpiecznik
    # rozmiaru payloadu. Wszystkie tunowalne runtime przez Coolify env (bez
    # rebuildu — is_runtime).
    #
    # Kalibracja 2026-05-29 na żywych rozkładach z joba 15 (Scrum Master):
    #   • legacy rerank score (Voyage rerank-2.5, 0-1): klaster 0.61-0.87 →
    #     próg 0.5 trzyma trafny zbiór, ucina szum gdy poszerzymy pulę.
    #   • hybrydowy composite (0-100): historycznie ZANIŻONY (długi płaski ogon
    #     24-34 — semantycznie trafni, ale composite ciągniony w dół bo surowy
    #     cosinus + salary/location nieznane → 0 pkt). RECALIBRACJA 2026-06-23
    #     (patrz scoring_service.SEMANTIC_CALIBRATION_GAMMA / UNKNOWN_NEUTRAL_
    #     FRACTION niżej) podnosi krzywą semantyczną i traktuje brak danych jako
    #     neutralny (połowa budżetu, jak availability/champion). Trafny kandydat
    #     ląduje teraz ~55-70 zamiast ~30-37 → próg podniesiony 25 → 40, by
    #     utrzymać podobny zbiór wyników na nowej skali (tunowalny env runtime).
    # legacy /ai-matches (rerank/cosine/skill-fraction, skala 0-1)
    AI_MATCH_MIN_SCORE: float = 0.5
    # ile kandydatów retrieve z Qdrant przed filtrem progu (koszt rerank ~liniowy)
    AI_MATCH_POOL_SIZE: int = 100
    # hybrydowe /recommendations + proposals (skala 0-100). Po recalibracji
    # (2026-06-23) skala jest realistyczna, więc próg podniesiony z 25 → 40.
    RECOMMENDATION_MIN_SCORE: float = 40.0
    # twardy bezpiecznik rozmiaru wyniku (oba silniki)
    MATCH_MAX_RESULTS: int = 200
    # Gdy filtr lokalizacji jest aktywny na /recommendations, poszerzamy pulę
    # retrieve z Qdrant do tej wartości — tylko ~17% kandydatów ma jakąkolwiek
    # lokalizację, więc domyślny semantic cut (top-200) głodzi zlokalizowany
    # podzbiór. Po retrieve pre-filtrujemy po lokalizacji i scorujemy DOPIERO
    # dopasowany podzbiór, więc koszt scoringu pozostaje ograniczony.
    RECOMMENDATION_LOCATION_POOL_SIZE: int = 500

    # ── Hybrid composite calibration (recalibracja 2026-06-23) ────────────────
    # Composite 0-100 było systematycznie zaniżane: (1) surowy cosinus Voyage dla
    # trafnych kandydatów to ~0.4-0.65 → liniowe sim*budżet niedoszacowuje; (2)
    # salary/location dawały 0 przy braku danych (~99% importów bez stawki,
    # ~99.6% ofert bez lokalizacji), podczas gdy availability/champion_fit już
    # używały neutralnej połowy. Oba sterowalne runtime (env, is_runtime):
    #   • SEMANTIC_CALIBRATION_GAMMA<1 podnosi środek krzywej (0.6: cos 0.5→0.66
    #     budżetu) bez saturacji szczytu; monotoniczne → ranking zachowany.
    #     1.0 = stare liniowe zachowanie.
    #   • SCORE_UNKNOWN_NEUTRAL_FRACTION → „brak sygnału = ten ułamek budżetu".
    #     Steruje WSZYSTKIMI czterema warstwami metadanych przy braku danych
    #     (salary, location, availability, champion_fit) — jeden spójny pokrętło.
    #     0.0 = stare twarde zero.
    # Pełny rollback bez redeployu: ustaw 1.0 / 0.0.
    #
    # Dostrojenie 2026-06-30 („AI scoring dalej zbyt surowy" — joby z Traffitu):
    # ~99% importów to oferty bez lokalizacji/widełek/deadline'u/championa (np.
    # „Ferryt Developer" #240915), więc 35 z 100 pkt żyje w warstwach metadanych,
    # które mogą przyznać tylko swój neutralny ułamek. Przy 0.5 nawet idealny
    # trafny kandydat dobijał ~55. Dwie zmiany (obie zachowują ranking →
    # P@5/Recall@20/MRR/nDCG niezmienione, bo to stały addytywny shift per-job dla
    # dominującej kohorty „wszystko nieznane"):
    #   1. location przestaje twardo-zerować przy braku sygnału (brak lokalizacji
    #      oferty / brak preferencji remote kandydata) — teraz neutralny ułamek,
    #      spójnie z salary/availability/champion (patrz scoring_service).
    #   2. ułamek podniesiony 0.5 → 0.65 (benefit of the doubt dla nieznanych).
    # Efekt: trafny kandydat ~64, dotąd ~55; cała pula +~9 pkt. Mniej → 0.5;
    # więcej leniency → 0.7 (env, bez redeployu).
    SEMANTIC_CALIBRATION_GAMMA: float = 0.6
    SCORE_UNKNOWN_NEUTRAL_FRACTION: float = 0.65

    # Ollama (local LLM + embeddings fallback)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"
    OLLAMA_EMBED_MODEL: str = "mxbai-embed-large"

    # Anthropic (Claude) — used by CV enrichment and AI job writer
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL_CV: str = "claude-sonnet-5"
    CV_ENRICHMENT_ENABLED: bool = True  # kill-switch without redeploy

    # Fireflies integration
    FIREFLIES_API_KEY: str = ""

    # CEIDG API v3 (dane.biznes.gov.pl) — token JWT do auto-uzupełniania nazwy
    # firmy JDG w Generatorze Umów B2B. Pusty = używamy tylko Białej Listy MF
    # (zwraca imię+nazwisko właściciela zamiast pełnej nazwy firmy JDG).
    # Token: dane.biznes.gov.pl → rejestracja → wygeneruj klucz API.
    CEIDG_API_TOKEN: str = ""

    # Sentry (error tracking)
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"

    # Ops snapshot endpoint (/api/admin/snapshot) — token auth for cron + Claude
    # Code. Empty = token auth disabled, JWT-admin still works as fallback.
    SNAPSHOT_TOKEN: str = ""

    # CORS — tight by default; widen via env CORS_ORIGINS='["https://app"]'
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # Public-facing base URL for building shareable links (e.g. invite apply URLs).
    # In production: https://app.example.com. In dev: whatever the Next.js server
    # runs on (default http://localhost:3000).
    PUBLIC_BASE_URL: str = "http://localhost:3000"

    # File uploads
    UPLOAD_DIR: str = "/tmp/nexus/uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # ── Phase 13: notification triggers ──────────────────────────────────────
    BUSINESS_TZ: str = "Europe/Warsaw"
    # Ile Call (status=completed) / dzień roboczy rekrutera musi mieć do 11:45.
    POWERCALLING_DAILY_TARGET: int = 15
    POWERCALLING_CHECK_HOUR: int = 11
    POWERCALLING_CHECK_MINUTE: int = 45
    # Alert do DL o braku feedbacku klienta — przed końcem dnia pracy.
    CLIENT_FEEDBACK_ALERT_HOUR: int = 16
    CLIENT_FEEDBACK_ALERT_MINUTE: int = 30
    # "Zweryfikowany kandydat" utknął w cv_sent od X godzin → alert do DL.
    DL_STAGE_STALE_HOURS: int = 6
    # Górna granica okna: nie alertuj kandydatów zalegających w cv_sent dłużej
    # niż X dni. Bez tego limitu historyczny backlog (np. 10k+ kandydatów z
    # importów nigdy nieprzesuniętych) odpalał alert codziennie — patrz
    # incydent notifications 2026-05-22.
    DL_STAGE_STALE_MAX_DAYS: int = 14
    # Kandydat na nieterminalnym etapie bez zmiany od X dni → alert do rekrutera.
    STAGE_STUCK_DAYS: int = 7
    # Call completed X minut temu bez ScreeningNote → alert do rekrutera.
    CANDIDATE_FEEDBACK_AFTER_MINUTES: int = 60
    # Interwał orkiestratora (wszystkie 5 triggerów w jednej pętli).
    TRIGGERS_LOOP_INTERVAL_SECONDS: int = 300

    # ── Targ kandydatów (Candidate Marketplace) ──────────────────────────────
    # Singleton pula + auto-sync + notyfikacje po score >= threshold.
    # Kill-switch bez redeploya: MARKETPLACE_ENABLED=false wyłącza skany oraz
    # loop, ale pozostawia endpointy API (UI może dalej listować kandydatów).
    MARKETPLACE_ENABLED: bool = True
    # Próg alertów Targu (skala composite 0-100). Podniesiony 70 → 80 wraz z
    # recalibracją scoringu (2026-06-23): po podniesieniu skali stary próg 70
    # stał się osiągalny przez ~6-10× większy zbiór → ryzyko zalewu notyfikacji.
    # 80 przywraca rzadkość „tylko realnie mocne dopasowania". Tunowalny env.
    MARKETPLACE_SCORE_THRESHOLD: float = 80.0
    MARKETPLACE_DEFAULT_DURATION_DAYS: int = 30
    MARKETPLACE_SWEEP_INTERVAL_SECONDS: int = 1800  # 30 min safety net
    MARKETPLACE_TOP_K_MATCHES_PER_CANDIDATE: int = 3
    # Rate-limit: max notyfikacji na kandydata per owner per 24h. Powyżej →
    # agregat "N nowych matchy ≥70" (Phase 2 feature; w MVP wyłączone przez 0).
    MARKETPLACE_MAX_ALERTS_PER_CANDIDATE_PER_DAY: int = 0

    # ── Szybkie przepinanie (similar-job notify) ─────────────────────────────
    # Po utworzeniu joba: jeśli istnieją Tier A podobne historyczne requesty
    # z kandydatami po etapach klienckich — notyfikacja in-app do
    # recruiter/TAC/twórcy joba. Kill-switch bez redeploya.
    SIMILAR_JOB_NOTIFY_ENABLED: bool = True
    SIMILAR_JOB_NOTIFY_MIN_CANDIDATES: int = 1

    # ── Phase 14: post-interview feedback reminders ──────────────────────────
    # 3-stopniowy ping rekruterowi/DL po zakończonym interview.
    POST_INTERVIEW_T15_MINUTES: int = 15
    POST_INTERVIEW_T45_MINUTES: int = 45
    POST_INTERVIEW_T2H_MINUTES: int = 120
    # Po ilu minutach od end_time interview z status=scheduled → auto-flip na
    # completed (sygnał, że event się odbył, nawet jeśli nikt go ręcznie nie
    # oznaczył). 10 min grace period absorbuje opóźnienia.
    INTERVIEW_AUTO_COMPLETE_GRACE_MINUTES: int = 10

    # ── Email (SMTP) — fallback kanał po T+45 dla post-interview alertów ─────
    # Default: OFF. Włącza się envem SMTP_ENABLED=true. Bez credsów mailer jest
    # no-op'em (log i return) — nie blokuje triggerów ani handlerów.
    SMTP_ENABLED: bool = False
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "nexus@b2bnet.pl"
    SMTP_USE_TLS: bool = True

    # ── KPI Coach (dynamiczna analiza KPI rekruterów) ─────────────────────────
    # Interwał pętli `app/tasks/kpi_coach_nudger.py`. 300s (5min) to dobry
    # kompromis między "niemal real-time" a niską presją na DB. Clampowane
    # do >= 60s w loopie.
    KPI_COACH_LOOP_INTERVAL_SECONDS: int = 300

    # Externally reachable base URL for the public API. Used by Outlook
    # Actionable Messages (Phase 7.5) which require Microsoft's servers to be
    # able to resolve the action target URL — localhost/tunnel won't work.
    PUBLIC_API_BASE_URL: str = "https://api.nexus.dynaminds.pl"

    # ── Microsoft 365 integration (Phase M365.1) ─────────────────────────────
    # Kill-switch for the whole integration. When False: router skips registration,
    # sync loop exits immediately — used when rolling out or reverting.
    M365_INTEGRATION_ENABLED: bool = True
    # Azure AD App Registration (multi-tenant). Empty in dev until IT Admin provides them.
    M365_CLIENT_ID: str = ""
    M365_CLIENT_SECRET: str = ""
    # "common" for multi-tenant authorize URL; actual tenant guid is recorded on the
    # connection row from the ID token claim.
    M365_TENANT_ID: str = "common"
    # Absolute URL Microsoft redirects back to after consent. Must match one of the
    # Redirect URIs configured in the Azure app.
    M365_REDIRECT_URI: str = "https://api.nexus.dynaminds.pl/api/microsoft365/callback"
    # Fernet key for token-at-rest encryption. Generate via:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Empty → TokenCipher raises at first use, not at startup (so dev/tests can run
    # without the secret as long as nothing actually calls M365 paths).
    M365_TOKEN_ENCRYPTION_KEY: str = ""
    # Separate signing key for the short-lived OAuth state JWT so it does not share
    # the main SECRET_KEY. Defaults to SECRET_KEY when empty — acceptable for dev,
    # override in prod.
    M365_STATE_SIGNING_KEY: str = ""
    # Scopes requested during authorize. MSAL adds `offline_access`, `openid`,
    # and `profile` automatically (they are reserved — passing them raises
    # ValueError). Refresh token is still returned because MSAL injects
    # `offline_access` at the token endpoint under the hood.
    M365_SCOPES: List[str] = [
        "Mail.ReadWrite",
        "Mail.Send",
        "Calendars.ReadWrite",
        "User.Read",
    ]
    # Sync loop cadence; clamped to >=60s in the loop itself.
    M365_SYNC_INTERVAL_SECONDS: int = 300
    # Separate kill-switch for the background sync loop (router stays live so
    # the user can connect/disconnect via UI regardless). Default OFF in prod
    # until we're confident the loop can't exhaust the DB pool again.
    # Flip to True via Coolify env var after a stable window.
    M365_SYNC_LOOP_ENABLED: bool = False
    # Initial backfill window when user first connects.
    M365_BACKFILL_MONTHS: int = 12
    # Outlook category string that opts an email OUT of ATS sync (user-controlled).
    M365_IGNORE_CATEGORY: str = "ATS:ignore"
    # Hard cap on attachment download size (Phase 1 inline only; large upload in Phase 2).
    M365_MAX_ATTACHMENT_MB: int = 25
    # Whether to auto-parse CV attachments via cv_parser (Claude calls = $$).
    M365_AUTO_PARSE_CV: bool = True
    # Phase 5.2 — hourly background loop that retries `matcher.match` on emails
    # synced before the candidate row existed in the DB. Cheap (LIMIT 500, single
    # SELECT + per-row UPDATEs) but kept behind a flag so it stays off until the
    # main sync loop is stable in prod.
    M365_REMATCH_ENABLED: bool = False
    # Cadence; clamped to >=600s in the loop (we never want to rematch faster
    # than 10 min — it's a catch-up job, not real-time).
    M365_REMATCH_INTERVAL_SECONDS: int = 3600
    # Look-back window. Older emails are skipped — if a candidate appears 30+ days
    # after the email, the user is expected to use manual linking from the UI.
    M365_REMATCH_LOOKBACK_DAYS: int = 30
    # Max emails to process per pass. Keeps a single iteration cheap and bounded.
    M365_REMATCH_BATCH_SIZE: int = 500
    # Phase 7.7 — append the user's Outlook signature to every outbound mail
    # so NEXUS-sent emails look identical to ones sent from Outlook itself.
    # Kill-switch if signature parsing causes regressions (e.g. unexpected
    # HTML bloating the body or duplicating an existing signature in the
    # composer template).
    M365_SIGNATURE_INJECTION_ENABLED: bool = True
    # Per-mailbox cache TTL for the parsed signature. 24h matches how often
    # most users update their signature (~never) while still surfacing
    # changes within a day. Clamped to >=60s by the cache.
    M365_SIGNATURE_CACHE_TTL_SECONDS: int = 86400

    # Phase 7.8 — periodic OneDrive scan for Teams meeting recordings.
    # Teams auto-saves the recording to the organizer's OneDrive in
    # /Recordings/<title>.mp4 once the meeting ends. We poll a few times
    # after the event (~6h cadence over the lookback window) so the link
    # appears in NEXUS without anyone uploading anything manually.
    # OFF by default — needs the Phase 7.1 columns deployed first, and we
    # only want to spend Graph quota when interviews are routinely recorded.
    M365_RECORDING_DISCOVERY_ENABLED: bool = False
    # Cadence. Clamped to >=600s inside the loop; 6h matches how long it
    # typically takes Teams to publish the recording (transcode + upload).
    M365_RECORDING_DISCOVERY_INTERVAL_SECONDS: int = 21600
    # How far back to scan. 7 days catches every realistic Teams publish
    # delay while keeping the candidate set small (a single recruiter has
    # at most a handful of interview events per week).
    M365_RECORDING_DISCOVERY_LOOKBACK_DAYS: int = 7
    # Max events to inspect per pass — bounds Graph search calls per tick.
    M365_RECORDING_DISCOVERY_BATCH_SIZE: int = 100

    # ── M365 Graph push webhooks (Phase 7.3) ──────────────────────────────────
    # Push notifications replace polling once stable. Default OFF — flip to True
    # in Coolify env after deploying so the lifespan task spawns. While the flag
    # is False the renewal loop exits immediately and the POST /webhooks
    # endpoint refuses to enrol new subscriptions.
    M365_WEBHOOKS_ENABLED: bool = False
    # Public HTTPS base URL Graph will POST notifications to. Must terminate at
    # this FastAPI app — Graph rejects HTTP / IP / self-signed. Override per env.
    M365_WEBHOOK_BASE_URL: str = "https://api.nexus.dynaminds.pl"
    # How long to ask Graph to keep a single subscription alive. Graph caps at
    # 4230 min (~70h) for messages/events; we use 60 min so a missed renewal
    # only loses ~1h of pushes (polling falls back during co-existence window).
    M365_WEBHOOK_LIFETIME_MINUTES: int = 60
    # Renewal-loop cadence. Clamped to >=60s in the loop itself.
    M365_WEBHOOK_RENEWAL_INTERVAL_SECONDS: int = 600
    # Renew subscriptions whose expires_at falls inside this window. Must be
    # comfortably larger than the renewal interval so we never miss an expiry.
    M365_WEBHOOK_RENEWAL_WINDOW_MINUTES: int = 15
    # Mark a subscription inactive (deletes the row, lets the next sync re-enrol)
    # after this many consecutive renew/subscribe failures. Avoids hammering
    # Graph for a token that has been revoked server-side.
    M365_WEBHOOK_FAILURE_THRESHOLD: int = 3

    # ── SSO "Sign in with Microsoft" (Faza B) ────────────────────────────────
    # Reuses M365 Azure AD app — same client_id/secret/tenant, different redirect.
    # Empty in dev → /api/auth/microsoft/* return 503.
    MICROSOFT_LOGIN_REDIRECT_URI: str = ""
    # Email-domain whitelist for auto-provisioning. CSV string ("b2bnetwork.pl,foo.com")
    # — kept as ``str`` instead of ``List[str]`` because pydantic-settings v2 forces
    # JSON parsing for List types from env vars, which broke a plain ``b2bnetwork.pl``
    # value at startup. Use ``settings.sso_allowed_domains_list`` to get the parsed
    # list of lowercased, stripped domains.
    #
    # NB: this whitelist now governs BOTH Microsoft SSO auto-provisioning AND
    # email/password self-registration (POST /api/auth/register). The same set
    # of corporate domains is allowed to self-provision via either path.
    SSO_ALLOWED_DOMAINS: str = ""

    # ── Self-service email/password registration (POST /api/auth/register) ────
    # Kill-switch. When False the endpoint returns 503 (registration closed) and
    # the frontend /register page shows "rejestracja wyłączona". Default OFF for
    # safety — flip to True in Coolify env vault once SSO_ALLOWED_DOMAINS is set
    # to the corporate domain(s). Self-registered accounts are always created as
    # the read-only ``user`` (viewer) role, email-unverified until they click the
    # verification link; an admin elevates the role afterwards in the panel.
    SELF_REGISTRATION_ENABLED: bool = False

    # ── AAD group-based RBAC (Phase 7.2) ─────────────────────────────────────
    # Kill-switch. When False the SSO callback skips Graph /me/memberOf entirely
    # and falls back to legacy behaviour (new SSO users land as ``recruiter``,
    # existing users keep their role). Flip to True in Coolify env vault AFTER
    # ``AAD_GROUP_ROLE_MAP_JSON`` is populated and admin consent for the
    # ``GroupMember.Read.All`` Graph scope has been granted in the Azure app
    # registration — otherwise every login fails with a Graph 403.
    AAD_GROUP_RBAC_ENABLED: bool = False
    # JSON-encoded map ``{<aad-group-guid>: <userrole-string>}``. First match
    # wins → admins control precedence by ordering keys (Python preserves dict
    # insertion order, json.loads does too in 3.7+). Empty string = empty map
    # = every login blocked (fail-closed) when RBAC is enabled.
    # Example: '{"<uuid-admins>": "admin", "<uuid-recruiters>": "recruiter"}'.
    AAD_GROUP_ROLE_MAP_JSON: str = ""

    @field_validator("AAD_GROUP_RBAC_ENABLED")
    @classmethod
    def _force_aad_group_rbac_disabled(cls, v: bool) -> bool:
        """HARD-DISABLED 2026-07-13 — Microsoft is login-only; NEXUS roles live
        in the admin panel.

        Background: the Coolify env vault still carries
        ``AAD_GROUP_RBAC_ENABLED=true``. With RBAC on, the SSO callback
        (``app.api.auth_microsoft.callback``) re-derives every user's
        ``role``/``roles``/``is_active`` from Azure AD group membership on
        EVERY Microsoft login. That silently overwrites admin roles set in the
        NEXUS admin panel and blocks (deactivates) anyone not in a mapped AAD
        group — which is exactly what stopped teammates from logging in as
        admin. Per product decision, NEXUS role management is decoupled from
        Azure AD: Microsoft SSO authenticates identity only.

        The Coolify env var is not reachable to change directly from here, so
        this validator neutralizes the stale value in code — it always wins,
        regardless of what the env says. Tests that exercise the RBAC path set
        the flag with ``monkeypatch.setattr`` on the live settings object,
        which bypasses this validator, so they are unaffected.

        To fully re-enable AAD-group RBAC later: (1) remove this validator, and
        (2) set ``AAD_GROUP_RBAC_ENABLED=true`` in the Coolify env vault.
        """
        return False

    # ── Autenti e-signature integration (Phase Autenti.1) ───────────────────
    # Kill-switch: when False, /api/autenti/* router is not mounted, send/webhook
    # endpoints return 503, sweeper loop exits immediately. Default OFF until
    # API credentials are provisioned by Autenti sales (paid add-on).
    AUTENTI_ENABLED: bool = False
    # OAuth2 endpoints + REST base. Production defaults; sandbox URLs differ
    # only in subdomain — set via env on dev/staging deployments.
    AUTENTI_BASE_URL: str = "https://api.autenti.com/api/v2"
    AUTENTI_OAUTH_URL: str = "https://api.autenti.com/oauth2/token"
    # Client credentials (Plan A: client_credentials grant w/ `bpa` scope).
    # Empty in dev — sender service raises 503 before any HTTP call when blank.
    AUTENTI_CLIENT_ID: str = ""
    AUTENTI_CLIENT_SECRET: str = ""
    # OAuth scope — `bpa` = enterprise feature (sender as organization). If
    # Autenti sales doesn't grant it we fall back to authorization_code per
    # user (Phase 2 alternative — see plan).
    AUTENTI_OAUTH_SCOPE: str = "bpa"
    # JWKS URL used to verify webhook JWT signatures. Public key endpoint
    # documented at developers.autenti.com.
    AUTENTI_WEBHOOK_JWKS_URL: str = "https://autenti.com/developers/keys/webhook.jwks"
    # Default signature type (Pydantic Literal in API requests overrides).
    # Per plan §3: SES = Basic Electronic Signature by Autenti — sufficient
    # for B2B with JDG (98% of cases). UI offers SES | AdES | QES dropdown.
    AUTENTI_DEFAULT_SIGNATURE_TYPE: str = "SES"
    # Webhook clock skew tolerance — `iat` claim must be within this many
    # hours of "now" to be accepted. Defends against replay of old webhook
    # bodies. 24h is generous (Autenti retries up to ~10× over hours).
    AUTENTI_WEBHOOK_IAT_MAX_AGE_HOURS: int = 24
    # Background sweeper cadence (Phase 5 belt-and-braces). Polls expired
    # signatures + retries failed signed-PDF downloads. Clamped to >=300s
    # to avoid Autenti API hammering. 1h tick is plenty since the primary
    # state pump is the webhook handler.
    AUTENTI_SWEEPER_INTERVAL_SECONDS: int = 3600

    # ── In-house QES signing (Faza 1+ — drop Autenti, single-vendor KIR) ────
    # Kill-switch: when False, /api/signing/* write endpoints return 503 and
    # the signing sweeper loop exits immediately. Default OFF until KIR
    # (Szafir SDK + mSzafir) is contracted and creds provisioned. See
    # docs/in-house-qes-signature-plan.md.
    SIGNING_ENABLED: bool = False
    # Default provider for new signatures: ``szafir_sdk`` (card, client-side)
    # | ``mszafir_oneshot`` (cloud) | ``upload_validate`` | ``autenti`` (legacy).
    SIGNING_PROVIDER: str = "szafir_sdk"
    # Token TTL for the public /sign/{token} signing links (days).
    SIGNING_LINK_EXPIRY_DAYS: int = 14
    # Signing sweeper cadence (timeout sweep, attach retry, expiry). Clamped
    # to >=300s in the loop.
    SIGNING_SWEEPER_INTERVAL_SECONDS: int = 3600

    # KIR Szafir SDK (pas główny — podpis kartą client-side). Asset/licence
    # config filled from KIR onboarding (Faza 0). Web Module JS URL is served
    # to the /sign page; empty = SDK pas unavailable (UI hides it).
    QTSP_SZAFIR_SDK_ENABLED: bool = False
    QTSP_SZAFIR_WEB_MODULE_URL: str = ""
    QTSP_SZAFIR_LICENSE_KEY: str = ""

    # KIR mSzafir One Shot (pas zapasowy — cert jednorazowy w chmurze). API
    # shape confirmed in Faza 0; empty creds = mSzafir pas returns 503.
    QTSP_MSZAFIR_ENABLED: bool = False
    QTSP_MSZAFIR_BASE_URL: str = ""
    QTSP_MSZAFIR_API_KEY_ID: str = ""
    QTSP_MSZAFIR_API_KEY_SECRET: str = ""

    # EU DSS validation sidecar (autorytatywny "is QES"). Empty = validation
    # falls back to pyHanko trust-chain only (non-authoritative).
    DSS_VALIDATION_URL: str = ""

    # ── Proxycurl LinkedIn tracking (Phase: LinkedIn sync) ──────────────────
    # Kill-switch: when False OR API key empty, sync loop exits immediately
    # and on-demand sync returns 503. Used for roll-back without redeploy.
    PROXYCURL_ENABLED: bool = True
    # API key from https://nubela.co/proxycurl — static, no per-user OAuth.
    PROXYCURL_API_KEY: str = ""
    # Loop cadence; clamped to >=60s in the loop itself. 1h tick + 7-day stale
    # candidate cutoff gives predictable cost at $0.01/lookup with caching.
    PROXYCURL_SYNC_INTERVAL_SECONDS: int = 3600
    # Candidate is due for refresh when linkedin_synced_at is NULL or older
    # than this cutoff. Default 60 days ≈ once per 2 months — sensible for
    # IT staffing (people rarely change jobs more than once per quarter) and
    # keeps Proxycurl cost predictable.
    PROXYCURL_CANDIDATE_STALE_DAYS: int = 60
    # Max candidates processed per tick (2s stagger × 50 = ~100s per tick).
    PROXYCURL_BATCH_SIZE: int = 50
    # Fuzzy company-name match threshold (0..100). >= threshold means "same
    # company" — guards against rebrand false-positives.
    PROXYCURL_COMPANY_FUZZ_THRESHOLD: int = 90

    # ── CloudTalk telephony (Phase CloudTalk.1) ──────────────────────────────
    # Kill-switch: when False, /api/calls/webhook stays in DRY-RUN (returns 200
    # with `{"status":"dry-run"}` and never writes to DB), /api/cloudtalk/*
    # endpoints return 503, sync loop exits immediately. Default OFF until
    # API_KEY_SECRET is provisioned in Coolify env vault.
    CLOUDTALK_ENABLED: bool = False
    # Public part of the API key pair from CloudTalk dashboard
    # (Settings → API Keys). Used as the Basic Auth username.
    CLOUDTALK_API_KEY_ID: str = ""
    # Secret part of the API key pair — shown ONCE by CloudTalk at generation.
    # Used as the Basic Auth password. Empty in dev — client.from_settings()
    # raises RuntimeError before any HTTP call when blank.
    CLOUDTALK_API_KEY_SECRET: str = ""
    # REST base URL — production default. CloudTalk EU/US share this host.
    CLOUDTALK_BASE_URL: str = "https://my.cloudtalk.io/api"
    # Shared secret for HMAC-SHA256 verification of inbound webhooks. The same
    # value must be configured in CloudTalk dashboard → Integrations → Webhooks
    # → Signing secret. Generated locally via `openssl rand -hex 32`; not
    # derived from the API key pair.
    CLOUDTALK_WEBHOOK_SECRET: str = ""
    # Background sync loop cadence (Phase 5 — historical backfill + catch-up
    # after webhook downtime). Clamped to >=300s in the loop.
    CLOUDTALK_SYNC_INTERVAL_SECONDS: int = 3600
    # On first sync (or after long downtime) backfill calls from the last N
    # days. Older calls are skipped — out of scope for the ATS workflow.
    CLOUDTALK_HISTORICAL_BACKFILL_DAYS: int = 30

    # ── Traffit daily sync (scheduled import) ────────────────────────────────
    # Keeps Nexus in sync with Traffit: daily incremental delta (updated_at >=
    # watermark) + weekly full-scan reconcile safety net. The importer is the
    # same one used for the one-time migration (app/services/traffit/importer.py)
    # — every write is ON CONFLICT idempotent. Secrets (TRAFFIT_TENANT,
    # TRAFFIT_CLIENT_ID, TRAFFIT_CLIENT_SECRET, TRAFFIT_THROTTLE_RPS) are read
    # from the environment by TraffitConfig.from_env() — NOT declared here.
    #
    # Kill-switch: when False the loop exits immediately and POST
    # /api/admin/traffit/sync returns 503. Default OFF until activated.
    TRAFFIT_SYNC_ENABLED: bool = False
    # Background loop wake cadence (how often it checks whether a run is due).
    # The actual import runs at most once/day (delta) + once/week (full),
    # gated on the persisted watermark — clamped to >=300s in the loop.
    TRAFFIT_SYNC_CHECK_INTERVAL_SECONDS: int = 1800
    # UTC hour at/after which the daily delta is allowed to run (low-traffic
    # window). The first run after enabling fires immediately regardless.
    TRAFFIT_SYNC_HOUR_UTC: int = 2
    # Weekday for the heavy full-scan reconcile (0=Mon … 6=Sun).
    TRAFFIT_SYNC_FULL_WEEKDAY: int = 6
    # Overlap window subtracted from the last watermark when computing the
    # delta cutoff — absorbs clock skew / late-arriving edits. Idempotent
    # upserts make the overlap harmless.
    TRAFFIT_SYNC_DELTA_LOOKBACK_HOURS: int = 48
    # First-ever delta (no watermark yet) looks back this far to catch
    # everything changed in Traffit since the one-time migration. After that,
    # the watermark drives the cutoff.
    TRAFFIT_SYNC_INITIAL_BACKFILL_DAYS: int = 45

    # ── Microsoft Teams notifications (Phase 7.6) ────────────────────────────
    # Kill-switch: when False, /api/teams-channels/* keep working for CRUD but
    # outbound posts are no-op'd (logged, return False) so admins can stage
    # configuration before flipping the integration on. When True the AAD app
    # client credentials below MUST be set or sends will fail. Default OFF —
    # admin consent for `ChannelMessage.Send` is required first.
    TEAMS_NOTIFICATIONS_ENABLED: bool = False
    # Tenant-specific (NOT "common") — client_credentials flow requires the
    # actual tenant GUID. Defaults to M365_TENANT_ID at runtime if blank.
    TEAMS_TENANT_ID: str = ""
    # AAD app client ID. Reuses M365_CLIENT_ID at runtime if blank — same app
    # registration is fine as long as `ChannelMessage.Send` *Application*
    # permission is granted with admin consent.
    TEAMS_CLIENT_ID: str = ""
    # AAD app client secret. Reuses M365_CLIENT_SECRET at runtime if blank.
    # Application permissions need a confidential client (not public PKCE).
    TEAMS_CLIENT_SECRET: str = ""

    @property
    def sso_allowed_domains_list(self) -> list[str]:
        """Parse SSO_ALLOWED_DOMAINS CSV into a list of lowercased domains."""
        if not self.SSO_ALLOWED_DOMAINS:
            return []
        return [
            d.strip().lower() for d in self.SSO_ALLOWED_DOMAINS.split(",") if d.strip()
        ]

    @property
    def aad_group_role_map(self) -> dict[str, str]:
        """Parse ``AAD_GROUP_ROLE_MAP_JSON`` into a dict, raising on malformed JSON.

        We parse lazily (per-call) instead of in a ``@field_validator`` because
        validating the role values requires importing :class:`UserRole`, which
        creates a circular import at module load time
        (``app.core.config`` → ``app.models.user`` → ``app.core.database``).
        Lazy parsing keeps startup decoupled.
        """
        import json as _json

        if not self.AAD_GROUP_ROLE_MAP_JSON:
            return {}
        try:
            parsed = _json.loads(self.AAD_GROUP_ROLE_MAP_JSON)
        except _json.JSONDecodeError as exc:
            raise ValueError(
                "AAD_GROUP_ROLE_MAP_JSON is not valid JSON. "
                'Expected: \'{"<guid>": "admin", "<guid>": "recruiter"}\'. '
                f"Parser error: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(
                "AAD_GROUP_ROLE_MAP_JSON must decode to an object, "
                f"got {type(parsed).__name__}"
            )
        # Validate role strings against UserRole enum (deferred import — see
        # docstring). Misspelled roles in env would otherwise silently no-op
        # at login → user blocked with confusing 403.
        from app.models.user import UserRole

        valid_roles = {r.value for r in UserRole}
        out: dict[str, str] = {}
        for group_id, role in parsed.items():
            if role not in valid_roles:
                raise ValueError(
                    f"AAD_GROUP_ROLE_MAP_JSON contains unknown role {role!r} "
                    f"for group {group_id!r}. Valid: {sorted(valid_roles)}"
                )
            out[str(group_id)] = role
        return out

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        # Security: in production we MUST fail startup if SECRET_KEY is the
        # well-known default. Previously this was only a warnings.warn() call
        # which doesn't stop the container from booting — a misconfigured
        # Coolify env vault (variable missing) would silently boot with the
        # default key, making every JWT forgeable. Hard fail in production
        # turns a silent vulnerability into a noisy startup crash.
        is_default = (not v) or v.strip().lower() in {
            "change-me-in-production",
            "change-me",
        }
        # DEBUG flag is the dev-mode signal in this codebase.
        is_production = not bool(os.getenv("DEBUG", "").lower() in {"1", "true", "yes"})
        if is_default:
            if is_production:
                raise ValueError(
                    "SECRET_KEY is unset or left at the default in production. "
                    "Set a strong value in Coolify env vault. "
                    'Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
            warnings.warn(
                "SECRET_KEY is unset or left at default. Set a strong value in .env. "
                'Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"',
                RuntimeWarning,
                stacklevel=2,
            )
        if len(v) < 32:
            warnings.warn(
                "SECRET_KEY is shorter than 32 chars — use at least 48 bytes of entropy.",
                RuntimeWarning,
                stacklevel=2,
            )
        return v

    @field_validator("SESSION_COOKIE_PREFIX")
    @classmethod
    def validate_session_cookie_prefix(cls, v: str) -> str:
        value = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value):
            raise ValueError(
                "SESSION_COOKIE_PREFIX must be 1-32 letters, digits, '_' or '-'"
            )
        return value

    @field_validator("M365_STATE_SIGNING_KEY")
    @classmethod
    def validate_m365_state_signing_key(cls, v: str) -> str:
        # Security: ensure M365_STATE_SIGNING_KEY is independent of SECRET_KEY
        # in production. Sharing the same key means an attacker who can forge
        # one type of token (user JWT) can also forge OAuth state JWTs and
        # vice versa — confused-deputy class of bug. We can't compare here
        # because Pydantic validators can't see other field values cleanly,
        # but we CAN reject the empty-string default in production (which
        # falls back to SECRET_KEY at runtime via _state_signing_key()).
        is_production = not bool(os.getenv("DEBUG", "").lower() in {"1", "true", "yes"})
        if not v and is_production:
            # Don't hard fail — the M365 integration is optional and most
            # deployments may not have configured it. But emit a stern warning
            # so admins notice during the migration.
            warnings.warn(
                "M365_STATE_SIGNING_KEY is empty in production — OAuth state "
                "JWTs will be signed with SECRET_KEY (shared signing key risk). "
                "Set this to a separate secret in Coolify env vault.",
                RuntimeWarning,
                stacklevel=2,
            )
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
