"""Ustawienia → Bezpieczeństwo (0800): przegląd, znaleziska, rutyny — tylko admin.

Każda trasa za ``AdminUser`` (bramka sekcji niepotrzebna: admin ma zapis
w każdej sekcji, ``test_section_ceiling_contract``). Źródła wysyłają dane
osobnym wejściem na klucz API (``api/security_ingest.py``).

Wyjątek („Wyjątek do…”) wymaga powodu i daty w przyszłości (najwyżej rok);
po terminie znalezisko wraca na listę „Czeka na reakcję”. Każda zmiana stanu
zostawia zdarzenie ``nexus`` bez danych osobowych — kto, mówią kolumny
znaleziska (``exception_by_user_id``, ``closed_by_user_id``).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.security import SecurityEvent, SecurityFinding, SecurityRoutine
from app.models.user import User, UserRole
from app.services.security_defender import finding_link
from app.services.security_screen import (
    MAX_EXCEPTION_DAYS,
    SEVERITY_RANK,
    SourceRow,
    build_overview,
    effective_status,
    mark_routine_done,
    routine_state,
)

router = APIRouter()


# ── Schematy ─────────────────────────────────────────────────────────────────


class SecurityFindingOut(BaseModel):
    id: int
    source: str
    scanner: Optional[str]
    severity: str
    title: str
    location: Optional[str]
    evidence: Optional[str]
    impact: Optional[str]
    steps: list[str]
    status: str
    stored_status: str
    exception_expired: bool
    owner_user_id: Optional[int]
    exception_reason: Optional[str]
    exception_until: Optional[date]
    closed_note: Optional[str]
    closed_at: Optional[datetime]
    first_seen_at: datetime
    last_seen_at: datetime
    # Źródło z własnym portalem (Defender: incydent w security.microsoft.com).
    link: Optional[str] = None


class SecurityEventOut(BaseModel):
    id: int
    source: str
    kind: str
    severity: str
    summary: str
    count: int
    link: Optional[str]
    occurred_at: datetime


class SecurityRoutineOut(BaseModel):
    id: int
    key: str
    title: str
    cadence: str
    owner_label: str
    automatic: bool
    last_done_on: Optional[date]
    next_due_on: date
    last_note: Optional[str]
    state: Literal["ok", "soon", "overdue"]


class SecuritySourceOut(BaseModel):
    key: str
    name: str
    where: str
    state: str
    state_label: str
    last_at: Optional[datetime]
    last_on: Optional[date]
    detail: Optional[str]
    link: Optional[str]


class SecurityOwnerOut(BaseModel):
    id: int
    name: str


class SecurityOverviewOut(BaseModel):
    today: date
    workflow_url: str
    tiles: dict
    waiting: list[SecurityFindingOut]
    excepted: list[SecurityFindingOut]
    recently_closed: list[SecurityFindingOut]
    events: list[SecurityEventOut]
    sources: list[SecuritySourceOut]
    routines_overdue: int
    owners: list[SecurityOwnerOut]


class SecurityOwnerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_user_id: Optional[int] = None


class SecurityExceptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=1000)
    until: date

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Powód wyjątku musi mieć co najmniej 10 znaków")
        return value


class SecurityCloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = Field(default=None, max_length=1000)


class SecurityRoutineDoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    done_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=1000)


# ── Pomocnicze ───────────────────────────────────────────────────────────────


def _finding_out(row: SecurityFinding, today: date) -> SecurityFindingOut:
    status = effective_status(row, today)
    return SecurityFindingOut(
        id=row.id,
        source=row.source,
        scanner=row.scanner,
        severity=row.severity,
        title=row.title,
        location=row.location,
        evidence=row.evidence,
        impact=row.impact,
        steps=list(row.steps or []),
        status=status,
        stored_status=row.status,
        exception_expired=row.status == "excepted" and status == "open",
        owner_user_id=row.owner_user_id,
        exception_reason=row.exception_reason,
        exception_until=row.exception_until,
        closed_note=row.closed_note,
        closed_at=row.closed_at,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        link=finding_link(row.source, row.fingerprint),
    )


def _event_out(row: SecurityEvent) -> SecurityEventOut:
    return SecurityEventOut(
        id=row.id,
        source=row.source,
        kind=row.kind,
        severity=row.severity,
        summary=row.summary,
        count=row.count,
        link=row.link,
        occurred_at=row.occurred_at,
    )


def _routine_out(row: SecurityRoutine, today: date) -> SecurityRoutineOut:
    return SecurityRoutineOut(
        id=row.id,
        key=row.key,
        title=row.title,
        cadence=row.cadence,
        owner_label=row.owner_label,
        automatic=row.auto_source is not None,
        last_done_on=row.last_done_on,
        next_due_on=row.next_due_on,
        last_note=row.last_note,
        state=routine_state(row, today),
    )


def _source_out(row: SourceRow) -> SecuritySourceOut:
    return SecuritySourceOut(**row.__dict__)


async def _admins(db: AsyncSession) -> list[SecurityOwnerOut]:
    rows = await db.execute(
        select(User.id, User.name)
        .where(
            User.is_active.is_(True),
            or_(User.role == UserRole.admin, User.roles.contains(["admin"])),
        )
        .order_by(User.name)
    )
    return [
        SecurityOwnerOut(id=uid, name=name or f"Konto {uid}")
        for uid, name in rows.all()
    ]


async def _finding(db: AsyncSession, finding_id: int) -> SecurityFinding:
    row = await db.get(SecurityFinding, finding_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego znaleziska")
    return row


def _trail(db: AsyncSession, row: SecurityFinding, kind: str, text: str) -> None:
    db.add(
        SecurityEvent(
            source="nexus",
            kind=kind,
            severity="info",
            summary=f"{text}: {row.title}"[:300],
            occurred_at=datetime.now(timezone.utc),
        )
    )


# ── Trasy ────────────────────────────────────────────────────────────────────


@router.get("/overview", response_model=SecurityOverviewOut)
async def security_overview(
    _: AdminUser, db: AsyncSession = Depends(get_db)
) -> SecurityOverviewOut:
    data = await build_overview(db)
    today = data["today"]
    return SecurityOverviewOut(
        today=today,
        workflow_url=data["workflow_url"],
        tiles=data["tiles"],
        waiting=[_finding_out(f, today) for f in data["waiting"]],
        excepted=[_finding_out(f, today) for f in data["excepted"]],
        recently_closed=[_finding_out(f, today) for f in data["recently_closed"]],
        events=[_event_out(e) for e in data["events"]],
        sources=[_source_out(s) for s in data["sources"]],
        routines_overdue=data["routines_overdue"],
        owners=await _admins(db),
    )


@router.get("/findings", response_model=list[SecurityFindingOut])
async def list_findings(
    _: AdminUser,
    status: Literal["all", "waiting", "excepted", "fixed"] = "all",
    db: AsyncSession = Depends(get_db),
) -> list[SecurityFindingOut]:
    today = business_today()
    rows = [
        _finding_out(r, today)
        for r in await db.scalars(select(SecurityFinding).limit(1000))
    ]
    if status != "all":
        wanted = {"waiting": "open", "excepted": "excepted", "fixed": "fixed"}[status]
        rows = [r for r in rows if r.status == wanted]
    rows.sort(key=lambda r: (SEVERITY_RANK.get(r.severity, 9), r.first_seen_at))
    return rows


@router.get("/findings/{finding_id}", response_model=SecurityFindingOut)
async def get_finding(
    finding_id: int, _: AdminUser, db: AsyncSession = Depends(get_db)
) -> SecurityFindingOut:
    return _finding_out(await _finding(db, finding_id), business_today())


@router.patch("/findings/{finding_id}", response_model=SecurityFindingOut)
async def set_owner(
    finding_id: int,
    body: SecurityOwnerIn,
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> SecurityFindingOut:
    row = await _finding(db, finding_id)
    if body.owner_user_id is not None:
        if body.owner_user_id not in {o.id for o in await _admins(db)}:
            raise HTTPException(
                status_code=422,
                detail="Właścicielem może być tylko aktywny administrator",
            )
    row.owner_user_id = body.owner_user_id
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _finding_out(row, business_today())


@router.post("/findings/{finding_id}/exception", response_model=SecurityFindingOut)
async def except_finding(
    finding_id: int,
    body: SecurityExceptionIn,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> SecurityFindingOut:
    today = business_today()
    if body.until <= today:
        raise HTTPException(
            status_code=422, detail="Termin wyjątku musi być po dzisiejszym dniu"
        )
    if body.until > today + timedelta(days=MAX_EXCEPTION_DAYS):
        raise HTTPException(status_code=422, detail="Wyjątek może trwać najwyżej rok")
    row = await _finding(db, finding_id)
    if row.status == "fixed":
        raise HTTPException(
            status_code=409, detail="Znalezisko jest zamknięte jako naprawione"
        )
    row.status = "excepted"
    row.exception_reason = body.reason
    row.exception_until = body.until
    row.exception_by_user_id = user.id
    row.updated_at = datetime.now(timezone.utc)
    _trail(db, row, "finding_excepted", f"Wyjątek do {body.until:%d.%m.%Y}")
    await db.commit()
    return _finding_out(row, today)


@router.post("/findings/{finding_id}/close", response_model=SecurityFindingOut)
async def close_finding(
    finding_id: int,
    body: SecurityCloseIn,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> SecurityFindingOut:
    row = await _finding(db, finding_id)
    row.status = "fixed"
    row.closed_note = (body.note or "").strip() or None
    row.closed_at = datetime.now(timezone.utc)
    row.closed_by_user_id = user.id
    row.updated_at = row.closed_at
    _trail(db, row, "finding_closed", "Zamknięte jako naprawione")
    await db.commit()
    return _finding_out(row, business_today())


@router.post("/findings/{finding_id}/reopen", response_model=SecurityFindingOut)
async def reopen_finding(
    finding_id: int, _: AdminUser, db: AsyncSession = Depends(get_db)
) -> SecurityFindingOut:
    row = await _finding(db, finding_id)
    row.status = "open"
    row.closed_at = None
    row.closed_by_user_id = None
    row.closed_note = None
    row.updated_at = datetime.now(timezone.utc)
    _trail(db, row, "finding_reopened", "Otwarte ponownie")
    await db.commit()
    return _finding_out(row, business_today())


@router.get("/events", response_model=list[SecurityEventOut])
async def list_events(
    _: AdminUser,
    source: Optional[str] = Query(default=None, max_length=20),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[SecurityEventOut]:
    stmt = select(SecurityEvent).order_by(SecurityEvent.occurred_at.desc()).limit(limit)
    if source:
        stmt = stmt.where(SecurityEvent.source == source)
    return [_event_out(e) for e in await db.scalars(stmt)]


@router.get("/routines", response_model=list[SecurityRoutineOut])
async def list_routines(
    _: AdminUser, db: AsyncSession = Depends(get_db)
) -> list[SecurityRoutineOut]:
    today = business_today()
    rows = await db.scalars(
        select(SecurityRoutine).order_by(SecurityRoutine.position, SecurityRoutine.id)
    )
    return [_routine_out(r, today) for r in rows]


@router.post("/routines/{routine_id}/done", response_model=SecurityRoutineOut)
async def routine_done(
    routine_id: int,
    body: SecurityRoutineDoneIn,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> SecurityRoutineOut:
    today = business_today()
    done_on = body.done_on or today
    if done_on > today:
        raise HTTPException(
            status_code=422, detail="Data wykonania nie może być z przyszłości"
        )
    row = await db.get(SecurityRoutine, routine_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej rutyny")
    mark_routine_done(
        row, done_on, note=(body.note or "").strip() or None, user_id=user.id
    )
    db.add(
        SecurityEvent(
            source="nexus",
            kind="routine_done",
            severity="info",
            summary=f"Rutyna wykonana {done_on:%d.%m}: {row.title}"[:300],
            occurred_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return _routine_out(row, today)
