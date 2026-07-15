"""AI feature settings + usage log.

Inspired by Traffit's "Ustawienia AI" panel: each AI-powered capability
(scoring, job description generator, CV parser, candidate AI summary, etc.)
has its own toggle and monthly call limit. Calls are counted in `ai_usage_log`
and reset on the 1st of each month.

Why a config table instead of env vars:
- Admin can flip toggles in production without restart.
- Per-feature monthly limits are visible in the Settings UI alongside
  current usage (Traffit shows "2 994 / 20 000 scoringów").

Why a single global config (no per-tenant): NEXUS is single-tenant
(one B2B Network instance). Multi-tenant would add `org_id` everywhere.
"""

import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class AIFeatureKey(str, enum.Enum):
    """Stable keys for AI-powered capabilities exposed in Settings → AI.

    Adding a new feature: add the enum value here, run a migration to extend
    the Postgres enum, seed a default row in `ai_features`, then wrap the
    relevant endpoint with `@check_ai_quota(AIFeatureKey.X)`.
    """

    scoring = "scoring"
    job_description_generator = "job_description_generator"
    cv_parser = "cv_parser"
    candidate_summary = "candidate_summary"
    champion_draft = "champion_draft"
    embeddings = "embeddings"
    reranking = "reranking"
    matching = "matching"
    job_writer = "job_writer"
    champion_profile = "champion_profile"
    match_explanation = "match_explanation"
    mindy = "mindy"
    uop_analysis = "uop_analysis"
    criteria_suggestions = "criteria_suggestions"
    cv_b2b = "cv_b2b"


# Human-readable labels surfaced in the Settings UI (PL — primary language
# of NEXUS recruiters; we don't expose the keys directly).
FEATURE_LABELS: dict[AIFeatureKey, str] = {
    AIFeatureKey.scoring: "Scoring kandydatów",
    AIFeatureKey.job_description_generator: "Generator ogłoszeń",
    AIFeatureKey.cv_parser: "Tworzenie kandydata z CV",
    AIFeatureKey.candidate_summary: "Podsumowanie kandydata",
    AIFeatureKey.champion_draft: "Profil Championa AI",
    AIFeatureKey.embeddings: "Embeddings kandydatów i ofert",
    AIFeatureKey.reranking: "Reranking wyników",
    AIFeatureKey.matching: "Matching kandydatów",
    AIFeatureKey.job_writer: "Job Writer",
    AIFeatureKey.champion_profile: "Profil Championa",
    AIFeatureKey.match_explanation: "Wyjaśnienie dopasowania",
    AIFeatureKey.mindy: "MINDY",
    AIFeatureKey.uop_analysis: "Analiza UoP",
    AIFeatureKey.criteria_suggestions: "Sugestie kryteriów",
    AIFeatureKey.cv_b2b: "Generator CV B2B",
}


# Description of what data is sent to the LLM per feature. Surfaced in the UI
# under each feature card so admins know what leaves NEXUS.
FEATURE_DATA_SENT: dict[AIFeatureKey, list[str]] = {
    AIFeatureKey.scoring: [
        "Treść CV kandydatów",
        "Nazwa stanowiska i wymagania",
        "Competence Category + skills",
    ],
    AIFeatureKey.job_description_generator: [
        "Szczegóły rekrutacji (tytuł, wymagania, lokalizacja)",
        "Kontekst klienta (Client Knowledge)",
        "Wybrany tone of voice",
    ],
    AIFeatureKey.cv_parser: [
        "Treść CV kandydatów (PDF/DOCX → tekst)",
    ],
    AIFeatureKey.candidate_summary: [
        "Aktywności kandydata z timeline",
        "Ostatnie 3 notatki",
        "Tagi i Talenty kandydata",
    ],
    AIFeatureKey.champion_draft: [
        "Treść CV kandydata-Championa",
        "Historia rekrutacji (top-K podobnych zamkniętych ról)",
    ],
    AIFeatureKey.embeddings: ["Zanonimizowany tekst indeksu kandydatów i ofert"],
    AIFeatureKey.reranking: ["Zapytanie oraz zanonimizowane fragmenty wyników"],
    AIFeatureKey.matching: ["Wektory i strukturalne kryteria dopasowania"],
    AIFeatureKey.job_writer: [
        "Brief oferty, wymagania i zatwierdzony kontekst klienta"
    ],
    AIFeatureKey.champion_profile: ["CV, notatki i transkrypty wskazane jako źródła"],
    AIFeatureKey.match_explanation: ["Wyłącznie komponenty ScoreBreakdown"],
    AIFeatureKey.mindy: ["Dozwolone KPI, okres i zagregowane wyniki"],
    AIFeatureKey.uop_analysis: ["Dane umowy i wynik deterministycznego silnika reguł"],
    AIFeatureKey.criteria_suggestions: ["Opis roli i dopasowania do taksonomii"],
    AIFeatureKey.cv_b2b: ["Treść CV i zatwierdzone kryteria formatowania"],
}


class AIFeatureConfig(Base, TimestampMixin):
    """Per-feature toggle + monthly limit configuration.

    Single global config (no per-tenant). One row per `AIFeatureKey`.
    """

    __tablename__ = "ai_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    feature: Mapped[AIFeatureKey] = mapped_column(
        Enum(AIFeatureKey, name="aifeaturekey"),
        nullable=False,
        unique=True,
        index=True,
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    monthly_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Monthly call cap. 0 = unlimited.",
    )

    monthly_budget_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        default=Decimal("0"),
        doc="Monthly provider cost cap in USD. 0 = unlimited.",
    )

    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class AIMasterToggle(Base, TimestampMixin):
    """Global kill-switch for all AI features.

    A single-row table (id=1). When `enabled=False`, every quota-checked
    endpoint returns 503 regardless of per-feature `AIFeatureConfig.enabled`.

    Stored as a row (not env var) so admin can flip without redeploy.
    """

    __tablename__ = "ai_master_toggle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class AIUsageLog(Base):
    """Aggregated monthly call counts per (feature, user, period).

    One row per (feature, user_id, period_start). Incremented atomically
    via INSERT ... ON CONFLICT DO UPDATE on each successful AI call.

    Why aggregated (not append-only audit log): we only need quota counts
    in the UI ("2994 / 20000"). For cost/usage forensics we'd ship to
    Loki/Grafana via structured logs (see observability.md).

    `period_start` = first day of the calendar month (UTC). The 1st-of-month
    reset is enforced by query: SELECT … WHERE period_start = date_trunc('month', NOW()).
    """

    __tablename__ = "ai_usage_log"
    __table_args__ = (
        UniqueConstraint(
            "feature", "user_id", "period_start", name="uq_ai_usage_feature_user_period"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)

    feature: Mapped[AIFeatureKey] = mapped_column(
        Enum(AIFeatureKey, name="aifeaturekey"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="NULL = system-initiated call (background task).",
    )

    period_start: Mapped[datetime] = mapped_column(
        Date,
        nullable=False,
        index=True,
        doc="First day of the calendar month (UTC). Used as quota window key.",
    )

    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_call_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
