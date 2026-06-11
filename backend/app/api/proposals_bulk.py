"""Bulk-add candidates to a job pipeline (manual search → recruitment).

Single-candidate moves use ``POST /api/pipeline/move`` (terminal validation,
verification gate, rate snapshot). For *manual search* bulk-add the user just
wants to place 1–100 candidates into the job's first non-terminal stage in
one click; this endpoint is the minimal safe variant of that.

Skipped on purpose:

* Terminal-stage validation — bulk-add never targets a terminal stage.
* Verification gate (rate vs salary_max) — only triggers on ``verified``,
  which manual search never targets.
* Rejection-reason FK — N/A for bulk-add (entry stage is non-terminal).

Returned shape lets the UI render a "Added 7, skipped 3" toast with reasons.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus
from app.core.database import get_db
from app.models.candidate import Candidate, CandidateStatus
from app.models.job import Job
from app.models.note import Note, NoteType
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
)

router = APIRouter()

SkipReason = Literal["already_in_job", "blacklisted", "candidate_not_found"]


class BulkProposalsRequest(BaseModel):
    candidate_ids: list[int] = Field(..., min_length=1, max_length=100)
    initial_stage_def_id: Optional[int] = Field(
        default=None,
        description=(
            "Optional pipeline stage to place candidates into. Defaults to the"
            " template's first non-terminal stage (or PipelineStage.new)."
        ),
    )
    note: Optional[str] = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class BulkSkippedRow(BaseModel):
    candidate_id: int
    reason: SkipReason


class BulkProposalsResponse(BaseModel):
    added: list[int]
    skipped: list[BulkSkippedRow]
    total_added: int
    total_skipped: int


async def _resolve_initial_stage(
    db: AsyncSession, job: Job, override_id: Optional[int]
) -> Optional[PipelineStageDef]:
    """First non-terminal stage from the job's template, or the override."""
    if override_id is not None:
        stage_def = await db.scalar(
            select(PipelineStageDef).where(PipelineStageDef.id == override_id)
        )
        if not stage_def:
            raise HTTPException(
                status_code=422, detail="initial_stage_def_id not found"
            )
        if stage_def.template_id != job.pipeline_template_id:
            raise HTTPException(
                status_code=422,
                detail="initial_stage_def_id does not belong to this job's template",
            )
        if stage_def.is_terminal:
            raise HTTPException(
                status_code=422,
                detail="initial_stage_def_id must be a non-terminal stage",
            )
        # Stage 'verified' wymaga stawki per rekrutacja + gate'u DL (migracja
        # 0056) — bulk-add nie zbiera stawek, więc nie może tam celować.
        if stage_def.legacy_enum_value == PipelineStage.verified.value:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Etap 'verified' wymaga stawki i weryfikacji DL — użyj"
                    " POST /api/pipeline/move dla pojedynczego kandydata."
                ),
            )
        return stage_def

    if not job.pipeline_template_id:
        return None

    stage_def = await db.scalar(
        select(PipelineStageDef)
        .where(
            PipelineStageDef.template_id == job.pipeline_template_id,
            PipelineStageDef.is_terminal.is_(False),
        )
        .order_by(PipelineStageDef.order.asc())
        .limit(1)
    )
    return stage_def


@router.post(
    "/jobs/{job_id}/proposals/bulk",
    response_model=BulkProposalsResponse,
    summary="Bulk-add candidates to job pipeline (manual search → recruitment)",
)
async def bulk_add_proposals(
    job_id: int,
    body: BulkProposalsRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> BulkProposalsResponse:
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    stage_def = await _resolve_initial_stage(db, job, body.initial_stage_def_id)
    legacy_enum = PipelineStage.new
    if stage_def and stage_def.legacy_enum_value:
        try:
            legacy_enum = PipelineStage(stage_def.legacy_enum_value)
        except ValueError:
            legacy_enum = PipelineStage.new

    # Pre-fetch in two batches so we don't issue 100×2 round-trips.
    cand_rows = (
        (
            await db.execute(
                select(Candidate).where(Candidate.id.in_(body.candidate_ids))
            )
        )
        .scalars()
        .all()
    )
    candidates_by_id: dict[int, Candidate] = {c.id: c for c in cand_rows}

    already_in_job = (
        (
            await db.execute(
                select(CandidateStage.candidate_id).where(
                    CandidateStage.job_id == job_id,
                    CandidateStage.candidate_id.in_(body.candidate_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    already_in_job_set: set[int] = set(already_in_job)

    added: list[int] = []
    skipped: list[BulkSkippedRow] = []

    for candidate_id in body.candidate_ids:
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None:
            skipped.append(
                BulkSkippedRow(candidate_id=candidate_id, reason="candidate_not_found")
            )
            continue
        if candidate.status == CandidateStatus.blacklisted:
            skipped.append(
                BulkSkippedRow(candidate_id=candidate_id, reason="blacklisted")
            )
            continue
        if candidate_id in already_in_job_set:
            skipped.append(
                BulkSkippedRow(candidate_id=candidate_id, reason="already_in_job")
            )
            continue

        stage = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=legacy_enum,
            stage_def_id=stage_def.id if stage_def else None,
            moved_by=current_user.id,
        )
        db.add(stage)

        # Optional shared note attached to every newly added candidate.
        if body.note:
            db.add(
                Note(
                    content=body.note,
                    note_type=NoteType.private,
                    candidate_id=candidate_id,
                    job_id=job_id,
                    author_id=current_user.id,
                )
            )

        # Optional shared tags merged into the candidate's tags JSONB. We
        # treat candidate.tags as a list when populated and a placeholder dict
        # otherwise — same convention as the rest of the codebase.
        if body.tags:
            existing = candidate.tags
            if isinstance(existing, list):
                merged = list({*existing, *body.tags})
                candidate.tags = merged
            elif isinstance(existing, dict) and "items" in existing:
                merged = list({*existing.get("items", []), *body.tags})
                candidate.tags = {"items": merged}
            else:
                candidate.tags = list(set(body.tags))

        added.append(candidate_id)

    await db.commit()

    return BulkProposalsResponse(
        added=added,
        skipped=skipped,
        total_added=len(added),
        total_skipped=len(skipped),
    )
