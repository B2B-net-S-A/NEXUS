"""Sprawy administracja@ — odczyt: tablica, szczegół, listy wyboru.

Zakres listy liczy ``service.is_handler``: obsługa widzi wszystkie sprawy,
osoba przypisana bez uprawnienia — tylko swoje. Kontrakt pokazujemy jako
osobę i klienta, bez kwot.

Chipy tablicy (makieta 19.10.2026): „Na ten tydzień” = otwarta sprawa
z terminem najpóźniej w piątek tego tygodnia (też po terminie), „Bez osoby”
= otwarta bez przypisanej osoby. Filtrują po stronie serwera (lista ma
limit), a liczniki ``counts`` liczy jedno zapytanie z grupowaniem po
obszarze — w zakresie czytającego i wyszukiwania, bez filtrów chipów.

Opieka (22.10.2026): kontrakt na karcie niesie efektywnego opiekuna
(łańcuch ``care.access.effective_owners``) i zdrowie relacji (tylko dla
czytającego z kręgu D11 — liczy ``care.health``), chip „Moi podopieczni”
(``mine_care``) to sprawy kontraktów, których efektywnym opiekunem jest
czytający. Szczegół sprawy z kontraktem ma sekcję ``consultant``, bez
kontraktu — propozycje „Kogo dotyczy?” (``contract_links``). Karta
konsultanta w opiece czyta ``cases_for_contract``. Dane opieki liczą się
w punkcie zapisu: awaria modułu opieki nie kładzie tablicy spraw.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, case as sql_case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.models.admin_case import AdminCase, AdminCaseComment, AdminCaseMessage
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.hr_ops import HrAuditEvent
from app.models.user import User, UserRole
from app.services.admin_cases import rules
from app.services.admin_cases.service import is_handler, may_read

logger = logging.getLogger(__name__)

#: Zrobione sprawy starsze niż tyle dni schodzą z tablicy (zostają w filtrze).
DONE_VISIBLE_DAYS = 30
LIST_LIMIT = 500
#: Karta konsultanta: zamknięte sprawy kontraktu z tylu dni i najwyżej tyle spraw.
CONTRACT_CLOSED_VISIBLE_DAYS = 90
CONTRACT_CASES_LIMIT = 30
#: Fragment ostatniej rozmowy opieki w szczególe sprawy.
EXCERPT_MAX = 160

FORM_LABELS: dict[str, str] = {
    "b2b": "B2B",
    "uop": "Umowa o pracę",
    "uzlecenie": "Umowa zlecenie",
}

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
    #: „Moi podopieczni”: kontrakty, których efektywnym opiekunem jest czytający.
    mine_care: bool = False


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


async def _health(
    db: AsyncSession, ids: Iterable[int], viewer: User
) -> dict[int, Optional[dict[str, Any]]]:
    """Zdrowie relacji (``None`` poza kręgiem D11 — rozstrzyga ``care.health``)."""

    wanted = sorted(set(ids))
    if not wanted:
        return {}
    try:
        from app.services.care.health import health_for_contracts
    except ImportError:  # TODO(B1): moduł zdrowia relacji jeszcze nie wszedł
        return {}
    try:
        async with db.begin_nested():
            return dict(await health_for_contracts(db, wanted, viewer=viewer))
    except Exception:  # noqa: BLE001 — zdrowie to dodatek, nie warunek tablicy
        logger.exception("[admin_cases] zdrowie relacji nie policzone")
        return {}


async def _care_owners(
    db: AsyncSession, ids: Iterable[int]
) -> dict[int, tuple[Optional[int], Optional[str]]]:
    """Kontrakt → (efektywny opiekun, jego nazwa); awaria opieki = pusto."""

    wanted = sorted(set(ids))
    if not wanted:
        return {}
    from app.services.care import access as care_access

    try:
        async with db.begin_nested():
            contracts = await care_access.contracts_by_id(db, wanted)
            owners = await care_access.effective_owners(db, list(contracts.values()))
            names = await care_access.user_names(
                db, (choice.user_id for choice in owners.values())
            )
    except Exception:  # noqa: BLE001 — sprawy działają bez modułu opieki
        logger.exception("[admin_cases] opiekun kontraktów nie policzony")
        return {}
    return {
        contract_id: (choice.user_id, names.get(choice.user_id))
        for contract_id, choice in owners.items()
    }


async def _contract_labels(
    db: AsyncSession, ids: set[int], viewer: User
) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}
    rows = await db.execute(
        select(
            Contract.id,
            Contract.candidate_id,
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
    owners = await _care_owners(db, ids)
    health = await _health(db, ids, viewer)
    return {
        row.id: {
            "id": row.id,
            "candidate_id": row.candidate_id,
            "candidate_name": row.candidate_name,
            "client_name": row.client_name,
            "start_date": row.start_date,
            "end_date": row.end_date,
            "care_owner_user_id": owners.get(row.id, (None, None))[0],
            "care_owner_name": owners.get(row.id, (None, None))[1],
            "health": health.get(row.id),
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


async def _cared_contract_ids(
    db: AsyncSession, viewer: User, scope: list, *, recent: datetime
) -> set[int]:
    """Kontrakty spraw z tablicy, których efektywnym opiekunem jest czytający.

    Bierzemy tylko kontrakty spraw widocznych na tablicy (otwarte i zrobione
    z ostatnich dni) — każdy kontrakt ma sprawę wejścia, więc liczenie
    opiekuna dla całej historii rosłoby z każdym rokiem.
    """

    ids = set(
        await db.scalars(
            select(AdminCase.contract_id)
            .where(
                *scope,
                AdminCase.contract_id.is_not(None),
                or_(
                    AdminCase.status.in_(OPEN_STATUSES),
                    AdminCase.closed_at >= recent,
                ),
            )
            .distinct()
        )
    )
    owners = await _care_owners(db, ids)
    return {cid for cid, (owner_id, _name) in owners.items() if owner_id == viewer.id}


async def _chip_counts(
    db: AsyncSession, scope: list, *, friday: date, cared: set[int]
) -> dict[str, Any]:
    """Liczniki chipów: otwarte sprawy po obszarze, „na ten tydzień”, „bez osoby”,
    „moi podopieczni”."""

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
    mine_care = 0
    if cared:
        mine_care = await db.scalar(
            select(func.count(AdminCase.id)).where(
                AdminCase.status.in_(OPEN_STATUSES),
                AdminCase.contract_id.in_(sorted(cared)),
                *scope,
            )
        )
    return {
        "areas": {area: int(total) for area, total, _w, _u in rows},
        "week": sum(int(w) for _a, _t, w, _u in rows),
        "unassigned": sum(int(u) for _a, _t, _w, u in rows),
        "mine_care": int(mine_care or 0),
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
    recent = datetime.now(timezone.utc) - timedelta(days=DONE_VISIBLE_DAYS)
    cared = await _cared_contract_ids(db, viewer, scope, recent=recent)
    if filters.mine_care:
        stmt = stmt.where(AdminCase.contract_id.in_(sorted(cared) or [-1]))
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
        db, {case.contract_id for case in cases if case.contract_id}, viewer
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
        "counts": await _chip_counts(db, scope, friday=friday, cared=cared),
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
        db, {case.contract_id} if case.contract_id else set(), viewer
    )
    card = _card(case, names=names, contracts=contracts, today=business_today())
    consultant = None
    suggestions: list[dict[str, Any]] = []
    if case.contract_id is not None:
        consultant = await consultant_section(db, case, viewer)
    elif is_handler(viewer):
        from app.services.admin_cases.contract_links import link_suggestions

        suggestions = await link_suggestions(db, case)
    return {
        **card,
        "consultant": consultant,
        "link_suggestions": suggestions,
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


# ── Opieka: konsultant sprawy i sprawy konsultanta ───────────────────────────


def _excerpt(text_value: Optional[str]) -> Optional[str]:
    cleaned = " ".join((text_value or "").split())
    if len(cleaned) <= EXCERPT_MAX:
        return cleaned or None
    return cleaned[: EXCERPT_MAX - 1].rstrip() + "…"


async def consultant_section(
    db: AsyncSession, case: AdminCase, viewer: User
) -> Optional[dict[str, Any]]:
    """Sekcja „Konsultant” sprawy z kontraktem (bez kwot).

    Fragment ostatniej rozmowy opieki widzi tylko ktoś, kto prowadzi opiekę
    u tego klienta (DL w portfelu, TCM, admin) — reszta dostaje samą datę.
    Zdrowie relacji tylko krąg D11 (``care.health``). Awaria modułu opieki =
    ``None``, sprawa dalej się otwiera.
    """

    if case.contract_id is None:
        return None
    from app.services.care import access as care_access
    from app.services.care import plan as care_plan
    from app.services.care.cadence import LEVEL_LABELS
    from app.services.care.cadence_rules import level_on

    try:
        async with db.begin_nested():
            contract = (await care_access.contracts_by_id(db, [case.contract_id])).get(
                case.contract_id
            )
            if contract is None:
                return None
            owner = (await care_access.effective_owners(db, [contract]))[contract.id]
            names = await care_access.user_names(db, [owner.user_id])
            periods = (await care_plan.periods_by_contract(db, [contract.id])).get(
                contract.id, []
            )
            latest = (await care_plan.latest_conversations(db, [contract.id])).get(
                contract.id
            )
            allowed = await care_access.allowed_client_ids(viewer, db)
            other_open = await db.scalar(
                select(func.count(AdminCase.id)).where(
                    AdminCase.contract_id == contract.id,
                    AdminCase.id != case.id,
                    AdminCase.status.in_(OPEN_STATUSES),
                )
            )
    except Exception:  # noqa: BLE001 — sprawa otwiera się bez sekcji opieki
        logger.exception("[admin_cases] sekcja konsultanta nie policzona")
        return None

    today = business_today()
    cadence_label = None
    if contract.is_live:
        level = level_on(contract.start_date or date.min, periods, today).level
        cadence_label = LEVEL_LABELS.get(level)
    sees_notes = care_access.is_care_worker(viewer) and (
        allowed is None or contract.client_id in allowed
    )
    health = await _health(db, [contract.id], viewer)
    return {
        "contract_id": contract.id,
        "candidate_id": contract.candidate_id,
        "candidate_name": contract.candidate_name,
        "client_id": contract.client_id,
        "client_name": contract.client_name,
        "role": contract.job_title,
        "form": FORM_LABELS.get(contract.contract_type or ""),
        "order_end_on": contract.end_date,
        "owner_user_id": owner.user_id,
        "owner_name": names.get(owner.user_id) if owner.user_id else None,
        "cadence_label": cadence_label,
        "last_conversation": (
            {
                "on": latest.occurred_on,
                "excerpt": _excerpt(latest.note) if sees_notes else None,
            }
            if latest is not None
            else None
        ),
        "other_open_cases": int(other_open or 0),
        "health": health.get(contract.id),
    }


def content_hidden(case: AdminCase, viewer: User) -> bool:
    """Treść sprawy w karcie konsultanta: tylko ``may_read``; negocjacje nigdy."""

    return case.area == "negotiation" or not may_read(viewer, case)


def contract_case_row(
    case: AdminCase, *, names: dict[int, str], viewer: User, today: date
) -> dict[str, Any]:
    """Sprawa w karcie konsultanta: tytuł, obszar, status, termin, osoba.

    Bez opisu, maili i komentarzy — ``content_hidden`` mówi frontowi, czy
    czytający może otworzyć sprawę (``may_read``; negocjacje nigdy z karty).
    """

    return {
        "id": case.id,
        "title": case.title,
        "area": case.area,
        "area_label": rules.AREA_LABELS.get(case.area, case.area),
        "status": case.status,
        "status_label": rules.STATUS_LABELS.get(case.status, case.status),
        "due_on": case.due_on,
        "follow_up_on": case.follow_up_on,
        "overdue": bool(
            case.due_on and case.due_on < today and not rules.is_terminal(case.status)
        ),
        "assignee_name": (
            names.get(case.assignee_user_id) if case.assignee_user_id else None
        ),
        "source": case.source,
        "content_hidden": content_hidden(case, viewer),
    }


async def cases_for_contract(
    db: AsyncSession, contract_id: int, viewer: User
) -> list[dict[str, Any]]:
    """Sprawy kontraktu dla karty konsultanta (opieka).

    Otwarte najpierw (termin rosnąco), potem zamknięte z ostatnich
    ``CONTRACT_CLOSED_VISIBLE_DAYS`` dni. Wyłączony moduł „Sprawy” = pusta
    lista (link do sprawy prowadziłby na 404). Zakres kontraktu sprawdza trasa.
    """

    from app.services.admin_cases.service import module_enabled

    if not await module_enabled(db):
        return []
    recent = datetime.now(timezone.utc) - timedelta(days=CONTRACT_CLOSED_VISIBLE_DAYS)
    is_open = AdminCase.status.in_(OPEN_STATUSES)
    cases = list(
        (
            await db.scalars(
                select(AdminCase)
                .where(
                    AdminCase.contract_id == contract_id,
                    or_(is_open, AdminCase.closed_at >= recent),
                )
                .order_by(
                    sql_case((is_open, 0), else_=1),
                    AdminCase.due_on.asc().nulls_last(),
                    AdminCase.closed_at.desc().nulls_last(),
                    AdminCase.id.desc(),
                )
                .limit(CONTRACT_CASES_LIMIT)
            )
        ).all()
    )
    names = await _names(
        db, {c.assignee_user_id for c in cases if c.assignee_user_id is not None}
    )
    today = business_today()
    return [
        contract_case_row(c, names=names, viewer=viewer, today=today) for c in cases
    ]


async def contract_case_events(
    db: AsyncSession, contract_id: int
) -> list[dict[str, Any]]:
    """Zdarzenia spraw kontraktu dla osi konsultanta (bez treści).

    ``case_opened`` (założenie sprawy), ``case_closed`` (zrobiona albo
    zamknięta) i ``case_linked`` (sprawa przypięta do kontraktu przez
    czytnik albo obsługę — ślad ``case_linked`` w ``hr_audit_events``).
    """

    cases = list(
        (
            await db.scalars(
                select(AdminCase)
                .where(AdminCase.contract_id == contract_id)
                .order_by(AdminCase.created_at.asc(), AdminCase.id.asc())
                .limit(200)
            )
        ).all()
    )
    events: list[dict[str, Any]] = []
    by_id = {c.id: c for c in cases}

    def _event(kind: str, at: Any, c: AdminCase) -> dict[str, Any]:
        return {
            "kind": kind,
            "at": at,
            "case_id": c.id,
            "title": c.title,
            "area": c.area,
            "area_label": rules.AREA_LABELS.get(c.area, c.area),
        }

    for c in cases:
        events.append(_event("case_opened", c.created_at, c))
        if c.closed_at is not None:
            events.append(_event("case_closed", c.closed_at, c))
    if by_id:
        linked = (
            await db.execute(
                select(HrAuditEvent.entity_id, HrAuditEvent.created_at).where(
                    HrAuditEvent.entity_type == "admin_case",
                    HrAuditEvent.action == "case_linked",
                    HrAuditEvent.entity_id.in_([str(cid) for cid in by_id]),
                    HrAuditEvent.details["contract_id"].astext == str(contract_id),
                )
            )
        ).all()
        for entity_id, at in linked:
            c = by_id.get(int(entity_id))
            if c is not None:
                events.append(_event("case_linked", at, c))
    return sorted(events, key=lambda e: (e["at"], e["case_id"]))
