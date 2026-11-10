"""Mapa decyzyjna ← Outlook: status kontaktu osoby przesuwa się sam.

Decyzje Artura z 10.11.2026 (rekomendacja B4). Status na mapie zmieniał wyłącznie
człowiek w oknie osoby i od 24.10 nikt go nie ruszył, więc lista kont i kolejka
Fabryk IT (``factories.py``) mówiły „bez kontaktu” o osobach, z którymi handlowiec
już pisał.

Zdarzenie → status:

* nasz mail do osoby → „w toku”;
* mail przychodzący, w którym osoba jest tylko w kopii albo nie znamy nadawcy
  (historia z importu bez adresów) → „w toku”;
* mail, którego nadawcą jest osoba, albo odbyte, nieodwołane spotkanie →
  „pierwszy kontakt”;
* „stały dialog” ustawia tylko człowiek.

Auto-odpowiedź, potwierdzenie zaproszenia i zwrotka nie są kontaktem
(``my_day.is_auto_subject``): osoba, która ma włączoną nieobecność, nie odpisała.

Status nigdy się nie cofa, data ostatniego kontaktu idzie tylko w przód, a osoba
ze sprzeciwem zostaje nietknięta. Ręczna zmiana statusu albo daty w oknie osoby ma
pierwszeństwo: zdarzenia sprzed niej już się nie liczą
(``decision_map.CONTACT_EDITED_AT``).

Liczą się tylko maile i spotkania z Outlooka zapisane w Sprzedaży
(``outlook_activities.py``). Korespondencja z kandydatem tam nie trafia, więc
statusu też nie przesuwa. Osobę z kontaktem łączy ta sama reguła co karta szansy
(``motion.match_contacts``), a do tego adres wpisany na mapie, gdy jest wśród
adresów maila albo uczestników spotkania.

Wynik zależy tylko od zdarzeń i stanu mapy, więc drugi przebieg nic nie zmienia.
Zapis trzyma blokadę wiersza szansy i liczy zmianę od nowa na zablokowanej treści.
Nie dotyka aktywności ani ``last_activity_at``: dotyk szansy (``touch.py``) wynika
z samego maila albo spotkania.
"""

from __future__ import annotations

import enum
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.scheduling import business_date
from app.models.app_setting import AppSetting
from app.models.calendar_event import CalendarEvent
from app.models.m365 import Email
from app.models.sales import SalesActivity, SalesContact, SalesOpportunity
from app.services.sales import decision_map, history
from app.services.sales.motion import ContactIndex, load_contact_index, match_contacts
from app.services.sales.my_day import is_auto_subject
from app.services.sales.outlook_activities import EMAIL_SOURCE, EVENT_SOURCE
from app.services.sales.task_scope import live_opportunity
from app.services.sales.touch import not_cancelled
from app.services.sales_schema import OpportunityEventKind

HISTORY_FIELD = "decision_map"
#: Chwila pierwszego przebiegu po wdrożeniu. Wcześniejsze zdarzenia przechodzi
#: ``scripts/sales_decision_map_outlook.py``, na produkcji po zgodzie Artura.
LIVE_SINCE_KEY = "sales_decision_map_outlook_since"
#: Przebieg po synchronizacji patrzy najwyżej tyle wstecz, żeby zapytanie nie rosło
#: z historią; starsze zdarzenia poprzednie przebiegi już policzyły.
LIVE_LOOKBACK = timedelta(days=30)

_STATUS_RANK = {
    "not_contacted": 0,
    "in_progress": 1,
    "first_contact": 2,
    "regular_dialog": 3,
}
_MAP_PATH = ("atlas", "it_factory", "decision_map")


class Signal(enum.Enum):
    """Co zaszło między nami a osobą: podpis do historii i status, który z tego wynika."""

    OUR_MAIL = ("mail od nas", "in_progress")
    INCOMING_MAIL = ("mail przychodzący", "in_progress")
    THEIR_MAIL = ("mail od osoby", "first_contact")
    MEETING = ("spotkanie", "first_contact")

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def status(self) -> str:
        return self.value[1]


@dataclass(frozen=True)
class _Event:
    contact_id: Optional[int]
    kind: str
    direction: Optional[str]
    occurred_at: datetime
    #: Nadawca maila, gdy NEXUS ma wiersz poczty z adresami.
    sender: Optional[str]
    #: Mail: nadawca i odbiorcy; spotkanie: uczestnicy. Puste = znamy sam kontakt.
    addresses: frozenset[str]


@dataclass(frozen=True)
class _Contact:
    email: Optional[str]
    objects: bool


@dataclass(frozen=True)
class Change:
    opportunity_id: int
    index: int
    before: dict[str, Any]
    after: dict[str, Any]
    fields: tuple[str, ...]
    signal: Signal

    @property
    def old_status(self) -> str:
        return _status(self.before)

    @property
    def new_status(self) -> str:
        return _status(self.after)


@dataclass
class Report:
    open_maps: int = 0
    people: int = 0
    people_with_contact: int = 0
    skipped_objection: int = 0
    events: dict[str, int] = field(default_factory=dict)
    changes: list[Change] = field(default_factory=list)


def _open_maps() -> list[ColumnElement[bool]]:
    """Szansa, która trwa i ma listę osób na mapie."""

    return [
        live_opportunity(),
        func.jsonb_typeof(SalesOpportunity.custom_fields[_MAP_PATH]) == "array",
    ]


def _norm(value: Any) -> Optional[str]:
    text = value.strip().lower() if isinstance(value, str) else ""
    return text or None


def _named(entry: dict[str, Any]) -> bool:
    name = entry.get("name")
    return isinstance(name, str) and bool(name.strip())


def _status(entry: dict[str, Any]) -> str:
    """Status z mapy; wartość spoza listy (import bez walidacji) to brak kontaktu."""

    status = entry.get("contact_status")
    if isinstance(status, str) and status in _STATUS_RANK:
        return status
    return "not_contacted"


def _day(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _moment(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _addresses(recipients: Any) -> list[str]:
    """Adresy z listy odbiorców albo uczestników (``[{address, name}]``)."""

    if not isinstance(recipients, list):
        return []
    found = [
        _norm(row.get("address") if isinstance(row, dict) else row)
        for row in recipients
    ]
    return [address for address in found if address]


async def _mail_addresses(
    db: AsyncSession, message_ids: Collection[str]
) -> dict[str, tuple[Optional[str], set[str]]]:
    """``internetMessageId`` → nadawca i wszystkie adresy wiadomości."""

    if not message_ids:
        return {}
    rows = await db.execute(
        select(
            Email.m365_internet_message_id,
            Email.from_address,
            Email.to_addresses,
            Email.cc_addresses,
        ).where(Email.m365_internet_message_id.in_(message_ids))
    )
    mails: dict[str, tuple[Optional[str], set[str]]] = {}
    for message_id, sender, to, cc in rows.all():
        sender = _norm(sender)
        # Ta sama wiadomość w dwóch skrzynkach NEXUSA ma tego samego nadawcę.
        addresses = mails.setdefault(message_id, (sender, set()))[1]
        addresses.update(a for a in (sender, *_addresses(to), *_addresses(cc)) if a)
    return mails


async def _meeting_addresses(
    db: AsyncSession, ical_uids: Collection[str]
) -> dict[str, set[str]]:
    if not ical_uids:
        return {}
    rows = await db.execute(
        select(CalendarEvent.m365_ical_uid, CalendarEvent.attendees).where(
            CalendarEvent.m365_ical_uid.in_(ical_uids)
        )
    )
    meetings: dict[str, set[str]] = {}
    for ical_uid, attendees in rows.all():
        meetings.setdefault(ical_uid, set()).update(_addresses(attendees))
    return meetings


async def _load_events(
    db: AsyncSession,
    company_ids: Collection[int],
    contact_ids: Collection[int],
    *,
    now: datetime,
    since: Optional[datetime],
) -> list[_Event]:
    """Maile w obie strony i odbyte, nieodwołane spotkania z Outlooka."""

    involved = [SalesActivity.company_id.in_(company_ids)]
    if contact_ids:
        # Kontakt znaleziony po id z Atlasa bywa przy innej karcie tej samej firmy.
        involved.append(SalesActivity.contact_id.in_(contact_ids))
    conditions = [
        or_(*involved),
        SalesActivity.occurred_at <= now,
        or_(
            and_(
                SalesActivity.external_source == EMAIL_SOURCE,
                SalesActivity.kind == "email",
                SalesActivity.direction.in_(("in", "out")),
            ),
            and_(
                SalesActivity.external_source == EVENT_SOURCE,
                SalesActivity.kind == "meeting",
                *not_cancelled(),
            ),
        ),
    ]
    if since is not None:
        conditions.append(SalesActivity.occurred_at > since)
    rows = (
        await db.execute(
            select(
                SalesActivity.contact_id,
                SalesActivity.kind,
                SalesActivity.direction,
                SalesActivity.occurred_at,
                SalesActivity.external_id,
                SalesActivity.subject,
            ).where(*conditions)
        )
    ).all()
    rows = [
        row for row in rows if row.kind != "email" or not is_auto_subject(row.subject)
    ]
    mails = await _mail_addresses(
        db, {row.external_id for row in rows if row.kind == "email" and row.external_id}
    )
    meetings = await _meeting_addresses(
        db,
        {row.external_id for row in rows if row.kind == "meeting" and row.external_id},
    )
    events = []
    for row in rows:
        sender: Optional[str] = None
        addresses: Collection[str] = ()
        if row.kind == "email":
            sender, addresses = mails.get(row.external_id, (None, ()))
        else:
            addresses = meetings.get(row.external_id, ())
        events.append(
            _Event(
                contact_id=row.contact_id,
                kind=row.kind,
                direction=row.direction,
                occurred_at=row.occurred_at,
                sender=sender,
                addresses=frozenset(addresses),
            )
        )
    return events


async def _contacts(
    db: AsyncSession, contact_ids: Collection[int]
) -> dict[int, _Contact]:
    if not contact_ids:
        return {}
    rows = await db.execute(
        select(
            SalesContact.id, SalesContact.email, SalesContact.do_not_contact_at
        ).where(SalesContact.id.in_(contact_ids))
    )
    return {
        contact_id: _Contact(email=_norm(email), objects=objected_at is not None)
        for contact_id, email, objected_at in rows.all()
    }


def _signal(
    event: _Event, contact_id: Optional[int], addresses: frozenset[str]
) -> Optional[Signal]:
    """Czym to zdarzenie jest dla osoby; ``None``, gdy jej nie dotyczy."""

    by_contact = contact_id is not None and event.contact_id == contact_id
    if not by_contact and not (addresses & event.addresses):
        return None
    if event.kind == "meeting":
        return Signal.MEETING
    if event.direction == "out":
        return Signal.OUR_MAIL
    if event.sender is not None and event.sender in addresses:
        return Signal.THEIR_MAIL
    return Signal.INCOMING_MAIL


def _objects(entry: dict[str, Any], contact: Optional[_Contact]) -> bool:
    return bool(entry.get("do_not_contact")) or bool(contact and contact.objects)


def _plan(
    opportunity_id: int,
    entries: Sequence[dict[str, Any]],
    contact_ids: Sequence[Optional[int]],
    contacts: dict[int, _Contact],
    events: Sequence[_Event],
) -> list[Change]:
    """Zmiany statusu i daty kontaktu, które wynikają ze zdarzeń; niczego nie zapisuje."""

    changes = []
    for index, (entry, contact_id) in enumerate(zip(entries, contact_ids)):
        contact = contacts.get(contact_id) if contact_id is not None else None
        if not _named(entry) or _objects(entry, contact):
            continue
        addresses = frozenset(
            a
            for a in (_norm(entry.get("email")), contact.email if contact else None)
            if a
        )
        edited_at = _moment(entry.get(decision_map.CONTACT_EDITED_AT))
        hits = [
            (event, signal)
            for event in events
            if (edited_at is None or event.occurred_at > edited_at)
            and (signal := _signal(event, contact_id, addresses)) is not None
        ]
        if not hits:
            continue
        latest, signal = max(hits, key=lambda hit: hit[0].occurred_at)
        _, strongest = max(
            hits, key=lambda hit: (_STATUS_RANK[hit[1].status], hit[0].occurred_at)
        )
        after = dict(entry)
        fields = []
        if _STATUS_RANK[strongest.status] > _STATUS_RANK[_status(entry)]:
            after["contact_status"] = strongest.status
            fields.append("contact_status")
            signal = strongest
        day = business_date(latest.occurred_at)
        known = _day(entry.get("last_contact_at"))
        if known is None or known < day:
            after["last_contact_at"] = day.isoformat()
            fields.append("last_contact_at")
        if fields:
            changes.append(
                Change(
                    opportunity_id=opportunity_id,
                    index=index,
                    before=entry,
                    after=after,
                    fields=tuple(fields),
                    signal=signal,
                )
            )
    return changes


async def _write(
    db: AsyncSession,
    opportunity_id: int,
    index: ContactIndex,
    contacts: dict[int, _Contact],
    events: Sequence[_Event],
    now: datetime,
) -> list[Change]:
    """Zapis pod blokadą wiersza szansy, jak poprawka osoby w oknie.

    Zmiana liczy się od nowa na zablokowanej treści: między odczytem a blokadą
    ktoś mógł poprawić osobę albo zamknąć szansę.
    """

    opportunity = await db.scalar(
        select(SalesOpportunity)
        .where(SalesOpportunity.id == opportunity_id, *_open_maps())
        .with_for_update()
        # Sesja przebiegu skrzynki żyje długo i mogła wczytać tę szansę wcześniej;
        # bez tego ORM oddałby jej starą kopię i zapis zgubiłby cudzą poprawkę.
        .execution_options(populate_existing=True)
    )
    if opportunity is None:
        return []
    entries = decision_map.decision_entries(opportunity.custom_fields)
    changes = _plan(
        opportunity.id,
        entries,
        match_contacts(index, opportunity.company_id, entries),
        contacts,
        events,
    )
    if not changes:
        return []
    for change in changes:
        entries[change.index] = change.after
    opportunity.custom_fields = decision_map.with_entries(
        opportunity.custom_fields, entries, user_id=None, now=now
    )
    for change in changes:
        old_value, new_value = decision_map.describe_change(
            change.before, change.after, list(change.fields)
        )
        # Sam rodzaj zdarzenia: tematu ani treści z Outlooka historia nie trzyma.
        history.record(
            db,
            opportunity_id=opportunity.id,
            user_id=None,
            kind=OpportunityEventKind.updated,
            field=HISTORY_FIELD,
            old_value=old_value,
            new_value=f"{new_value} · z Outlooka: {change.signal.label}",
        )
    return changes


def _event_counts(events: Sequence[_Event]) -> dict[str, int]:
    return dict(
        Counter(
            "meeting" if event.kind == "meeting" else f"mail_{event.direction}"
            for event in events
        )
    )


async def sync(
    db: AsyncSession, *, now: datetime, since: Optional[datetime] = None, apply: bool
) -> Report:
    """Statusy na mapach otwartych szans według zdarzeń z Outlooka.

    ``since`` zawęża zdarzenia do późniejszych niż ta chwila; bez niego liczy się
    cała historia. ``apply=False`` tylko liczy. Wywołujący robi commit.
    """

    rows = (
        await db.execute(
            select(
                SalesOpportunity.id,
                SalesOpportunity.company_id,
                SalesOpportunity.custom_fields,
            )
            .where(*_open_maps())
            .order_by(SalesOpportunity.id)
        )
    ).all()
    if not rows:
        return Report()
    maps = [
        (row.company_id, decision_map.decision_entries(row.custom_fields))
        for row in rows
    ]
    index = await load_contact_index(db, maps)
    matched = [
        match_contacts(index, company_id, entries) for company_id, entries in maps
    ]
    contact_ids = {cid for ids in matched for cid in ids if cid is not None}
    contacts = await _contacts(db, contact_ids)
    events = await _load_events(
        db, {company_id for company_id, _ in maps}, contact_ids, now=now, since=since
    )
    report = Report(events=_event_counts(events))
    for row, (_, entries), ids in zip(rows, maps, matched):
        people = [(entry, cid) for entry, cid in zip(entries, ids) if _named(entry)]
        if not people:
            continue
        report.open_maps += 1
        report.people += len(people)
        report.people_with_contact += sum(1 for _, cid in people if cid is not None)
        report.skipped_objection += sum(
            1
            for entry, cid in people
            if _objects(entry, contacts.get(cid) if cid is not None else None)
        )
        changes = _plan(row.id, entries, ids, contacts, events)
        if changes and apply:
            changes = await _write(db, row.id, index, contacts, events, now)
        report.changes.extend(changes)
    return report


async def _live_since(db: AsyncSession, now: datetime) -> datetime:
    await db.execute(
        pg_insert(AppSetting)
        .values(key=LIVE_SINCE_KEY, value={"since": now.isoformat()})
        .on_conflict_do_nothing(index_elements=[AppSetting.key])
    )
    value = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == LIVE_SINCE_KEY)
    )
    return datetime.fromisoformat(value["since"])


async def sync_live(db: AsyncSession, *, now: Optional[datetime] = None) -> int:
    """Przebieg po synchronizacji skrzynki: zdarzenia od uruchomienia automatu.

    Pierwszy przebieg tylko zapamiętuje start, więc wdrożenie samo nie przepisuje
    map według historii. Zwraca liczbę zmienionych osób; wywołujący robi commit.
    """

    moment = now or datetime.now(timezone.utc)
    started = await _live_since(db, moment)
    report = await sync(
        db, now=moment, since=max(started, moment - LIVE_LOOKBACK), apply=True
    )
    return len(report.changes)
