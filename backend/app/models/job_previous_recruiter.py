"""„Poprzedni rekruter” — osoby uśpione przy rekrutacji (prośba Head of Recruitment, 14.10.2026).

Zamknięcie rekrutacji albo zejście z P1 przenosi wszystkich, którzy pracowali
jako „Rekruter”, do „Poprzedni rekruter”; powrót na P1 albo ponowne otwarcie
przy P1 przywraca ich samo. Nic nie jest kasowane: ``jobs.recruiter_id``
i ręcznie dopisani zostają (dostęp, metryki, historia), a reguła zespołu
(``services/job_team``) pomija osoby z otwartym wierszem tej tabeli.

Otwarty wiersz (``cleared_at IS NULL``) jest jeden na parę (rekrutacja,
osoba). Zdjęcie znacznika zostawia wiersz z powodem — z nich widać, kto
i kiedy przesunął zespół.
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

PARK_VIA = ("owner", "assignment", "collaborator")
PARK_REASONS = ("closed", "priority")
CLEAR_REASONS = ("restored", "dismissed", "readded", "removed", "skipped")


class JobPreviousRecruiter(Base):
    __tablename__ = "job_previous_recruiters"
    __table_args__ = (
        CheckConstraint(
            "via IN ('owner', 'assignment', 'collaborator')",
            name="ck_job_previous_recruiters_via",
        ),
        CheckConstraint(
            "assignment_source IS NULL OR assignment_source IN ('auto', 'manual')",
            name="ck_job_previous_recruiters_assignment_source",
        ),
        CheckConstraint(
            "reason IN ('closed', 'priority')",
            name="ck_job_previous_recruiters_reason",
        ),
        CheckConstraint(
            "cleared_reason IS NULL OR cleared_reason IN "
            "('restored', 'dismissed', 'readded', 'removed', 'skipped')",
            name="ck_job_previous_recruiters_cleared_reason",
        ),
        Index(
            "ux_job_previous_recruiters_open",
            "job_id",
            "user_id",
            unique=True,
            postgresql_where=text("cleared_at IS NULL"),
        ),
        Index(
            "ix_job_previous_recruiters_user_open",
            "user_id",
            postgresql_where=text("cleared_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    via: Mapped[str] = mapped_column(String(20), nullable=False)
    assignment_source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    parked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    parked_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cleared_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cleared_reason: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    cleared_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
