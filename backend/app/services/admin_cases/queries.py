"""Sprawy administracja@ — odczyt: tablica, szczegół, listy wyboru.

Zakres listy liczy ``service.is_handler``: obsługa widzi wszystkie sprawy,
osoba przypisana bez uprawnienia — tylko swoje. Kontrakt pokazujemy jako
osobę i klienta, bez kwot.

Chipy tablicy (makieta 19.10.2026): „Na ten tydzień” = otwarta sprawa
z terminem najpóźniej w piątek tego tygodnia (też po terminie), „Bez osoby”
= otwarta bez przypisanej osoby. Filtrują po stronie serwera (lista ma
limit), a liczniki ``counts`` liczy jedno zapytanie z grupowaniem po
obszarze — w zakresie czytającego i wyszukiwania, bez filtrów chipów.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.models.admin_case import AdminCase, AdminCaseComment, AdminCaseMessage
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.user import User, UserRole
from app.services.admin_cases import rules
from app.services.admin_cases.service import is_handler, may_read

#: Zrobione sprawy starsze niż tyle dni schodzą z tablicy (zostają w filtrze).
DONE_VISIBLE_DAYS = 30
LIST_LIMIT = 500

#: Imię i nazwisko konsultanta z kontraktu (kandydat trzyma je w dwóch kolumnach).
CANDIDATE_FULL_NAME = func.concat_ws(" ", Candidate.name, Candidate.lastname)


@dataclass(frozen=True)
class ListFilters:
    mine: bool = False
    area: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    q: Optional[str] = None
    include_closed: bool = False
    #: Otwarte z terminem do piątku tego tygodnia (także po terminie).
    week: bool = False
    #: Otwarte bez przypisanej osoby.
    unassigned: bool = False


OPEN_STATUSES = ("new", "in_progress", "waiting")


def week_end(today: date) -> date:
    """Piątek tygodnia ``today`` (w weekend — piątek, który minął)."""

    return today + timedelta(days=4 - today.weekday())


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {row.id: row.name for row in rows}


async def _contract_labels(
    db: AsyncSession, ids: set[int]
) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}
    rows = await db.execute(
        select(
            Contract.id,
            Contract.start_date,
            Contract.end_date,
            CANDIDATE_FULL_NAME.label("candidate_name"),
            Client.name.label("client_name"),
        )
        .select_from(Contract)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(Client, Client.id == Contract.client_id)
        .where(Contract.id.in_(ids))
    )
    return {
        row.id: {
            "id": row.id,
            "candidate_name": row.candidate_name,
            "client_name": row.client_name,
            "start_date": row.start_date,
            "end_date": row.end_date,
        }
        for row in rows
    }


def _card(
    case: AdminCase,
    *,
    names: dict[int, str],
    contracts: dict[int, dict[str, Any]],
    today: date,
) -> dict[str, Any]:
    checklist = case.checklist or []
    return {
        "id": case.id,
        "title": case.title,
        "area": case.area,
        "priority": case.priority,
        "status": case.status,
        "due_on": case.due_on,
        "follow_up_on": case.follow_up_on,
        "overdue": bool(
            case.due_on and case.due_on < today and not rules.is_terminal(case.status)
        ),
        "assignee": (
            {"id": case.assignee_user_id, "name": names.get(case.assignee_user_id)}
            if case.assignee_user_id
            else None
        ),
        "subject_user": (
            {"id": case.subject_user_id, "name": names.get(case.subject_user_id)}
            if case.subject_user_id
            else None
        ),
        "contract": contracts.get(case.contract_id) if case.contract_id else None,
        "source": case.source,
        "checklist_done": sum(1 for item in checklist if item.get("done")),
        "checklist_total": len(checklist),
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "closed_at": case.closed_at,
    }


def _search(term: str):
    pattern = _like(term)
    return or_(
        AdminCase.title.ilike(pattern, escape="\\"),
        AdminCase.description.ilike(pattern, escape="\\"),
    )


async def _chip_counts(
    db: AsyncSession, scope: list, *, friday: date
) -> dict[str, Any]:
    """Liczniki chipów: otwarte sprawy po obszarze, „na ten tydzień”, „bez osoby”."""

    rows = (
        await db.execute(
            select(
                AdminCase.area,
                func.count(AdminCase.id),
                func.count(AdminCase.id).filter(AdminCase.due_on <= friday),
                func.count(AdminCase.id).filter(AdminCase.assignee_user_id.is_(None)),
            )
            .where(AdminCase.status.in_(OPEN_STATUSES), *scope)
            .group_by(AdminCase.area)
        )
    ).all()
    return {
        "areas": {area: int(total) for area, total, _w, _u in rows},
        "week": sum(int(w) for _a, _t, w, _u in rows),
        "unassigned": sum(int(u) for _a, _t, _w, u in rows),
    }


async def list_cases(
    db: AsyncSession, viewer: User, filters: ListFilters
) -> dict[str, Any]:
    today = business_today()
    friday = week_end(today)
    stmt = select(AdminCase)
    scope = []
    if filters.mine or not is_handler(viewer):
        scope.append(AdminCase.assignee_user_id == viewer.id)
    term = (filters.q or "").replace("\x00", "").strip()
    if term:
        scope.append(_search(term))
    stmt = stmt.where(*scope)
    if filters.week:
        stmt = stmt.where(
            AdminCase.status.in_(OPEN_STATUSES), AdminCase.due_on <= friday
        )
    if filters.unassigned:
        stmt = stmt.where(
            AdminCase.status.in_(OPEN_STATUSES), AdminCase.assignee_user_id.is_(None)
        )
    if filters.area:
        stmt = stmt.where(AdminCase.area == filters.area)
    if filters.priority:
        stmt = stmt.where(AdminCase.priority == filters.priority)
    if filters.status:
        stmt = stmt.where(AdminCase.status == filters.status)
    else:
        # Tablica: zamknięte tylko na życzenie, zrobione z ostatnich 30 dni.
        recent = datetime.now(timezone.utc) - timedelta(days=DONE_VISIBLE_DAYS)
        visible = or_(
            AdminCase.status.in_(("new", "in_progress", "waiting")),
            and_(AdminCase.status == "done", AdminCase.closed_at >= recent),
        )
        if filters.include_closed:
            visible = or_(visible, AdminCase.status == "closed")
        stmt = stmt.where(visible)
    stmt = stmt.order_by(
        AdminCase.priority.asc(),
        AdminCase.due_on.asc().nulls_last(),
        AdminCase.updated_at.desc(),
    ).limit(LIST_LIMIT + 1)
    cases = list((await db.scalars(stmt)).all())
    truncated = len(cases) > LIST_LIMIT
    cases = cases[:LIST_LIMIT]

    user_ids = {
        uid
        for case in cases
        for uid in (case.assignee_user_id, case.subject_user_id)
        if uid is not None
    }
    names = await _names(db, user_ids)
    contracts = await _contract_labels(
        db, {case.contract_id for case in cases if case.contract_id}
    )
    month_start = local_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    done_this_month = await db.scalar(
        select(func.count(AdminCase.id)).where(
            AdminCase.status.in_(("done", "closed")),
            AdminCase.closed_at >= month_start,
            *(
                [AdminCase.assignee_user_id == viewer.id]
                if filters.mine or not is_handler(viewer)
                else []
            ),
        )
    )
    return {
        "items": [
            _card(case, names=names, contracts=contracts, today=today) for case in cases
        ],
        "total": len(cases),
        "truncated": truncated,
        "done_this_month": int(done_this_month or 0),
        "counts": await _chip_counts(db, scope, friday=friday),
        "today": today,
        "week_end": friday,
        "can_manage": is_handler(viewer),
    }


async def case_detail(
    db: AsyncSession, case: AdminCase, viewer: User
) -> dict[str, Any]:
    messages = list(
        (
            await db.scalars(
                select(AdminCaseMessage)
                .where(AdminCaseMessage.case_id == case.id)
                .order_by(
                    AdminCaseMessage.received_at.asc().nulls_last(),
                    AdminCaseMessage.id.asc(),
                )
            )
        ).all()
    )
    comments = list(
        (
            await db.scalars(
                select(AdminCaseComment)
                .where(AdminCaseComment.case_id == case.id)
                .order_by(AdminCaseComment.created_at.asc(), AdminCaseComment.id.asc())
            )
        ).all()
    )
    user_ids = {
        uid
        for uid in (case.assignee_user_id, case.subject_user_id, case.created_by)
        if uid is not None
    } | {c.author_user_id for c in comments if c.author_user_id is not None}
    names = await _names(db, user_ids)
    contracts = await _contract_labels(
        db, {case.contract_id} if case.contract_id else set()
    )
    card = _card(case, names=names, contracts=contracts, today=business_today())
    return {
        **card,
        "description": case.description,
        "checklist": case.checklist or [],
        "lifecycle_case_id": case.lifecycle_case_id,
        "created_by": (
            {"id": case.created_by, "name": names.get(case.created_by)}
            if case.created_by
            else None
        ),
        "messages": [
            {
                "id": m.id,
                "sender_email": m.sender_email,
                "sender_name": m.sender_name,
                "subject": m.subject,
                "received_at": m.received_at,
                "body_text": m.body_text,
                "attachments": m.attachments or [],
            }
            for m in messages
        ],
        "comments": [
            {
                "id": c.id,
                "author": (
                    {"id": c.author_user_id, "name": names.get(c.author_user_id)}
                    if c.author_user_id
                    else None
                ),
                "body": c.body,
                "created_at": c.created_at,
            }
            for c in comments
        ],
        "can_manage": is_handler(viewer),
        "can_comment": may_read(viewer, case),
    }


async def assignee_options(db: AsyncSession) -> list[dict[str, Any]]:
    """Aktywne konta do przypisania; najpierw obsługa skrzynki (uprawnienie „Sprawy”)."""

    from app.services.section_permissions import (
        resolve_effective_section_access_for_users,
    )

    users = list(
        (
            await db.scalars(
                select(User).where(User.is_active.is_(True)).order_by(User.name.asc())
            )
        ).all()
    )
    users = [user for user in users if not user.has_role(UserRole.trainee)]
    await resolve_effective_section_access_for_users(db, users)
    options = [
        {"id": user.id, "name": user.name, "handler": is_handler(user)}
        for user in users
    ]
    return sorted(options, key=lambda item: (not item["handler"], item["name"].lower()))


async def contract_options(db: AsyncSession, q: str) -> list[dict[str, Any]]:
    """Kontrakty do powiązania: osoba i klient, bez kwot."""

    term = (q or "").replace("\x00", "").strip()
    if len(term) < 2:
        return []
    rows = await db.execute(
        select(
            Contract.id,
            Contract.start_date,
            Contract.end_date,
            CANDIDATE_FULL_NAME.label("candidate_name"),
            Client.name.label("client_name"),
        )
        .select_from(Contract)
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(Client, Client.id == Contract.client_id)
        .where(CANDIDATE_FULL_NAME.ilike(_like(term), escape="\\"))
        .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
        .limit(15)
    )
    return [
        {
            "id": row.id,
            "candidate_name": row.candidate_name,
            "client_name": row.client_name,
            "start_date": row.start_date,
            "end_date": row.end_date,
        }
        for row in rows
    ]
