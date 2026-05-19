"""DynaReporter — model dr_user_seniority (Acceleration Path tracking).

Phase B follow-up. Tabela utworzona przez migrację 0114.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DrUserSeniority(Base):
    """Per-user seniority tracking (1:1 z `users`)."""

    __tablename__ = "dr_user_seniority"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    seniority_level: Mapped[str] = mapped_column(
        String(20), default="junior", server_default="junior", nullable=False
    )
    acceleration_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    senior_since: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expert_since: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
