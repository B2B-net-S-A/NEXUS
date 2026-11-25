"""Kolejka rekrutera „Raporty ze strony” (N6, decyzje Artura 25.11.2026).

Raport kompetencji powstaje ze zgłoszenia na nowej stronie (``report=1``), jest
gotowy w godzinę i bez reakcji rekrutera wychodzi sam o ``send_due_at``
(zgłoszenie + 23 h). Tu rekruter go widzi i może:

* ``GET  /api/competence-reports?scope=mine|all&status=`` — kolejka po terminie;
* ``GET  /api/competence-reports/{id}`` — szczegóły z podglądem maila
  (kotwice zamiast linków z tokenem — token powstaje dopiero przy wysyłce);
* ``POST /{id}/send-now`` — wysyłka od razu (silnik ``competence_report_engine``);
* ``POST /{id}/hold`` / ``/{id}/release`` — wstrzymanie automatu i zwolnienie;
* ``PATCH /{id}/conditions`` — poprawa warunków i przeliczenie snapshotu;
* ``POST /{id}/owner`` — zmiana opiekuna na osobę z listy;
* ``GET|PUT /api/competence-reports/owners`` — lista opiekunów (tylko admin),
  po której raporty idą po kolei (``competence_report_store.assign_owner``).

Bramki: sekcja Sourcing na routerze (zapis wymaga zapisu w sekcji), odczyt jak
dane kandydata (``CandidatePIIAccess`` — lista ma imię i nazwisko), akcje jak
zapis kandydata (``CandidateWriteAccess`` — bez roli tylko do odczytu), lista
opiekunów ``AdminUser``. Akcje zostawiają ``Activity`` na kandydacie bez danych
osobowych i bez wartości warunków (same nazwy zmienionych pól).
"""

from __future__ import annotations

import importlib
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidatePIIAccess, CandidateWriteAccess
from app.api.deps import AdminUser
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.competence_report import CompetenceReport, CompetenceReportOwner
from app.models.user import User
from app.services.competence_report_ddl import STATUSES
from app.services.competence_report_queue import (
    HOLD_WARNING,
    OPEN_STATUSES,
    SENDABLE_STATUSES,
    changed_condition_keys,
    conditions_summary,
    hours_left,
    is_owner_eligible,
    preview_mail,
    snapshot_or_none,
)
from app.services.competence_report_schema import ReportConditions, ReportOwner

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

_ENGINE = "app.services.competence_report_engine"
_LIST_LIMIT = 300


def _engine():
    """Silnik raportu ładowany przy użyciu (budowany równolegle, N3/N4)."""
    return importlib.import_module(_ENGINE)


# ── Schematy ────────────────────────────────────────────────────────────────


class PersonRef(BaseModel):
    id: int
    name: str


class ReportListItem(BaseModel):
    id: int
    candidate: PersonRef
    role_label: Optional[str] = None
    conditions_summary: str
    status: str
    owner: Optional[PersonRef] = None
    created_at: datetime
    send_due_at: datetime
    hours_left: float
    held: bool
    held_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None


class ReportDetail(ReportListItem):
    email: str
    conditions: dict
    snapshot: Optional[dict] = None
    preview_subject: Optional[str] = None
    preview_html: Optional[str] = None
    held_by: Optional[PersonRef] = None
    sent_by: Optional[PersonRef] = None
    ready_at: Optional[datetime] = None
    attempts: int = 0
    last_error: Optional[str] = None
    warning: Optional[str] = None
    #: aktywne osoby z listy opiekunów — wybór w „Zmień opiekuna”
    owner_choices: list[PersonRef] = []


class OwnerChange(BaseModel):
    user_id: int


class PoolMemberIn(BaseModel):
    user_id: int
    active: bool = True


class PoolUpdate(BaseModel):
    members: list[PoolMemberIn] = Field(max_length=100)


class PoolMemberOut(BaseModel):
    user_id: int
    name: str
    active: bool
    account_active: bool
    position: int
    last_assigned_at: Optional[datetime] = None


class PoolOut(BaseModel):
    members: list[PoolMemberOut]
    eligible: list[PersonRef]


# ── Pomocniki ───────────────────────────────────────────────────────────────


def _ref(user: Optional[User]) -> Optional[PersonRef]:
    return PersonRef(id=user.id, name=user.name) if user is not None else None


async def _users(db: AsyncSession, ids: set[Optional[int]]) -> dict[int, User]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await db.scalars(select(User).where(User.id.in_(wanted)))
    return {u.id: u for u in rows}


def _list_item(
    report: CompetenceReport,
    candidate: Candidate,
    users: dict[int, User],
    now: datetime,
) -> dict:
    snapshot = snapshot_or_none(report.snapshot)
    return {
        "id": report.id,
        "candidate": PersonRef(
            id=candidate.id, name=f"{candidate.name} {candidate.lastname}".strip()
        ),
        "role_label": snapshot.profile.role_label if snapshot else None,
        "conditions_summary": conditions_summary(report.conditions),
        "status": report.status,
        "owner": _ref(users.get(report.owner_user_id)),
        "created_at": report.created_at,
        "send_due_at": report.send_due_at,
        "hours_left": hours_left(report.send_due_at, now),
        "held": report.held_at is not None,
        "held_at": report.held_at,
        "sent_at": report.sent_at,
    }


async def _load(db: AsyncSession, report_id: int) -> tuple[CompetenceReport, Candidate]:
    row = (
        await db.execute(
            select(CompetenceReport, Candidate)
            .join(Candidate, Candidate.id == CompetenceReport.candidate_id)
            .where(CompetenceReport.id == report_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego raportu.")
    return row[0], row[1]


async def _detail(db: AsyncSession, report_id: int) -> ReportDetail:
    report, candidate = await _load(db, report_id)
    users = await _users(
        db, {report.owner_user_id, report.held_by_user_id, report.sent_by_user_id}
    )
    subject, html = preview_mail(report.snapshot, candidate.name)
    choices = await db.scalars(
        select(User)
        .join(CompetenceReportOwner, CompetenceReportOwner.user_id == User.id)
        .where(CompetenceReportOwner.active.is_(True), User.is_active.is_(True))
        .order_by(CompetenceReportOwner.position, User.id)
    )
    return ReportDetail(
        **_list_item(report, candidate, users, datetime.now(timezone.utc)),
        email=report.email,
        conditions=report.conditions,
        snapshot=report.snapshot,
        preview_subject=subject,
        preview_html=html,
        held_by=_ref(users.get(report.held_by_user_id)),
        sent_by=_ref(users.get(report.sent_by_user_id)),
        ready_at=report.ready_at,
        attempts=report.attempts,
        last_error=report.last_error,
        warning=HOLD_WARNING if report.held_at is not None else None,
        owner_choices=[PersonRef(id=u.id, name=u.name) for u in choices],
    )


def _require_status(
    report: CompetenceReport, allowed: tuple[str, ...], what: str
) -> None:
    if report.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "competence_report_wrong_status",
                "status": report.status,
                "message": f"Tego raportu nie można już {what}.",
            },
        )


def _audit(
    db: AsyncSession, report: CompetenceReport, user: User, action: str, **details
) -> None:
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=report.candidate_id,
            action=action,
            user_id=user.id,
            details={"competence_report_id": report.id, **details},
        )
    )


# ── Lista opiekunów (admin) — przed ``/{report_id}`` ────────────────────────


async def _pool(db: AsyncSession) -> PoolOut:
    rows = (
        await db.execute(
            select(CompetenceReportOwner, User)
            .join(User, User.id == CompetenceReportOwner.user_id)
            .order_by(CompetenceReportOwner.position, CompetenceReportOwner.user_id)
        )
    ).all()
    members = [
        PoolMemberOut(
            user_id=owner.user_id,
            name=user.name,
            active=owner.active,
            account_active=user.is_active,
            position=owner.position,
            last_assigned_at=owner.last_assigned_at,
        )
        for owner, user in rows
    ]
    active_users = await db.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.name)
    )
    eligible = [
        PersonRef(id=u.id, name=u.name) for u in active_users if is_owner_eligible(u)
    ]
    return PoolOut(members=members, eligible=eligible)


@router.get("/owners", response_model=PoolOut)
async def get_owner_pool(_: AdminUser, db: AsyncSession = Depends(get_db)) -> PoolOut:
    return await _pool(db)


@router.put("/owners", response_model=PoolOut)
async def put_owner_pool(
    body: PoolUpdate, current_user: AdminUser, db: AsyncSession = Depends(get_db)
) -> PoolOut:
    ids = [m.user_id for m in body.members]
    if len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=422, detail="Ta sama osoba jest na liście dwa razy."
        )
    users = await _users(db, set(ids))
    wrong = [i for i in ids if not is_owner_eligible(users.get(i))]
    if wrong:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "competence_report_owner_not_eligible",
                "user_ids": wrong,
                "message": "Na liście mogą być tylko aktywne konta zespołu rekrutacji.",
            },
        )
    existing = {o.user_id: o for o in await db.scalars(select(CompetenceReportOwner))}
    await db.execute(
        delete(CompetenceReportOwner).where(
            CompetenceReportOwner.user_id.not_in(ids or [0])
        )
    )
    for position, member in enumerate(body.members):
        row = existing.get(member.user_id)
        if row is None:
            db.add(
                CompetenceReportOwner(
                    user_id=member.user_id, active=member.active, position=position
                )
            )
        else:
            row.active = member.active
            row.position = position
    await db.commit()
    logger.info(
        "competence report owner pool saved by user_id=%s members=%d active=%d",
        current_user.id,
        len(ids),
        sum(1 for m in body.members if m.active),
    )
    return await _pool(db)


# ── Kolejka ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ReportListItem])
async def list_reports(
    current_user: CandidatePIIAccess,
    scope: Literal["mine", "all"] = Query("mine"),
    status: Optional[str] = Query(
        None, description="Stan raportu albo „open” (czeka na wysyłkę)"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[ReportListItem]:
    query = select(CompetenceReport, Candidate).join(
        Candidate, Candidate.id == CompetenceReport.candidate_id
    )
    if scope == "mine":
        query = query.where(CompetenceReport.owner_user_id == current_user.id)
    if status == "open":
        query = query.where(CompetenceReport.status.in_(OPEN_STATUSES))
    elif status:
        if status not in STATUSES:
            raise HTTPException(status_code=422, detail="Nieznany stan raportu.")
        query = query.where(CompetenceReport.status == status)
    rows = (
        await db.execute(
            query.order_by(CompetenceReport.send_due_at, CompetenceReport.id).limit(
                _LIST_LIMIT
            )
        )
    ).all()
    users = await _users(db, {r.owner_user_id for r, _ in rows})
    now = datetime.now(timezone.utc)
    return [ReportListItem(**_list_item(r, c, users, now)) for r, c in rows]


@router.get("/{report_id}", response_model=ReportDetail)
async def get_report(
    report_id: int, _: CandidatePIIAccess, db: AsyncSession = Depends(get_db)
) -> ReportDetail:
    return await _detail(db, report_id)


@router.post("/{report_id}/send-now", response_model=ReportDetail)
async def send_now(
    report_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> ReportDetail:
    report, _ = await _load(db, report_id)
    _require_status(report, SENDABLE_STATUSES, "wysłać")
    if report.snapshot is None:
        raise HTTPException(status_code=409, detail="Raport nie jest jeszcze gotowy.")
    try:
        await _engine().send_report_now(db, report, current_user)
        _audit(db, report, current_user, "competence_report_sent_now")
        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        logger.exception("competence report send-now failed report_id=%s", report_id)
        raise HTTPException(
            status_code=502, detail="Nie udało się wysłać raportu. Spróbuj ponownie."
        )
    return await _detail(db, report_id)


@router.post("/{report_id}/hold", response_model=ReportDetail)
async def hold_report(
    report_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> ReportDetail:
    report, _ = await _load(db, report_id)
    _require_status(report, OPEN_STATUSES, "wstrzymać")
    if report.held_at is None:
        report.held_at = datetime.now(timezone.utc)
        report.held_by_user_id = current_user.id
        _audit(db, report, current_user, "competence_report_held")
        await db.commit()
    return await _detail(db, report_id)


@router.post("/{report_id}/release", response_model=ReportDetail)
async def release_report(
    report_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> ReportDetail:
    report, _ = await _load(db, report_id)
    if report.held_at is not None:
        report.held_at = None
        report.held_by_user_id = None
        _audit(db, report, current_user, "competence_report_released")
        await db.commit()
    return await _detail(db, report_id)


@router.patch("/{report_id}/conditions", response_model=ReportDetail)
async def update_conditions(
    report_id: int,
    body: ReportConditions,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> ReportDetail:
    report, _ = await _load(db, report_id)
    _require_status(report, OPEN_STATUSES, "poprawić")
    changed = changed_condition_keys(report.conditions, body)
    if not changed:
        return await _detail(db, report_id)
    report.conditions = body.model_dump(mode="json")
    try:
        # Raport ``waiting_cv`` nie ma jeszcze snapshotu — pętla złoży go z nowych warunków.
        if report.snapshot is not None:
            snapshot = await _engine().rebuild_snapshot(db, report)
            report.snapshot = snapshot.model_dump(mode="json")
        _audit(
            db,
            report,
            current_user,
            "competence_report_conditions_changed",
            fields=changed,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("competence report rebuild failed report_id=%s", report_id)
        raise HTTPException(
            status_code=502,
            detail="Nie udało się przeliczyć raportu. Warunki nie zostały zapisane.",
        )
    return await _detail(db, report_id)


@router.post("/{report_id}/owner", response_model=ReportDetail)
async def change_owner(
    report_id: int,
    body: OwnerChange,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> ReportDetail:
    report, _ = await _load(db, report_id)
    _require_status(report, OPEN_STATUSES, "przekazać")
    member = await db.get(CompetenceReportOwner, body.user_id)
    user = await db.get(User, body.user_id)
    if member is None or not member.active or user is None or not user.is_active:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "competence_report_owner_not_in_pool",
                "message": "Opiekunem może zostać tylko aktywna osoba z listy opiekunów.",
            },
        )
    if report.owner_user_id != user.id:
        previous = report.owner_user_id
        report.owner_user_id = user.id
        snapshot = snapshot_or_none(report.snapshot)
        if snapshot is not None:
            # Mail podpisuje opiekun — podpis idzie za zmianą bez przeliczania raportu.
            owner = ReportOwner(user_id=user.id, name=user.name)
            report.snapshot = snapshot.model_copy(update={"owner": owner}).model_dump(
                mode="json"
            )
        _audit(
            db,
            report,
            current_user,
            "competence_report_owner_changed",
            from_user_id=previous,
            to_user_id=user.id,
        )
        await db.commit()
    return await _detail(db, report_id)
