"""„Nie publikujemy tej rekrutacji na …” — 0525.

Kolumny i powód istnienia: ``app/services/job_ad_reminder_schema.py``.
Logika: ``app/services/job_ad/reminders.py``, trasy: ``app/api/job_ads.py``.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class JobAdChannelSkip(Base, TimestampMixin):
    __tablename__ = "job_ad_channel_skips"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('kariera', 'pracuj', 'jjit')",
            name="ck_job_ad_channel_skips_channel",
        ),
    )

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    channel: Mapped[str] = mapped_column(String(16), primary_key=True)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
