"""Autonomiczne dopasowanie: nowe CV → otwarte rekrutacje, nowa rekrutacja → świeże CV.

Dwie tabele:

- ``candidate_match_outbox`` — trwała kolejka zdarzeń. Wpis powstaje w tej samej
  transakcji, która zapisuje profil z CV (albo publikuje rekrutację), więc
  restart kontenera przy deployu nie gubi dopasowania. Worker
  ``tasks/candidate_auto_match.py`` bierze wiersze ``FOR UPDATE SKIP LOCKED``.
- ``candidate_auto_match_log`` — decyzja dla KAŻDEJ rozważonej pary (kandydat,
  rekrutacja) w danej wersji profilu. UNIQUE na trójce jest kontraktem dedupu:
  ta sama wersja CV nie trafi drugi raz do tej samej rekrutacji, a Artur widzi,
  dlaczego system kogoś NIE dodał.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

AUTO_MATCH_TRIGGERS = (
    "cv_upload",
    "cv_refresh",
    "email",
    "public_apply",
    "job_publish",
    "manual",
)
AUTO_MATCH_STATUSES = ("pending", "processing", "done", "failed", "dead", "skipped")
AUTO_MATCH_DECISIONS = (
    "added",
    "below_threshold",
    "must_gap",
    "ineligible",
    "capped",
    "already_in_pipeline",
    "dry_run",
    "penalized",
)


class CandidateMatchOutbox(Base):
    __tablename__ = "candidate_match_outbox"
    __table_args__ = (
        CheckConstraint(
            "candidate_id IS NOT NULL OR job_id IS NOT NULL",
            name="ck_candidate_match_outbox_subject",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed', 'dead', 'skipped')",
            name="ck_candidate_match_outbox_status",
        ),
        Index("ix_candidate_match_outbox_status_created", "status", "created_at"),
        Index(
            "ux_candidate_match_outbox_candidate_open",
            "candidate_id",
            "profile_revision",
            unique=True,
            postgresql_where=text(
                "candidate_id IS NOT NULL AND status IN ('pending', 'processing', 'failed')"
            ),
        ),
        Index(
            "ux_candidate_match_outbox_job_open",
            "job_id",
            unique=True,
            postgresql_where=text(
                "job_id IS NOT NULL AND status IN ('pending', 'processing', 'failed')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True
    )
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    profile_revision: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CandidateAutoMatchLog(Base):
    __tablename__ = "candidate_auto_match_log"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "job_id",
            "profile_revision",
            name="uq_candidate_auto_match_log_pair_revision",
        ),
        Index("ix_candidate_auto_match_log_job", "job_id"),
        Index("ix_candidate_auto_match_log_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    profile_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    stage_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
