"""DynaReporter B.2.6 — Liga Mistrzów models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DrCompetitionWinner(Base):
    """Historyczne podium per period (kwartał/miesiąc).

    competition_type: 'quarterly' | 'monthly_recommendations' | 'monthly_placements'
    period: string identifier (np. "2026-Q1" lub "2026-04")
    rank: 1, 2, 3
    """

    __tablename__ = "dr_competition_winners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    competition_type: Mapped[str] = mapped_column(String(50), nullable=False)
    period: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    metric_value: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    prize: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )


class DrCompetitionNotification(Base):
    """Powiadomienie kompetycyjne dla usera (zmiana pozycji / new leader / etc.)."""

    __tablename__ = "dr_competition_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    competition_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
