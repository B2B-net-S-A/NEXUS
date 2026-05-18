"""DynaReporter B.2.5 — Clients + MRR + Finances models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DrClient(Base):
    __tablename__ = "dr_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )


class DrClientMrr(Base):
    __tablename__ = "dr_client_mrr"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    report_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    consultants_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    mrr: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )


class DrFinance(Base):
    __tablename__ = "dr_finances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    report_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    total_costs: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    cv_database_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    consultants_churn: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    department: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
