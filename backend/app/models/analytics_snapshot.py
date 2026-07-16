"""Snapshoty metryk + rejestr cutoverów (plan PR 7).

- ``analytics_metric_snapshots`` — NIEMUTOWALNE kopie nieodtwarzalnej
  historii sprzed cutoveru (głównie stare Board/P&L z DynaReportera).
  Unikalność (module, metric, period_label, source) czyni backfill
  idempotentnym; wiersze nigdy nie są nadpisywane.
- ``analytics_cutovers`` — od kiedy dany moduł liczy live ATS. Resolver:
  okres < cutover → snapshot; okres >= cutover → live; NIGDY suma obu.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import Date, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AnalyticsMetricSnapshot(Base):
    __tablename__ = "analytics_metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "module", "metric", "period_label", "source", name="uq_analytics_snapshot"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Moduł planu (np. 'finance', 'board').
    module: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # Nazwa metryki (np. 'revenue', 'monthly_margin', 'active_consultants').
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    # Etykieta okresu — miesiąc 'YYYY-MM' (kalendarz Warsaw).
    period_label: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # Wartość + metadane (kwoty jako decimal-string).
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, default="dynareporter"
    )
    # sha256 wartości źródłowej — weryfikacja integralności backfillu.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AnalyticsCutover(Base):
    __tablename__ = "analytics_cutovers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    module: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True
    )
    # Początek pełnego miesiąca Warsaw, od którego liczy live ATS.
    cutover_date: Mapped[date] = mapped_column(Date, nullable=False)
    legacy_source: Mapped[str] = mapped_column(
        String(40), nullable=False, default="dynareporter"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
