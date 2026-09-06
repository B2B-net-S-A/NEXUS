"""Background task: compute + persist AI candidate proposals for a job.

Triggered via FastAPI `BackgroundTasks` from `POST /api/jobs` and from
`POST /api/jobs/{id}/proposals/regenerate`. Writes a `ProposalSnapshot` row
that the frontend polls while `status="pending"`.

The task opens its own DB session via `AsyncSessionLocal` because
`Depends(get_db)` is already closed by the time FastAPI fires background tasks.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.job import Job
from app.models.proposal_snapshot import (
    ProposalSnapshot,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_READY,
)
from app.models.recruitment_pipeline import CandidateStage
from app.services.canonical_text import build_job_query_variants
from app.services.retrieval_pool import retrieve_candidate_pool

logger = logging.getLogger(__name__)


async def create_pending_snapshot(
    job_id: int,
    *,
    top_k: int = settings.MATCH_MAX_RESULTS,
    source: str = "create",
    created_by: Optional[int] = None,
    profile_id: int = 0,
) -> int:
    """Insert a pending snapshot row and return its id.

    Called synchronously from the request handler so the frontend can start
    polling immediately (even before the heavier scoring pass finishes).
    """
    async with AsyncSessionLocal() as session:
        snap = ProposalSnapshot(
            job_id=job_id,
            source=source,
            status=STATUS_PENDING,
            top_k=top_k,
            profile_id=profile_id,
            created_by=created_by,
            run_id=uuid.uuid4().hex,
        )
        session.add(snap)
        await session.commit()
        await session.refresh(snap)
        return snap.id


async def compute_proposal_for_job(
    snapshot_id: int,
    job_id: int,
    *,
    top_k: int = settings.MATCH_MAX_RESULTS,
) -> None:
    """Populate snapshot `snapshot_id` with top-K scored candidates.

    Never raises — any failure is recorded on the snapshot row as
    status="failed" + error_message so the frontend can display it cleanly.
    """
    # Lazy imports keep module import cheap and avoid circular deps with the
    # scoring stack (which imports models at init time).
    from app.services.embedding_service import (
        _build_job_text,
        embed_job,
    )
    from app.services.match_score_cache import bulk_get_or_compute
    from app.services.scoring_service import (
        DEFAULT_PROFILE,
        WeightProfile,
        resolve_active_profile,
    )

    async with AsyncSessionLocal() as session:
        snap = await session.scalar(
            select(ProposalSnapshot).where(ProposalSnapshot.id == snapshot_id)
        )
        if snap is None:
            logger.warning(
                "[Proposals] snapshot %s missing — cannot compute", snapshot_id
            )
            return

        try:
            job = await session.scalar(select(Job).where(Job.id == job_id))
            if job is None:
                raise RuntimeError(f"job {job_id} not found")

            # Make sure the job has a semantic embedding before we rank, so the
            # semantic layer isn't just zeros for a freshly-created job.
            #
            # Pusta kolumna NIE znaczy "brak wektora": `embed_job` upsertuje do
            # Qdranta PRZED commitem stempla, więc padnięty commit zostawia
            # wektor i pustą kolumnę. Ślepe `embed_job` płaciło wtedy Voyage'owi
            # za wektor, który już istnieje. `job_has_vector` odpowiada z kolumny
            # (0 ms), a gdy ta mówi "nie ma" — pyta Qdranta i sam naprawia stempel.
            try:
                from app.services.embedding_service import job_has_vector

                if await job_has_vector(job.id, job.embedding_id) is not True:
                    await embed_job(job_id, session)
                    # `refresh` POD warunkiem: to dodatkowy SELECT, a przy pełnej
                    # kolumnie nie ma czego odświeżać. Poza warunkiem płaciłby
                    # go KAŻDY przebieg liczenia propozycji.
                    await session.refresh(job)
            except Exception as e:  # pragma: no cover — best-effort
                logger.warning(
                    "[Proposals] embed_job(%s) failed, continuing without "
                    "semantic layer: %s",
                    job_id,
                    e,
                )

            profile: WeightProfile = DEFAULT_PROFILE
            if snap.profile_id and snap.profile_id > 0:
                from app.models.scoring_weight_profile import ScoringWeightProfile

                row = await session.scalar(
                    select(ScoringWeightProfile).where(
                        ScoringWeightProfile.id == snap.profile_id
                    )
                )
                if row:
                    profile = WeightProfile.from_record(row)
            else:
                profile = await resolve_active_profile(
                    session, user_id=snap.created_by, client_id=job.client_id
                )

            query_text = _build_job_text(job)
            # P0-B: fingerprint the matching inputs (brief + Champion narrative,
            # folded into _build_job_text) so a later brief/Champion edit that
            # changes them can be detected and this snapshot marked stale.
            input_fingerprint = hashlib.sha256(query_text.encode("utf-8")).hexdigest()

            # Mirror recommendations.py: pull a wider pool, then re-rank.
            # Pool size is independent of `top_k` on purpose. The old `top_k * 4`
            # heuristic tied "how many we retrieve" to "how many we show", so a request
            # for the top 20 retrieved 80 and capped its own recall ceiling at ~4%
            # (measured 2026-08-10: ceiling is 1.8% at pool 20, 13.6% at 200, 32.6% at
            # 1000). `top_k` still caps what comes back — it just no longer decides what
            # scoring is allowed to see.
            pool_size = settings.MATCH_POOL_SIZE
            # C12: noga BM25 dostaje TERMINY, nie `query_text`. Dokument
            # w roli tsquery ANDuje setki leksemów, czyli zwraca zero zawsze —
            # cicho, bo fuzja RRF z pustą listą wygląda jak porządek wektora.
            from app.services.hybrid_search import build_job_bm25_query

            hits = await retrieve_candidate_pool(
                session,
                query_text,
                top_k=pool_size,
                query_variants=build_job_query_variants(job, query_text),
                bm25_query=build_job_bm25_query(job),
            )
            similarity_map = {h["candidate_id"]: h["score"] for h in hits}
            candidate_ids = list(similarity_map.keys())

            # Degraded retrieval (Qdrant down/empty) — mirror recommendations:
            # composites liczone z neutralnym semantic NIE mogą trafić do
            # wspólnego score cache jako świeże (M3-CACHE-01).
            #
            # Pustka nie jest jedynym kształtem degradacji: fasada puli oznacza
            # `semantic_unknown` wiersze, dla których kosinusu NIE zmierzono
            # (padła dosypka po udanym BM25 albo kandydat nie ma wektora).
            # `score` wynosi tam 0.0, ale to „nie wiem", nie „zmierzono zero" —
            # a taka pula JEST niepusta, więc sam `not candidate_ids` wpuszczał
            # warstwę semantyczną 0/60 do wspólnego cache'u jako wynik świeży.
            semantic_unknown_ids = {
                h["candidate_id"] for h in hits if h.get("semantic_unknown")
            }
            semantic_degraded = not candidate_ids or bool(semantic_unknown_ids)
            for cid in semantic_unknown_ids:
                similarity_map.pop(cid, None)

            # Fallback when Qdrant is empty / job not indexed yet.
            if not candidate_ids:
                fallback = await session.execute(
                    select(Candidate.id)
                    .where(Candidate.status != CandidateStatus.blacklisted)
                    .limit(settings.MATCH_POOL_SIZE)
                )
                candidate_ids = [c for (c,) in fallback.all()]

            # Exclude candidates already in this job's pipeline — they aren't
            # "proposals" anymore; they're already being worked.
            if candidate_ids:
                in_pipeline = await session.execute(
                    select(CandidateStage.candidate_id)
                    .where(
                        CandidateStage.job_id == job_id,
                        CandidateStage.candidate_id.in_(candidate_ids),
                    )
                    .distinct()
                )
                already = {cid for (cid,) in in_pipeline.all()}
                candidate_ids = [cid for cid in candidate_ids if cid not in already]

            # Post-0237 snapshot ZAWSZE niesie liczniki (choćby zerowe) —
            # NULL zostaje jednoznacznym znacznikiem „sprzed 0237 /
            # nieprzefiltrowany", także gdy retrieval zwrócił pustą pulę
            # i dealbreakery nie miały na czym pracować (review #1207).
            from app.services.dealbreaker_filters import (
                DealbreakerResult,
                apply_dealbreakers,
                resolve_job_budget_hourly,
            )

            snap.hidden = DealbreakerResult().hidden_meta()
            breakdowns: list = []
            if candidate_ids:
                cand_res = await session.execute(
                    select(Candidate).where(Candidate.id.in_(candidate_ids))
                )
                candidates = list(cand_res.scalars().all())

                # P0-A: hard eligibility prefilter — the handoff snapshot IS the
                # recruiter's operational ranking, so a blacklisted /
                # hard-conflict / hiring-manager-vetoed candidate must never land
                # in it. Mirrors the live /recommendations path exactly; soft
                # warnings (current employment, candidate-excluded) stay.
                from app.services.pipeline_eligibility import (
                    filter_eligible_candidates,
                )

                candidates = await filter_eligible_candidates(
                    session,
                    job=job,
                    candidates=candidates,
                    now=datetime.now(timezone.utc),
                )

                # Twardy sufit budżetu Z AUTOMATU (decyzja produktowa 19.08):
                # snapshot jest DOMYŚLNYM widokiem rekrutera, więc znany budżet
                # oferty musi ukrywać znane stawki powyżej także tutaj — nie
                # tylko na żywej ścieżce /recommendations. Liczniki idą do
                # `snap.hidden`, bo ukrywanie nigdy nie jest ciche; remote_only
                # zostaje opt-in per wyszukiwanie (snapshot nie niesie tej
                # deklaracji rekrutera).
                dealbreakers = apply_dealbreakers(
                    candidates,
                    budget_hourly=resolve_job_budget_hourly(job),
                )
                candidates = dealbreakers.kept
                snap.hidden = dealbreakers.hidden_meta()

                if candidates:
                    breakdowns = await bulk_get_or_compute(
                        job,
                        candidates,
                        session,
                        similarity_map=similarity_map,
                        profile=profile,
                        allow_cache_write=not semantic_degraded,
                        # Patrz `/recommendations`: „pomiar niedostępny" zamiast
                        # zarzutu wobec profilu kandydata (#414).
                        semantic_unavailable_ids=semantic_unknown_ids,
                    )
                    # Boost historyczny — TA SAMA składowa, którą /recommendations
                    # dokłada PRZED odcięciem po min-score. Snapshot jej nie
                    # stosował, więc domyślny widok „Sugerowani kandydaci"
                    # (widget startuje w trybie snapshot) był rankowany słabszym
                    # wzorem niż każdy widok z filtrem, który przełącza się na
                    # żywy endpoint: kandydat ze score 28, sprawdzony już na
                    # trzech semantycznie podobnych projektach, dobija na żywo
                    # do 43 i przechodzi próg 40 — a w snapshocie po prostu go
                    # nie było. Sygnał „pierwszy ogień" to dokładnie ten, który
                    # rekruter chce zobaczyć najwyżej.
                    #
                    # Kolejność jest istotna: `bulk_get_or_compute` zapisał już
                    # cache W ŚRODKU, więc boost dołożony TUTAJ nie trafia do
                    # utrwalonych wierszy score'ów (recommendations.py trzyma go
                    # poza cache'em z tego samego powodu — stan pipeline'u zmienia
                    # się za często, żeby dało się to rzetelnie unieważniać).
                    #
                    # `_apply_historical_boost` mieszka w routerze; import jest
                    # leniwy i celowy — kopia tej pętli byłaby CZWARTĄ
                    # implementacją tego samego wzoru (router, harness ewaluacyjny
                    # i tutaj), a rozjazd między nimi jest właśnie tym defektem,
                    # który to zamyka.
                    from app.api.recommendations import _apply_historical_boost
                    from app.services.similar_job_candidates import (
                        fetch_historical_boost_map,
                    )

                    try:
                        boost_map = await fetch_historical_boost_map(session, job_id)
                    except Exception as boost_exc:  # pragma: no cover — best-effort
                        logger.warning(
                            "[Proposals] historical_boost lookup failed for job=%s: %s",
                            job_id,
                            boost_exc,
                        )
                        boost_map = {}
                    _apply_historical_boost(breakdowns, boost_map)

                    # Persist ALL candidates that fit (score >= threshold),
                    # ranked best-first — not a fixed top-K. `top_k` is now just
                    # a payload safety cap. Mirrors the live /recommendations
                    # endpoint so the snapshot and fallback paths agree on
                    # "who matches".
                    breakdowns = [
                        b
                        for b in breakdowns
                        if b.total >= settings.RECOMMENDATION_MIN_SCORE
                    ][:top_k]

            snap.status = STATUS_READY
            snap.candidate_ids = [b.candidate_id for b in breakdowns]
            snap.breakdowns = [b.as_dict() for b in breakdowns]
            # P0-A: record whether the semantic leg was degraded (Qdrant/Voyage
            # down or the job unindexed) so the UI can flag this ranking as a
            # fallback instead of a healthy one. Previously computed only to gate
            # cache writes, then discarded.
            snap.degraded = semantic_degraded
            # P0-B: a fresh compute is current by definition; record the revision
            # it was scored against and clear any stale flag.
            snap.input_fingerprint = input_fingerprint
            snap.stale = False
            snap.error_message = None
            await session.commit()
            logger.info(
                "[Proposals] snapshot %s ready — %d candidates for job %s",
                snapshot_id,
                len(breakdowns),
                job_id,
            )
        except Exception as e:  # pragma: no cover
            logger.exception(
                "[Proposals] snapshot %s failed for job %s: %s",
                snapshot_id,
                job_id,
                e,
            )
            snap.status = STATUS_FAILED
            snap.error_message = str(e)[:500]
            try:
                await session.commit()
            except Exception as commit_err:
                logger.warning(
                    "[Proposals] failed to persist failure state: %s", commit_err
                )
                await session.rollback()
