"""Dzienny licznik użycia obszarów (0631) — patrz ``app/services/access_usage.py``."""

from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AccessUsageDaily(Base):
    __tablename__ = "access_usage_daily"
    __table_args__ = (Index("ix_access_usage_daily_day", "day"),)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    area: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    entries: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
