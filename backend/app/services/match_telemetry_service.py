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
import math
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

# Durable full-search results pages (`GET /api/candidate-search/runs/{id}`):
# a saved recruitment (the C2 screens) vs an ad-hoc Talent Radar request.
FULL_SEARCH_SURFACE = "full_search"
RADAR_SEARCH_SURFACE = "talent_radar"

# Hard ceiling on rows written by ONE call. The served page is already bounded
# (`limit` <= 100, bulk-add <= 100 ids); this keeps a future caller from turning
# telemetry into an unbounded write on the request path.
MAX_ROWS_PER_CALL = 100

# The only breakdown keys copied into `match_impressions.fit_breakdown`:
# numbers and a status, never the free-text `reason` (it can quote a location,
# a rate or a skill list verbatim).
_BREAKDOWN_LAYERS = (
    "semantic",
    "skills",
    "salary",
    "location",
    "availability",
    "champion_fit",
)


def _number(value) -> Optional[float]:
    # NaN/inf would serialize to invalid JSON and fail the WHOLE page insert.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def numeric_fit_breakdown(
    breakdown: Optional[dict],
    *,
    total: Optional[float] = None,
    measurement: Optional[str] = None,
) -> dict:
    """Ids-and-numbers projection of a served breakdown (PII policy above).

    Per layer only ``points``/``max`` (``None`` where the response redacted
    them, e.g. salary without ``view_finance``); plus the served ``total`` and
    the ``measurement`` status. Reasons, skill names and any other free text
    are dropped structurally, not by convention.
    """
    source = breakdown if isinstance(breakdown, dict) else {}
    out: dict = {}
    for name in _BREAKDOWN_LAYERS:
        layer = source.get(name)
        if isinstance(layer, dict):
            out[name] = {
                "points": _number(layer.get("points")),
                "max": _number(layer.get("max")),
            }
    out["total"] = _number(total)
    if measurement is not None:
        out["measurement"] = str(measurement)[:24]
    return out


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

    ONE statement for the whole page (the entries travel as parallel arrays
    through ``unnest``) instead of one INSERT per row on the request path.
    Idempotent per (run_id, candidate_id) via ``ON CONFLICT DO NOTHING``; a
    candidate repeated within ``entries`` keeps its first (best) rank.
    Returns the number of rows inserted (0 when the flag is off or on any
    error — never raises).
    """
    if not telemetry_enabled() or not entries:
        return 0

    rows: dict[int, ImpressionEntry] = {}
    for entry in entries:
        rows.setdefault(int(entry.candidate_id), entry)
    shown = list(rows.values())

    def _json(value: Optional[dict]) -> Optional[str]:
        return json.dumps(value) if value is not None else None

    def _float(value) -> Optional[float]:
        return float(value) if value is not None else None

    try:
        # Dedicated session (M3-TX-01): telemetry is fire-and-forget and must
        # NEVER commit or roll back the CALLER's request transaction. The passed
        # ``db`` (the request session owned by the recommendation flow) is
        # deliberately not used for the write — a telemetry failure has to stay
        # isolated from the business operation, so the INSERT runs on its own
        # ``AsyncSessionLocal``.
        async with AsyncSessionLocal() as s:
            result = await s.execute(
                _IMPRESSIONS_INSERT,
                {
                    "run_id": run_id,
                    "surface": surface,
                    "job_id": job_id,
                    "request_id": request_id,
                    "user_ref": pseudonymize(user_id),
                    "client_ref": pseudonymize(client_id),
                    "ranker_version": ranker_version,
                    "index_version": index_version,
                    "text_schema_version": text_schema_version,
                    "taxonomy_version": taxonomy_version,
                    "degraded": degraded,
                    "candidate_ids": [int(e.candidate_id) for e in shown],
                    "ranks": [int(e.rank) for e in shown],
                    "eligibles": [bool(e.eligible) for e in shown],
                    "retrieval_sources": [_json(e.retrieval_sources) for e in shown],
                    "retrieval_scores": [_float(e.retrieval_score) for e in shown],
                    "rerank_scores": [_float(e.rerank_score) for e in shown],
                    "fit_scores": [_float(e.fit_score) for e in shown],
                    "fit_breakdowns": [_json(e.fit_breakdown) for e in shown],
                },
            )
            inserted = result.rowcount or 0
            await s.commit()
    except Exception as exc:  # noqa: BLE001 — telemetry never breaks matching
        logger.warning("[telemetry] impression write failed: %s", exc)
        return 0
    return inserted


# Every per-page scalar is CAST: in `INSERT ... SELECT` Postgres does not infer
# a parameter's type from the target column (tests/test_raw_sql_prepares.py).
_IMPRESSIONS_INSERT = text(
    """
    INSERT INTO match_impressions (
        run_id, surface, job_id, request_id, user_ref, client_ref,
        candidate_id, rank, eligible, retrieval_sources, retrieval_score,
        rerank_score, fit_score, fit_breakdown, ranker_version,
        index_version, text_schema_version, taxonomy_version, degraded
    )
    SELECT
        CAST(:run_id AS VARCHAR), CAST(:surface AS VARCHAR),
        CAST(:job_id AS INTEGER), CAST(:request_id AS INTEGER),
        CAST(:user_ref AS VARCHAR), CAST(:client_ref AS VARCHAR),
        e.candidate_id, e.rank, e.eligible,
        CAST(e.retrieval_sources AS JSONB), e.retrieval_score,
        e.rerank_score, e.fit_score, CAST(e.fit_breakdown AS JSONB),
        CAST(:ranker_version AS VARCHAR), CAST(:index_version AS VARCHAR),
        CAST(:text_schema_version AS VARCHAR),
        CAST(:taxonomy_version AS VARCHAR), CAST(:degraded AS BOOLEAN)
    FROM unnest(
        CAST(:candidate_ids AS INTEGER[]),
        CAST(:ranks AS INTEGER[]),
        CAST(:eligibles AS BOOLEAN[]),
        CAST(:retrieval_sources AS TEXT[]),
        CAST(:retrieval_scores AS DOUBLE PRECISION[]),
        CAST(:rerank_scores AS DOUBLE PRECISION[]),
        CAST(:fit_scores AS DOUBLE PRECISION[]),
        CAST(:fit_breakdowns AS TEXT[])
    ) AS e(
        candidate_id, rank, eligible, retrieval_sources, retrieval_score,
        rerank_score, fit_score, fit_breakdown
    )
    ON CONFLICT (run_id, candidate_id) DO NOTHING
    """
)


_OUTCOME_INSERT = text(
    """
    INSERT INTO match_outcomes (
        event_id, run_id, candidate_id, job_id, event_type, reason_code
    ) VALUES (
        :event_id, :run_id, :candidate_id, :job_id, :event_type, :reason_code
    )
    ON CONFLICT (event_id) DO NOTHING
    """
)


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
    try:
        # Dedicated session (M3-TX-01): see record_impressions. ``db`` stays
        # untouched so an outcome-write failure never disturbs the caller's txn.
        async with AsyncSessionLocal() as s:
            result = await s.execute(
                _OUTCOME_INSERT,
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

    No-op when telemetry is off. Idempotent per
    ``(event_type, run_id, job, candidate)`` — a repeated click within the same
    ranking run records once, but the same pair acted on after a NEW ranking run
    is captured again, so outcomes correlate per run (PR #1036 review follow-up).
    Falls back to the pair when no run_id is available. Never raises — telemetry
    must never break the user action. ``db`` is used only to look up the run_id;
    the write itself happens in ``record_outcome``'s own session.
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
        event_id=f"{event_type}:{run_id or 'norun'}:{job_id}:{candidate_id}",
        event_type=event_type,
        run_id=run_id,
        candidate_id=candidate_id,
        job_id=job_id,
        reason_code=reason_code,
    )


# ── Full search (C2 / Talent Radar) ───────────────────────────────────────────
#
# Until 09.2026 the only impression writer was `matching_orchestrator._emit`,
# which no live surface calls — so with the flag ON in production the table
# stayed at 0 rows and every outcome pointed at a run nobody could replay. The
# durable full search is the ranking users actually see; its run id
# (`candidate_search_runs.id`) is the impression run id, so an outcome can be
# joined back to the exact page, rank and fit that preceded it.


def _stamp(trace: Optional[dict], key: str, default: str) -> str:
    value = trace.get(key) if isinstance(trace, dict) else None
    return str(value)[:64] if value else default


async def record_full_search_page(
    db: AsyncSession,
    *,
    run_id: str,
    job_id: Optional[int],
    client_id: Optional[int],
    user_id: Optional[int],
    version_trace: Optional[dict],
    entries: Sequence[ImpressionEntry],
    degraded: bool,
) -> int:
    """Impressions for one served results page of a durable full search.

    Only the rows actually served (the page), capped at ``MAX_ROWS_PER_CALL``;
    idempotent per (run, candidate), so re-reading the page writes nothing.
    Version stamps come from the RUN, not from the process: the page shows the
    ranking frozen when the scan ran. Never raises.
    """
    if not telemetry_enabled() or not entries:
        return 0
    return await record_impressions(
        db,
        run_id=run_id,
        surface=FULL_SEARCH_SURFACE if job_id is not None else RADAR_SEARCH_SURFACE,
        entries=list(entries)[:MAX_ROWS_PER_CALL],
        job_id=job_id,
        user_id=user_id,
        client_id=client_id,
        ranker_version=_stamp(version_trace, "ranker_version", LEGACY_RANKER_VERSION),
        index_version=_stamp(version_trace, "index_version", LEGACY_INDEX_VERSION),
        text_schema_version=_stamp(
            version_trace, "text_schema_version", LEGACY_TEXT_SCHEMA_VERSION
        ),
        taxonomy_version=_stamp(
            version_trace, "taxonomy_version", LEGACY_TAXONOMY_VERSION
        ),
        degraded=degraded,
    )


# Screens that add to a pipeline through the shared bulk route
# (`POST /api/jobs/{id}/proposals/bulk`). Stored as the outcome's
# `reason_code`: for `add_to_pipeline` there is no other reason to record, and
# it is what separates an unattributed (NULL-run) add by surface. Anything
# outside this closed vocabulary is stored as NULL, never as free text.
PIPELINE_ADD_SOURCES = frozenset(
    {
        "full_search",
        "manual_search",
        "historical",
        "quick_add",
        "talent_radar",
        "candidate_list",
        "jarvis",
    }
)

# The run the caller declared, accepted only when it verifiably preceded the
# add: a durable full-search run owned by this user, for this job, that served
# this candidate (its impression). `= ANY(:ids)`, not an expanding `IN :ids`:
# the statement stays one plain, preparable text
# (tests/test_raw_sql_prepares.py plans every literal).
_VERIFIED_RUN_CANDIDATES = text(
    """
    SELECT i.candidate_id
    FROM match_impressions i
    JOIN candidate_search_runs r ON r.id = i.run_id
    WHERE i.run_id = :run_id
      AND r.created_by = :user_id
      AND r.job_id = :job_id
      AND i.candidate_id = ANY(:ids)
    """
)


async def _verified_run_candidates(
    *,
    run_id: Optional[str],
    job_id: int,
    user_id: Optional[int],
    candidate_ids: Sequence[int],
) -> set[int]:
    """Candidates of ``candidate_ids`` that ``run_id`` showed THIS user for THIS
    job. Own session, never raises: an unverifiable run is ``set()``."""
    if not run_id or user_id is None or not candidate_ids:
        return set()
    try:
        async with AsyncSessionLocal() as s:
            rows = await s.execute(
                _VERIFIED_RUN_CANDIDATES,
                {
                    "run_id": run_id,
                    "user_id": user_id,
                    "job_id": job_id,
                    "ids": list(candidate_ids),
                },
            )
            return {int(cid) for (cid,) in rows.all()}
    except Exception as exc:  # noqa: BLE001 — telemetry never breaks the action
        logger.warning("[telemetry] run attribution lookup failed: %s", exc)
        return set()


async def emit_pipeline_additions(
    *,
    job_id: int,
    candidate_ids: Sequence[int],
    user_id: Optional[int],
    run_id: Optional[str] = None,
    source: Optional[str] = None,
) -> int:
    """``add_to_pipeline`` outcomes for candidates just added to a pipeline.

    An outcome joins a ranking only through the run the CALLER declares
    (``run_id``, sent by the full-search screen), and only for candidates that
    run verifiably showed this user for this job — so it joins its impression:
    page, rank, fit. Everything else is stored with ``run_id = NULL``.

    No attribution is guessed. The bulk route is shared by manual search, the
    historical section, quick-add and the job page, so "the latest impression
    this user saw" (or "the job's latest proposals run") credited adds made on
    another screen to an unrelated ranking. ``source`` records which screen
    the add came from (``reason_code``). Same idempotency key shape as
    ``emit_match_outcome``. One session for the whole batch, at most
    ``MAX_ROWS_PER_CALL`` rows. Never raises; returns the number of NEW rows.
    """
    ids = list(dict.fromkeys(int(cid) for cid in candidate_ids))[:MAX_ROWS_PER_CALL]
    if not telemetry_enabled() or not ids:
        return 0
    try:
        shown = await _verified_run_candidates(
            run_id=run_id, job_id=job_id, user_id=user_id, candidate_ids=ids
        )
        reason_code = source if source in PIPELINE_ADD_SOURCES else None
        params = []
        for cid in ids:
            attributed = run_id if cid in shown else None
            params.append(
                {
                    "event_id": (
                        f"add_to_pipeline:{attributed or 'norun'}:{job_id}:{cid}"
                    ),
                    "run_id": attributed,
                    "candidate_id": cid,
                    "job_id": job_id,
                    "event_type": "add_to_pipeline",
                    "reason_code": reason_code,
                }
            )
        inserted = 0
        async with AsyncSessionLocal() as s:
            for row in params:
                result = await s.execute(_OUTCOME_INSERT, row)
                inserted += result.rowcount or 0
            await s.commit()
        return inserted
    except Exception as exc:  # noqa: BLE001 — telemetry never breaks the action
        logger.warning("[telemetry] pipeline outcome write failed: %s", exc)
        return 0
