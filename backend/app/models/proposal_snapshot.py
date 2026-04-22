"""ProposalSnapshot — immutable record of AI candidate proposals per job (Phase 13).

Populated asynchronously after `POST /api/jobs` (and on manual regenerate).
Frontend polls `GET /api/jobs/{job_id}/proposals/latest` while `status="pending"`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# Status values — kept as plain strings (mirrors CandidateJobMatchScore style
# where enums live as Python constants + CHECK constraint at DB level).
STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
ALL_STATUSES = (STATUS_PENDING, STATUS_READY, STATUS_FAILED)

SOURCE_CREATE = "create"
SOURCE_MANUAL_REGENERATE = "manual_regenerate"
SOURCE_JOB_UPDATED = "job_updated"
ALL_SOURCES = (SOURCE_CREATE, SOURCE_MANUAL_REGENERATE, SOURCE_JOB_UPDATED)


class ProposalSnapshot(Base):
    __tablename__ = "proposal_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=SOURCE_CREATE
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=STATUS_PENDING
    )
    top_k: Mapped[int] = mapped_column(Integer, nullable=False, server_default="20")
    # 0 = built-in DEFAULT_PROFILE (mirrors CandidateJobMatchScore.profile_id)
    profile_id: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    candidate_ids: Mapped[Optional[list[int]]] = mapped_column(JSONB, nullable=True)
    breakdowns: Mapped[Optional[list[dict]]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
    )

    job = relationship("Job", lazy="selectin")
