import logging
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

    # Ollama (local LLM + embeddings fallback)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"
    OLLAMA_EMBED_MODEL: str = "mxbai-embed-large"

    # Anthropic (Claude) — used by CV enrichment and AI job writer
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL_CV: str = "claude-haiku-4-5-20251001"
    CV_ENRICHMENT_ENABLED: bool = True  # kill-switch without redeploy

    # Fireflies integration
    FIREFLIES_API_KEY: str = ""

    # Sentry (error tracking)
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"

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
    MARKETPLACE_SCORE_THRESHOLD: float = 70.0
    MARKETPLACE_DEFAULT_DURATION_DAYS: int = 30
    MARKETPLACE_SWEEP_INTERVAL_SECONDS: int = 1800  # 30 min safety net
    MARKETPLACE_TOP_K_MATCHES_PER_CANDIDATE: int = 3
    # Rate-limit: max notyfikacji na kandydata per owner per 24h. Powyżej →
    # agregat "N nowych matchy ≥70" (Phase 2 feature; w MVP wyłączone przez 0).
    MARKETPLACE_MAX_ALERTS_PER_CANDIDATE_PER_DAY: int = 0

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

    # ── SSO "Sign in with Microsoft" (Faza B) ────────────────────────────────
    # Reuses M365 Azure AD app — same client_id/secret/tenant, different redirect.
    # Empty in dev → /api/auth/microsoft/* return 503.
    MICROSOFT_LOGIN_REDIRECT_URI: str = ""
    # Email-domain whitelist for auto-provisioning. CSV string ("b2bnetwork.pl,foo.com")
    # — kept as ``str`` instead of ``List[str]`` because pydantic-settings v2 forces
    # JSON parsing for List types from env vars, which broke a plain ``b2bnetwork.pl``
    # value at startup. Use ``settings.sso_allowed_domains_list`` to get the parsed
    # list of lowercased, stripped domains.
    SSO_ALLOWED_DOMAINS: str = ""

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

    @property
    def sso_allowed_domains_list(self) -> list[str]:
        """Parse SSO_ALLOWED_DOMAINS CSV into a list of lowercased domains."""
        if not self.SSO_ALLOWED_DOMAINS:
            return []
        return [
            d.strip().lower() for d in self.SSO_ALLOWED_DOMAINS.split(",") if d.strip()
        ]

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if not v or v.strip().lower() in {"change-me-in-production", "change-me"}:
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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
