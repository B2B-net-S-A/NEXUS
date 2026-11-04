"""Powód odrzucenia osoby od systemu (0516) — DDL w ``services/autofill_feedback_schema.py``."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AutofillFeedback(Base):
    __tablename__ = "autofill_feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("candidate_stages.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    learned_from: Mapped[str] = mapped_column(String(16), nullable=False)
    bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    rate_hourly: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    note: Mapped[Optional[str]] = mapped_column(String(500))
    snapshot: Mapped[Optional[dict]] = mapped_column(JSONB)
    # 0606: powód „klient” dotyczy wszystkich rekrutacji tego klienta.
    whole_client: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
