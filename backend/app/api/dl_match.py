# UWAGA: bez `from __future__ import annotations` — moduł ma `@limiter.limit`
# (slowapi #579: PEP 563 zamienia parametry `Annotated` w parametry query → 422).
"""„Match” — Delivery Lead wysyła osobę od razu do innych swoich rekrutacji.

Reguły i lista: :mod:`app.services.dl_match`. Wysyłka do każdej rekrutacji B
to trzy kroki, które już istnieją, każdy w swojej transakcji:

1. dodanie do B jako przepięcie z A (kopia CV etapu, ``entry_source=reassign``,
   ślad ``entry_meta.via = dl_match``) i ruch na „Zweryfikowany” przez DL-a —
   bramki pól DL omija (``skips_fill_gates``), więc proces zalicza się jemu;
2. ruch na „CV wysłane” albo do kolejki Cpro (Nordea) ze stawką do klienta,
   przez ``apply_move`` — te same bramki co przegląd DL-a;
3. gdy CV nie przechodzi QC: obejście DL-a zapisane jak „Wyślij mimo to”
   i drugi ruch.

Kroki 2 i 3 idą w osobnych transakcjach, bo QC zapisuje przebieg we własnej
sesji, a dodanie trzyma wiersz kandydata (``assert_qc_passed`` każe wołać
bramkę przed blokadami ruchu). Gdy wysyłka do B się nie uda, osoba zostaje
w B na „Zweryfikowanym”, a odpowiedź to mówi.
"""

import logging
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.permission_access import RecruitmentManageUser
from app.api.pipeline import (
    MoveApplied,
    apply_move,
    run_move_effects,
)
from app.api.proposals_bulk import add_candidates_to_job
from app.api.recruitment_access import ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.schemas.pipeline import RateUnit, StageMove
from app.services import candidate_claim, cv_qc
from app.services import dl_match as svc
from app.services.job_working_title import display_title
from app.services.recruitment_move_policy import UserMovePolicy

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class MatchJobOut(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str] = None
    client_reference: Optional[str] = None
    score: Optional[int] = None
    matching_must: list[str] = []
    gap_must: list[str] = []
    linked: bool = False
    destination: Literal["cv_sent", "cpro"]
    sendable: bool
    budget_min_hourly: Optional[Decimal] = None
    budget_max_hourly: Optional[Decimal] = None


class AlreadyInOut(BaseModel):
    job_id: int
    title: str
    client_reference: Optional[str] = None
    column: str


class MatchSuggestionsResponse(BaseModel):
    candidate_id: int
    from_job_id: int
    status: str
    jobs: list[MatchJobOut]
    already_in: list[AlreadyInOut]


class MatchTarget(BaseModel):
    job_id: int = Field(..., gt=0)
    client_rate_value: Decimal = Field(..., gt=0)
    client_rate_unit: RateUnit = RateUnit.hourly
    client_rate_currency: str = Field("PLN", min_length=3, max_length=3)


class MatchSendRequest(BaseModel):
    candidate_id: int = Field(..., gt=0)
    from_job_id: int = Field(..., gt=0)
    targets: list[MatchTarget] = Field(..., min_length=1, max_length=svc.MAX_TARGETS)
    recruiter_remark: Optional[str] = Field(None, max_length=2000)


class MatchSendResult(BaseModel):
    job_id: int
    title: Optional[str] = None
    #: sent — „CV wysłane” albo kolejka Cpro; verified_only — osoba dodana
    #: na „Zweryfikowany”, wysyłka nie przeszła; failed — nic nie zapisano.
    status: Literal["sent", "verified_only", "failed"]
    destination: Optional[Literal["cv_sent", "cpro"]] = None
    qc: Optional[Literal["passed", "overridden"]] = None
    #: Powód odmowy słowami serwera (nie ``detail`` błędu HTTP).
    reason: Optional[str] = None
    cv_carried: bool = False


class MatchSendResponse(BaseModel):
    candidate_id: int
    from_job_id: int
    results: list[MatchSendResult]


@router.get(
    "/dl-match/candidates/{candidate_id}",
    response_model=MatchSuggestionsResponse,
)
# Jedno wywołanie = jedno zapytanie wektorowe + pełna ocena kilku rekrutacji.
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def match_suggestions(
    request: Request,
    candidate_id: int,
    current_user: RecruitmentManageUser,
    from_job_id: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
) -> MatchSuggestionsResponse:
    """„Pasuje też do Twoich rekrutacji” w przeglądzie DL-a i w panelu osoby."""
    await ensure_job_read_access(db, current_user, from_job_id)
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej osoby.")
    result = await svc.suggestions(
        db, user=current_user, candidate=candidate, from_job_id=from_job_id
    )
    return MatchSuggestionsResponse(
        candidate_id=candidate_id,
        from_job_id=from_job_id,
        status=result.status,
        jobs=[
            MatchJobOut(
                job_id=j.job_id,
                title=j.title,
                client_name=j.client_name,
                client_reference=j.client_reference,
                score=j.score,
                matching_must=list(j.matching_must),
                gap_must=list(j.gap_must),
                linked=j.linked,
                destination=j.destination,
                sendable=j.sendable,
                budget_min_hourly=j.budget_min_hourly,
                budget_max_hourly=j.budget_max_hourly,
            )
            for j in result.jobs
        ],
        already_in=[
            AlreadyInOut(
                job_id=a.job_id,
                title=a.title,
                client_reference=a.client_reference,
                column=a.column,
            )
            for a in result.already_in
        ],
    )


def _detail_text(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or "Odmowa.")
    return str(detail)


def _is_qc_failure(exc: HTTPException) -> bool:
    return (
        exc.status_code == 409
        and isinstance(exc.detail, dict)
        and exc.detail.get("code") == "CV_QC_FAILED"
    )


def _job_label(job: Job) -> str:
    ref = (job.client_reference or "").strip()
    return f"{ref} {display_title(job)}".strip() if ref else display_title(job)


async def _latest_stage(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[CandidateStage]:
    return await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )


async def _source_rate(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[CandidateStage]:
    """Najnowszy wiersz pary w A ze stawką kandydata — przechodzi do B."""
    return await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
            CandidateStage.expected_rate_value.is_not(None),
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )


async def _apply(db: AsyncSession, move: StageMove, user: User) -> MoveApplied:
    outcome = await apply_move(db, move, policy=UserMovePolicy(user, db))
    if not isinstance(outcome, MoveApplied):
        raise HTTPException(status_code=409, detail="Ruch nie został zapisany.")
    return outcome


async def _effects(db: AsyncSession, outcome: MoveApplied, user: User) -> None:
    try:
        await run_move_effects(db, outcome, mover=user)
    except Exception:  # noqa: BLE001 — efekty nigdy nie cofają wysyłki
        logger.exception("[dl_match] efekty ruchu stage=%s", outcome.stage.id)


class _NotAdded(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def _send_one(
    db: AsyncSession,
    *,
    user: User,
    candidate_id: int,
    source: Job,
    target: MatchTarget,
    remark: Optional[str],
) -> MatchSendResult:
    """Jedna rekrutacja B. Każdy krok w savepoincie — nigdy ``db.rollback()``
    na sesji żądania: wygasiłby ``current_user`` dla kolejnych rekrutacji
    (ten sam błąd co w ``/move`` do 25.09.2026)."""
    job = await db.get(Job, target.job_id)
    if job is None:
        return MatchSendResult(
            job_id=target.job_id, status="failed", reason="Nie ma takiej rekrutacji."
        )
    job_id = int(job.id)
    title = _job_label(job)
    allowed = await svc.open_target_ids(
        db,
        candidate_id=candidate_id,
        from_job_id=source.id,
        job_ids=[job_id],
        scope=await svc.scope_for(db, user),
    )
    if job_id not in allowed:
        return MatchSendResult(
            job_id=job_id,
            title=title,
            status="failed",
            reason=(
                "Tej rekrutacji nie ma w Twoim portfelu, nie jest otwarta "
                "albo osoba już w niej jest."
            ),
        )
    destination = svc.destination_for(job.client_id)
    stages = await svc.template_stages(db, job)
    target_def = svc.target_stage_id(stages, destination)
    if stages is None or stages.verified_id is None or target_def is None:
        return MatchSendResult(
            job_id=job_id,
            title=title,
            status="failed",
            destination=destination,
            reason="Szablon tej rekrutacji nie ma etapu „Zweryfikowany” albo etapu wysyłki.",
        )

    # 1. Dodanie (kopia CV z A) + „Zweryfikowany” przez DL-a.
    rate_row = await _source_rate(db, candidate_id=candidate_id, job_id=source.id)
    try:
        async with db.begin_nested():
            intake = await add_candidates_to_job(
                db,
                job=job,
                candidate_ids=[candidate_id],
                actor_user_id=user.id,
                entry_source=candidate_claim.ENTRY_REASSIGN,
                claim=False,
                entry_meta={"via": svc.MATCH_VIA, "from_job_id": source.id},
                mark_proposals=True,
                reassign_from_job_id=source.id,
            )
            if candidate_id not in intake.added:
                skipped = next(
                    (s for s in intake.skipped if s.candidate_id == candidate_id), None
                )
                raise _NotAdded(
                    (skipped.reason_label if skipped else None)
                    or "Nie udało się dodać osoby do tej rekrutacji."
                )
            verified = await _apply(
                db,
                StageMove(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    stage_def_id=stages.verified_id,
                    expected_rate_value=(
                        rate_row.expected_rate_value if rate_row else None
                    ),
                    expected_rate_unit=rate_row.expected_rate_unit
                    if rate_row
                    else None,
                    expected_rate_currency=(
                        rate_row.expected_rate_currency if rate_row else None
                    ),
                    acknowledge_eligibility=True,
                ),
                user,
            )
        await db.commit()
    except (_NotAdded, HTTPException) as exc:
        return MatchSendResult(
            job_id=job_id,
            title=title,
            status="failed",
            destination=destination,
            reason=exc.detail if isinstance(exc, _NotAdded) else _detail_text(exc),
        )
    await _effects(db, verified, user)
    cv_carried = candidate_id in intake.cv_carried

    # 2. Wysyłka: „CV wysłane” albo kolejka Cpro, ze stawką do klienta.
    send_move = StageMove(
        candidate_id=candidate_id,
        job_id=job_id,
        stage_def_id=target_def,
        client_rate_value=target.client_rate_value,
        client_rate_unit=target.client_rate_unit,
        client_rate_currency=target.client_rate_currency.upper(),
        recruiter_remark=remark or None,
        acknowledge_eligibility=True,
    )
    qc = "passed"
    try:
        try:
            async with db.begin_nested():
                sent = await _apply(db, send_move, user)
        except HTTPException as exc:
            if not _is_qc_failure(exc):
                raise
            # 3. QC doradcze: DL wysyła mimo uwag — to samo co „Wyślij mimo to”.
            # Obejście zatwierdzone PRZED drugim ruchem: bramka liczy QC we
            # własnej sesji i musi je widzieć.
            stage = await _latest_stage(db, candidate_id=candidate_id, job_id=job_id)
            if stage is None:
                raise
            await cv_qc.record_override(
                db,
                stage,
                user_id=user.id,
                reason_code="other",
                reason=f"Match z {_job_label(source)}: Delivery Lead wysłał z przeglądu",
            )
            await db.commit()
            qc = "overridden"
            async with db.begin_nested():
                sent = await _apply(db, send_move, user)
        await db.commit()
    except HTTPException as exc:
        return MatchSendResult(
            job_id=job_id,
            title=title,
            status="verified_only",
            destination=destination,
            reason=_detail_text(exc),
            cv_carried=cv_carried,
        )
    await _effects(db, sent, user)
    await _notify_target_recruiter(
        db,
        job=job,
        source=source,
        candidate_id=candidate_id,
        user=user,
        stage=sent.stage,
    )
    return MatchSendResult(
        job_id=job_id,
        title=title,
        status="sent",
        destination=destination,
        qc=qc,
        cv_carried=cv_carried,
    )


async def _person(db: AsyncSession, candidate_id: int) -> str:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        return "Kandydat"
    return f"{candidate.name or ''} {candidate.lastname or ''}".strip() or "Kandydat"


async def _emit(db: AsyncSession, **kwargs) -> None:
    from app.services.notification_triggers import emit  # noqa: PLC0415

    try:
        async with db.begin_nested():
            await emit(db, **kwargs)
        await db.commit()
    except Exception:  # noqa: BLE001 — dzwonek nigdy nie cofa wysyłki
        logger.exception("[dl_match] dzwonek nie wyszedł")


async def _notify_target_recruiter(
    db: AsyncSession,
    *,
    job: Job,
    source: Job,
    candidate_id: int,
    user: User,
    stage: CandidateStage,
) -> None:
    """Prowadzący B wie, że DL wysłał mu osobę do klienta (i skąd)."""
    if job.recruiter_id is None or job.recruiter_id == user.id:
        return
    person = await _person(db, candidate_id)
    await _emit(
        db,
        user_id=job.recruiter_id,
        title=f"{user.name} wysłał(a) {person} do klienta — Match z {_job_label(source)}",
        message=f"{_job_label(job)} · osoba z przeglądu Delivery Leada w innej rekrutacji",
        ntype=NotificationType.stage_changed,
        related_entity_type="candidate_stage",
        related_entity_id=stage.id,
        link=f"/jobs/{job.id}?candidate={candidate_id}",
    )


async def _source_recruiter_id(
    db: AsyncSession, *, source: Job, candidate_id: int, user: User
) -> Optional[int]:
    """Kto prowadzi osobę w A: pierwszy, kto ją zweryfikował, bez niego —
    rekruter rekrutacji. Nigdy sam DL."""
    verifier = await db.scalar(
        select(CandidateStage.moved_by)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == source.id,
            CandidateStage.stage == PipelineStage.verified,
            CandidateStage.moved_by.is_not(None),
        )
        .order_by(CandidateStage.moved_at, CandidateStage.id)
        .limit(1)
    )
    for candidate_user in (verifier, source.recruiter_id):
        if candidate_user is not None and candidate_user != user.id:
            return int(candidate_user)
    return None


async def _notify_source_recruiter(
    db: AsyncSession,
    *,
    source: Job,
    candidate_id: int,
    user: User,
    sent_titles: list[str],
) -> None:
    """Rekruter z A daje znać kandydatowi (decyzja: zadanie, nie blokada)."""
    recipient = await _source_recruiter_id(
        db, source=source, candidate_id=candidate_id, user=user
    )
    if recipient is None or not sent_titles:
        return
    stage = await _latest_stage(db, candidate_id=candidate_id, job_id=source.id)
    person = await _person(db, candidate_id)
    await _emit(
        db,
        user_id=recipient,
        title=f"Daj znać: {person} poszła(-szedł) też do {len(sent_titles)} rekrutacji",
        message=(
            f"{user.name} wysłał(a) {person} z {_job_label(source)} także do: "
            + "; ".join(sent_titles)
            + ". Powiedz kandydatowi o tych rekrutacjach. Gdy zrezygnuje, zamknij "
            "kartę w tamtej rekrutacji z powodem „Kandydat zrezygnował”."
        ),
        ntype=NotificationType.stage_changed,
        related_entity_type="candidate_stage",
        related_entity_id=stage.id if stage is not None else None,
        link=f"/jobs/{source.id}?candidate={candidate_id}",
    )


@router.post("/dl-match/send", response_model=MatchSendResponse)
async def match_send(
    data: MatchSendRequest,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> MatchSendResponse:
    """Wyślij osobę z A do zaznaczonych rekrutacji — każda osobno, wynik per rekrutacja.

    Osoba musi być w A od „Zweryfikowany” wzwyż (po przeglądzie DL-a albo już
    wysłana) — Match nie zastępuje weryfikacji w rekrutacji, z której przychodzi.
    """
    await ensure_job_read_access(db, current_user, data.from_job_id)
    source = await db.get(Job, data.from_job_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej rekrutacji.")
    verified_in_source = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == data.candidate_id,
            CandidateStage.job_id == source.id,
            CandidateStage.stage == PipelineStage.verified,
        )
        .limit(1)
    )
    if verified_in_source is None:
        raise HTTPException(
            status_code=422,
            detail="Match wysyła osobę, która w tej rekrutacji jest już po weryfikacji.",
        )
    seen: set[int] = set()
    results: list[MatchSendResult] = []
    for target in data.targets:
        if target.job_id in seen or target.job_id == source.id:
            continue
        seen.add(target.job_id)
        results.append(
            await _send_one(
                db,
                user=current_user,
                candidate_id=data.candidate_id,
                source=source,
                target=target,
                remark=data.recruiter_remark,
            )
        )
    await _notify_source_recruiter(
        db,
        source=source,
        candidate_id=data.candidate_id,
        user=current_user,
        sent_titles=[r.title or f"#{r.job_id}" for r in results if r.status == "sent"],
    )
    return MatchSendResponse(
        candidate_id=data.candidate_id, from_job_id=source.id, results=results
    )
