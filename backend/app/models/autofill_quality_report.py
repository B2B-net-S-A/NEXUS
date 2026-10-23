"""Raport „Jakość podpowiedzi systemu” (0517) — DDL w ``services/autofill_quality_schema.py``."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AutofillQualityReport(Base):
    __tablename__ = "autofill_quality_reports"
    __table_args__ = (
        UniqueConstraint("week_start", name="uq_autofill_quality_reports_week"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    proposals: Mapped[list] = mapped_column(JSONB, nullable=False)
    from_model: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
