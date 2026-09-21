"""Transactional storage for exhaustive searches and restart-safe batch leases.

All functions use the caller's transaction. A worker must commit each batch;
no process-local status is considered evidence of completion.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Integer,
    Numeric,
    String,
    case,
    delete,
    func,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.models.candidate_search_run import CandidateSearchResult, CandidateSearchRun
from app.services.full_candidate_scan import (
    CandidateEvaluation,
    CandidateSnapshot,
    snapshot_candidate_population,
)

# Lifecycle vocabulary shared by the worker, the API, erasure and retention.
# `failed` is terminal: it frees the author's active-search slot and is never
# claimed again, so a poisoned run cannot be retried at every lease expiry.
ACTIVE_STATES = ("queued", "running")
RESULT_STATES = ("complete", "partial")
FINISHED_STATES = (*RESULT_STATES, "failed")

# Durable claim counter kept in `metrics`. It is incremented by the claim
# UPDATE itself, so a crash between the claim commit and any later checkpoint
# still counts as an attempt. Telemetry snapshots replace `metrics`, therefore
# every write below re-applies the database value of these keys.
CLAIMS_KEY = "claims"
_LIFECYCLE_KEYS = (CLAIMS_KEY,)


# Przegląd uruchomiony przez system w imieniu rekrutacji (nocny automat,
# `services/auto_full_review.py`). Znacznik żyje w `version_trace`, bo `metrics`
# nadpisuje telemetria workera. Taki przegląd: jest czytelny dla każdego, kto
# przechodzi bramkę rekrutacji; nie zajmuje autorowi żadnego z dwóch slotów;
# nie jest chroniony przez retencję; nie dzwoni autorowi po zakończeniu.
ORIGIN_KEY = "origin"
ORIGIN_AUTO = "auto"


def is_auto_run(run) -> bool:
    trace = getattr(run, "version_trace", None)
    return isinstance(trace, dict) and trace.get(ORIGIN_KEY) == ORIGIN_AUTO


def auto_origin_clause():
    """SQL: przegląd automatyczny (NULL-safe — brak klucza to przegląd ręczny)."""
    return func.coalesce(
        CandidateSearchRun.version_trace[ORIGIN_KEY].astext, literal("manual")
    ) == literal(ORIGIN_AUTO)


def manual_origin_clause():
    return func.coalesce(
        CandidateSearchRun.version_trace[ORIGIN_KEY].astext, literal("manual")
    ) != literal(ORIGIN_AUTO)


class SearchLeaseLost(RuntimeError):
    pass


def claim_count(metrics: dict | None) -> int:
    value = (metrics or {}).get(CLAIMS_KEY)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def telemetry_metrics(metrics: dict | None) -> dict:
    """Metrics without lifecycle keys — the part owned by SearchTelemetry."""
    return {k: v for k, v in (metrics or {}).items() if k not in _LIFECYCLE_KEYS}


def _with_lifecycle(current: dict | None, metrics: dict) -> dict:
    kept = {k: v for k, v in (current or {}).items() if k in _LIFECYCLE_KEYS}
    return {**metrics, **kept}


async def create_run(
    db,
    *,
    actor_id: int,
    client_id: int,
    job_id: int | None,
    request_fingerprint: str,
    request_context: dict,
    version_trace: dict,
):
    run = CandidateSearchRun(
        id=str(uuid.uuid4()),
        created_by=actor_id,
        client_id=client_id,
        job_id=job_id,
        state="queued",
        request_fingerprint=request_fingerprint,
        request_context=request_context,
        version_trace=version_trace,
        population_size=0,
        metrics={},
    )
    db.add(run)
    await db.flush()
    # One statement fixes membership before any scoring or top-K retrieval.
    population = await snapshot_candidate_population(db)
    for start in range(0, len(population), 500):
        await db.execute(
            insert(CandidateSearchResult),
            [
                {
                    "run_id": run.id,
                    "candidate_id": item.candidate_id,
                    "candidate_version": item.version,
                    "state": "pending",
                }
                for item in population[start : start + 500]
            ],
        )
    run.population_size = len(population)
    await db.flush()
    return run


def _incremented_claims():
    """`metrics || {"claims": claims + 1}`, tolerant of a missing/foreign value."""
    stored = CandidateSearchRun.metrics[CLAIMS_KEY]
    previous = case(
        (
            func.jsonb_typeof(stored) == "number",
            stored.astext.cast(Numeric).cast(Integer),
        ),
        else_=0,
    )
    return func.coalesce(CandidateSearchRun.metrics, literal({}, JSONB)).op("||")(
        func.jsonb_build_object(literal(CLAIMS_KEY, String), previous + 1)
    )


async def claim_run(db, run_id: str, *, lease_seconds: int = 120) -> str | None:
    now = datetime.now(timezone.utc)
    token = str(uuid.uuid4())
    claimed = await db.execute(
        update(CandidateSearchRun)
        .where(
            CandidateSearchRun.id == run_id,
            CandidateSearchRun.state.in_(ACTIVE_STATES),
            or_(
                CandidateSearchRun.lease_expires_at.is_(None),
                CandidateSearchRun.lease_expires_at < now,
            ),
        )
        .values(
            state="running",
            lease_token=token,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            metrics=_incremented_claims(),
        )
        .returning(CandidateSearchRun.id)
    )
    return token if claimed.scalar_one_or_none() else None


async def fail_run(db, run_id: str, reason: str, *, token: str | None = None) -> bool:
    """Terminal failure of a still-active run; the caller commits.

    With ``token`` only the current lease owner may fail the run, so a replaced
    worker cannot overwrite its successor. Without a token (reaper, candidate
    erasure) any active run is fenced: its next checkpoint raises
    ``SearchLeaseLost`` because the state is no longer ``running``.
    """
    conditions = [
        CandidateSearchRun.id == run_id,
        CandidateSearchRun.state.in_(ACTIVE_STATES),
    ]
    if token is not None:
        conditions.append(CandidateSearchRun.lease_token == token)
    failed = await db.execute(
        update(CandidateSearchRun)
        .where(*conditions)
        .values(
            state="failed",
            # Codes only (exception type or lifecycle reason), never provider
            # text or candidate data.
            error_code=(reason or "failed")[:100],
            completed_at=datetime.now(timezone.utc),
            lease_token=None,
            lease_expires_at=None,
        )
        .returning(CandidateSearchRun.id)
    )
    return failed.scalar_one_or_none() is not None


async def release_run(db, run_id: str, token: str) -> bool:
    """Expire our own lease now so a bounded retry does not wait for timeout."""
    released = await db.execute(
        update(CandidateSearchRun)
        .where(
            CandidateSearchRun.id == run_id,
            CandidateSearchRun.state == "running",
            CandidateSearchRun.lease_token == token,
        )
        .values(lease_expires_at=datetime.now(timezone.utc))
        .returning(CandidateSearchRun.id)
    )
    return released.scalar_one_or_none() is not None


async def reap_stalled_runs(db, *, stalled_after: timedelta) -> list[str]:
    """Fail claimed runs without progress; the caller commits.

    Every claim and checkpoint moves ``updated_at``, so a claimed run whose
    timestamp stands still past ``stalled_after`` with no live lease is not
    being worked on. Failing it frees the author's slot instead of leaving an
    eternal "running" search that the per-user cap keeps counting. Never-claimed
    ``queued`` runs are only waiting their turn in the single drain loop and
    are left alone.
    """
    now = datetime.now(timezone.utc)
    reaped = await db.execute(
        update(CandidateSearchRun)
        .where(
            CandidateSearchRun.state == "running",
            CandidateSearchRun.updated_at < now - stalled_after,
            or_(
                CandidateSearchRun.lease_expires_at.is_(None),
                CandidateSearchRun.lease_expires_at < now,
            ),
        )
        .values(
            state="failed",
            error_code="stalled",
            completed_at=now,
            lease_token=None,
            lease_expires_at=None,
        )
        .returning(CandidateSearchRun.id)
    )
    return list(reaped.scalars().all())


async def erase_candidate(db, candidate_id: int) -> dict:
    """Remove one candidate's snapshot rows from every run (RODO erasure).

    Finished runs simply lose the row. An active run cannot: ``finish_run``
    requires every snapshot ID to stay accounted for, so the run is failed
    first (the author restarts it) and then loses the row as well. Runs are
    locked before their rows, in the same order as ``save_batch``. The caller
    owns the transaction — the candidate delete commits it.
    """
    active_ids = list(
        (
            await db.scalars(
                select(CandidateSearchRun.id)
                .where(
                    CandidateSearchRun.state.in_(ACTIVE_STATES),
                    CandidateSearchRun.id.in_(
                        select(CandidateSearchResult.run_id).where(
                            CandidateSearchResult.candidate_id == candidate_id
                        )
                    ),
                )
                .order_by(CandidateSearchRun.id)
                .with_for_update()
            )
        ).all()
    )
    failed = 0
    for run_id in active_ids:
        failed += int(await fail_run(db, run_id, "candidate_erased"))
    removed = await db.execute(
        delete(CandidateSearchResult).where(
            CandidateSearchResult.candidate_id == candidate_id
        )
    )
    return {"search_rows_deleted": removed.rowcount or 0, "search_runs_failed": failed}


async def _locked_run(db, run_id: str, token: str):
    run = await db.scalar(
        select(CandidateSearchRun)
        .where(CandidateSearchRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        run is None
        or run.state != "running"
        or run.lease_token != token
        or run.lease_expires_at is None
        or run.lease_expires_at <= datetime.now(timezone.utc)
    ):
        raise SearchLeaseLost("Search run lease expired or was replaced")
    return run


async def pending_batch(
    db, run_id: str, *, limit: int = 256
) -> list[CandidateSnapshot]:
    if not 1 <= limit <= 1000:
        raise ValueError("Invalid batch size")
    rows = await db.execute(
        select(
            CandidateSearchResult.candidate_id, CandidateSearchResult.candidate_version
        )
        .where(
            CandidateSearchResult.run_id == run_id,
            CandidateSearchResult.state == "pending",
        )
        .order_by(CandidateSearchResult.candidate_id)
        .limit(limit)
    )
    return [CandidateSnapshot(cid, version) for cid, version in rows]


async def save_batch(
    db,
    run_id: str,
    token: str,
    batch: list[CandidateSnapshot],
    evaluations: list[CandidateEvaluation],
    *,
    error_code: str | None = None,
    metrics: dict | None = None,
):
    run = await _locked_run(db, run_id, token)
    expected = {item.candidate_id: item.version for item in batch}
    by_id = {item.candidate_id: item for item in evaluations}
    if (
        len(by_id) != len(evaluations)
        or by_id.keys() - expected.keys()
        or len(expected) != len(batch)
    ):
        raise ValueError("Duplicate or foreign evaluation ID")
    for cid, version in expected.items():
        value = by_id.get(cid)
        valid = value is not None and value.candidate_version == version
        fields = {
            "state": "evaluated" if valid else "failed",
            "eligible": value.eligible if valid else None,
            "fit_score": value.fit_score if valid else None,
            "measurement": value.measurement if valid else "stale",
            "evidence": value.evidence if valid else None,
            "exclusion_reasons": list(value.exclusion_reasons) if valid else [],
        }
        await db.execute(
            update(CandidateSearchResult)
            .where(
                CandidateSearchResult.run_id == run_id,
                CandidateSearchResult.candidate_id == cid,
                CandidateSearchResult.candidate_version == version,
                CandidateSearchResult.state == "pending",
            )
            .values(**fields)
        )
    run.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=120)
    if error_code:
        run.error_code = error_code[:100]
    if metrics is not None:
        run.metrics = _with_lifecycle(run.metrics, metrics)
    await db.flush()


async def save_metrics(db, run_id: str, token: str, metrics: dict):
    run = await _locked_run(db, run_id, token)
    run.metrics = _with_lifecycle(run.metrics, metrics)
    run.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=300)
    await db.flush()


EXCLUSION_CATEGORIES = (
    "over_budget",
    "missing_must",
    "office_days_exceeded",
    "office_city_mismatch",
    "remote_only",
    "eligibility_hidden",
)


async def run_counts(db, run_id: str) -> dict:
    row = (
        (
            await db.execute(
                select(
                    *[
                        func.count()
                        .filter(
                            CandidateSearchResult.eligible.is_(False),
                            CandidateSearchResult.exclusion_reasons[0].astext == reason,
                        )
                        .label(f"excluded_{reason}")
                        for reason in EXCLUSION_CATEGORIES
                    ],
                    func.count().label("population"),
                    func.count()
                    .filter(CandidateSearchResult.state == "pending")
                    .label("pending"),
                    func.count()
                    .filter(CandidateSearchResult.state == "failed")
                    .label("failed"),
                    func.count()
                    .filter(CandidateSearchResult.state == "evaluated")
                    .label("evaluated"),
                    func.count()
                    .filter(CandidateSearchResult.eligible.is_(True))
                    .label("eligible"),
                    func.count()
                    .filter(
                        CandidateSearchResult.eligible.is_(True),
                        CandidateSearchResult.fit_score >= 75,
                    )
                    .label("strong"),
                    func.count()
                    .filter(CandidateSearchResult.eligible.is_(False))
                    .label("excluded"),
                    func.count()
                    .filter(
                        CandidateSearchResult.eligible.is_(True),
                        CandidateSearchResult.measurement != "measured",
                    )
                    .label("needs_verification"),
                ).where(CandidateSearchResult.run_id == run_id)
            )
        )
        .mappings()
        .one()
    )
    counts = dict(row)
    reasons = {
        reason: counts.pop(f"excluded_{reason}") for reason in EXCLUSION_CATEGORIES
    }
    reasons["unknown"] = counts["excluded"] - sum(reasons.values())
    counts["exclusion_reasons"] = reasons
    return counts


async def finish_run(db, run_id: str, token: str):
    run = await _locked_run(db, run_id, token)
    counts = await run_counts(db, run_id)
    if counts["pending"] or counts["population"] != run.population_size:
        raise ValueError("Cannot finalize a run with unaccounted population")
    run.state = (
        "partial" if counts["failed"] or counts["needs_verification"] else "complete"
    )
    run.completed_at = datetime.now(timezone.utc)
    run.metrics = {
        **(run.metrics or {}),
        "elapsed_ms": max(
            0.0, (run.completed_at - run.created_at).total_seconds() * 1000
        ),
    }
    run.lease_token = None
    run.lease_expires_at = None
    await db.flush()
    return counts


async def owned_run(db, run_id: str, actor_id: int):
    """No cross-user reuse/access; resource authorization is also rechecked by API."""
    return await db.scalar(
        select(CandidateSearchRun).where(
            CandidateSearchRun.id == run_id,
            CandidateSearchRun.created_by == actor_id,
        )
    )


async def shared_auto_run(db, run_id: str):
    """Automatyczny przegląd ZAPISANEJ rekrutacji — bez względu na „autora".

    Cudzy RĘCZNY przegląd zostaje prywatny (`owned_run`). Przegląd automatyczny
    nie ma właściciela w sensie produktu: dostęp do niego rozstrzyga bramka
    rekrutacji, którą API sprawdza tuż po tym odczycie.
    """
    return await db.scalar(
        select(CandidateSearchRun).where(
            CandidateSearchRun.id == run_id,
            CandidateSearchRun.job_id.is_not(None),
            auto_origin_clause(),
        )
    )


async def result_page(
    db,
    run_id: str,
    *,
    offset: int = 0,
    limit: int = 20,
    min_score: float = 0,
    filters=None,
):
    if offset < 0 or not 1 <= limit <= 100 or not 0 <= min_score <= 100:
        raise ValueError("Invalid page")
    conditions = (
        CandidateSearchResult.run_id == run_id,
        CandidateSearchResult.state == "evaluated",
        CandidateSearchResult.eligible.is_(True),
        or_(
            CandidateSearchResult.fit_score.is_(None),
            CandidateSearchResult.fit_score >= min_score,
        ),
    )
    if filters is not None:
        conditions = (*conditions, *filters.conditions())
    total = await db.scalar(
        select(func.count()).select_from(CandidateSearchResult).where(*conditions)
    )
    rows = (
        (
            await db.execute(
                select(CandidateSearchResult)
                .where(*conditions)
                .order_by(
                    CandidateSearchResult.fit_score.desc().nulls_last(),
                    CandidateSearchResult.candidate_id,
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return rows, total


async def population_changed(db, run_id: str) -> bool:
    """Invalidate a frozen ranking after any member changes or membership shifts."""
    from sqlalchemy import DateTime, and_, cast, exists
    from app.models.candidate import Candidate

    changed = exists(
        select(CandidateSearchResult.candidate_id)
        .outerjoin(
            Candidate,
            Candidate.id == CandidateSearchResult.candidate_id,
        )
        .where(
            CandidateSearchResult.run_id == run_id,
            or_(
                Candidate.id.is_(None),
                Candidate.updated_at
                != cast(
                    CandidateSearchResult.candidate_version, DateTime(timezone=True)
                ),
            ),
        )
    )
    added = exists(
        select(Candidate.id)
        .outerjoin(
            CandidateSearchResult,
            and_(
                CandidateSearchResult.candidate_id == Candidate.id,
                CandidateSearchResult.run_id == run_id,
            ),
        )
        .where(CandidateSearchResult.candidate_id.is_(None))
    )
    return bool(await db.scalar(select(or_(changed, added))))
