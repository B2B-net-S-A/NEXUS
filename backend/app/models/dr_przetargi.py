"""DynaReporter B.2.7 — Przetargi models (projects/allocations/costs/consultants)."""

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


class DrPrzetargiProject(Base):
    __tablename__ = "dr_przetargi_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    client_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )


class DrPrzetargiConsultant(Base):
    __tablename__ = "dr_przetargi_consultants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    default_cost_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, server_default="0")
    default_revenue_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )


class DrPrzetargiAllocation(Base):
    __tablename__ = "dr_przetargi_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    consultant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0, server_default="0")
    cost_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, server_default="0")
    revenue_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )


class DrPrzetargiProjectCost(Base):
    __tablename__ = "dr_przetargi_project_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, server_default="0")
    category: Mapped[str] = mapped_column(String(50), default="other", server_default="other")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
