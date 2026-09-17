"""Shared eligibility gate for pipeline stage-writing ingress (P1-PIPE-01).

Every stage-writing ingress — single assign, bulk-add, shortlist promote,
LinkedIn quick-assign, ``POST /api/pipeline/move`` and ``/bulk-move`` — asks
the same pure :func:`evaluate_eligibility` and rejects a hard-blocked candidate
**identically** (HTTP 409, Polish reason from ``_REASON_LABELS_PL``). This
module only does the I/O: candidate status, active client conflicts,
candidate-declared excluded clients, current employment derived from live
contracts and hiring-manager verdicts.

Scope notes:

* Hard blocks are the global blacklist and (on moves that put a candidate back
  in front of the client) a standing hiring-manager rejection. Client
  conflicts — blacklist / NDA / competitor — are **soft warnings since
  17.09.2026**, like current employment and candidate-excluded clients: they
  never block, they surface as badges and bulk-add warnings.
* ``already_in_job`` is a *dedup* concern for **assignment**, not a move: a
  move presupposes the candidate is in the job, so it defaults to ``False``;
  bulk-add passes its own set via ``already_in_job_ids``.
* Terminal **removal** moves (``rejected`` / ``withdrawn``) must stay allowed
  so a blacklisted candidate can always be closed OUT of a pipeline — the
  caller decides not to invoke the gate for those (see ``api/pipeline.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import AbstractSet, Mapping, Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.core.scheduling import business_today
from app.models.candidate_conflict import CandidateConflict
from app.models.job import Job
from app.services.candidate_job_eligibility import (
    ConflictInput,
    EligibilityDecision,
    EligibilityInput,
    EligibilityReason,
    evaluate_eligibility,
    extract_excluded_client_ids,
)
from app.services.current_employment import current_employment_client_ids
from app.services.eligibility_annotation import eligibility_annotation
from app.services.hiring_manager_verdicts import ManagerVerdict, load_manager_rejections


async def evaluate_candidates_for_job(
    db: AsyncSession,
    *,
    job: Job,
    candidate_ids: Sequence[int],
    now: datetime,
    enforce_manager_verdict: bool = True,
) -> dict[int, EligibilityDecision]:
    """Batch-load eligibility inputs and evaluate each candidate for ``job``.

    Thin wrapper over :func:`evaluate_candidates_for_job_with_verdicts` for
    callers that only need the decisions.
    """
    decisions, _ = await evaluate_candidates_for_job_with_verdicts(
        db,
        job=job,
        candidate_ids=candidate_ids,
        now=now,
        enforce_manager_verdict=enforce_manager_verdict,
    )
    return decisions


async def evaluate_candidates_for_job_with_verdicts(
    db: AsyncSession,
    *,
    job: Job,
    candidate_ids: Sequence[int],
    now: datetime,
    enforce_manager_verdict: bool = True,
    already_in_job_ids: Optional[AbstractSet[int]] = None,
    candidates: Optional[Mapping[int, Candidate]] = None,
) -> tuple[dict[int, EligibilityDecision], dict[int, ManagerVerdict]]:
    """Evaluate eligibility and return the hiring-manager verdicts alongside.

    Pure policy stays in :func:`evaluate_eligibility`; this only performs the
    batched reads (candidates, active client conflicts, manager verdicts).
    Candidates that do not exist are simply absent from the result — the caller
    decides how to treat a missing candidate (``/move`` leaves it to the DB FK;
    ``/bulk-move`` validates existence separately). ``already_in_job`` defaults
    to ``False`` (a move presupposes being in the job); bulk-add passes its own
    set via ``already_in_job_ids`` and its ``FOR UPDATE`` rows via
    ``candidates`` so no second candidate SELECT happens under its lock.

    Current employment at the job's client is read from live contracts
    (``services/current_employment.py``) on top of manual
    ``current_employment`` conflict rows.

    The verdict map is returned separately because the decision carries only the
    reason code; the details (who rejected, when, why) belong in the 409 message
    and in the badge, not in the policy's shape.

    ``enforce_manager_verdict=False`` skips the veto read entirely. Move
    endpoints use it for transitions that are not "put this person in front of
    the manager again" — see ``api/pipeline.py``.
    """
    ids = list(dict.fromkeys(candidate_ids))
    if not ids:
        return {}, {}

    if candidates is None:
        cand_rows = (
            (await db.execute(select(Candidate).where(Candidate.id.in_(ids))))
            .scalars()
            .all()
        )
        candidates_by_id: dict[int, Candidate] = {c.id: c for c in cand_rows}
    else:
        candidates_by_id = dict(candidates)

    conflicts_by_candidate: dict[int, list[ConflictInput]] = {}
    if job.client_id is not None:
        # Wyłącznie kolumny potrzebne polityce — nie cała encja. Gorąca ścieżka
        # (każdy ruch, bulk-add, ranking) nie może zależeć od kolumn audytu
        # dołożonych w 0321: na prodzie wprowadza je safety-net entrypointu
        # z lock_timeout, a pominięty ALTER dawałby 500 na każdym ruchu.
        conflict_rows = (
            await db.execute(
                select(
                    CandidateConflict.candidate_id,
                    CandidateConflict.client_id,
                    CandidateConflict.type,
                    CandidateConflict.active,
                    CandidateConflict.expires_at,
                ).where(
                    CandidateConflict.candidate_id.in_(ids),
                    CandidateConflict.client_id == job.client_id,
                    CandidateConflict.active.is_(True),
                )
            )
        ).all()
        for row in conflict_rows:
            conflicts_by_candidate.setdefault(row.candidate_id, []).append(
                ConflictInput(
                    type=row.type.value,
                    client_id=row.client_id,
                    active=row.active,
                    expires_at=row.expires_at,
                )
            )
        derived = await current_employment_client_ids(
            db, ids, client_id=job.client_id, today=business_today()
        )
        for cid, client_ids in derived.items():
            for employer_id in client_ids:
                conflicts_by_candidate.setdefault(cid, []).append(
                    ConflictInput(type="current_employment", client_id=employer_id)
                )

    in_job = already_in_job_ids or frozenset()
    verdicts: dict[int, ManagerVerdict] = {}
    if enforce_manager_verdict:
        verdicts = await load_manager_rejections(db, job=job, candidate_ids=ids)

    decisions: dict[int, EligibilityDecision] = {}
    for cid in ids:
        candidate = candidates_by_id.get(cid)
        if candidate is None:
            continue
        decisions[cid] = evaluate_eligibility(
            EligibilityInput(
                candidate_status=candidate.status.value,
                job_client_id=job.client_id,
                conflicts=tuple(conflicts_by_candidate.get(cid, ())),
                excluded_client_ids=extract_excluded_client_ids(candidate.preferences),
                already_in_job=cid in in_job,
                rejected_by_hiring_manager=cid in verdicts,
            ),
            now,
        )
    return decisions, verdicts


async def partition_eligible_candidates(
    db: AsyncSession,
    *,
    job: Job,
    candidates: Sequence[Candidate],
    now: datetime,
    enforce_manager_verdict: bool = True,
) -> tuple[list[Candidate], dict[int, dict]]:
    """Drop hard-blocked candidates from a ranking pool and annotate the rest.

    Dropped: ``assignment_allowed is False`` — global blacklist or a standing
    hiring-manager veto — so "recommended ⟹ assignable" holds. Client conflicts
    (blacklist / NDA / competitor), current employment and candidate-excluded
    clients stay in the pool; their badges come back in the annotation map
    (``services/eligibility_annotation.py``) so the surface can render them
    without a second round of queries.

    A candidate absent from the decision map (e.g. deleted mid-request) is kept
    unannotated: a lookup miss must not silently hide a real row, and the
    assign-time gate still guards any downstream write. ``already_in_job`` is
    left ``False`` — callers exclude in-pipeline candidates separately.
    """
    if not candidates:
        return list(candidates), {}
    decisions = await evaluate_candidates_for_job(
        db,
        job=job,
        candidate_ids=[c.id for c in candidates],
        now=now,
        enforce_manager_verdict=enforce_manager_verdict,
    )
    kept = [
        c
        for c in candidates
        if (decisions.get(c.id) is None or decisions[c.id].assignment_allowed)
    ]
    annotations: dict[int, dict] = {}
    for c in kept:
        ann = eligibility_annotation(decisions.get(c.id))
        if ann is not None:
            annotations[c.id] = ann
    return kept, annotations


async def filter_eligible_candidates(
    db: AsyncSession,
    *,
    job: Job,
    candidates: Sequence[Candidate],
    now: datetime,
    enforce_manager_verdict: bool = True,
) -> list[Candidate]:
    """:func:`partition_eligible_candidates` without the annotations."""
    kept, _ = await partition_eligible_candidates(
        db,
        job=job,
        candidates=candidates,
        now=now,
        enforce_manager_verdict=enforce_manager_verdict,
    )
    return kept


def detail_for(decision: EligibilityDecision, verdict: Optional[ManagerVerdict]) -> str:
    """409 body: name the manager and the date when the veto is what blocked."""
    if (
        decision.reason_code is EligibilityReason.rejected_by_hiring_manager
        and verdict is not None
    ):
        return verdict.as_polish_detail()
    return decision.reason


async def assert_candidate_move_eligible(
    db: AsyncSession,
    *,
    candidate_id: int,
    job: Job,
    now: datetime,
    enforce_manager_verdict: bool = True,
) -> None:
    """Raise **409** if ``candidate_id`` is hard-blocked for ``job``.

    Shared by ``POST /api/pipeline/move``, single assign, shortlist promote and
    LinkedIn quick-assign, so a globally blacklisted candidate or one vetoed by
    the job's hiring manager is rejected identically everywhere. Client
    conflicts are warnings and never reach this 409. ``detail`` is the Polish
    eligibility reason (the veto names the manager and the date).
    """
    decisions, verdicts = await evaluate_candidates_for_job_with_verdicts(
        db,
        job=job,
        candidate_ids=[candidate_id],
        now=now,
        enforce_manager_verdict=enforce_manager_verdict,
    )
    decision = decisions.get(candidate_id)
    if decision is not None and not decision.assignment_allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail_for(decision, verdicts.get(candidate_id)),
        )


async def assert_candidates_move_eligible(
    db: AsyncSession,
    *,
    candidate_ids: Sequence[int],
    job: Job,
    now: datetime,
    enforce_manager_verdict: bool = True,
) -> None:
    """Raise **409** if *any* candidate in ``candidate_ids`` is hard-blocked.

    ``POST /api/pipeline/bulk-move`` is all-or-nothing (it already 422s the
    whole batch on any invalid input), so a single hard-blocked candidate
    rejects the batch — fail-closed, with the same 409 + Polish reason a
    single ``/move`` returns, plus the offending candidate id(s).
    """
    decisions, verdicts = await evaluate_candidates_for_job_with_verdicts(
        db,
        job=job,
        candidate_ids=candidate_ids,
        now=now,
        enforce_manager_verdict=enforce_manager_verdict,
    )
    blocked = [(cid, d) for cid, d in decisions.items() if not d.assignment_allowed]
    if blocked:
        reason = detail_for(blocked[0][1], verdicts.get(blocked[0][0]))
        blocked_ids = sorted(cid for cid, _ in blocked)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{reason} (kandydaci: {blocked_ids})",
        )
