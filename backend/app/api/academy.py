# UWAGA: bez `from __future__ import annotations` — `@limiter.limit` na
# funkcji z adnotacjami jako stringami (PEP 563) sprawia, że slowapi nie widzi
# typów zależności i ciało żądania ląduje jako parametr query (slowapi #579).
"""Router `/api/academy` — nabór do akademii (0369).

Przepływ: ogłoszenia → sortowanie Luny → telefon z zapisem na termin
w biurze → spotkanie → zadanie → umowa → edycja od 1. dnia miesiąca.
Logika: ``services/academy.py`` (baza), ``academy_rules`` (sortowanie),
``academy_flow`` (przejścia).

Bramki: sekcja Pipeline (router) + ``RecruiterPlus`` na pracę z ludźmi
i terminami. Program, jego kryteria i ogłoszenia-źródła zmienia admin
albo Head of Recruitment (``HeadOfRecruitmentPlus``) — to one decydują,
kogo system w ogóle bierze pod uwagę.
"""

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus, RecruiterPlus
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.activity import Activity
from app.models.academy import (
    AcademyApplication,
    AcademyProgram,
    AcademyProgramSource,
    AcademySession,
)
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.services import academy as svc
from app.services import academy_documents as docs
from app.services.academy_flow import (
    ACTIONS,
    AcademyActionError,
    ActionInput,
    next_cohort,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

_MANAGER_ROLES = (UserRole.admin, UserRole.head_of_recruitment)
BULK_MAX = 200
CONDITIONS_MAX = 8


def _can_manage(user: User) -> bool:
    return user.has_any_role(*_MANAGER_ROLES)


def _clean_conditions(value: list[str]) -> list[str]:
    cleaned = [" ".join(str(v).split())[:200] for v in value if str(v).strip()]
    if len(cleaned) > CONDITIONS_MAX:
        raise ValueError(f"Najwyżej {CONDITIONS_MAX} pytań na telefon.")
    return cleaned


# ── schematy ───────────────────────────────────────────────────────────────


class ProgramInput(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    is_active: bool = True
    max_experience_years: int = Field(default=6, ge=0, le=40)
    require_polish: bool = True
    luna_enabled: bool = True
    conditions: list[str] = Field(default_factory=list)
    session_capacity: int = Field(default=8, ge=1, le=200)
    task_due_days: int = Field(default=5, ge=1, le=60)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("conditions")
    @classmethod
    def _valid_conditions(cls, value: list[str]) -> list[str]:
        return _clean_conditions(value)


class ProgramPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    is_active: Optional[bool] = None
    max_experience_years: Optional[int] = Field(default=None, ge=0, le=40)
    require_polish: Optional[bool] = None
    luna_enabled: Optional[bool] = None
    conditions: Optional[list[str]] = None
    session_capacity: Optional[int] = Field(default=None, ge=1, le=200)
    task_due_days: Optional[int] = Field(default=None, ge=1, le=60)

    @field_validator("conditions")
    @classmethod
    def _valid_conditions(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return None if value is None else _clean_conditions(value)


class SourceInput(BaseModel):
    job_id: int
    since: Optional[date] = None


class ActionBody(BaseModel):
    action: Literal[ACTIONS]  # type: ignore[valid-type]
    reason: Optional[str] = Field(default=None, max_length=500)
    session_id: Optional[int] = None
    task_due: Optional[date] = None
    cohort_month: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=2000)

    def to_input(self) -> ActionInput:
        return ActionInput(
            action=self.action,
            reason=self.reason,
            session_id=self.session_id,
            task_due=self.task_due,
            cohort_month=self.cohort_month,
            note=self.note,
        )


class BulkBody(ActionBody):
    ids: list[int] = Field(min_length=1, max_length=BULK_MAX)


class SessionInput(BaseModel):
    starts_at: datetime
    location: Optional[str] = Field(default=None, max_length=255)
    capacity: Optional[int] = Field(default=None, ge=1, le=200)


class RhythmInput(BaseModel):
    """Stały rytm spotkań: dni tygodnia (0 = poniedziałek) o jednej godzinie."""

    weekdays: list[int] = Field(min_length=1, max_length=7)
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    weeks: int = Field(default=2, ge=1, le=8)
    start_date: Optional[date] = None
    location: Optional[str] = Field(default=None, max_length=255)
    capacity: Optional[int] = Field(default=None, ge=1, le=200)

    @field_validator("weekdays")
    @classmethod
    def _valid_days(cls, value: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in value):
            raise ValueError("Dni tygodnia: 0 (poniedziałek) … 6 (niedziela).")
        return sorted(set(value))


class DocumentsBody(BaseModel):
    """Dane do kompletu dokumentów. PESEL i adres NIE są zapisywane w bazie."""

    signing_date: Optional[date] = None
    address: Optional[str] = Field(default=None, max_length=300)
    pesel: Optional[str] = Field(default=None, max_length=11)
    program_start: Optional[date] = None
    program_end: Optional[date] = None
    handover_name: Optional[str] = Field(default=None, max_length=200)
    protocol_date: Optional[date] = None


DOCUMENT_STATUSES = ("task_passed", "contract_sent", "signed")


def _cohort_payload(month: date) -> dict:
    start, end = docs.program_dates(month)
    return {"month": month, "start": start, "end": end}


class SessionPatch(BaseModel):
    cancelled: Optional[bool] = None
    location: Optional[str] = Field(default=None, max_length=255)
    capacity: Optional[int] = Field(default=None, ge=1, le=200)


# ── pomocnicze ─────────────────────────────────────────────────────────────


async def _program_or_404(db: AsyncSession, program_id: int) -> AcademyProgram:
    program = await db.get(AcademyProgram, program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej akademii.")
    return program


def _program_dict(program: AcademyProgram) -> dict:
    return {
        "id": program.id,
        "name": program.name,
        "is_active": program.is_active,
        "max_experience_years": program.max_experience_years,
        "require_polish": program.require_polish,
        "luna_enabled": program.luna_enabled,
        "conditions": list(program.conditions or []),
        "session_capacity": program.session_capacity,
        "task_due_days": program.task_due_days,
        "created_at": program.created_at,
    }


def _action_error(exc: AcademyActionError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}
    )


async def _row_payload(db: AsyncSession, application_id: int) -> dict:
    rows = await svc.list_applications_by_ids(db, [application_id])
    return rows[0] if rows else {}


# ── programy ───────────────────────────────────────────────────────────────


@router.get("/programs")
async def list_programs(
    current_user: RecruiterPlus, db: AsyncSession = Depends(get_db)
):
    programs = (
        (
            await db.execute(
                select(AcademyProgram).order_by(
                    AcademyProgram.is_active.desc(), AcademyProgram.name
                )
            )
        )
        .scalars()
        .all()
    )
    items = []
    for program in programs:
        counts = await svc.status_counts(db, program.id)
        sources = await db.scalar(
            select(func.count()).where(AcademyProgramSource.program_id == program.id)
        )
        items.append(
            {
                **_program_dict(program),
                "counts": counts,
                "sources_count": int(sources or 0),
            }
        )
    return {"items": items, "can_manage": _can_manage(current_user)}


@router.post("/programs", status_code=201)
async def create_program(
    body: ProgramInput,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    program = AcademyProgram(**body.model_dump(), created_by=current_user.id)
    db.add(program)
    await db.commit()
    await db.refresh(program)
    return _program_dict(program)


@router.get("/programs/{program_id}")
async def get_program(
    program_id: int, current_user: RecruiterPlus, db: AsyncSession = Depends(get_db)
):
    program = await _program_or_404(db, program_id)
    source_rows = (
        await db.execute(
            select(AcademyProgramSource, Job.title, Job.status)
            .join(Job, Job.id == AcademyProgramSource.job_id)
            .where(AcademyProgramSource.program_id == program_id)
            .order_by(AcademyProgramSource.added_at)
        )
    ).all()
    sources = []
    for source, title, status in source_rows:
        applicants = await db.scalar(
            select(func.count(func.distinct(CandidateStage.candidate_id))).where(
                CandidateStage.job_id == source.job_id
            )
        )
        sources.append(
            {
                "job_id": source.job_id,
                "title": title,
                "status": getattr(status, "value", status),
                "since": source.since,
                "applicants": int(applicants or 0),
            }
        )
    return {
        **_program_dict(program),
        "sources": sources,
        "counts": await svc.status_counts(db, program_id),
        "can_manage": _can_manage(current_user),
        "next_cohort": _cohort_payload(next_cohort(business_today())),
    }


@router.patch("/programs/{program_id}")
async def update_program(
    program_id: int,
    body: ProgramPatch,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    program = await _program_or_404(db, program_id)
    criteria_before = svc.screening_criteria(program)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(program, key, value)
    rescreen = svc.screening_criteria(program) != criteria_before
    if rescreen:
        # Runda 8 (R8-N2-2): odłożeni według starego limitu/wymogu wracają do
        # sortowania — „Zatwierdź” nie wykluczy ich według kryterium, którego
        # już nie ma.
        await svc.reset_stale_skips(db, program)
    await db.commit()
    await db.refresh(program)
    if rescreen:
        svc.start_screening(program_id)
    return _program_dict(program)


@router.post("/programs/{program_id}/sources", status_code=201)
async def add_source(
    program_id: int,
    body: SourceInput,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    await _program_or_404(db, program_id)
    if await db.get(Job, body.job_id) is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej rekrutacji.")
    existing = await db.get(AcademyProgramSource, (program_id, body.job_id))
    if existing is not None:
        existing.since = body.since
    else:
        db.add(
            AcademyProgramSource(
                program_id=program_id,
                job_id=body.job_id,
                since=body.since,
                added_by=current_user.id,
            )
        )
    await db.commit()
    return {"program_id": program_id, "job_id": body.job_id, "since": body.since}


@router.delete("/programs/{program_id}/sources/{job_id}", status_code=204)
async def remove_source(
    program_id: int,
    job_id: int,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    source = await db.get(AcademyProgramSource, (program_id, job_id))
    if source is not None:
        await db.delete(source)
        await db.commit()


@router.get("/jobs")
async def search_source_jobs(
    current_user: HeadOfRecruitmentPlus,
    q: str = Query(default="", max_length=100),
    db: AsyncSession = Depends(get_db),
):
    """Podpowiedzi rekrutacji-ogłoszeń do podpięcia jako źródło."""
    stmt = select(Job.id, Job.title, Job.status, Job.external_source, Job.created_at)
    text = q.strip()
    if text:
        if text.isdigit():
            stmt = stmt.where(Job.id == int(text))
        else:
            escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(Job.title.ilike(f"%{escaped}%"))
    rows = (await db.execute(stmt.order_by(Job.created_at.desc()).limit(20))).all()
    return {
        "items": [
            {
                "id": r.id,
                "title": r.title,
                "status": getattr(r.status, "value", r.status),
                "external_source": r.external_source,
            }
            for r in rows
        ]
    }


@router.post("/programs/{program_id}/sync")
@limiter.limit("6/minute", key_func=user_or_ip_key)
async def sync_program(
    request: Request,
    program_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz zgłoszenia z ogłoszeń teraz; Luna sortuje je w tle.

    Sortowanie to do 25 wywołań modelu po kolei — w żądaniu przekroczyłoby
    limit czasu przeglądarki, a backend pracowałby dalej z założoną blokadą.
    """
    await _program_or_404(db, program_id)
    await db.commit()  # nie trzymaj połączenia na czas naboru
    stats = await svc.intake_now(program_id)
    if stats is None:
        return {"busy": True, "message": "Pobieranie już trwa — odśwież za chwilę."}
    svc.start_screening(program_id)
    return {"busy": False, "screening": True, **stats}


# ── zgłoszenia ─────────────────────────────────────────────────────────────


@router.get("/programs/{program_id}/applications")
async def list_applications(
    program_id: int,
    current_user: RecruiterPlus,
    status: list[str] = Query(default=[]),
    q: Optional[str] = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    await _program_or_404(db, program_id)
    items, total = await svc.list_applications(
        db, program_id, statuses=status or None, q=q
    )
    return {
        "items": items,
        "total": total,
        "truncated": total > len(items),
        "counts": await svc.status_counts(db, program_id),
    }


@router.post("/applications/{application_id}/actions")
async def application_action(
    application_id: int,
    body: ActionBody,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(AcademyApplication, application_id, with_for_update=True)
    if row is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego zgłoszenia.")
    program = await _program_or_404(db, row.program_id)
    try:
        await svc.perform_action(
            db,
            row=row,
            program=program,
            action=body.to_input(),
            user_id=current_user.id,
        )
    except AcademyActionError as exc:
        raise _action_error(exc) from None
    await db.commit()
    return await _row_payload(db, application_id)


@router.get("/cohort-dates")
async def cohort_dates(
    current_user: RecruiterPlus,
    month: date = Query(...),
):
    """Domyślne daty edycji: 10 dni roboczych od 1. dnia roboczego miesiąca."""
    return _cohort_payload(date(month.year, month.month, 1))


@router.post("/applications/{application_id}/documents")
async def application_documents(
    application_id: int,
    body: DocumentsBody,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Komplet dokumentów uczestnika (ZIP): umowa, harmonogram, oświadczenie,
    regulamin, protokół przekazania Manuala.

    PESEL i adres idą wyłącznie do pliku — nie trafiają do bazy ani do logu.
    """
    row = await db.get(AcademyApplication, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego zgłoszenia.")
    if row.status not in DOCUMENT_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Dokumenty generujemy po zaliczonym zadaniu.",
        )
    pesel = (body.pesel or "").strip() or None
    if pesel is not None and not docs.pesel_valid(pesel):
        raise HTTPException(status_code=422, detail="PESEL jest niepoprawny.")
    month = row.cohort_month or next_cohort(business_today())
    default_start, default_end = docs.program_dates(month)
    start = body.program_start or default_start
    end = body.program_end or default_end
    if end < start:
        raise HTTPException(
            status_code=422, detail="Koniec programu nie może być przed początkiem."
        )
    candidate = await db.get(Candidate, row.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego kandydata.")
    full_name = f"{candidate.name or ''} {candidate.lastname or ''}".strip()
    data = docs.DocumentInput(
        participant_name=full_name,
        phone=candidate.phone,
        email=candidate.email,
        address=body.address,
        pesel=pesel,
        signing_date=body.signing_date,
        program_start=start,
        program_end=end,
        handover_name=body.handover_name,
        protocol_date=body.protocol_date,
    )
    # Pięć DOCX-ów renderuje się synchronicznie — poza pętlą zdarzeń.
    payload = await asyncio.to_thread(docs.render_package, data)
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=row.candidate_id,
            action="academy_documents",
            user_id=current_user.id,
            details={
                "program_id": row.program_id,
                "program_start": start.isoformat(),
                "program_end": end.isoformat(),
            },
        )
    )
    await db.commit()
    filename = f"Akademia_dokumenty_{docs.file_stem(full_name)}.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/programs/{program_id}/applications/bulk")
async def bulk_action(
    program_id: int,
    body: BulkBody,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Ta sama akcja na wielu osobach (np. „Zatwierdź odłożone przez Lunę”).

    Każdy wiersz w savepoincie — odmowa jednego nie cofa pozostałych.
    """
    program = await _program_or_404(db, program_id)
    done: list[int] = []
    failed: list[dict] = []
    rescreen = False
    # Stała kolejność blokad — dwa nakładające się wywołania nie zakleszczą się.
    for application_id in sorted(set(body.ids)):
        row = await db.get(AcademyApplication, application_id, with_for_update=True)
        if row is None or row.program_id != program_id:
            failed.append(
                {"id": application_id, "message": "Nie ma takiego zgłoszenia."}
            )
            continue
        action = body.to_input()
        if body.action == "reject" and not (body.reason or "").strip():
            # „Zatwierdź odłożone przez Lunę”: powód = powody sortowania.
            # Lista w przeglądarce bywa nieaktualna (odświeża się co 2 min),
            # a odrzucenie jest trwałe — pod blokadą wiersza sprawdzamy, że
            # osoba NADAL czeka odłożona przez Lunę. Kogoś, kogo ktoś w
            # międzyczasie przywrócił albo umówił, nie wykluczamy.
            if row.status != "new" or row.screening_verdict != "skip":
                failed.append(
                    {
                        "id": application_id,
                        "message": (
                            "Ta osoba nie czeka już odłożona przez Lunę — ktoś "
                            "ją przesunął. Nie wykluczono jej."
                        ),
                    }
                )
                continue
            if not svc.skip_is_current(row.screening, program):
                # R8-N2-2: werdykt policzony starymi regułami albo kryteriami
                # programu — sortujemy od nowa zamiast wykluczać na zawsze.
                svc.clear_screening(row)
                rescreen = True
                failed.append(
                    {
                        "id": application_id,
                        "message": (
                            "Kryteria sortowania zmieniły się od decyzji Luny — "
                            "posortuje tę osobę ponownie. Nie wykluczono jej."
                        ),
                    }
                )
                continue
            reasons = [
                r.get("text")
                for r in ((row.screening or {}).get("reasons") or [])
                if isinstance(r, dict)
                and r.get("code") in ("experience_over", "polish_basic")
            ]
            action = ActionInput(
                action="reject", reason="; ".join(t for t in reasons if t) or None
            )
        try:
            async with db.begin_nested():
                await svc.perform_action(
                    db, row=row, program=program, action=action, user_id=current_user.id
                )
            done.append(application_id)
        except AcademyActionError as exc:
            failed.append({"id": application_id, "message": exc.message})
    await db.commit()
    if rescreen:
        svc.start_screening(program_id)
    return {"done": done, "failed": failed}


# ── terminy w biurze ───────────────────────────────────────────────────────


@router.get("/programs/{program_id}/sessions")
async def list_sessions(
    program_id: int,
    current_user: RecruiterPlus,
    upcoming: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
):
    await _program_or_404(db, program_id)
    since = None
    if upcoming:
        tz = ZoneInfo(DEFAULT_TZ)
        since = datetime.combine(
            business_today() - timedelta(days=14), time(0), tzinfo=tz
        )
    return {"items": await svc.sessions_with_counts(db, program_id, since=since)}


@router.post("/programs/{program_id}/sessions", status_code=201)
async def create_session(
    program_id: int,
    body: SessionInput,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    program = await _program_or_404(db, program_id)
    starts_at = body.starts_at
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=ZoneInfo(DEFAULT_TZ))
    session = AcademySession(
        program_id=program_id,
        starts_at=starts_at,
        location=(body.location or "").strip() or None,
        capacity=body.capacity or program.session_capacity,
        created_by=current_user.id,
    )
    db.add(session)
    await db.commit()
    return {"id": session.id}


@router.post("/programs/{program_id}/sessions/rhythm", status_code=201)
async def create_rhythm(
    program_id: int,
    body: RhythmInput,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Załóż terminy wg stałego rytmu (np. pon/śr/czw 10:00 na 2 tygodnie)."""
    program = await _program_or_404(db, program_id)
    tz = ZoneInfo(DEFAULT_TZ)
    hour, minute = (int(part) for part in body.time.split(":"))
    if hour > 23 or minute > 59:
        raise HTTPException(status_code=422, detail="Niepoprawna godzina.")
    start = body.start_date or business_today()
    existing = set(
        (
            await db.execute(
                select(AcademySession.starts_at).where(
                    AcademySession.program_id == program_id,
                    AcademySession.cancelled_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    existing_local = {value.astimezone(tz).replace(tzinfo=None) for value in existing}
    created = 0
    now_local = datetime.now(tz)
    for offset in range(body.weeks * 7):
        day = start + timedelta(days=offset)
        if day.weekday() not in body.weekdays:
            continue
        local = datetime.combine(day, time(hour, minute))
        if local in existing_local or local.replace(tzinfo=tz) <= now_local:
            continue
        db.add(
            AcademySession(
                program_id=program_id,
                starts_at=local.replace(tzinfo=tz),
                location=(body.location or "").strip() or None,
                capacity=body.capacity or program.session_capacity,
                created_by=current_user.id,
            )
        )
        created += 1
    await db.commit()
    return {"created": created}


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: int,
    body: SessionPatch,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(AcademySession, session_id, with_for_update=True)
    if session is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego terminu.")
    data = body.model_dump(exclude_unset=True)
    if data.get("cancelled") is True and session.cancelled_at is None:
        people = await svc.session_taken(db, session_id)
        if people:
            raise HTTPException(
                status_code=409,
                detail=f"Na ten termin są zapisane osoby ({people}) — najpierw przenieś je na inny.",
            )
        session.cancelled_at = datetime.now(ZoneInfo(DEFAULT_TZ))
    elif data.get("cancelled") is False:
        session.cancelled_at = None
    if "location" in data:
        session.location = (data["location"] or "").strip() or None
    if data.get("capacity") is not None:
        session.capacity = data["capacity"]
    await db.commit()
    return {"id": session.id, "cancelled": session.cancelled_at is not None}
