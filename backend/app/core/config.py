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
