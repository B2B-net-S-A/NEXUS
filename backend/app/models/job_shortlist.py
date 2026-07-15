"""Job shortlist — a pre-pipeline evaluation list per (job, candidate).

SEARCH-P1-05. The plan's ADR asked: a separate pre-pipeline entity, or extend
``CandidateStage``? Chosen: a **separate** table. A shortlist entry is an
*evaluation* record (do we want this person?) with two orthogonal statuses,
an owner, a decision reason and a next action — none of which belong on a
pipeline stage, which represents an *actual* recruitment process the candidate
is already in. Keeping them separate means adding to the shortlist is a
low-commitment act (no pipeline row, no notifications), and only *approved*
entries get promoted into the pipeline (which creates the ``CandidateStage``).

Statuses are stored as plain ``VARCHAR`` (validated by the Pydantic layer, see
``schemas/job_shortlist.py``) rather than native PG enums — new enum *types*
are a migration hazard on NEXUS's chronically multi-head prod, and a string
column is created cleanly by ``Base.metadata.create_all``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin

# Evaluation: do we want to put this person forward?
EVALUATION_STATUSES = ("do_oceny", "potencjalny", "zatwierdzony", "odrzucony")
# Outreach: where are we in contacting them? Orthogonal to evaluation.
OUTREACH_STATUSES = (
    "nie_kontaktowano",
    "do_kontaktu",
    "kontakt_w_toku",
    "zainteresowany",
    "brak_zainteresowania",
)


class JobShortlistEntry(Base, TimestampMixin):
    __tablename__ = "job_shortlist_entries"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "candidate_id", name="uq_job_shortlist_job_candidate"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )

    evaluation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="do_oceny"
    )
    outreach_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="nie_kontaktowano"
    )

    owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    decision_reason_code: Mapped[Optional[str]] = mapped_column(String(64))
    note: Mapped[Optional[str]] = mapped_column(Text)
    next_action_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Snapshot of the request-fit score at add time (for later comparison).
    score_snapshot: Mapped[Optional[int]] = mapped_column(Integer)

    # Optimistic-locking counter — bumped on every update; a stale PATCH 409s.
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    # Set when the entry is promoted into the pipeline (idempotency guard).
    promoted_to_pipeline_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
