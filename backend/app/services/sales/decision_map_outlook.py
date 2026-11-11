"""Mapa decyzyjna ← Outlook i telefon: status kontaktu osoby przesuwa się sam.

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

Zapisana rozmowa telefoniczna (decyzje Artura z 10.11.2026, ``_CALL_SIGNALS``):

* osoba odebrała („Dodzwoniłem”, „Prosi o ofertę”, „Nie teraz”, z kolejki
  dzwonienia „Oferta ogólna wysłana” i „Umówione spotkanie”) → „pierwszy kontakt”;
* próba bez rozmowy („Nie odebrał”, „Oddzwonić”) i telefon z importu bez wyniku →
  „w toku”, jak nasz mail bez odpowiedzi;
* „Nie kontaktować” to sprzeciw, nie kontakt.

Rozmowa zapisana na karcie szansy zmienia status od razu, w tym samym zapisie
(``record_call``). Telefon przy firmie bez szansy, z kolejki dzwonienia i z importu
dolicza przebieg po synchronizacji skrzynki, po kontakcie aktywności.

Status nigdy się nie cofa, data ostatniego kontaktu idzie tylko w przód, a osoba
ze sprzeciwem zostaje nietknięta. Ręczna zmiana statusu albo daty w oknie osoby ma
pierwszeństwo: zdarzenia sprzed niej już się nie liczą
(``decision_map.CONTACT_EDITED_AT``).

Z poczty i kalendarza liczą się tylko maile i spotkania z Outlooka zapisane
w Sprzedaży (``outlook_activities.py``). Korespondencja z kandydatem tam nie trafia, więc
statusu też nie przesuwa. Osobę z kontaktem łączy ta sama reguła co karta szansy
(``motion.match_contacts``), a do tego adres wpisany na mapie, gdy jest wśród
adresów maila albo uczestników spotkania.

Wynik zależy tylko od zdarzeń i stanu mapy, więc drugi przebieg nic nie zmienia.
Zapis trzyma blokadę wiersza szansy i liczy zmianę od nowa na zablokowanej treści.
Nie dotyka aktywności ani ``last_activity_at``: dotyk szansy (``touch.py``) wynika
z samego maila, spotkania albo telefonu.
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
    """Co zaszło między nami a osobą: dopisek do historii i status, który z tego wynika."""

    OUR_MAIL = ("z Outlooka: mail od nas", "in_progress")
    INCOMING_MAIL = ("z Outlooka: mail przychodzący", "in_progress")
    THEIR_MAIL = ("z Outlooka: mail od osoby", "first_contact")
    MEETING = ("z Outlooka: spotkanie", "first_contact")
    CALL_TALK = ("z telefonu: rozmowa", "first_contact")
    CALL_ATTEMPT = ("z telefonu: próba bez rozmowy", "in_progress")
    CALL_NO_OUTCOME = ("z telefonu: wpis bez wyniku", "in_progress")

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def status(self) -> str:
        return self.value[1]


#: Wynik zapisanej rozmowy → sygnał (decyzje Artura z 10.11.2026). ``None`` to telefon
#: z importu, który wyniku nie niesie. „Nie kontaktować” i wynik, o którym nikt jeszcze
#: nie zdecydował, kontaktem nie są; nowy wpis w ``CALL_OUTCOMES`` bez decyzji
#: zatrzymuje ``test_sales_decision_map_calls.py``.
_CALL_SIGNALS: dict[Optional[str], Signal] = {
    "connected": Signal.CALL_TALK,
    "wants_offer": Signal.CALL_TALK,
    "not_now": Signal.CALL_TALK,
    "offer_sent": Signal.CALL_TALK,
    "meeting_booked": Signal.CALL_TALK,
    "no_answer": Signal.CALL_ATTEMPT,
    "call_back": Signal.CALL_ATTEMPT,
    # 11.11.2026 (Excel dzwoniących): „Nie zainteresowany” to rozmowa jak „Nie teraz”,
    # „Zły numer / brak danych” to próba bez rozmowy jak „Nie odebrał”.
    "not_interested": Signal.CALL_TALK,
    "bad_contact": Signal.CALL_ATTEMPT,
    None: Signal.CALL_NO_OUTCOME,
}


def call_signal(outcome: Optional[str]) -> Optional[Signal]:
    """Czym zapisana rozmowa z tym wynikiem jest dla mapy; ``None`` = niczym."""

    return _CALL_SIGNALS.get(outcome)


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
    #: Wynik telefonu; pusty przy mailu, spotkaniu i telefonie z importu.
    outcome: Optional[str] = None


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
    #: Zakończone telefony osób z map według wyniku; „bez_wyniku” to import.
    calls: dict[str, int] = field(default_factory=dict)
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


async def _load_calls(
    db: AsyncSession,
    contact_ids: Collection[int],
    *,
    now: datetime,
    since: Optional[datetime],
) -> list[_Event]:
    """Zakończone telefony z osobami z map: zapis w NEXUSIE i historia z importu.

    Telefon łączy z osobą wyłącznie kontakt aktywności. Pozycja z terminem bez
    ``done_at`` to zadanie „zadzwonić”, nie rozmowa.
    """

    if not contact_ids:
        return []
    conditions = [
        SalesActivity.kind == "call",
        SalesActivity.contact_id.in_(contact_ids),
        SalesActivity.done_at.is_not(None),
        SalesActivity.done_at <= now,
    ]
    if since is not None:
        conditions.append(SalesActivity.done_at > since)
    rows = await db.execute(
        select(
            SalesActivity.contact_id, SalesActivity.done_at, SalesActivity.outcome
        ).where(*conditions)
    )
    return [
        _Event(
            contact_id=contact_id,
            kind="call",
            direction=None,
            occurred_at=done_at,
            sender=None,
            addresses=frozenset(),
            outcome=outcome,
        )
        for contact_id, done_at, outcome in rows.all()
    ]


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
    if event.kind == "call":
        return call_signal(event.outcome)
    if event.kind == "meeting":
        return Signal.MEETING
    if event.direction == "out":
        return Signal.OUR_MAIL
    if event.sender is not None and event.sender in addresses:
        return Signal.THEIR_MAIL
    return Signal.INCOMING_MAIL


def _objects(entry: dict[str, Any], contact: Optional[_Contact]) -> bool:
    return bool(entry.get("do_not_contact")) or bool(contact and contact.objects)


def _advance(
    opportunity_id: int,
    index: int,
    entry: dict[str, Any],
    hits: Sequence[tuple[datetime, Signal]],
) -> Optional[Change]:
    """Status i data kontaktu osoby po zdarzeniach, które jej dotyczą.

    Zdarzenia sprzed ręcznej zmiany się nie liczą, status tylko rośnie, a data
    idzie tylko w przód. ``None``, gdy nic się nie zmienia.
    """

    edited_at = _moment(entry.get(decision_map.CONTACT_EDITED_AT))
    hits = [hit for hit in hits if edited_at is None or hit[0] > edited_at]
    if not hits:
        return None
    latest_at, signal = max(hits, key=lambda hit: hit[0])
    _, strongest = max(hits, key=lambda hit: (_STATUS_RANK[hit[1].status], hit[0]))
    after = dict(entry)
    fields = []
    if _STATUS_RANK[strongest.status] > _STATUS_RANK[_status(entry)]:
        after["contact_status"] = strongest.status
        fields.append("contact_status")
        signal = strongest
    day = business_date(latest_at)
    known = _day(entry.get("last_contact_at"))
    if known is None or known < day:
        after["last_contact_at"] = day.isoformat()
        fields.append("last_contact_at")
    if not fields:
        return None
    return Change(
        opportunity_id=opportunity_id,
        index=index,
        before=entry,
        after=after,
        fields=tuple(fields),
        signal=signal,
    )


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
        hits = [
            (event.occurred_at, signal)
            for event in events
            if (signal := _signal(event, contact_id, addresses)) is not None
        ]
        change = _advance(opportunity_id, index, entry, hits)
        if change is not None:
            changes.append(change)
    return changes


def _save(
    db: AsyncSession,
    opportunity: SalesOpportunity,
    entries: list[dict[str, Any]],
    changes: Sequence[Change],
    now: datetime,
) -> None:
    """Zmiany na mapie i wiersz historii na osobę; wiersz szansy jest pod blokadą."""

    for change in changes:
        entries[change.index] = change.after
    opportunity.custom_fields = decision_map.with_entries(
        opportunity.custom_fields, entries, user_id=None, now=now
    )
    for change in changes:
        old_value, new_value = decision_map.describe_change(
            change.before, change.after, list(change.fields)
        )
        # Sam rodzaj zdarzenia: tematu, treści ani notatki z rozmowy historia nie trzyma.
        history.record(
            db,
            opportunity_id=opportunity.id,
            user_id=None,
            kind=OpportunityEventKind.updated,
            field=HISTORY_FIELD,
            old_value=old_value,
            new_value=f"{new_value} · {change.signal.label}",
        )


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
    if changes:
        _save(db, opportunity, entries, changes, now)
    return changes


def record_call(
    db: AsyncSession,
    opportunity: SalesOpportunity,
    entries: list[dict[str, Any]],
    indexes: Collection[int],
    *,
    outcome: str,
    at: datetime,
) -> list[Change]:
    """Rozmowa zapisana na karcie szansy: status osoby od razu, w tym samym zapisie.

    Wywołujący (``calls.log_call``) trzyma blokadę wiersza szansy, wskazuje wpisy
    osoby, z którą była rozmowa, i wcześniej odrzucił sprzeciw jej kontaktu. Osoba
    tylko z mapy kontaktu nie ma, więc przebieg po synchronizacji by jej nie znalazł.
    """

    signal = call_signal(outcome)
    live = opportunity.status == "open" and opportunity.archived_at is None
    if signal is None or not live:
        return []
    changes = []
    for index in sorted(indexes):
        entry = entries[index]
        if not _named(entry) or _objects(entry, None):
            continue
        change = _advance(opportunity.id, index, entry, [(at, signal)])
        if change is not None:
            changes.append(change)
    if changes:
        _save(db, opportunity, entries, changes, at)
    return changes


def _event_counts(events: Sequence[_Event]) -> dict[str, int]:
    return dict(
        Counter(
            "meeting" if event.kind == "meeting" else f"mail_{event.direction}"
            for event in events
        )
    )


def _call_counts(calls: Sequence[_Event]) -> dict[str, int]:
    return dict(Counter(call.outcome or "bez_wyniku" for call in calls))


async def sync(
    db: AsyncSession, *, now: datetime, since: Optional[datetime] = None, apply: bool
) -> Report:
    """Statusy na mapach otwartych szans według zdarzeń z Outlooka i telefonów.

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
    calls = await _load_calls(db, contact_ids, now=now, since=since)
    report = Report(events=_event_counts(events), calls=_call_counts(calls))
    events = [*events, *calls]
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
