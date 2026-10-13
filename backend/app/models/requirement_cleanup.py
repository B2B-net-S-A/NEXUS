"""Decyzja Delivery Leada o propozycji „Wymagania do poprawy” (0438, 13.10.2026)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RequirementCleanupDecision(Base):
    __tablename__ = "requirement_cleanup_decisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('applied','dismissed')",
            name="ck_requirement_cleanup_decisions_status",
        ),
    )

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
