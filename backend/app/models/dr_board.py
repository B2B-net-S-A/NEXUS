"""DynaReporter B.2.8 — Board Monthly Report models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DrBoardMonthlyReport(Base):
    """Top-level monthly report dla Rady Nadzorczej (CEO view)."""

    __tablename__ = "dr_board_monthly_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    report_month: Mapped[date] = mapped_column(
        Date, nullable=False, unique=True, index=True
    )
    revenue: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, server_default="0"
    )
    consultant_costs: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, server_default="0"
    )
    other_costs: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, server_default="0"
    )
    active_consultants: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    departures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    placements: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    avg_margin_per_hour: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=0, server_default="0"
    )
    hit_ratio: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )


class DrBoardPlacementClient(Base):
    """Breakdown placementów per klient × miesiąc dla widoku Rady."""

    __tablename__ = "dr_board_placement_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    report_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    placement_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
