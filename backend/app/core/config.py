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
    VOYAGE_MODEL: str = "voyage-3"
    EMBEDDING_DIMENSION: int = 1024

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
    # Scopes requested during authorize. `offline_access` is mandatory for refresh tokens.
    M365_SCOPES: List[str] = [
        "offline_access",
        "Mail.ReadWrite",
        "Mail.Send",
        "Calendars.ReadWrite",
        "User.Read",
    ]
    # Sync loop cadence; clamped to >=60s in the loop itself.
    M365_SYNC_INTERVAL_SECONDS: int = 300
    # Initial backfill window when user first connects.
    M365_BACKFILL_MONTHS: int = 12
    # Outlook category string that opts an email OUT of ATS sync (user-controlled).
    M365_IGNORE_CATEGORY: str = "ATS:ignore"
    # Hard cap on attachment download size (Phase 1 inline only; large upload in Phase 2).
    M365_MAX_ATTACHMENT_MB: int = 25
    # Whether to auto-parse CV attachments via cv_parser (Claude calls = $$).
    M365_AUTO_PARSE_CV: bool = True

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
