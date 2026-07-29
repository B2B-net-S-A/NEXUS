"""Job shortlist API (SEARCH-P1-05).

A pre-pipeline evaluation list per job. Recruiters add candidates from search,
track evaluation + outreach status, then promote approved entries into the
pipeline (promotion lands in a follow-up). Updates use optimistic locking:
the client echoes the ``version`` it read and a stale PATCH 409s.

Zakres zasobu: każda z pięciu tras woła ``ensure_job_membership`` (#984) — bez
flagi, bo bramka jest kontraktem, nie rolloutem. Obie strony tej decyzji trzyma
``tests/test_job_shortlist_scope.py``: obcy dostaje 403, a właściciel oferty,
aktywny współpracownik i admin dalej przechodzą. Test kontraktowy
``test_job_scope_contract.py`` tego modułu nie obejmuje (nie ma go w
``_SCOPED_MODULES``), więc plik z testami JEST tu jedynym zabezpieczeniem przed
cichą regresją w którąkolwiek stronę.

Znana niespójność (poza tym plikiem): cięższy bliźniak z tego samego ekranu,
``POST /api/jobs/{job_id}/proposals/bulk`` w ``app/api/proposals_bulk.py``,
wpisuje do pipeline'u dowolnej oferty BEZ sprawdzenia zakresu. Dopóki tam nie
przybędzie ta sama bramka, zamknięte jest lżejsze parkowanie, a otwarte cięższe
wpisanie. Luka jest zaznaczona jako ``xfail`` w pliku testów wyżej.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus
from app.api.proposals_bulk import _resolve_initial_stage
from app.api.recruitment_access import ensure_job_membership
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict
from app.models.job import Job
from app.models.job_shortlist import JobShortlistEntry
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_priority import PriorityChannel
from app.schemas.job_shortlist import (
    ShortlistAddRequest,
    ShortlistAddResponse,
    ShortlistEntryResponse,
    ShortlistPromoteResponse,
    ShortlistUpdateRequest,
)
from app.services.candidate_stage_cv_service import create_original_cv_snapshot
from app.services.candidate_contact_hooks import (
    has_active_contact_trigger,
    maybe_close_contact_opportunity,
    maybe_ensure_contact_opportunity,
)
from app.services.candidate_job_eligibility import (
    ConflictInput,
    EligibilityInput,
    EligibilityReason,
    evaluate_eligibility,
    extract_excluded_client_ids,
)
from app.services.hiring_manager_verdicts import load_manager_rejections
from app.services.recruitment_process_commands import open_process

router = APIRouter()


def _to_response(
    entry: JobShortlistEntry,
    name: Optional[str] = None,
    lastname: Optional[str] = None,
) -> ShortlistEntryResponse:
    resp = ShortlistEntryResponse.model_validate(entry)
    resp.candidate_name = name
    resp.candidate_lastname = lastname
    return resp


@router.post(
    "/jobs/{job_id}/shortlist",
    response_model=ShortlistAddResponse,
    summary="Add candidates to a job's shortlist",
)
async def add_to_shortlist(
    job_id: int,
    body: ShortlistAddRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> ShortlistAddResponse:
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await ensure_job_membership(db, current_user, job_id)

    valid = set(
        (
            await db.execute(
                select(Candidate.id).where(Candidate.id.in_(body.candidate_ids))
            )
        )
        .scalars()
        .all()
    )
    already = set(
        (
            await db.execute(
                select(JobShortlistEntry.candidate_id).where(
                    JobShortlistEntry.job_id == job_id,
                    JobShortlistEntry.candidate_id.in_(body.candidate_ids),
                )
            )
        )
        .scalars()
        .all()
    )

    added: list[int] = []
    skipped: list[int] = []
    seen: set[int] = set()
    for cid in body.candidate_ids:
        if cid in seen:
            continue
        seen.add(cid)
        if cid not in valid or cid in already:
            skipped.append(cid)
            continue
        db.add(
            JobShortlistEntry(
                job_id=job_id,
                candidate_id=cid,
                note=body.note,
                created_by=current_user.id,
                updated_by=current_user.id,
            )
        )
        added.append(cid)

    await db.commit()
    return ShortlistAddResponse(
        added=added,
        skipped=skipped,
        total_added=len(added),
        total_skipped=len(skipped),
    )


@router.get(
    "/jobs/{job_id}/shortlist",
    response_model=list[ShortlistEntryResponse],
    summary="List a job's shortlist",
)
async def list_shortlist(
    job_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> list[ShortlistEntryResponse]:
    await ensure_job_membership(db, current_user, job_id)
    rows = (
        await db.execute(
            select(JobShortlistEntry, Candidate.name, Candidate.lastname)
            .join(Candidate, Candidate.id == JobShortlistEntry.candidate_id)
            .where(JobShortlistEntry.job_id == job_id)
            .order_by(JobShortlistEntry.created_at.desc())
        )
    ).all()
    return [_to_response(entry, name, lastname) for entry, name, lastname in rows]


@router.patch(
    "/shortlist/{entry_id}",
    response_model=ShortlistEntryResponse,
    summary="Update a shortlist entry (optimistic-locked)",
)
async def update_shortlist_entry(
    entry_id: int,
    body: ShortlistUpdateRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> ShortlistEntryResponse:
    entry = await db.scalar(
        select(JobShortlistEntry).where(JobShortlistEntry.id == entry_id)
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Shortlist entry not found")
    await ensure_job_membership(db, current_user, entry.job_id)
    if entry.version != body.version:
        raise HTTPException(
            status_code=409,
            detail="Wpis zmieniony przez kogoś innego — odśwież i spróbuj ponownie.",
        )

    previous_outreach_status = entry.outreach_status
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    for field, value in changes.items():
        setattr(entry, field, value)
    entry.version += 1
    entry.updated_by = current_user.id
    # Kontakt uruchamia PRZEJŚCIE na „do_kontaktu", nie samo to, że pole taką
    # wartość trzyma. `exclude_unset` odróżnia „pola nie ma w żądaniu" od
    # „ustawiono je na tę samą wartość", ale żadna z tych sytuacji nie jest
    # decyzją o dzwonieniu — a poprzednia wersja odpalała intake przy PATCH-u
    # dowolnego innego pola (np. samej oceny) i potrafiła wskrzesić szansę
    # zamkniętą wprost odmową kandydata.
    started_outreach = (
        entry.outreach_status == "do_kontaktu"
        and previous_outreach_status != "do_kontaktu"
    )
    if started_outreach:
        await maybe_ensure_contact_opportunity(
            db,
            candidate_id=entry.candidate_id,
            job_id=entry.job_id,
            source="shortlist",
            source_external_ref=str(entry.id),
            occurred_at=datetime.now(timezone.utc),
            # Świadome przestawienie statusu przez rekrutera to jedyna ścieżka
            # ponownego podejścia do kandydata, który odmówił tej oferty.
            allow_declined_reopen=True,
        )
    elif (
        previous_outreach_status == "do_kontaktu"
        and entry.outreach_status != "do_kontaktu"
    ):
        if not await has_active_contact_trigger(
            db,
            candidate_id=entry.candidate_id,
            job_id=entry.job_id,
            exclude_shortlist_entry_id=entry.id,
        ):
            await maybe_close_contact_opportunity(
                db,
                candidate_id=entry.candidate_id,
                job_id=entry.job_id,
                actor_user_id=current_user.id,
                reason=f"shortlist_outreach:{entry.outreach_status}",
            )

    await db.commit()
    await db.refresh(entry)
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == entry.candidate_id)
    )
    return _to_response(
        entry,
        candidate.name if candidate else None,
        candidate.lastname if candidate else None,
    )


@router.delete(
    "/shortlist/{entry_id}",
    summary="Remove a shortlist entry",
)
async def delete_shortlist_entry(
    entry_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    entry = await db.scalar(
        select(JobShortlistEntry).where(JobShortlistEntry.id == entry_id)
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Shortlist entry not found")
    await ensure_job_membership(db, current_user, entry.job_id)
    if not await has_active_contact_trigger(
        db,
        candidate_id=entry.candidate_id,
        job_id=entry.job_id,
        exclude_shortlist_entry_id=entry.id,
    ):
        await maybe_close_contact_opportunity(
            db,
            candidate_id=entry.candidate_id,
            job_id=entry.job_id,
            actor_user_id=current_user.id,
            reason="shortlist_removed",
        )
    await db.delete(entry)
    await db.commit()
    return {"status": "deleted", "id": entry_id}


@router.post(
    "/shortlist/{entry_id}/promote",
    response_model=ShortlistPromoteResponse,
    summary="Promote a shortlist entry into the job's pipeline",
)
async def promote_shortlist_entry(
    entry_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> ShortlistPromoteResponse:
    """Move an approved shortlist entry into the pipeline (creates a
    ``CandidateStage`` at the first non-terminal stage). Idempotent: if the
    candidate is already in the job's pipeline it just records the promotion.
    Applies the same eligibility gate as bulk-add / single-assign — a global
    blacklist or an active client conflict → 409.
    """
    entry = await db.scalar(
        select(JobShortlistEntry).where(JobShortlistEntry.id == entry_id)
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Shortlist entry not found")
    await ensure_job_membership(db, current_user, entry.job_id)
    job = await db.scalar(select(Job).where(Job.id == entry.job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == entry.candidate_id)
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    now = datetime.now(timezone.utc)
    existing_stage = await db.scalar(
        select(CandidateStage).where(
            CandidateStage.job_id == job.id,
            CandidateStage.candidate_id == candidate.id,
        )
    )

    # Already in the pipeline — record the promotion (idempotent) and return.
    if existing_stage is not None:
        already_promoted = entry.promoted_to_pipeline_at is not None
        await maybe_ensure_contact_opportunity(
            db,
            candidate_id=candidate.id,
            job_id=job.id,
            source="shortlist",
            source_external_ref=str(entry.id),
            occurred_at=now,
        )
        if not already_promoted:
            entry.promoted_to_pipeline_at = now
            entry.updated_by = current_user.id
            await db.commit()
        else:
            # The ensure call above may have created the contact case during
            # cutover even though the shortlist promotion was already stamped.
            await db.commit()
        return ShortlistPromoteResponse(
            entry_id=entry.id,
            candidate_id=candidate.id,
            job_id=job.id,
            stage_id=existing_stage.id,
            already_promoted=already_promoted,
            already_in_pipeline=True,
        )

    # Eligibility gate before creating a new pipeline row.
    conflict_rows = (
        (
            await db.execute(
                select(CandidateConflict).where(
                    CandidateConflict.candidate_id == candidate.id,
                    CandidateConflict.client_id == job.client_id,
                    CandidateConflict.active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    manager_verdicts = await load_manager_rejections(
        db, job=job, candidate_ids=[candidate.id]
    )
    decision = evaluate_eligibility(
        EligibilityInput(
            candidate_status=candidate.status.value,
            job_client_id=job.client_id,
            conflicts=tuple(
                ConflictInput(
                    type=r.type.value,
                    client_id=r.client_id,
                    active=r.active,
                    expires_at=r.expires_at,
                )
                for r in conflict_rows
            ),
            excluded_client_ids=extract_excluded_client_ids(candidate.preferences),
            already_in_job=False,
            rejected_by_hiring_manager=candidate.id in manager_verdicts,
        ),
        now,
    )
    if not decision.assignment_allowed:
        detail = decision.reason
        verdict = manager_verdicts.get(candidate.id)
        if (
            decision.reason_code is EligibilityReason.rejected_by_hiring_manager
            and verdict is not None
        ):
            detail = verdict.as_polish_detail()
        raise HTTPException(status_code=409, detail=detail)

    stage_def = await _resolve_initial_stage(db, job, None)
    legacy_enum = PipelineStage.new
    if stage_def and stage_def.legacy_enum_value:
        try:
            legacy_enum = PipelineStage(stage_def.legacy_enum_value)
        except ValueError:
            legacy_enum = PipelineStage.new

    stage = await open_process(
        db,
        candidate_id=candidate.id,
        job_id=job.id,
        stage=legacy_enum,
        stage_def_id=stage_def.id if stage_def else None,
        actor_user_id=current_user.id,
        work_channel=PriorityChannel.database,
    )
    # M3-ACT-01: snapshot the CV current at promotion + emit the audit, the
    # same invariant the single-assign path holds — shortlist promotion was
    # skipping it. Idempotent + fail-soft.
    await create_original_cv_snapshot(db, stage)
    entry.promoted_to_pipeline_at = now
    entry.updated_by = current_user.id
    await maybe_ensure_contact_opportunity(
        db,
        candidate_id=candidate.id,
        job_id=job.id,
        source="shortlist",
        source_external_ref=str(entry.id),
        occurred_at=now,
    )
    await db.commit()
    await db.refresh(stage)
    return ShortlistPromoteResponse(
        entry_id=entry.id,
        candidate_id=candidate.id,
        job_id=job.id,
        stage_id=stage.id,
    )
