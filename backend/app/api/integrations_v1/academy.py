"""Akademia w API v1: programy szkoleniowe i nabór (odczyt).

Scope ``academy:read``. Liczniki etapów, terminy w biurze i daty edycji
liczą te same funkcje co ekran ``/academy`` (``services/academy.status_counts``,
``api/academy.list_sessions``, ``academy_documents.program_dates``).

Uczestnicy (zgłoszenia) mają imię i nazwisko — jak profil z
``candidates:read`` — a e-mail i telefon wyłącznie z ``candidates:contact``
(bez niego ``null`` i ``contact_redacted = true``). Nie wychodzą: notatka
zgłoszenia, powód wykluczenia ani fakty i cytaty z sortowania Luny (wolny
tekst o osobie i treść CV). Ogłoszenia-źródła rekrutacji ukrytych albo
usuniętych klientów nie istnieją dla klucza (``jobs_register_base_clause``).

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import academy as academy_routes
from app.api.integrations_v1.common import (
    AcademyRead,
    IdPath,
    IntegrationRoute,
    Page,
    PageQuery,
    PageSizeQuery,
    page_of,
    principal_rate_key,
    read_rate_limit,
    sees_candidate_contact,
)
from app.api.jobs import jobs_register_base_clause
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.scheduling import business_today
from app.models.academy import (
    ACADEMY_ACTIVE_STATUSES,
    ACADEMY_STATUSES,
    AcademyApplication,
    AcademyProgram,
    AcademyProgramSource,
    AcademySession,
)
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.services import academy as academy_svc
from app.services.academy_documents import program_dates
from app.services.academy_flow import next_cohort

router = APIRouter(route_class=IntegrationRoute)

_PROGRAM_404 = "Nie ma takiej akademii."

AcademyStatus = Literal[
    "new",
    "to_call",
    "scheduled",
    "task_given",
    "task_passed",
    "contract_sent",
    "signed",
    "rejected",
    "withdrew",
]
#: Statusy zamknięte idą na koniec listy — jak na ekranie.
_CLOSED_STATUSES = ("rejected", "withdrew")


# ── Modele odpowiedzi ────────────────────────────────────────────────────────


class AcademyCountsOut(BaseModel):
    """Liczba zgłoszeń na etapie przepływu (jak liczniki ekranu)."""

    by_status: dict[str, int] = Field(
        description="new · to_call · scheduled · task_given · task_passed · "
        "contract_sent · signed · rejected · withdrew"
    )
    total: int
    in_progress: int = Field(description="Osoby w toku (od „new” do „contract_sent”).")
    luna_skipped: int = Field(
        description="„new” odłożone przez sortowanie — czekają na decyzję człowieka."
    )
    unscreened: int = Field(description="„new” jeszcze nieposortowane.")
    reapplied_excluded: int = Field(
        description="Wykluczeni, którzy zgłosili się ponownie (nie wracają do naboru)."
    )


class CohortOut(BaseModel):
    month: date = Field(description="Pierwszy dzień miesiąca edycji.")
    program_start: date
    program_end: date = Field(description="10. dzień roboczy od startu.")


class CohortCountOut(CohortOut):
    contract_sent: int
    signed: int


class AcademyProgramOut(BaseModel):
    id: int
    name: str
    is_active: bool
    max_experience_years: int = Field(
        description="Limit lat doświadczenia liczonego od końca studiów."
    )
    require_polish: bool
    luna_enabled: bool
    call_questions: list[str] = Field(description="Pytania na telefon.")
    session_capacity: int
    task_due_days: int
    sources_count: int = Field(description="Ogłoszenia-źródła widoczne dla klucza.")
    counts: AcademyCountsOut
    next_cohort: CohortOut
    created_at: datetime
    updated_at: datetime


class AcademySourceOut(BaseModel):
    job_id: int
    title: str
    status: str
    since: Optional[date] = Field(description="Zgłoszenia starsze nie wpadają.")
    applicants: int = Field(description="Osoby z wierszem etapu w ogłoszeniu.")


class AcademySessionOut(BaseModel):
    id: int
    starts_at: datetime
    location: Optional[str]
    capacity: int
    taken: int = Field(description="Zajęte miejsca (zapisani na spotkanie).")
    people: int
    cancelled: bool


class AcademyProgramDetailOut(AcademyProgramOut):
    sources: list[AcademySourceOut]
    sessions: list[AcademySessionOut] = Field(
        description="Terminy w biurze od 14 dni wstecz (jak ekran)."
    )
    cohorts: list[CohortCountOut] = Field(
        description="Edycje z przypisanymi osobami (umowa wysłana lub podpisana)."
    )


class AcademyParticipantOut(BaseModel):
    application_id: int
    candidate_id: int
    first_name: Optional[str]
    last_name: Optional[str]
    status: str
    screening_verdict: Optional[str] = Field(description="call | review | skip")
    source_job_id: Optional[int]
    applied_at: datetime
    reapplied_at: Optional[datetime]
    call_attempts: int
    last_call_at: Optional[datetime]
    session_id: Optional[int]
    session_starts_at: Optional[datetime]
    attended: Optional[bool]
    task_due: Optional[date]
    task_result: Optional[str] = Field(description="passed | failed")
    contract_sent_at: Optional[datetime]
    signed_at: Optional[datetime]
    cohort_month: Optional[date]
    closed_stage: Optional[str]
    closed_at: Optional[datetime]
    contact_redacted: bool
    email: Optional[str] = Field(description="Tylko z candidates:contact.")
    phone: Optional[str] = Field(description="Tylko z candidates:contact.")


# ── Pomocnicze ───────────────────────────────────────────────────────────────


def counts_out(raw: dict) -> AcademyCountsOut:
    by_status = {status: int(raw.get(status, 0)) for status in ACADEMY_STATUSES}
    return AcademyCountsOut(
        by_status=by_status,
        total=sum(by_status.values()),
        in_progress=sum(by_status[s] for s in ACADEMY_ACTIVE_STATUSES),
        luna_skipped=int(raw.get("luna_skipped", 0)),
        unscreened=int(raw.get("unscreened", 0)),
        reapplied_excluded=int(raw.get("reapplied_excluded", 0)),
    )


def cohort_out(month: date) -> CohortOut:
    start, end = program_dates(month)
    return CohortOut(month=month, program_start=start, program_end=end)


def participant_out(
    row: AcademyApplication,
    *,
    first_name: Optional[str],
    last_name: Optional[str],
    email: Optional[str],
    phone: Optional[str],
    session_starts_at: Optional[datetime],
    contact: bool,
    source_visible: bool,
) -> AcademyParticipantOut:
    return AcademyParticipantOut(
        application_id=row.id,
        candidate_id=row.candidate_id,
        first_name=first_name,
        last_name=last_name,
        status=row.status,
        screening_verdict=row.screening_verdict,
        # Ogłoszenie klienta ukrytego albo usuniętego nie istnieje dla klucza
        # (jak źródła programu w ``_visible_sources``).
        source_job_id=row.source_job_id if source_visible else None,
        applied_at=row.applied_at,
        reapplied_at=row.reapplied_at,
        call_attempts=row.call_attempts,
        last_call_at=row.last_call_at,
        session_id=row.session_id,
        session_starts_at=session_starts_at,
        attended=row.attended,
        task_due=row.task_due,
        task_result=row.task_result,
        contract_sent_at=row.contract_sent_at,
        signed_at=row.signed_at,
        cohort_month=row.cohort_month,
        closed_stage=row.closed_stage,
        closed_at=row.closed_at,
        contact_redacted=not contact,
        email=email if contact else None,
        phone=phone if contact else None,
    )


async def _program_or_404(db: AsyncSession, program_id: int) -> AcademyProgram:
    program = await db.get(AcademyProgram, program_id)
    if program is None:
        raise HTTPException(404, detail=_PROGRAM_404)
    return program


async def _visible_sources(db: AsyncSession, program_id: int) -> list:
    return list(
        (
            await db.execute(
                select(AcademyProgramSource, Job.title, Job.status)
                .join(Job, Job.id == AcademyProgramSource.job_id)
                .where(
                    AcademyProgramSource.program_id == program_id,
                    jobs_register_base_clause(),
                )
                .order_by(AcademyProgramSource.added_at)
            )
        ).all()
    )


async def _program_out(
    db: AsyncSession, program: AcademyProgram, *, today: date
) -> dict:
    sources = await db.scalar(
        select(func.count())
        .select_from(AcademyProgramSource)
        .join(Job, Job.id == AcademyProgramSource.job_id)
        .where(
            AcademyProgramSource.program_id == program.id,
            jobs_register_base_clause(),
        )
    )
    return {
        "id": program.id,
        "name": program.name,
        "is_active": program.is_active,
        "max_experience_years": program.max_experience_years,
        "require_polish": program.require_polish,
        "luna_enabled": program.luna_enabled,
        "call_questions": [str(q) for q in (program.conditions or [])],
        "session_capacity": program.session_capacity,
        "task_due_days": program.task_due_days,
        "sources_count": int(sources or 0),
        "counts": counts_out(await academy_svc.status_counts(db, program.id)),
        "next_cohort": cohort_out(next_cohort(today)),
        "created_at": program.created_at,
        "updated_at": program.updated_at,
    }


# ── Trasy ────────────────────────────────────────────────────────────────────


@router.get(
    "/academy/programs",
    response_model=Page[AcademyProgramOut],
    summary="Programy akademii z licznikami naboru",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_programs(
    request: Request,
    _caller: AcademyRead,
    db: AsyncSession = Depends(get_db),
    is_active: Optional[bool] = Query(None, description="Tylko aktywne / nieaktywne."),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 100,
):
    """Programy (najpierw aktywne, potem po nazwie): kryteria naboru, liczba
    zgłoszeń na każdym etapie i daty najbliższej edycji. Bez danych osobowych."""
    query = select(AcademyProgram)
    if is_active is not None:
        query = query.where(AcademyProgram.is_active.is_(is_active))
    total = int(
        await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    )
    programs = (
        (
            await db.execute(
                query.order_by(
                    AcademyProgram.is_active.desc(),
                    AcademyProgram.name,
                    AcademyProgram.id,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    today = business_today()
    items = []
    for program in programs:
        items.append(AcademyProgramOut(**await _program_out(db, program, today=today)))
    return page_of(items, page=page, page_size=page_size, total=total)


@router.get(
    "/academy/programs/{program_id}",
    response_model=AcademyProgramDetailOut,
    summary="Program akademii: źródła, terminy w biurze, edycje",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_program(
    request: Request,
    program_id: IdPath,
    _caller: AcademyRead,
    db: AsyncSession = Depends(get_db),
) -> AcademyProgramDetailOut:
    """Program z ogłoszeniami-źródłami (liczba osób w każdym), terminami
    spotkań w biurze (zajęte miejsca) i edycjami, do których przypisano osoby
    (umowa wysłana / podpisana). Uczestnicy: ``/participants``."""
    program = await _program_or_404(db, program_id)
    today = business_today()
    sources = []
    for source, title, status in await _visible_sources(db, program_id):
        applicants = await db.scalar(
            select(func.count(func.distinct(CandidateStage.candidate_id))).where(
                CandidateStage.job_id == source.job_id
            )
        )
        sources.append(
            AcademySourceOut(
                job_id=source.job_id,
                title=title,
                status=str(getattr(status, "value", status)),
                since=source.since,
                applicants=int(applicants or 0),
            )
        )
    sessions = await academy_routes.list_sessions(
        program_id, current_user=None, upcoming=True, db=db
    )
    cohort_rows = (
        await db.execute(
            select(
                AcademyApplication.cohort_month,
                func.count().filter(AcademyApplication.status == "contract_sent"),
                func.count().filter(AcademyApplication.status == "signed"),
            )
            .where(
                AcademyApplication.program_id == program_id,
                AcademyApplication.cohort_month.is_not(None),
                AcademyApplication.status.in_(("contract_sent", "signed")),
            )
            .group_by(AcademyApplication.cohort_month)
            .order_by(AcademyApplication.cohort_month)
        )
    ).all()
    return AcademyProgramDetailOut(
        **await _program_out(db, program, today=today),
        sources=sources,
        sessions=[AcademySessionOut(**item) for item in sessions["items"]],
        cohorts=[
            CohortCountOut(
                **cohort_out(month).model_dump(),
                contract_sent=int(sent or 0),
                signed=int(signed or 0),
            )
            for month, sent, signed in cohort_rows
        ],
    )


@router.get(
    "/academy/programs/{program_id}/participants",
    response_model=Page[AcademyParticipantOut],
    summary="Uczestnicy naboru (zgłoszenia) — kontakt tylko z candidates:contact",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_participants(
    request: Request,
    program_id: IdPath,
    caller: AcademyRead,
    db: AsyncSession = Depends(get_db),
    status: Optional[list[AcademyStatus]] = Query(None),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 100,
):
    """Zgłoszenia programu w kolejności ekranu: najpierw osoby w toku, potem
    zamknięte; w obu grupach najnowsze pierwsze. Imię i nazwisko, etap
    i daty przepływu; e-mail i telefon tylko z ``candidates:contact``."""
    await _program_or_404(db, program_id)
    contact = sees_candidate_contact(caller)
    filters = [AcademyApplication.program_id == program_id]
    if status:
        filters.append(AcademyApplication.status.in_(sorted(set(status))))
    total = int(
        await db.scalar(
            select(func.count()).select_from(AcademyApplication).where(*filters)
        )
        or 0
    )
    closed_last = case((AcademyApplication.status.in_(_CLOSED_STATUSES), 1), else_=0)
    rows = (
        await db.execute(
            select(
                AcademyApplication,
                Candidate.name,
                Candidate.lastname,
                Candidate.email,
                Candidate.phone,
                AcademySession.starts_at,
            )
            .join(Candidate, Candidate.id == AcademyApplication.candidate_id)
            .outerjoin(
                AcademySession, AcademySession.id == AcademyApplication.session_id
            )
            .where(*filters)
            .order_by(
                closed_last,
                AcademyApplication.applied_at.desc(),
                AcademyApplication.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    source_ids = {row.source_job_id for row, *_ in rows if row.source_job_id}
    listed_sources = (
        set(
            await db.scalars(
                select(Job.id).where(
                    Job.id.in_(source_ids), jobs_register_base_clause()
                )
            )
        )
        if source_ids
        else set()
    )
    items = [
        participant_out(
            row,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            session_starts_at=starts_at,
            contact=contact,
            source_visible=row.source_job_id in listed_sources,
        )
        for row, first_name, last_name, email, phone, starts_at in rows
    ]
    return page_of(items, page=page, page_size=page_size, total=total)
