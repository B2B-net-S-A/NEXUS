"""Persistent invalidation ledger for the match-score cache (audyt F-28).

The CAS fence added in migration ``0190_match_score_cache_cas`` stamps
``candidate_job_match_scores.invalidated_at`` so a compute that STARTED before a
``mark_stale_*`` cannot resurrect ``stale=False`` on the *conflict* (row exists)
write-back. But that fence lives ON the cache row — so it protects nothing on the
*miss* path: when no cache row exists yet, ``mark_stale_*`` updates zero rows and
leaves no trace. An in-flight miss-compute then INSERTs ``stale=False`` against
the OLD inputs and the row looks fresh forever.

This table is the missing trace. ``mark_stale_for_candidate`` / ``_for_job`` /
``_for_profile`` UPSERT a row here to ``now()`` **even when no cache row exists**,
and the miss/INSERT path reads ``last_invalidated_at`` for the (candidate, job,
profile) keys before writing: if an invalidation landed after the compute began,
the row is written ``stale=True`` instead of falsely fresh.

Keyed by ``(entity_type, entity_id)`` so one table covers all invalidation
vectors. Rows are cheap and long-lived (one per touched entity); this is a
watermark table, not an event log — the UPSERT keeps a single row per key.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, PrimaryKeyConstraint, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MatchScoreInvalidation(Base):
    __tablename__ = "match_score_invalidations"
    __table_args__ = (
        PrimaryKeyConstraint(
            "entity_type", "entity_id", name="pk_match_score_invalidations"
        ),
    )

    # 'candidate' | 'job' | 'profile' — the cache key is (candidate, job, profile),
    # so each dimension that can be invalidated gets its own ledger namespace.
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # DB clock of the most recent invalidation for this entity. Compared against a
    # compute's ``compute_start`` on the miss/INSERT path: if this is >= the start,
    # the freshly computed row is written stale (an edit raced the compute).
    last_invalidated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
