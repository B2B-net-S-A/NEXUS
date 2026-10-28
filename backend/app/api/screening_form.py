# UWAGA: bez `from __future__ import annotations` — `@limiter.limit` na
# trasach z `Annotated` guardami zamieniłby je w parametry QUERY (slowapi #579).
"""Jeden formularz screeningu — ``/api/screening-form`` (0424, 07.10.2026).

Arkusz pytań Championa, ręczne pola karty rekomendacji i stawka kandydata
pary (kandydat, rekrutacja) w jednym formularzu dla Delivery Leada — z NEXUSA
nic z niego nie idzie do klienta (decyzje Artura D1–D10 z 07.10.2026).
Kontrakt: ``docs/screening-form-contract.md``; reguły zapisu:
``app/services/screening_form.py``.

* ``GET /screening-form`` — stan formularza (pytania, arkusz, karta, stawka,
  wersja, czy można edytować).
* ``PUT /screening-form`` — zapis w jednej transakcji, nowa wersja tylko przy
  realnej zmianie; ``expected_version`` i ``state_token`` chronią przed
  nadpisaniem cudzej zmiany (409).
* ``GET /screening-form/versions`` — historia wersji ze zmianami „przed → po”.
* ``POST /screening-form/restore`` — przywrócenie albo cofnięcie jako NOWA
  wersja.

Dostęp: sekcja Pipeline; odczyt jak karta (odczyt kandydata + odczyt
rekrutacji), zapis jak arkusz (zapis kandydata + bramka zespołu rekrutacji)
z poszanowaniem 12-godzinnej blokady osoby.
"""

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import (
    CANDIDATE_WRITE_ROLES,
    CandidatePIIAccess,
    CandidateWriteAccess,
)
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.services import candidate_rate_change as rate_change
from app.services import screening_form as form
from app.services.pipeline_realtime import broadcast_pipeline_changed
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class ScreeningFormSave(form.SaveInput):
    candidate_id: int = Field(gt=0)
    job_id: int = Field(gt=0)


class ScreeningFormRestore(BaseModel):
    candidate_id: int = Field(gt=0)
    job_id: int = Field(gt=0)
    version_no: int = Field(gt=0)
    expected_version: int = Field(ge=0)
    state_token: str = Field(min_length=1, max_length=form.STATE_TOKEN_MAX)
    mode: Literal["restore", "undo"] = "restore"


async def _pair(
    db: AsyncSession, candidate_id: int, job_id: int
) -> tuple[Candidate, Job]:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje.")
    return candidate, job


def _can_write(user: User) -> bool:
    """Lustro bramek ``PUT``: zapis w sekcji Pipeline i rola z zapisem kandydata."""
    if section_access_for_user(user, ProductSection.pipeline) < SectionAccess.write:
        return False
    if user.has_role(UserRole.admin):
        return True
    if user.has_role(UserRole.user):
        return False
    return user.has_any_role(*CANDIDATE_WRITE_ROLES)


async def _is_member(db: AsyncSession, user: User, job_id: int) -> bool:
    try:
        await ensure_job_membership(db, user, job_id)
    except HTTPException:
        return False
    return True


async def _mark_stale(db: AsyncSession, candidate_id: int) -> bool:
    """Odpowiedzi zmieniają ``champion_fit`` — wynik dopasowania się przeliczy.

    Cache nie ma TTL, więc nieudane oznaczenie zostaje w logu, a odpowiedź
    mówi o nim przeglądarce (lustro zapisu arkusza w ``api/pipeline``).
    """
    from app.services.match_score_cache import (  # noqa: PLC0415
        mark_stale_for_candidate,
    )

    try:
        await mark_stale_for_candidate(db, candidate_id)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "screening_form: nie oznaczono wyników kandydata=%s (%s)",
            candidate_id,
            type(exc).__name__,
        )
        await db.rollback()
        return False
    return True


async def _finish(
    db: AsyncSession,
    *,
    user: User,
    candidate_id: int,
    job_id: int,
    outcome: form.SaveOutcome,
) -> dict[str, Any]:
    """Commit, maile o zmianie stawki i oznaczenie wyników — dopiero po zapisie."""
    actor_id = user.id  # przed commitem — obiekty sesji wygasają
    await db.commit()
    await rate_change.send_pending_emails(outcome.emails)
    cache_invalidated = True
    if outcome.sheet_changed:
        cache_invalidated = await _mark_stale(db, candidate_id)
    # Rollback po nieudanym oznaczeniu wygasza obiekty sesji — świeży odczyt.
    candidate = await db.get(Candidate, candidate_id, populate_existing=True)
    job = await db.get(Job, job_id, populate_existing=True)
    if candidate is None or job is None:
        raise HTTPException(status_code=404, detail="Para nie istnieje.")
    state = await form.load_state(
        db, user=user, candidate=candidate, job=job, can_write=True
    )
    if outcome.claimed:
        # Zapis wziął osobę na 12 h (14.10.2026) — Tablice zespołu odświeżają
        # kartę jak po „Biorę”. Na końcu: savepoint rozgłoszenia otwiera
        # transakcję, a wycofanie po nieudanym oznaczeniu wyników wygasiłoby
        # wtedy `user`, którego `load_state` jeszcze potrzebuje.
        await broadcast_pipeline_changed(db, job_id, actor_id)
    return {
        **state,
        "saved_version": outcome.saved_version,
        "undo_to_version": outcome.undo_to_version,
        "changed": outcome.changed,
        "note_id": outcome.note_id,
        "cache_invalidated": cache_invalidated,
    }


@router.get("/screening-form")
async def get_screening_form(
    user: CandidatePIIAccess,
    candidate_id: int = Query(gt=0),
    job_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    candidate, job = await _pair(db, candidate_id, job_id)
    await ensure_job_read_access(db, user, job_id)
    can_write = _can_write(user) and await _is_member(db, user, job_id)
    return await form.load_state(
        db, user=user, candidate=candidate, job=job, can_write=can_write
    )


@router.get("/screening-form/joint-context")
async def get_joint_screening_context(
    user: CandidatePIIAccess,
    candidate_id: int = Query(gt=0),
    job_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Screening dla” (14.10.2026, D3): inne rekrutacje osoby do jednej rozmowy.

    Każda para mówi, czy można ją wybrać (Nowi/Screening, otwarta, bez cudzej
    blokady) i z jakim etapem „Zweryfikowany” przekazać ją dalej — ta sama
    reguła co ruch z Tablicy bez ``stage_def_id`` (szablon klonowany bez kodu
    etapu = ``None``: przekazanie tylko z jej Tablicy). Bez prawa zapisu —
    pusta lista.
    """
    from app.api.pipeline import _resolve_stage_def  # noqa: PLC0415
    from app.api.recruitment_access import job_read_scope_clause  # noqa: PLC0415
    from app.models.recruitment_pipeline import PipelineStage  # noqa: PLC0415

    _, anchor_job = await _pair(db, candidate_id, job_id)
    await ensure_job_read_access(db, user, job_id)
    anchor = await form.joint_anchor(db, anchor_job)
    if not _can_write(user):
        return {
            "candidate_id": candidate_id,
            "job_id": job_id,
            "anchor": anchor,
            "pairs": [],
        }
    from app.services import job_twins  # noqa: PLC0415

    twin_set = set(await job_twins.twin_ids(db, job_id))
    pairs = await form.joint_pairs(
        db,
        user=user,
        candidate_id=candidate_id,
        anchor_job_id=job_id,
        scope_clause=job_read_scope_clause(user, Job.id),
    )
    out = []
    for pair in pairs:
        if not await _is_member(db, user, pair["job_id"]):
            continue
        other = await db.get(Job, pair["job_id"])
        verified = await _resolve_stage_def(
            db, other, legacy_stage=PipelineStage.verified
        )
        out.append(
            {
                **pair,
                "verified_stage_def_id": verified.id if verified else None,
                "twin": pair["job_id"] in twin_set,
            }
        )
    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "anchor": anchor,
        "pairs": out,
        # Bliźniaki (0615), w których osoby jeszcze nie ma — formularz dodaje
        # ją do „Nowych” i bierze do rozmowy. Bez tego bramka „Zweryfikowany”
        # zatrzyma ruch w tej rekrutacji.
        "missing_twins": await _missing_twins(
            db, user=user, candidate_id=candidate_id, twin_ids=twin_set
        ),
    }


async def _missing_twins(
    db: AsyncSession, *, user: User, candidate_id: int, twin_ids: set[int]
) -> list[dict]:
    from app.api.pipeline import _resolve_stage_def  # noqa: PLC0415
    from app.models.recruitment_pipeline import (  # noqa: PLC0415
        CandidateStage,
        PipelineStage,
    )
    from app.services.dealbreaker_filters import resolve_job_budget_hourly  # noqa: PLC0415
    from app.services.job_working_title import display_title  # noqa: PLC0415

    if not twin_ids:
        return []
    present = set(
        (
            await db.execute(
                select(CandidateStage.job_id).where(
                    CandidateStage.candidate_id == candidate_id,
                    CandidateStage.job_id.in_(sorted(twin_ids)),
                )
            )
        ).scalars()
    )
    out = []
    for twin_id in sorted(twin_ids - present):
        twin = await db.get(Job, twin_id)
        if twin is None or twin.status == JobStatus.closed:
            continue
        if not await _is_member(db, user, twin_id):
            continue
        verified = await _resolve_stage_def(
            db, twin, legacy_stage=PipelineStage.verified
        )
        budget = resolve_job_budget_hourly(twin)
        out.append(
            {
                "job_id": twin_id,
                "title": display_title(twin),
                "client_reference": twin.client_reference,
                "client_id": twin.client_id,
                "verified_stage_def_id": verified.id if verified else None,
                "budget_hourly": float(budget) if budget is not None else None,
            }
        )
    return out


@router.get("/screening-form/question-groups")
async def get_screening_question_groups(
    user: CandidatePIIAccess,
    job_ids: list[int] = Query(min_length=2, max_length=4),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pytania kilku rekrutacji złożone w grupy „to samo pytanie” (D3).

    Tylko identyfikatory — teksty, „Idealnie” i deal-breakery formularz ma ze
    stanu każdej pary (``GET /screening-form``).
    """
    from app.services import screening_sheets  # noqa: PLC0415
    from app.services.screening_question_groups import (  # noqa: PLC0415
        group_questions,
    )

    order = list(dict.fromkeys(int(j) for j in job_ids if int(j) > 0))
    questions: dict[int, dict[str, str]] = {}
    for jid in order:
        job = await db.get(Job, jid)
        if job is None:
            raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
        await ensure_job_read_access(db, user, jid)
        questions[jid] = screening_sheets.question_texts(job.champion_profile)
    # Bliźniaki (0615): pary pytań potwierdzone przy łączeniu.
    from app.services import job_twins  # noqa: PLC0415

    pairs = job_twins.explicit_question_groups(
        await job_twins.twin_links(db, order), order
    )
    groups = group_questions(questions, order, pairs)
    return {
        "groups": [
            [{"job_id": m.job_id, "question_id": m.question_id} for m in group]
            for group in groups
        ]
    }


@router.put("/screening-form")
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def save_screening_form(
    request: Request,
    body: ScreeningFormSave,
    user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    candidate, job = await _pair(db, body.candidate_id, body.job_id)
    # Zapis arkusza to mutacja pipeline'u tej rekrutacji — ta sama bramka co `/move`.
    await ensure_job_membership(db, user, job.id)
    if body.rate is not None:
        # Bliźniaki (0615, 28.10.2026): stawka ponad budżet się nie zapisze.
        from app.services import job_twins  # noqa: PLC0415

        await job_twins.assert_rate_within_budget(
            db,
            job=job,
            amount=body.rate.amount,
            unit=body.rate.unit,
            currency=body.rate.currency,
        )
    outcome = await form.save(db, user=user, candidate=candidate, job=job, data=body)
    return await _finish(
        db, user=user, candidate_id=candidate.id, job_id=job.id, outcome=outcome
    )


@router.get("/screening-form/versions")
async def list_screening_form_versions(
    user: CandidatePIIAccess,
    candidate_id: int = Query(gt=0),
    job_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _pair(db, candidate_id, job_id)
    await ensure_job_read_access(db, user, job_id)
    return await form.list_versions(db, candidate_id=candidate_id, job_id=job_id)


@router.post("/screening-form/restore")
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def restore_screening_form(
    request: Request,
    body: ScreeningFormRestore,
    user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    candidate, job = await _pair(db, body.candidate_id, body.job_id)
    await ensure_job_membership(db, user, job.id)
    outcome = await form.restore(
        db,
        user=user,
        candidate=candidate,
        job=job,
        version_no=body.version_no,
        expected_version=body.expected_version,
        state_token=body.state_token,
        mode=body.mode,
    )
    result = await _finish(
        db, user=user, candidate_id=candidate.id, job_id=job.id, outcome=outcome
    )
    return {
        **result,
        "rate_not_restored": outcome.rate_not_restored,
        "rate_not_restored_reason": outcome.rate_not_restored_reason,
        "skipped_answers": outcome.skipped_answers,
    }
