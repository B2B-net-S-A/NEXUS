"""DynaReporter B.2.2 — SQLAlchemy model for dr_kpi_sales.

Tabela `dr_kpi_sales` (migracja 0112). KPI tygodniowe dla sprzedawców:
leads (nowe leady), offers_sent (wysłane oferty), offers_won (wygrane),
offers_lost (przegrane), days_worked.

UNIQUE (user_id, report_date).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DrKpiSales(Base):
    """Tygodniowy KPI sprzedawcy (Sales channel)."""

    __tablename__ = "dr_kpi_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)

    leads: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    offers_sent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    offers_won: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    offers_lost: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    days_worked: Mapped[int] = mapped_column(Integer, default=5, server_default="5")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "report_date", name="dr_kpi_sales_user_id_report_date_key"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<DrKpiSales id={self.id} user_id={self.user_id} "
            f"week={self.week_number} won={self.offers_won}>"
        )
