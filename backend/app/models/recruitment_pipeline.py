import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.models.candidate_risk import CandidateOfferResponse


class StageCategory(str, enum.Enum):
    """Podział na etapy wewnętrzne i zewnętrzne (inspiracja: Recruitify)."""

    internal = "internal"
    external = "external"
    terminal = "terminal"


class PipelineStage(str, enum.Enum):
    # ── Etapy wewnętrzne ────────────────────────────────
    new = "new"  # Nowy kandydat / Analiza CV
    prep_call = "prep_call"  # Preparation Call (pre-screening telefoniczny)
    screening = "screening"  # Screening rekruterski
    verified = "verified"  # Zweryfikowany — gate akceptacji rate'u (0056)
    interview = "interview"  # Interview wewnętrzny / techniczny
    cv_sent = "cv_sent"  # CV wysłane do klienta
    # ── Etapy zewnętrzne (klient) ───────────────────────
    client_interview = "client_interview"  # Rozmowa u klienta
    acceptance = "acceptance"  # Klient akceptuje kandydata
    negotiation = "negotiation"  # Negocjacje warunków
    onboarding = "onboarding"  # Onboarding — start pracy
    # ── Etapy końcowe ──────────────────────────────────
    hired = "hired"  # Zatrudniony / kontrakt aktywny
    rejected = "rejected"  # Odrzucony (na dowolnym etapie)
    withdrawn = "withdrawn"  # Kandydat się wycofał


class VerificationStatus(str, enum.Enum):
    """Status weryfikacji kandydata na stage'u 'verified' (migracja 0056).

    `active`   — domyślny; kandydat normalnie widoczny na stage'u (rate w widełkach
                 lub stage inny niż 'verified').
    `pending`  — rate poza budżetem; karta na szaro, czeka na akceptację
                 delivery_lead/head_of_recruitment/admin.
    `rejected` — odrzucony — przy reject tworzymy NOWY CandidateStage z poprzednim
                 stage'em (zachowujemy historię), a obecny zostaje oznaczony jako
                 rejected dla audit trail.
    """

    active = "active"
    pending = "pending"
    rejected = "rejected"


STAGE_CATEGORY: dict[PipelineStage, StageCategory] = {
    PipelineStage.new: StageCategory.internal,
    PipelineStage.prep_call: StageCategory.internal,
    PipelineStage.screening: StageCategory.internal,
    PipelineStage.verified: StageCategory.internal,
    PipelineStage.interview: StageCategory.internal,
    PipelineStage.cv_sent: StageCategory.internal,
    PipelineStage.client_interview: StageCategory.external,
    PipelineStage.acceptance: StageCategory.external,
    PipelineStage.negotiation: StageCategory.external,
    PipelineStage.onboarding: StageCategory.external,
    PipelineStage.hired: StageCategory.terminal,
    PipelineStage.rejected: StageCategory.terminal,
    PipelineStage.withdrawn: StageCategory.terminal,
}


# Ordered list for kanban display
STAGE_ORDER: list[PipelineStage] = [
    PipelineStage.new,
    PipelineStage.prep_call,
    PipelineStage.screening,
    PipelineStage.verified,
    PipelineStage.interview,
    PipelineStage.cv_sent,
    PipelineStage.client_interview,
    PipelineStage.acceptance,
    PipelineStage.negotiation,
    PipelineStage.onboarding,
    PipelineStage.hired,
]


class CandidateStage(Base, TimestampMixin):
    """
    Etap kandydata w procesie rekrutacyjnym dla danej oferty.
    Śledzi historię przejść między etapami — audit trail pipeline.
    """

    __tablename__ = "candidate_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id"), nullable=False, index=True
    )

    stage: Mapped[PipelineStage] = mapped_column(
        Enum(PipelineStage), default=PipelineStage.new, nullable=False, index=True
    )

    # Kiedy i przez kogo zmieniono etap
    moved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    moved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    # Notatka przy przejściu (opcjonalna)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Ocena kandydata na danym etapie (1-5)
    rating: Mapped[Optional[int]] = mapped_column(Integer)  # 1..5

    # Phase 1: new pipeline template system (enum `stage` column remains for
    # backward-compat and is populated alongside stage_def_id until Phase 3).
    stage_def_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pipeline_stage_defs.id"), nullable=True, index=True
    )
    rejection_reason_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("rejection_reasons.id"), nullable=True
    )

    # Phase 3: stage-specific scorecard answers stored with the move.
    # Shape: {"answers": [{"question_id": str, "value": Any}], "overall_rating": int}
    scorecard_answers: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Phase 10: recruiter's answers to the Champion Profile screening questions.
    # Shape validated by app.schemas.champion.ScreeningAnswers.
    screening_answers: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # ── Pending verification flow (migracja 0056) ──────────────────────────
    # Wszystkie ruchy z `verification_status='active'` są normalne. Tylko ruch
    # na stage `verified` z rate'm > Job.salary_max ustawia 'pending' i wymaga
    # akceptacji delivery_lead/head_of_recruitment/admin.
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="verificationstatus"),
        default=VerificationStatus.active,
        server_default="active",
        nullable=False,
    )
    # Snapshot stawki kandydata wprowadzonej przez recruitera przy ruchu na
    # `verified`. Trzymamy NUMERIC żeby uniknąć floatowych błędów.
    expected_rate_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    # Reuse RateUnit z contract.py (PG enum `rateunit`). Late import w samym
    # endpoincie żeby uniknąć cyklu — tu tylko nazwa typu w bazie.
    expected_rate_unit: Mapped[Optional[str]] = mapped_column(
        Enum(
            "hourly",
            "daily",
            "monthly",
            name="rateunit",
            create_type=False,
        ),
        nullable=True,
    )
    expected_rate_currency: Mapped[Optional[str]] = mapped_column(
        String(3), nullable=True
    )
    # Snapshot Job.salary_max w momencie ruchu — żeby audit pokazywał
    # konkretną liczbę nawet jeśli budżet się później zmieni.
    budget_max_at_move: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Stawka do klienta — cena wysłania kandydata do klienta (0122) ──────
    # Cena (sell rate), za jaką kandydat został zaproponowany klientowi na tej
    # rekrutacji — w odróżnieniu od `expected_rate_*` (oczekiwania kandydata).
    # Edytowalna z profilu kandydata (zakładka „Rekrutacje"). Trzymana na
    # najnowszym CandidateStage danej pary (candidate, job); odczyt w historii =
    # ostatnia niepusta wartość w obrębie rekrutacji. Reuse PG enum `rateunit`.
    client_rate_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    client_rate_unit: Mapped[Optional[str]] = mapped_column(
        Enum(
            "hourly",
            "daily",
            "monthly",
            name="rateunit",
            create_type=False,
        ),
        nullable=True,
    )
    client_rate_currency: Mapped[Optional[str]] = mapped_column(
        String(3), nullable=True
    )

    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    rejected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Candidate offer response (migracja 0066) ───────────────────────────
    # Tylko ma znaczenie gdy stage ∈ {acceptance, negotiation, onboarding}.
    # `declined` na późniejszym `withdrawn` = post-accept dropout (10pt).
    candidate_offer_response: Mapped[Optional[CandidateOfferResponse]] = mapped_column(
        Enum(CandidateOfferResponse, name="candidateofferresponse", create_type=False),
        nullable=True,
    )

    # External source tracking — Traffit recruitment_history move ID itp.
    # Migracja 0075 dodaje partial unique index na (external_source, external_id).
    external_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", index=True
    )

    # Durable dedup for the Slack SLA-breach alert loop (audyt P1 restart-safety).
    # Stamped inside the same transaction as a successful Slack POST, under a
    # `SELECT ... FOR UPDATE SKIP LOCKED` claim. NULL = never alerted. Replaces
    # the old in-memory `alerted` set that reset on every restart and diverged
    # per worker → re-alerting every SLA breach. Each CandidateStage row is a
    # single stage-entry, so one durable stamp = exactly one alert, ever.
    sla_alerted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    candidate = relationship("Candidate", back_populates="pipeline_stages")
    job = relationship("Job", back_populates="pipeline_stages")
    moved_by_user = relationship(
        "User", back_populates="pipeline_moves", foreign_keys=[moved_by]
    )
    approved_by_user = relationship("User", foreign_keys=[approved_by])
    rejected_by_user = relationship("User", foreign_keys=[rejected_by])
    stage_def = relationship("PipelineStageDef")
    rejection_reason = relationship("RejectionReason")
    # CV per rekrutacja (snapshot oryginalnego + draft brandowanego). 1:1.
    cv_instance = relationship(
        "CandidateStageCV",
        back_populates="candidate_stage",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<CandidateStage candidate={self.candidate_id} job={self.job_id} stage={self.stage}>"
