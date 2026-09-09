"""Human-reviewed requirement evidence; append-only history separate from AI JSON."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RequirementVerification(Base):
    __tablename__ = "requirement_verifications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('met', 'not_met', 'unknown')",
            name="ck_requirement_verification_status",
        ),
        Index(
            "ix_requirement_verification_lookup",
            "job_id",
            "candidate_id",
            "group_key",
            "id",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    group_key: Mapped[str] = mapped_column(String(64), nullable=False)
    requirement: Mapped[dict] = mapped_column(JSONB, nullable=False)
    requirements_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    usage_context: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
