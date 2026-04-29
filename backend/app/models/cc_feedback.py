"""Feedback loop modele dla AI CC matching.

`CcSuggestionOverride` — log gdy DL zmienia sugerowaną CC (użyty przez Head of
Recruitment do przeglądu jakości klasyfikatora).

`JobSecondaryCc` — wider matching (primary CC na jobs.competence_category_id +
max 2 secondary tutaj, bez kłamania w raportach gdzie liczy się primary).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CcSuggestionOverride(Base):
    __tablename__ = "cc_suggestion_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    suggested_cc_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("competence_categories.id", ondelete="SET NULL"), nullable=True
    )
    final_cc_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("competence_categories.id", ondelete="SET NULL"), nullable=True
    )
    suggested_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job = relationship("Job", foreign_keys=[job_id])
    suggested_cc = relationship("CompetenceCategory", foreign_keys=[suggested_cc_id])
    final_cc = relationship("CompetenceCategory", foreign_keys=[final_cc_id])
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return (
            f"<CcSuggestionOverride job={self.job_id} "
            f"suggested={self.suggested_cc_id} final={self.final_cc_id}>"
        )


class JobSecondaryCc(Base):
    __tablename__ = "job_secondary_cc"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "competence_category_id", name="uq_job_secondary_cc"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competence_category_id: Mapped[int] = mapped_column(
        ForeignKey("competence_categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job = relationship("Job", foreign_keys=[job_id], overlaps="secondary_cc_links")
    competence_category = relationship(
        "CompetenceCategory", foreign_keys=[competence_category_id]
    )

    def __repr__(self) -> str:
        return f"<JobSecondaryCc job={self.job_id} cc={self.competence_category_id}>"
