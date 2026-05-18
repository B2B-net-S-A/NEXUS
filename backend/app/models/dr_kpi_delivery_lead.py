"""DynaReporter B.2.3 — SQLAlchemy model for dr_kpi_delivery_lead.

Tabela `dr_kpi_delivery_lead` (migracja 0112). Miesięczne KPI dla
Delivery Lead-ów (nie tygodniowe jak KPI Body Leasing/Sales):
- requests — łączne zapytania klientów w miesiącu
- placements — placementy w miesiącu
- vacancies — sumarycznie nowo otwarte vacancy
- open_requests — niezamknięte na koniec miesiąca
- open_vacancies — niezamknięte vacancy na koniec miesiąca

UNIQUE (user_id, report_month) — jeden wpis per DL × miesiąc.
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


class DrKpiDeliveryLead(Base):
    __tablename__ = "dr_kpi_delivery_lead"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    report_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    placements: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    vacancies: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    open_requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    open_vacancies: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "report_month",
            name="dr_kpi_delivery_lead_user_id_report_month_key",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<DrKpiDeliveryLead id={self.id} user_id={self.user_id} "
            f"month={self.report_month} placements={self.placements}>"
        )
