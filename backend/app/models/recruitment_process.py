"""Kanoniczny agregat procesu rekrutacyjnego — shadow mode (M4 audyt P0.1, PR-06).

``RecruitmentProcess`` = dokładnie jedna rekrutacja pary (candidate, job).
W tym PR agregat jest WYŁĄCZNIE cieniem legacy ``CandidateStage`` (backfill +
komparator); żadna ścieżka runtime nie czyta z niego ani nie utrzymuje go —
authority przejmie command service (PR-07/08).

Decyzje Artura (2026-07-16):
- §20.2: reopen z terminala = TEN SAM proces (bez limitu czasu); nowy
  ``attempt_no`` powstaje wyłącznie przez przyszłą jawną komendę „nowa
  aplikacja" — dlatego backfill tworzy zawsze ``attempt_no=1``.
- §20.1: ``hired`` ≠ placement (status ``closed`` po terminalu ``hired``
  oznacza zamkniętą rekrutację, nie aktywny placement).

Inwarianty DB (sekcja 11.1/12 planu):
- partial unique: najwyżej JEDEN otwarty proces pary,
- unique ``(candidate_id, job_id, attempt_no)``.

Do PR-07 wskaźnikiem bieżącego stanu jest ``legacy_current_candidate_stage_id``
(latest legacy row wg kanonicznego ``(moved_at DESC, id DESC)``); canonical
transition pointer pozostaje nullable.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ProcessStatus(str, enum.Enum):
    open = "open"
    closed = "closed"
    voided = "voided"


class RecruitmentProcess(Base, TimestampMixin):
    __tablename__ = "recruitment_processes"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "job_id", "attempt_no", name="uq_process_attempt"
        ),
        # Najwyżej jeden OTWARTY proces pary (audyt P0.1).
        Index(
            "ux_process_one_open",
            "candidate_id",
            "job_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_processes_job_status", "job_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalizacja z Job — spójność kontrolowana przy zapisie.
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    attempt_no: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    previous_process_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recruitment_processes.id", ondelete="SET NULL"),
        nullable=True,
    )

    workflow_revision_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workflow_revisions.id", ondelete="SET NULL"), nullable=True
    )
    current_stage_revision_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("stage_revisions.id", ondelete="SET NULL"), nullable=True
    )
    current_semantic_state: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )
    # Pointer migracyjny (do PR-07): latest legacy row pary.
    legacy_current_candidate_stage_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidate_stages.id", ondelete="SET NULL"), nullable=True
    )

    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    status: Mapped[ProcessStatus] = mapped_column(
        Enum(ProcessStatus, name="processstatus"),
        nullable=False,
        default=ProcessStatus.open,
        index=True,
    )
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Skąd pochodzi rekord/prawda: backfill | live_command (PR-07+) |
    # external_observed (PR-10) | repair.
    source_authority: Mapped[str] = mapped_column(
        String(30), nullable=False, default="backfill", server_default="backfill"
    )

    opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    candidate = relationship("Candidate")
    job = relationship("Job")
    legacy_current_stage = relationship(
        "CandidateStage", foreign_keys=[legacy_current_candidate_stage_id]
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<RecruitmentProcess cand={self.candidate_id} job={self.job_id} "
            f"attempt={self.attempt_no} status={self.status.value}>"
        )
