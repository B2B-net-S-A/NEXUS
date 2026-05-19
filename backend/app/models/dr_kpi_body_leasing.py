"""DynaReporter B.2.1 — SQLAlchemy model for dr_kpi_body_leasing.

Phase B.2.1 of the DynaReporter migration plan. Tabela utworzona przez
migrację 0112 (DynaReporter B.0). Dane wgrane przez ETL (PR #4 B.0).

Każdy wpis to tygodniowy KPI rekrutera z Body Leasing:
- verifications — kandydaci zweryfikowani u klienta
- recommendations — rekomendacje kandydatów do procesu
- interviews — odbyte interview z klientem
- placements — umieszczeni kandydaci (najważniejszy KPI)
- requests — zapytania klientów (lead indicator)
- days_worked — dni robocze w tygodniu (default 5)
- linkedin_* — LinkedIn farming activity (B2B network channel)
- is_draft — flag czy wpis jeszcze nie zatwierdzony przez usera

UNIQUE (user_id, report_date) — jeden wpis per user × tydzień.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DrKpiBodyLeasing(Base):
    """Tygodniowy KPI rekrutera (Body Leasing channel).

    Tabela `dr_kpi_body_leasing` (migracja 0112). FK `user_id → users.id`
    (nexus identity — po ETL `user_id` w dr_* tabelach wskazuje na
    `nexus.users.id`, nie legacy DynaReporter id-ek).
    """

    __tablename__ = "dr_kpi_body_leasing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Core KPI counters — default 0 dla brakujących pomiarów
    verifications: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    recommendations: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    interviews: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    placements: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    days_worked: Mapped[int] = mapped_column(Integer, default=5, server_default="5")

    is_draft: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # LinkedIn farming sub-KPIs (Phase 14 z DynaReportera, migracja
    # `add_recruiter_role_and_linkedin_kpi.sql`).
    linkedin_cv_added: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    linkedin_messages_sent: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    linkedin_responses_received: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )

    # Partial unique index — `(user_id, report_date)` must be unique ONLY for
    # NON-draft rows. Drafts can coexist with a finalized row for the same
    # period (user keeps working on a draft after submitting a previous one,
    # or workflow re-creates drafts on each save).
    #
    # CRITICAL: this is a PARTIAL unique index (postgres syntax `WHERE`),
    # NOT a full table constraint. The original ORM had a full UniqueConstraint
    # which (a) didn't exist in the DB → Alembic autogenerate would try to
    # ADD it and conflict with the partial index, (b) didn't match the actual
    # semantics. Quality check DB-C-1 fix.
    #
    # `dynareporter_kpi_body_leasing.py` upsert MUST pass `index_where=` to
    # `on_conflict_do_update()` so Postgres can resolve to this partial index.
    __table_args__ = (
        Index(
            "dr_kpi_body_leasing_unique_non_draft",
            "user_id",
            "report_date",
            unique=True,
            postgresql_where=text("is_draft = false"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<DrKpiBodyLeasing id={self.id} user_id={self.user_id} "
            f"week={self.week_number} placements={self.placements}>"
        )
