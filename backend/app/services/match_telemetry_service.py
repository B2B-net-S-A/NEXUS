"""Append-only matching telemetry writer (plan PR2).

Flag-gated (``AI_MATCH_TELEMETRY_ENABLED``, off by default) so it is a strict
no-op until switched on per Coolify env. Every write is best-effort: telemetry
must NEVER break a recommendation response, so failures are swallowed and
logged, and the caller can surface a degraded marker.

PII policy (enforced structurally): callers pass only ids, ranks, scores and
the numeric fit breakdown. Raw CV text, search queries, names, emails and
phones are never accepted here. User/client ids are pseudonymised with a salted
SHA-256 hash before they touch the database.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.match_telemetry import (
    LEGACY_INDEX_VERSION,
    LEGACY_RANKER_VERSION,
    LEGACY_TAXONOMY_VERSION,
    LEGACY_TEXT_SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)

# Downstream event vocabulary. Kept permissive (validated, not enum-constrained
# in the DB) so new signal types don't need a migration.
OUTCOME_EVENTS = frozenset(
    {"view", "shortlist", "add_to_pipeline", "reject", "interview", "hire"}
)


def telemetry_enabled() -> bool:
    return bool(getattr(settings, "AI_MATCH_TELEMETRY_ENABLED", False))


def _salt() -> str:
    return getattr(settings, "AI_MATCH_TELEMETRY_SALT", "") or settings.SECRET_KEY


def pseudonymize(value: Optional[int | str]) -> Optional[str]:
    """Salted SHA-256 of an identifier, truncated to 32 hex chars.

    Returns None for None so a missing user/client stays missing rather than
    hashing the literal string "None".
    """
    if value is None:
        return None
    digest = hashlib.sha256(f"{_salt()}:{value}".encode("utf-8")).hexdigest()
    return digest[:32]


@dataclass(frozen=True)
class ImpressionEntry:
    """One ranked candidate as actually shown. Ids + numbers only — no PII."""

    candidate_id: int
    rank: int
    eligible: bool = True
    retrieval_sources: Optional[dict] = None
    retrieval_score: Optional[float] = None
    rerank_score: Optional[float] = None
    fit_score: Optional[float] = None
    fit_breakdown: Optional[dict] = None


async def record_impressions(
    db: AsyncSession,
    *,
    run_id: str,
    surface: str,
    entries: Sequence[ImpressionEntry],
    job_id: Optional[int] = None,
    request_id: Optional[int] = None,
    user_id: Optional[int] = None,
    client_id: Optional[int] = None,
    ranker_version: str = LEGACY_RANKER_VERSION,
    index_version: str = LEGACY_INDEX_VERSION,
    text_schema_version: str = LEGACY_TEXT_SCHEMA_VERSION,
    taxonomy_version: str = LEGACY_TAXONOMY_VERSION,
    degraded: bool = False,
) -> int:
    """Append the shown ranking to ``match_impressions``.

    Idempotent per (run_id, candidate_id) via ``ON CONFLICT DO NOTHING``.
    Returns the number of rows inserted (0 when the flag is off or on any
    error — never raises).
    """
    if not telemetry_enabled() or not entries:
        return 0

    user_ref = pseudonymize(user_id)
    client_ref = pseudonymize(client_id)
    stmt = text(
        """
        INSERT INTO match_impressions (
            run_id, surface, job_id, request_id, user_ref, client_ref,
            candidate_id, rank, eligible, retrieval_sources, retrieval_score,
            rerank_score, fit_score, fit_breakdown, ranker_version,
            index_version, text_schema_version, taxonomy_version, degraded
        ) VALUES (
            :run_id, :surface, :job_id, :request_id, :user_ref, :client_ref,
            :candidate_id, :rank, :eligible,
            CAST(:retrieval_sources AS JSONB), :retrieval_score,
            :rerank_score, :fit_score, CAST(:fit_breakdown AS JSONB),
            :ranker_version, :index_version, :text_schema_version,
            :taxonomy_version, :degraded
        )
        ON CONFLICT (run_id, candidate_id) DO NOTHING
        """
    )

    inserted = 0
    try:
        # Dedicated session (M3-TX-01): telemetry is fire-and-forget and must
        # NEVER commit or roll back the CALLER's request transaction. The passed
        # ``db`` (the request session owned by the recommendation flow) is
        # deliberately not used for the write — a telemetry failure has to stay
        # isolated from the business operation, so the INSERTs run on their own
        # ``AsyncSessionLocal``.
        async with AsyncSessionLocal() as s:
            for e in entries:
                result = await s.execute(
                    stmt,
                    {
                        "run_id": run_id,
                        "surface": surface,
                        "job_id": job_id,
                        "request_id": request_id,
                        "user_ref": user_ref,
                        "client_ref": client_ref,
                        "candidate_id": e.candidate_id,
                        "rank": e.rank,
                        "eligible": e.eligible,
                        "retrieval_sources": (
                            json.dumps(e.retrieval_sources)
                            if e.retrieval_sources is not None
                            else None
                        ),
                        "retrieval_score": e.retrieval_score,
                        "rerank_score": e.rerank_score,
                        "fit_score": e.fit_score,
                        "fit_breakdown": (
                            json.dumps(e.fit_breakdown)
                            if e.fit_breakdown is not None
                            else None
                        ),
                        "ranker_version": ranker_version,
                        "index_version": index_version,
                        "text_schema_version": text_schema_version,
                        "taxonomy_version": taxonomy_version,
                        "degraded": degraded,
                    },
                )
                inserted += result.rowcount or 0
            await s.commit()
    except Exception as exc:  # noqa: BLE001 — telemetry never breaks matching
        logger.warning("[telemetry] impression write failed: %s", exc)
        return 0
    return inserted


async def record_outcome(
    db: AsyncSession,
    *,
    event_id: str,
    event_type: str,
    run_id: Optional[str] = None,
    candidate_id: Optional[int] = None,
    job_id: Optional[int] = None,
    reason_code: Optional[str] = None,
) -> bool:
    """Append one downstream event to ``match_outcomes``.

    Idempotent per ``event_id`` — a retried click/webhook records once. Returns
    True when a new row landed, False when the flag is off, the event is a
    duplicate, or on any error (never raises).
    """
    if not telemetry_enabled():
        return False
    if event_type not in OUTCOME_EVENTS:
        logger.warning("[telemetry] ignoring unknown outcome event_type=%s", event_type)
        return False
    stmt = text(
        """
        INSERT INTO match_outcomes (
            event_id, run_id, candidate_id, job_id, event_type, reason_code
        ) VALUES (
            :event_id, :run_id, :candidate_id, :job_id, :event_type, :reason_code
        )
        ON CONFLICT (event_id) DO NOTHING
        """
    )
    try:
        # Dedicated session (M3-TX-01): see record_impressions. ``db`` stays
        # untouched so an outcome-write failure never disturbs the caller's txn.
        async with AsyncSessionLocal() as s:
            result = await s.execute(
                stmt,
                {
                    "event_id": event_id,
                    "run_id": run_id,
                    "candidate_id": candidate_id,
                    "job_id": job_id,
                    "event_type": event_type,
                    "reason_code": reason_code,
                },
            )
            await s.commit()
            return bool(result.rowcount)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[telemetry] outcome write failed: %s", exc)
        return False


async def emit_match_outcome(
    db: AsyncSession,
    *,
    event_type: str,
    candidate_id: int,
    job_id: int,
    reason_code: Optional[str] = None,
) -> None:
    """Best-effort: record a downstream match outcome for a (candidate, job),
    correlated with the job's latest ranking ``run_id`` (P0-B).

    No-op when telemetry is off. Idempotent per ``(event_type, job, candidate)``
    so a repeated click records once. Never raises — telemetry must never break
    the user action. ``db`` is used only to look up the run_id; the write itself
    happens in ``record_outcome``'s own session.
    """
    if not telemetry_enabled():
        return
    run_id: Optional[str] = None
    try:
        from sqlalchemy import select

        from app.models.proposal_snapshot import ProposalSnapshot

        run_id = await db.scalar(
            select(ProposalSnapshot.run_id)
            .where(ProposalSnapshot.job_id == job_id)
            .order_by(ProposalSnapshot.created_at.desc())
            .limit(1)
        )
    except Exception:  # pragma: no cover — never break the action for telemetry
        run_id = None
    await record_outcome(
        db,
        event_id=f"{event_type}:{job_id}:{candidate_id}",
        event_type=event_type,
        run_id=run_id,
        candidate_id=candidate_id,
        job_id=job_id,
        reason_code=reason_code,
    )
