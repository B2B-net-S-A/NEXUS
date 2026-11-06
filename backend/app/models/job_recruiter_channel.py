"""Koszyk „Baza” / „LinkedIn” osoby przy rekrutacji (0654, 06.11.2026).

Jeden wiersz na parę (rekrutacja, osoba). Reguła i powody:
``app/services/job_channels.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

CHANNELS = ("base", "linkedin")


class JobRecruiterChannel(Base):
    __tablename__ = "job_recruiter_channels"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('base', 'linkedin')", name="ck_job_recruiter_channels_channel"
        ),
        UniqueConstraint(
            "job_id", "user_id", name="uq_job_recruiter_channels_job_user"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    set_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
