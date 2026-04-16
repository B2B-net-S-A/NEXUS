import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


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


STAGE_CATEGORY: dict[PipelineStage, StageCategory] = {
    PipelineStage.new: StageCategory.internal,
    PipelineStage.prep_call: StageCategory.internal,
    PipelineStage.screening: StageCategory.internal,
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

    # Relationships
    candidate = relationship("Candidate", back_populates="pipeline_stages")
    job = relationship("Job", back_populates="pipeline_stages")
    moved_by_user = relationship(
        "User", back_populates="pipeline_moves", foreign_keys=[moved_by]
    )

    def __repr__(self) -> str:
        return f"<CandidateStage candidate={self.candidate_id} job={self.job_id} stage={self.stage}>"
