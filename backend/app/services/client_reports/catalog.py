"""Katalog raportów klienta: kto zatwierdza, terminy, kalendarz miesiąca.

Decyzje Artura 15.11.2026:

* wpis w katalogu zatwierdza Delivery Lead przypisany do klienta, admin
  zawsze; pozycje rodziny „zgodność” (sprawozdania, ciągłość działania,
  incydenty) zatwierdza tylko admin, bo to obowiązki spółki, nie DL-a;
* raport wysyła DL ze swojej poczty, NEXUS zapisuje wysyłkę w historii;
* kalendarz liczy się z definicji × okresów przy odczycie.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_report import ClientReportDefinition, ClientReportRun
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.access_scope import is_delivery_lead_governed
from app.services.client_reports import schedule
from app.services.client_reports.registry import get_generator

PREPARER_LABELS: dict[str, str] = {
    "dl": "Delivery Lead",
    "finance": "Finanse",
    "board": "Zarząd",
    "iod": "IOD",
    "consultant": "konsultanci → Finanse",
    "client": "przygotowuje klient",
}
FAMILY_LABELS: dict[str, str] = {
    "settlement": "Rozliczenie miesiąca (dowód pracy do faktury)",
    "management": "Raporty zarządcze z danych NEXUSA",
    "compliance": "Zgodność i bezpieczeństwo",
    "on_request": "Na żądanie klienta",
}
#: Zaległe z poprzednich miesięcy pokazujemy w bieżącym, żeby nie zniknęły.
OVERDUE_LOOKBACK_DAYS = 92
#: „Dalej: kwartalne i roczne” — terminy w kolejnych miesiącach.
UPCOMING_DAYS = 150
#: Parametry generatorów z kwotami, które nie niosą kwot ani stawek.
AMOUNT_FREE_PARAMS = frozenset(
    {"currency", "marginal", "include_active", "list_people"}
)
LONG_RHYTHMS = frozenset({"quarterly", "semiannual", "annual", "contract_year"})


def tracking_start(definition: ClientReportDefinition) -> Optional[date]:
    """Od kiedy NEXUS pilnuje terminów: „obowiązuje od” albo dzień dodania.

    Bez tego raport dodany dziś pokazywałby „po terminie” za miesiące, w których
    nikt go w NEXUSIE nie prowadził.
    """
    if definition.valid_from is not None:
        return definition.valid_from
    created = getattr(definition, "created_at", None)
    return created.date() if created is not None else None


def is_admin(user: User) -> bool:
    roles = {str(role) for role in (user.roles or [])} | {user.role.value}
    return UserRole.admin.value in roles


def can_confirm(
    user: User, family: str, client_id: int, allowed: Optional[frozenset[int]]
) -> bool:
    if is_admin(user):
        return True
    if family == "compliance":
        return False
    return (
        is_delivery_lead_governed(user) and allowed is not None and client_id in allowed
    )


@dataclass(frozen=True)
class Assignment:
    client_id: int
    user_id: int
    name: str
    is_head: bool


async def dl_assignments(
    db: AsyncSession, client_ids: Optional[Iterable[int]] = None
) -> dict[int, list[Assignment]]:
    query = (
        select(
            DeliveryLeadClientAssignment.client_id,
            User.id,
            User.name,
            DeliveryLeadClientAssignment.is_head,
        )
        .join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
        .where(User.is_active.is_(True))
    )
    if client_ids is not None:
        query = query.where(
            DeliveryLeadClientAssignment.client_id.in_(list(client_ids))
        )
    out: dict[int, list[Assignment]] = {}
    for client_id, user_id, name, is_head in (await db.execute(query)).all():
        out.setdefault(client_id, []).append(
            Assignment(client_id, user_id, name or "", bool(is_head))
        )
    for rows in out.values():
        rows.sort(key=lambda a: (not a.is_head, a.name))
    return out


def preparer_label(
    definition: ClientReportDefinition,
    assignments: dict[int, list[Assignment]],
    users: dict[int, str],
) -> str:
    if definition.preparer_user_id and definition.preparer_user_id in users:
        return users[definition.preparer_user_id]
    if definition.preparer == "dl":
        people = assignments.get(definition.client_id) or []
        if people:
            return people[0].name
    return PREPARER_LABELS.get(definition.preparer, definition.preparer)


def preparer_is(
    user: User,
    definition: ClientReportDefinition,
    assignments: dict[int, list[Assignment]],
) -> bool:
    if definition.preparer_user_id is not None:
        return definition.preparer_user_id == user.id
    if definition.preparer == "dl":
        return any(
            a.user_id == user.id for a in assignments.get(definition.client_id) or []
        )
    return False


async def user_names(db: AsyncSession, ids: Iterable[int]) -> dict[int, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = (
        await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    ).all()
    return {user_id: name or "" for user_id, name in rows}


async def sent_periods(
    db: AsyncSession, definition_ids: Sequence[int]
) -> dict[int, dict[str, ClientReportRun]]:
    """Ostatnia wysyłka per (definicja, okres)."""
    if not definition_ids:
        return {}
    runs = await db.scalars(
        select(ClientReportRun)
        .where(
            ClientReportRun.definition_id.in_(list(definition_ids)),
            ClientReportRun.status == "sent",
        )
        .order_by(ClientReportRun.sent_at)
    )
    out: dict[int, dict[str, ClientReportRun]] = {}
    for run in runs:
        out.setdefault(run.definition_id, {})[run.period_key] = run
    return out


def next_due(
    definition: ClientReportDefinition,
    sent: dict[str, ClientReportRun],
    today: date,
) -> dict[str, Any]:
    """Najbliższa niezałatwiona pozycja definicji: zaległa albo następna."""
    if definition.rhythm not in schedule.CALENDAR_RHYTHMS:
        return {"state": None, "due": None, "period_key": None, "period_label": None}
    try:
        periods = schedule.recent_periods(
            definition.rhythm, today, 14, definition.due_rule, definition.valid_from
        )
    except schedule.ScheduleError:
        return {
            "state": "no_date",
            "due": None,
            "period_key": None,
            "period_label": None,
        }
    # Od najstarszego: pierwsza niewysłana z terminem w przeszłości, inaczej
    # najbliższy termin w przyszłości (okres bieżący albo właśnie zamknięty).
    start = tracking_start(definition)
    candidates = []
    for period in reversed(periods):
        due = schedule.due_date(definition.due_rule, period)
        if start and ((due is not None and due < start) or period.end < start):
            continue
        candidates.append((period, due))
    if not candidates:
        current = periods[0]
        due = schedule.due_date(definition.due_rule, current)
        candidates = [(current, due)]
    open_overdue = [
        (p, d)
        for p, d in candidates
        if d is not None
        and d < today
        and p.key not in sent
        and d >= today - timedelta(days=OVERDUE_LOOKBACK_DAYS)
    ]
    if open_overdue:
        period, due = open_overdue[0]
    else:
        future = [(p, d) for p, d in candidates if d is not None and d >= today]
        if future:
            period, due = min(future, key=lambda item: item[1])
        else:
            closed = [(p, d) for p, d in candidates if p.end < today] or candidates
            period, due = closed[-1]
    state = schedule.report_state(due, period.key in sent, today)
    return {
        "state": state,
        "due": due.isoformat() if due else None,
        "period_key": period.key,
        "period_label": period.label,
    }


@dataclass(frozen=True)
class CalendarEntry:
    due: Optional[date]
    definition: ClientReportDefinition
    period: schedule.Period
    state: str
    carried: bool


def calendar_entries(
    definition: ClientReportDefinition,
    month_start: date,
    month_end: date,
    today: date,
    sent: dict[str, ClientReportRun],
) -> tuple[list[CalendarEntry], list[CalendarEntry]]:
    """Pozycje definicji w miesiącu i w „Dalej”; czysta funkcja (bez bazy)."""
    if definition.rhythm not in schedule.CALENDAR_RHYTHMS:
        return [], []
    horizon = month_end + timedelta(days=UPCOMING_DAYS)
    try:
        periods = schedule.recent_periods(
            definition.rhythm, horizon, 40, definition.due_rule, definition.valid_from
        )
    except schedule.ScheduleError:
        return [], []
    in_month: list[CalendarEntry] = []
    later: list[CalendarEntry] = []
    start = tracking_start(definition)
    is_current_month = month_start <= today <= month_end
    for period in sorted(periods, key=lambda p: p.start):
        if definition.valid_from and period.end < definition.valid_from:
            continue
        if definition.valid_to and period.start > definition.valid_to:
            continue
        due = schedule.due_date(definition.due_rule, period)
        if start and due is not None and due < start:
            continue
        is_sent = period.key in sent
        state = schedule.report_state(due, is_sent, today)
        if due is None:
            # Termin do ustalenia: jedna pozycja — ostatni okres zamknięty
            # najpóźniej w tym miesiącu.
            continue
        if month_start <= due <= month_end:
            in_month.append(CalendarEntry(due, definition, period, state, False))
        elif (
            is_current_month
            and due < month_start
            and not is_sent
            and due >= month_start - timedelta(days=OVERDUE_LOOKBACK_DAYS)
        ):
            in_month.append(CalendarEntry(due, definition, period, "overdue", True))
        elif month_end < due <= horizon and definition.rhythm in LONG_RHYTHMS:
            later.append(CalendarEntry(due, definition, period, state, False))
    if schedule.due_date(definition.due_rule, periods[0]) is None:
        closed = [p for p in periods if month_start <= p.end <= month_end]
        if closed:
            period = max(closed, key=lambda p: p.end)
            state = "sent" if period.key in sent else "no_date"
            in_month.append(CalendarEntry(None, definition, period, state, False))
    later.sort(key=lambda e: e.due or date.max)
    return in_month, later[:2]


def definition_payload(
    definition: ClientReportDefinition,
    *,
    preparer: str,
    next_info: dict[str, Any],
    last_sent: Optional[ClientReportRun],
    confirmable: bool,
    can_view_amounts: bool,
) -> dict[str, Any]:
    generator = get_generator(definition.generator_key)
    params = dict(definition.params or {})
    if generator and generator.needs_amounts and not can_view_amounts:
        # Progi i stawki rabatu to warunki handlowe z umowy — jak kwoty, tylko
        # dla „Stawki i kwoty: podgląd”. Zostają pola bez kwot (waluta, tryb).
        params = {k: v for k, v in params.items() if k in AMOUNT_FREE_PARAMS}
    return {
        "id": definition.id,
        "client_id": definition.client_id,
        "name": definition.name,
        "family": definition.family,
        "family_label": FAMILY_LABELS.get(definition.family, definition.family),
        "generator_key": definition.generator_key,
        "generator_label": generator.label if generator else None,
        "needs_amounts": bool(generator and generator.needs_amounts),
        "params": params,
        "rhythm": definition.rhythm,
        "due_rule": definition.due_rule or {},
        "due_label": schedule.describe_due_rule(definition.due_rule),
        "recipient": definition.recipient,
        "channel": definition.channel,
        "file_format": definition.file_format,
        "preparer": definition.preparer,
        "preparer_user_id": definition.preparer_user_id,
        "preparer_label": preparer,
        "source_kind": definition.source_kind,
        "source_contract_id": definition.source_contract_id,
        "source_chunk_id": definition.source_chunk_id,
        "source_ref": definition.source_ref,
        "status": definition.status,
        "valid_from": definition.valid_from.isoformat()
        if definition.valid_from
        else None,
        "valid_to": definition.valid_to.isoformat() if definition.valid_to else None,
        "notes": definition.notes,
        "confirmed_at": definition.confirmed_at.isoformat()
        if definition.confirmed_at
        else None,
        "can_confirm": confirmable,
        "next": next_info,
        "last_sent": (
            {
                "period_key": last_sent.period_key,
                "sent_at": last_sent.sent_at.isoformat() if last_sent.sent_at else None,
                "sent_to": last_sent.sent_to,
            }
            if last_sent
            else None
        ),
    }


async def client_names(db: AsyncSession, ids: Iterable[int]) -> dict[int, str]:
    wanted = set(ids)
    if not wanted:
        return {}
    rows = (
        await db.execute(select(Client.id, Client.name).where(Client.id.in_(wanted)))
    ).all()
    return {client_id: name for client_id, name in rows}
