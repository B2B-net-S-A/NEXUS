"""Kto pracuje nad requestem — jedno źródło dla pulpitu, obłożenia i historii.

Decyzja Artura 24.09.2026: przy requeście może pracować kilka osób (rekruter
i sourcer), a pulpit na daily pokazuje, kto przy czym jest, ile kto ma i co się
zmieniło od wczoraj. Automat przydziału (``services/request_allocation``)
zapisuje tu swoje decyzje; ręczne dodanie osoby z pulpitu też.

Wiersz nigdy nie jest kasowany przy zdjęciu osoby — dostaje ``state =
released`` z powodem. Z tych wierszy liczą się „Zmiany od wczoraj”, a osoba
zdjęta z requestu dzień wcześniej musi się w nich pojawić.

``proposed`` = decyzja automatu w trybie podglądu (``shadow``): widoczna na
pulpicie jako propozycja, nikogo do niczego nie przypisuje.

Świadomie osobna tabela, nie ``job_collaborators`` (tam ``auto_cc`` dopisuje
całą kategorię, co jest za szerokie) ani ``recruitment_priority_assignments``
(plan priorytetów z pozycjami i wersjami — za ciężki na „kto przy czym jest”).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

WORK_ROLES = ("recruiter", "sourcer")
WORK_SOURCES = ("auto", "manual")
WORK_STATES = ("proposed", "active", "released")


class JobWorkAssignment(Base):
    __tablename__ = "job_work_assignments"
    __table_args__ = (
        CheckConstraint(
            "role IN ('recruiter', 'sourcer')", name="ck_job_work_assignments_role"
        ),
        CheckConstraint(
            "source IN ('auto', 'manual')", name="ck_job_work_assignments_source"
        ),
        CheckConstraint(
            "state IN ('proposed', 'active', 'released')",
            name="ck_job_work_assignments_state",
        ),
        Index(
            "ux_job_work_assignments_live",
            "job_id",
            "user_id",
            unique=True,
            postgresql_where=text("state <> 'released'"),
        ),
        Index("ix_job_work_assignments_user_state", "user_id", "state"),
        Index("ix_job_work_assignments_changed", "assigned_at", "released_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    assigned_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    released_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Kod powodu (np. ``champion``, ``client_silent``, ``leave``,
    # ``excluded``, ``manual``) — słownik w ``services/request_allocation``.
    release_reason: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
