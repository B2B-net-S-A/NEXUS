"""Znacznik wysłania raportów KPI mailem (migracja 0355, plan PR3).

UNIQUE (kind, period_key) jest mechanizmem „bez duplikatu po restarcie":
pętla najpierw ZAKŁADA wiersz (`INSERT … ON CONFLICT DO NOTHING RETURNING`),
dopiero potem wysyła. Restart kontenera w trakcie deployu albo dwa kontenery
naraz nie wyślą tego samego raportu dwa razy — wolimy raport, który przepadł
(widoczny jako `claimed` bez `finished_at`), niż dwa maile do całego zarządu.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KpiEmailReportRun(Base):
    __tablename__ = "kpi_email_report_runs"
    __table_args__ = (
        UniqueConstraint("kind", "period_key", name="uq_kpi_email_report_runs"),
        CheckConstraint(
            "status IN ('claimed', 'sent', 'skipped', 'failed')",
            name="ck_kpi_email_report_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # kpi_weekly_report | board_monthly_report
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # „2026-W39" (tydzień ISO) albo „2026-09" (miesiąc)
    period_key: Mapped[str] = mapped_column(String(16), nullable=False)
    # claimed | sent | skipped | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="claimed")
    recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
