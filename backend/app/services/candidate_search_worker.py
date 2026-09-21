"""Durable exhaustive search execution shared by saved and ad-hoc requests."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.database import AsyncSessionLocal
from app.models.candidate_search_run import CandidateSearchRun
from app.models.notification import Notification, NotificationType
from app.services import candidate_search_store as store
from app.services.full_candidate_scan import CandidateEvaluation, load_snapshot_batch
from app.services.full_search_measurement import measure_candidates, request_vector
from app.services.notification_access import notification_recipient_has_access
from app.services.request_matching_context import RequestMatchingContext
from app.services.search_telemetry import SearchTelemetry, stage

logger = logging.getLogger(__name__)

# Leave time to roll back and persist an explicit incomplete result before
# the 300s query lease / 120s batch lease expires. These are execution bounds,
# not a promise of provider latency or a complete ranking after a timeout.
QUERY_TIMEOUT_SECONDS = 240
BATCH_TIMEOUT_SECONDS = 90
# A claim is an attempt even when the worker dies before its first checkpoint.
# A REPORTED failure is terminal from the third claim on. A claim that never
# reported back means the process died mid-run — at NEXUS that is usually a
# deploy (Coolify restarts the container on every push to main, often several
# times an hour), not a broken run — so unreported claims get a wider budget.
MAX_FAILED_ATTEMPTS = 3
MAX_CLAIMS = 8
# Hand the event loop back while a batch is scored in-process, so HTTP
# requests served by the same process are not starved by one long scan.
YIELD_EVERY = 32


async def _notify_search_finished(
    db, run_id: str, *, eligible: int | None, failed: bool
) -> None:
    """Bell entry for the author when a full search ends (17.09.2026).

    Runs in the caller's session BEFORE its commit, inside a savepoint: the
    notification commits together with the run's terminal state, so the state
    transition (``finish_run`` / a ``fail_run`` that returned ``True``) is what
    makes it exactly-once. Never blocks finishing the run — any error only
    drops the entry.
    """
    try:
        async with db.begin_nested():
            run = await db.get(CandidateSearchRun, run_id)
            if run is None or run.created_by is None:
                return
            if store.is_auto_run(run):
                # Nocny automat: „autor" niczego nie uruchamiał. O wyniku mówi
                # skrzynka „Propozycje" i zakładka „Praca w tle", nie dzwonek.
                return
            link = f"/jobs/{run.job_id}?tab=similar" if run.job_id else "/talent-radar"
            ntype = NotificationType.candidate_search_completed
            if not await notification_recipient_has_access(
                db,
                run.created_by,
                ntype,
                related_entity_type="candidate_search_run",
                link=link,
            ):
                return
            db.add(
                Notification(
                    user_id=run.created_by,
                    notification_type=ntype,
                    title=(
                        "Przegląd bazy nie powiódł się"
                        if failed
                        else "Przegląd bazy zakończony"
                    ),
                    message=(
                        "Uruchom go ponownie."
                        if failed
                        else f"{eligible} kandydatów w wynikach"
                    ),
                    link=link,
                    related_entity_type="candidate_search_run",
                    # The run id is a UUID; the column is an integer.
                    related_entity_id=None,
                )
            )
    except Exception as exc:  # noqa: BLE001 — never blocks finishing the run
        logger.warning(
            "search-finished notification skipped run=%s: %s",
            run_id,
            type(exc).__name__,
        )


def _is_transient(exc: BaseException) -> bool:
    """Infrastructure hiccups heal on their own; retry them at lease expiry."""
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True
    return isinstance(
        exc,
        (
            OperationalError,
            InterfaceError,
            PoolTimeoutError,
            ConnectionError,
            TimeoutError,
            OSError,
        ),
    )


async def evaluate_batch(db, request: RequestMatchingContext, batch, vector):
    # Reuse the established visibility policy, including visible assignment
    # blocks and the invariant that global blacklist remains hidden.
    from app.api.matching import _gate_and_dealbreakers
    from app.services.dealbreaker_filters import rate_fit_status
    from app.services.location_utils import location_tokens
    from app.services.requirement_contract import (
        requirements_for_job,
        evaluate_requirements,
        search_dealbreaker_inputs,
    )
    from app.services.canonical_fit import score_pair

    with stage("sql_load"):
        candidates = await load_snapshot_batch(db, batch)
    target = request.as_job()
    criteria = requirements_for_job(target)
    inputs = search_dealbreaker_inputs(target)
    exclusion_reasons = {}
    with stage("eligibility"):
        kept, annotations, _, _, _ = await _gate_and_dealbreakers(
            db,
            job=target,
            ordered=list(candidates.values()),
            now=datetime.now(timezone.utc),
            inputs=inputs,
            exclusion_reasons=exclusion_reasons,
        )
    visible = {candidate.id for candidate in kept}
    with stage("retrieval") as outcome:
        measurements = await measure_candidates(vector, kept)
        outcome["failed"] = any(
            m.status == "unavailable" for m in measurements.values()
        )
    versions = {item.candidate_id: item.version for item in batch}
    results = []
    for index, (cid, candidate) in enumerate(candidates.items()):
        if index and index % YIELD_EVERY == 0:
            await asyncio.sleep(0)
        if cid not in visible:
            results.append(
                CandidateEvaluation(
                    cid,
                    versions[cid],
                    False,
                    None,
                    "unavailable",
                    exclusion_reasons=(
                        exclusion_reasons.get(cid, "eligibility_or_filter"),
                    ),
                )
            )
            continue
        measurement = measurements[cid]
        fit = await score_pair(db, request, candidate, measurement)
        breakdown = fit.breakdown
        requirements = evaluate_requirements(criteria, candidate, job_id=target.id)
        results.append(
            CandidateEvaluation(
                cid,
                versions[cid],
                True,
                fit.fit_score,
                measurement.status,
                evidence={
                    "breakdown": breakdown.as_dict(),
                    "requirements": requirements,
                    "filters": {
                        "skills": [
                            " lub ".join(r["any_of"]).lower()
                            for r in requirements
                            if r["status"] == "met"
                        ],
                        "rate": rate_fit_status(candidate, inputs),
                        "locations": sorted(location_tokens(candidate.location)),
                    },
                    "eligibility": annotations.get(cid),
                    "brief_status": request.brief_status,
                },
            )
        )
    return results


async def execute_run(run_id: str):
    """Claim or resume pending IDs; committed batches survive process restarts.

    A scheduler/API trigger can safely call this again after lease expiry.
    It cannot race an active worker, or overwrite a replacement worker's rows.
    Every claim is counted durably; a run that keeps failing becomes ``failed``
    instead of being re-claimed forever.
    """
    async with AsyncSessionLocal() as db:
        token = await store.claim_run(db, run_id, lease_seconds=300)
        await db.commit()
        if token is None:
            return
    try:
        await _execute_claimed(run_id, token)
    except store.SearchLeaseLost:
        # Failed by erasure/reaper or replaced after lease expiry: the current
        # owner (or nobody) decides the outcome, never this stale worker.
        return
    except Exception as exc:
        if _is_transient(exc):
            raise  # the lease expires and a later claim resumes the run
        await _record_failure(run_id, token, exc)


async def _record_failure(run_id: str, token: str, exc: BaseException) -> None:
    code = type(exc).__name__
    async with AsyncSessionLocal() as db:
        run = await db.get(CandidateSearchRun, run_id)
        claims = store.claim_count(run.metrics if run is not None else None)
        if claims >= MAX_FAILED_ATTEMPTS:
            if await store.fail_run(db, run_id, code, token=token):
                logger.warning(
                    "Candidate search %s failed after %s attempts: %s",
                    run_id,
                    claims,
                    code,
                )
                await _notify_search_finished(db, run_id, eligible=None, failed=True)
        else:
            # Retry soon with a fresh claim; the counter bounds the retries.
            await store.release_run(db, run_id, token)
        await db.commit()


async def _execute_claimed(run_id: str, token: str):
    async with AsyncSessionLocal() as db:
        run = await db.get(CandidateSearchRun, run_id)
        if store.claim_count(run.metrics) > MAX_CLAIMS:
            # Earlier attempts died without reporting (e.g. process crash).
            if await store.fail_run(db, run_id, "attempts_exhausted", token=token):
                await _notify_search_finished(db, run_id, eligible=None, failed=True)
            await db.commit()
            return
        request = RequestMatchingContext(**run.request_context)
        telemetry = SearchTelemetry(store.telemetry_metrics(run.metrics) or None)
        telemetry.begin_attempt()
        await store.save_metrics(db, run_id, token, telemetry.snapshot())
        await db.commit()
    with telemetry.activate(), stage("query_embedding") as outcome:
        try:
            async with asyncio.timeout(QUERY_TIMEOUT_SECONDS):
                vector = await request_vector(request.query_text)
            outcome["failed"] = vector is None
        except Exception:
            # Account for the population as unknown instead of retrying a
            # permanently invalid query forever at each lease expiry.
            outcome["failed"] = True
            vector = None
    async with AsyncSessionLocal() as db:
        await store.save_metrics(db, run_id, token, telemetry.snapshot())
        await db.commit()
    while True:
        async with AsyncSessionLocal() as db:
            batch = await store.pending_batch(db, run_id)
            if not batch:
                counts = await store.finish_run(db, run_id, token)
                await _notify_search_finished(
                    db, run_id, eligible=counts["eligible"], failed=False
                )
                # Przegląd automatyczny: top-K → skrzynka „Propozycje", w tej
                # samej transakcji co stan końcowy (savepoint, nigdy nie rzuca).
                from app.services.auto_full_review import publish_on_finish

                await publish_on_finish(db, run_id, eligible=counts["eligible"])
                await db.commit()
                return
            error_code = None
            try:
                with telemetry.activate(), stage("batch"):
                    async with asyncio.timeout(BATCH_TIMEOUT_SECONDS):
                        evaluations = await evaluate_batch(db, request, batch, vector)
            except Exception as exc:
                # Do not persist provider text or candidate data in errors.
                await db.rollback()
                evaluations = []
                error_code = type(exc).__name__
            await store.save_batch(
                db,
                run_id,
                token,
                batch,
                evaluations,
                error_code=error_code,
                metrics=telemetry.snapshot(),
            )
            await db.commit()
        await asyncio.sleep(0)  # yield between bounded CPU/SQL batches
