import logging
import os
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
