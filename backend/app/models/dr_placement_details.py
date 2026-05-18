"""DynaReporter B.2.4 — Placement details (per user × client × date)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DrPlacementDetail(Base):
    """Pojedynczy placement — user × klient × data."""

    __tablename__ = "dr_placement_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    # FK do dr_clients (z migracji 0112, DynaReporter clients)
    client_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    placement_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<DrPlacementDetail id={self.id} user_id={self.user_id} "
            f"client_id={self.client_id} date={self.placement_date}>"
        )
