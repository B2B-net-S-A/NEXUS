"""Shared hard-eligibility gate for pipeline stage-writing ingress (P1-PIPE-01).

``api/recommendations.py`` (single assign) and ``api/proposals_bulk.py``
(bulk assign) already run :func:`evaluate_eligibility` before adding a
candidate to a job. The pipeline *move* endpoints —
``POST /api/pipeline/move`` and ``POST /api/pipeline/bulk-move`` — wrote a
``CandidateStage`` with **no** eligibility check at all, so a globally
blacklisted candidate, or one with an active client blacklist / NDA /
competitor conflict, could be pushed through a client's pipeline via a move.

This module centralises that hard block so every stage-writing ingress rejects
such a candidate **identically** (HTTP 409, Polish reason from
``_REASON_LABELS_PL`` — the exact contract the single-assign gate already
returns). The policy itself stays in the pure :func:`evaluate_eligibility`;
this module only does the I/O (load candidate status, active conflicts,
candidate-declared excluded clients) and raises.

Scope notes (deliberate, to avoid reversing existing behaviour):

* Only **hard** blocks are enforced — global blacklist and active client
  blacklist / NDA / competitor. Soft signals (current employment at the
  client, candidate-excluded client) never block a move; they surface as
  warnings on the assignment ingresses and are irrelevant to a move.
* ``already_in_job`` is a *dedup* concern for **assignment**, not a move: a
  move presupposes the candidate is in the job, so it is passed as ``False``
  here and never blocks a move (mirrors ``recommendations.assign_candidate_to_job``,
  which also passes ``already_in_job=False`` and handles dedup separately).
* Terminal **removal** moves (``rejected`` / ``withdrawn``) must stay allowed
  so a blacklisted candidate can always be closed OUT of a pipeline — the
  caller decides not to invoke the gate for those (see ``api/pipeline.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict
from app.models.job import Job
from app.services.candidate_job_eligibility import (
    ConflictInput,
    EligibilityDecision,
    EligibilityInput,
    evaluate_eligibility,
    extract_excluded_client_ids,
)


async def evaluate_candidates_for_job(
    db: AsyncSession,
    *,
    job: Job,
    candidate_ids: Sequence[int],
    now: datetime,
) -> dict[int, EligibilityDecision]:
    """Batch-load eligibility inputs and evaluate each candidate for ``job``.

    Pure policy stays in :func:`evaluate_eligibility`; this only performs the
    two batched reads (candidates, active client conflicts). Candidates that do
    not exist are simply absent from the result — the caller decides how to
    treat a missing candidate (``/move`` leaves it to the DB FK; ``/bulk-move``
    validates existence separately). ``already_in_job`` is always ``False``:
    this gate is for moves, where being in the job is the precondition.
    """
    ids = list(dict.fromkeys(candidate_ids))
    if not ids:
        return {}

    cand_rows = (
        (await db.execute(select(Candidate).where(Candidate.id.in_(ids))))
        .scalars()
        .all()
    )
    candidates_by_id: dict[int, Candidate] = {c.id: c for c in cand_rows}

    conflicts_by_candidate: dict[int, list[ConflictInput]] = {}
    if job.client_id is not None:
        conflict_rows = (
            (
                await db.execute(
                    select(CandidateConflict).where(
                        CandidateConflict.candidate_id.in_(ids),
                        CandidateConflict.client_id == job.client_id,
                        CandidateConflict.active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in conflict_rows:
            conflicts_by_candidate.setdefault(row.candidate_id, []).append(
                ConflictInput(
                    type=row.type.value,
                    client_id=row.client_id,
                    active=row.active,
                    expires_at=row.expires_at,
                )
            )

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
                already_in_job=False,  # a move presupposes in-job; not a block
            ),
            now,
        )
    return decisions


async def assert_candidate_move_eligible(
    db: AsyncSession,
    *,
    candidate_id: int,
    job: Job,
    now: datetime,
) -> None:
    """Raise **409** if ``candidate_id`` is hard-blocked for ``job``.

    Shared by ``POST /api/pipeline/move`` so a non-terminal (or ``hired``) move
    of a globally blacklisted candidate, or one with an active client
    blacklist / NDA / competitor conflict, is rejected exactly as the assign
    ingresses reject it. ``detail`` is the Polish eligibility reason —
    identical to ``recommendations.assign_candidate_to_job``.
    """
    decisions = await evaluate_candidates_for_job(
        db, job=job, candidate_ids=[candidate_id], now=now
    )
    decision = decisions.get(candidate_id)
    if decision is not None and not decision.assignment_allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=decision.reason
        )


async def assert_candidates_move_eligible(
    db: AsyncSession,
    *,
    candidate_ids: Sequence[int],
    job: Job,
    now: datetime,
) -> None:
    """Raise **409** if *any* candidate in ``candidate_ids`` is hard-blocked.

    ``POST /api/pipeline/bulk-move`` is all-or-nothing (it already 422s the
    whole batch on any invalid input), so a single hard-blocked candidate
    rejects the batch — fail-closed, with the same 409 + Polish reason a
    single ``/move`` returns, plus the offending candidate id(s).
    """
    decisions = await evaluate_candidates_for_job(
        db, job=job, candidate_ids=candidate_ids, now=now
    )
    blocked = [(cid, d) for cid, d in decisions.items() if not d.assignment_allowed]
    if blocked:
        reason = blocked[0][1].reason
        blocked_ids = sorted(cid for cid, _ in blocked)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{reason} (kandydaci: {blocked_ids})",
        )
