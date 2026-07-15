"""Append-only matching telemetry (plan PR2).

Two immutable logs that let us reconstruct *what a user actually saw* before a
later outcome, so weights can eventually be learned honestly instead of from
biased placement history:

* ``match_impressions`` — one row per (run, candidate) shown, with the exact
  rank, eligibility, retrieval/rerank/fit scores and the full fit breakdown,
  plus the version stamps in effect at exposure time.
* ``match_outcomes`` — one row per downstream event (view / shortlist / add /
  reject / interview / hire), keyed by a caller-supplied ``event_id`` so one
  impression can accrue many events without overwriting history.

Deliberate design choices:

* **No foreign keys** to candidates/jobs/users. Telemetry is analytics, not
  operational data: it must survive a candidate hard-delete (see the
  candidate cascade work) and is purged instead by an explicit retention/DSAR
  job. User/client identifiers are stored *pseudonymised* (salted hash), never
  raw. Raw CV text, queries, names, emails and phones never reach these tables.
* **Append-only** — writers use ``ON CONFLICT DO NOTHING`` on the natural
  uniqueness keys; there are no updates or deletes on the hot path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Legacy version placeholders used until later plan PRs introduce real runtime
# versioning (PR4 scoring, PR6 index, PR7 text schema, PR10 taxonomy). Explicit
# strings — never NULL — so a run recorded today is unambiguously "the legacy
# pipeline" rather than "unknown".
LEGACY_RANKER_VERSION = "scoring-v1-legacy"
LEGACY_INDEX_VERSION = "index-legacy-v1"
LEGACY_TEXT_SCHEMA_VERSION = "text-v1-legacy"
LEGACY_TAXONOMY_VERSION = "taxonomy-legacy-v1"


class MatchImpression(Base):
    __tablename__ = "match_impressions"
    __table_args__ = (
        UniqueConstraint("run_id", "candidate_id", name="uq_match_impression_run_cand"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    surface: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    request_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Pseudonymised (salted-hash) identifiers — never the raw user/client id.
    user_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    client_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    candidate_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    retrieval_sources: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    retrieval_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rerank_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fit_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fit_breakdown: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    ranker_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=LEGACY_RANKER_VERSION
    )
    index_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=LEGACY_INDEX_VERSION
    )
    text_schema_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=LEGACY_TEXT_SCHEMA_VERSION
    )
    taxonomy_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=LEGACY_TAXONOMY_VERSION
    )
    degraded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MatchOutcome(Base):
    __tablename__ = "match_outcomes"
    __table_args__ = (UniqueConstraint("event_id", name="uq_match_outcome_event_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Caller-supplied idempotency key — a retried webhook/click never
    # double-counts.
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
