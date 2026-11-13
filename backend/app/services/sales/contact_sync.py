"""Kontakty jako jedna lista: osoby od bota Kontakty i z Cognism w zakładce Kontakty.

Decyzje Artura z 13.11.2026:

* osoba, którą bot Kontakty albo rutyna Cognism zapisuje dla firmy, trafia też
  do ``sales_contacts`` tej firmy (bez dubli: ten sam e-mail albo to samo imię
  i nazwisko bez względu na kolejność wyrazów);
* pola ludzi bot nadpisuje nowszą wartością: stanowisko z nowszego źródła
  zastępuje obecne (także wpisane ręcznie), stare idzie do historii karty;
* osoba, która według źródła odeszła, dostaje stan „nie pracuje”
  (``sales_company_contacts.is_current = false``) i nic się nie kasuje;
* „Imię Nazwisko (Stanowisko)” w polu nazwiska rozdziela się, gdy stanowisko
  było puste.

„Nowsze” liczy się po dacie źródła (``as_of``: data publikacji u bota, dzień
odczytu w Cognism) wobec daty obecnego stanu kontaktu: dzień ostatniego zapisu
bota, gdy od tamtej chwili nikt kontaktu nie zmieniał, inaczej dzień ostatniej
zmiany kontaktu. Źródło bez daty niczego nie nadpisuje.

Historia: jeden wiersz ``sales_bot_results`` rodzaju ``contacts`` na bieg
i firmę (``payload.changes``), czytany przez ``bot_card_history``. Do bota nic
stąd nie idzie; dopasowanie osób robi NEXUS.

Reguły: ``docs/claude/sprzedaz/kontakty-jedna-lista.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.sales import (
    SalesBotResult,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
    SalesOpportunity,
    SalesPipeline,
    SalesSignalRun,
)
from app.services.sales import history
from app.services.sales.bot_tasks.base import result_fingerprint
from app.services.sales.contacts import set_primary_company
from app.services.sales.decision_map import (
    IT_FACTORIES_PIPELINE_KEY,
    decision_entries,
    describe_change,
    with_entries,
)
from app.services.sales.research_file import fold, person_key
from app.services.sales_schema import OpportunityEventKind

KIND = "contacts"
BOT = "bot"
COGNISM = "cognism"
#: ``sales_contacts.source`` nowego kontaktu (na ekranie się go nie pokazuje).
CONTACT_SOURCE = {BOT: "bot-kontakty", COGNISM: "cognism"}

ADDED = "added"
TITLE = "title"
LEFT = "left"
BACK = "back"
SPLIT = "split"

#: Zapis bota i ``updated_at`` kontaktu z tej samej transakcji różnią się o chwilę.
_SAME_WRITE = timedelta(minutes=5)
_NAME_WITH_TITLE = re.compile(r"^\s*(?P<name>[^()]+?)\s*\((?P<title>[^()]+)\)\s*$")
_LIMITS = {"email": 255, "phone": 60, "mobile_phone": 60, "linkedin_url": 500}


@dataclass(frozen=True)
class Seen:
    """Osoba ze źródła (bot Kontakty albo Cognism), już po walidacji raportu."""

    full_name: str
    source: str
    source_url: str
    #: Data źródła; bez niej stanowisko i odejście niczego nie nadpisują.
    as_of: Optional[date]
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile_phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    working: bool = True
    left_on: Optional[date] = None


@dataclass
class _Known:
    contact: SalesContact
    link: Optional[SalesCompanyContact]
    #: ``updated_at`` z chwili wczytania: po zapisie do bazy SQLAlchemy go
    #: przeterminowuje, a leniwy odczyt w sesji async kończy się błędem.
    updated: datetime
    marks: set[str] = field(default_factory=set)


def split_name(full_name: Optional[str]) -> Optional[tuple[str, str]]:
    """„Jan Kowalski (CTO)” → („Jan Kowalski”, „CTO”); inny kształt → ``None``."""

    match = _NAME_WITH_TITLE.match(full_name or "")
    if match is None:
        return None
    name, title = match["name"].strip(), match["title"].strip()
    if len(name.split()) < 2 or not title:
        return None
    return name, title


def marks(name: Optional[str], email: Optional[str]) -> set[str]:
    """Znaki osoby: imię i nazwisko (bez stanowiska w nawiasie) oraz e-mail."""

    found: set[str] = set()
    split = split_name(name)
    key = person_key(split[0] if split else name)
    if key:
        found.add(f"n:{key}")
    if email and email.strip():
        found.add(f"e:{email.strip().lower()}")
    return found


def same_title(left: Optional[str], right: Optional[str]) -> bool:
    return fold(left) == fold(right)


def newer(as_of: Optional[date], state_as_of: date) -> bool:
    return as_of is not None and as_of > state_as_of


def _title_here(known: _Known) -> Optional[str]:
    return (known.link.title if known.link else None) or known.contact.title


def _change(
    contact: SalesContact,
    change: str,
    seen: Optional[Seen],
    *,
    before: Optional[str] = None,
    after: Optional[str] = None,
    human: Optional[date] = None,
) -> dict[str, Any]:
    return {
        "contact_id": contact.id,
        "name": contact.full_name,
        "change": change,
        "before": before,
        "after": after,
        "source_url": seen.source_url if seen else None,
        "as_of": seen.as_of.isoformat() if seen and seen.as_of else None,
        # Dzień ręcznej zmiany sprzed tego zapisu: kolejny bieg porównuje się z nim.
        "human": human.isoformat() if human else None,
    }


async def _contacts(db: AsyncSession, company_id: int) -> list[_Known]:
    """Kontakty firmy (główne i powiązane) z wierszem powiązania z tą firmą."""

    link_here = and_(
        SalesCompanyContact.contact_id == SalesContact.id,
        SalesCompanyContact.company_id == company_id,
    )
    rows = (
        await db.execute(
            select(SalesContact, SalesCompanyContact)
            .outerjoin(SalesCompanyContact, link_here)
            .where(
                or_(
                    SalesContact.company_id == company_id,
                    SalesCompanyContact.company_id.is_not(None),
                )
            )
            # Aktywny kontakt przed zarchiwizowanym, potem najstarszy: pierwszy wygrywa.
            .order_by(SalesContact.archived_at.is_not(None), SalesContact.id)
        )
    ).all()
    return [
        _Known(
            contact,
            link,
            contact.updated_at or contact.created_at,
            marks(contact.full_name, contact.email),
        )
        for contact, link in rows
    ]


@dataclass
class Writes:
    """Zapisy automatu dla jednego kontaktu (z historii karty)."""

    #: Chwila ostatniego zapisu.
    at: datetime
    #: Dzień ręcznej zmiany sprzed ostatniego zapisu (``None``: kontakt założył automat).
    human: Optional[date]
    #: Najpóźniejsza data źródła spośród zapisów (bot i Cognism).
    as_of: Optional[date] = None
    #: Najpóźniejsza data opublikowanego źródła (tylko bot Kontakty).
    published: Optional[date] = None


async def _last_writes(db: AsyncSession, company_id: int) -> dict[int, Writes]:
    rows = await db.execute(
        select(SalesBotResult.decided_at, SalesBotResult.payload)
        .where(SalesBotResult.kind == KIND, SalesBotResult.company_id == company_id)
        .order_by(SalesBotResult.decided_at, SalesBotResult.id)
    )
    writes: dict[int, Writes] = {}
    for at, payload in rows.all():
        if at is None:
            continue
        source = (payload or {}).get("source")
        for item in (payload or {}).get("changes") or []:
            contact_id = item.get("contact_id")
            if not contact_id:
                continue
            human = item.get("human")
            found = writes.setdefault(contact_id, Writes(at=at, human=None))
            found.at = max(found.at, at)
            found.human = date.fromisoformat(human) if human else None
            if as_of := item.get("as_of"):
                day = date.fromisoformat(as_of)
                found.as_of = max(filter(None, (found.as_of, day)))
                if source == BOT:
                    found.published = max(filter(None, (found.published, day)))
    return writes


def human_date(updated: datetime, writes: Optional[Writes]) -> Optional[date]:
    """Dzień ostatniej zmiany kontaktu przez człowieka (albo import), jeśli jest znany.

    ``updated`` to ``updated_at`` kontaktu sprzed zmian w tym zapisie.
    """

    if writes is None or updated > writes.at + _SAME_WRITE:
        return business_date(updated) if updated else None
    return writes.human


def _latest(*days: Optional[date]) -> date:
    return max((day for day in days if day is not None), default=date.min)


def title_state(updated: datetime, writes: Optional[Writes]) -> date:
    """Data obecnego stanowiska: ręczna zmiana albo źródło ostatnich zapisów automatu."""

    return _latest(human_date(updated, writes), writes.as_of if writes else None)


def work_state(updated: datetime, writes: Optional[Writes]) -> date:
    """Data stanu „pracuje / nie pracuje”: ręczna zmiana albo opublikowane źródło.

    Odczyt Cognism się nie liczy: profil w Cognism bywa nieaktualny, więc nie
    dowodzi, że osoba wciąż pracuje, i nie blokuje datowanej informacji o odejściu.
    """

    return _latest(human_date(updated, writes), writes.published if writes else None)


def _fits(value: Optional[str], column: str) -> Optional[str]:
    return value if value and len(value) <= _LIMITS[column] else None


async def _add(
    db: AsyncSession, company_id: int, seen: Seen, *, working: bool
) -> SalesContact:
    contact = SalesContact(
        company_id=company_id,
        full_name=seen.full_name[:255],
        title=(seen.title or None) and seen.title[:255],
        email=_fits(seen.email, "email"),
        phone=_fits(seen.phone, "phone"),
        mobile_phone=_fits(seen.mobile_phone, "mobile_phone"),
        linkedin_url=_fits(seen.linkedin_url, "linkedin_url"),
        source=CONTACT_SOURCE[seen.source],
    )
    db.add(contact)
    await db.flush()
    await set_primary_company(db, contact, company_id)
    if not working:
        link = await db.get(SalesCompanyContact, (company_id, contact.id))
        if link is not None:
            link.is_current = False
            link.ended_at = seen.left_on
    return contact


def _set_title(known: _Known, company_id: int, title: str) -> None:
    title = title[:255]
    if known.link is not None:
        known.link.title = title
    if known.contact.company_id == company_id or not known.contact.title:
        known.contact.title = title


def _tidy_names(
    known: list[_Known], company_id: int, last: dict[int, Writes]
) -> list[dict[str, Any]]:
    """„Imię Nazwisko (Stanowisko)” → osobno, tylko gdy stanowiska nie było."""

    changes = []
    for item in known:
        contact = item.contact
        split = split_name(contact.full_name)
        if contact.archived_at is not None or split is None or _title_here(item):
            continue
        raw = contact.full_name
        name, title = split
        contact.full_name = name
        if contact.last_name and contact.last_name.rstrip().endswith(f"({title})"):
            contact.last_name = contact.last_name.rsplit("(", 1)[0].strip() or None
        _set_title(item, company_id, title)
        changes.append(
            _change(
                contact,
                SPLIT,
                None,
                before=raw,
                after=f"{name} · {title}",
                human=human_date(item.updated, last.get(contact.id)),
            )
        )
    return changes


async def _map_titles(
    db: AsyncSession,
    company_id: int,
    updates: Sequence[tuple[set[str], str]],
    now: datetime,
) -> None:
    """Nowe stanowisko trafia też na mapę konta w lejku Fabryki IT (wpis tej osoby)."""

    if not updates:
        return
    opportunity = (
        await db.execute(
            select(SalesOpportunity)
            .join(SalesPipeline, SalesPipeline.id == SalesOpportunity.pipeline_id)
            .where(
                SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY,
                SalesOpportunity.company_id == company_id,
                SalesOpportunity.archived_at.is_(None),
            )
            .order_by(SalesOpportunity.id)
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if opportunity is None:
        return
    entries = decision_entries(opportunity.custom_fields)
    changed = False
    for index, entry in enumerate(entries):
        entry_marks = marks(entry.get("name"), entry.get("email"))
        for person_marks, title in updates:
            if not (entry_marks & person_marks) or same_title(
                entry.get("role_in_company"), title
            ):
                continue
            after = {**entry, "role_in_company": title[:255]}
            old, new = describe_change(entry, after, ["role_in_company"])
            history.record(
                db,
                opportunity_id=opportunity.id,
                user_id=None,
                kind=OpportunityEventKind.updated,
                field="decision_map",
                old_value=old,
                new_value=f"{new} (nowsze źródło)",
            )
            entries[index] = after
            changed = True
            break
    if changed:
        opportunity.custom_fields = with_entries(
            opportunity.custom_fields, entries, user_id=None, now=now
        )


async def map_marks(db: AsyncSession, company_id: int) -> set[str]:
    """Znaki osób z mapy konta w lejku Fabryki IT."""

    rows = await db.execute(
        select(SalesOpportunity.custom_fields)
        .join(SalesPipeline, SalesPipeline.id == SalesOpportunity.pipeline_id)
        .where(
            SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY,
            SalesOpportunity.company_id == company_id,
            SalesOpportunity.archived_at.is_(None),
        )
    )
    found: set[str] = set()
    for (custom_fields,) in rows.all():
        for entry in decision_entries(custom_fields):
            name = entry.get("name") if isinstance(entry.get("name"), str) else None
            email = entry.get("email") if isinstance(entry.get("email"), str) else None
            found |= marks(name, email)
    return found


async def gone_marks(db: AsyncSession, company_id: int) -> set[str]:
    """Znaki osób, które w tej firmie „nie pracują” (kontakt poza archiwum)."""

    rows = await db.execute(
        select(SalesContact.full_name, SalesContact.email)
        .join(SalesCompanyContact, SalesCompanyContact.contact_id == SalesContact.id)
        .where(
            SalesCompanyContact.company_id == company_id,
            SalesCompanyContact.is_current.is_(False),
            SalesContact.archived_at.is_(None),
        )
    )
    found: set[str] = set()
    for name, email in rows.all():
        found |= marks(name, email)
    return found


async def sync(
    db: AsyncSession, company_id: int, people: Sequence[Seen], *, now: datetime
) -> list[dict[str, Any]]:
    """Zapis osób ze źródła w kontaktach firmy; zwraca zmiany do historii karty.

    Wywołujący odsiewa wcześniej klienta NEXUSA, naszą firmę, firmę „Nie
    kontaktować” i osoby ze sprzeciwem. Commit robi wywołujący.
    """

    # Dwa biegi tej samej firmy naraz nie zakładają tej samej osoby dwa razy.
    await db.execute(
        select(SalesCompany.id).where(SalesCompany.id == company_id).with_for_update()
    )
    known = await _contacts(db, company_id)
    last = await _last_writes(db, company_id)
    changes = _tidy_names(known, company_id, last)
    for item in known:
        item.marks = marks(item.contact.full_name, item.contact.email)
    on_map = await map_marks(db, company_id)
    map_updates: list[tuple[set[str], str]] = []
    handled: set[int] = set()
    seen_marks: set[str] = set()

    for seen in people:
        person = marks(seen.full_name, seen.email)
        if not person or person & seen_marks:
            continue
        seen_marks |= person
        match = next((k for k in known if k.marks & person), None)
        if match is None:
            if seen.working:
                contact = await _add(db, company_id, seen, working=True)
                changes.append(_change(contact, ADDED, seen, after=seen.title))
            elif person & on_map and seen.as_of is not None:
                # Osoba z mapy, która odeszła: kontakt z historią, „nie pracuje”.
                contact = await _add(db, company_id, seen, working=False)
                changes.append(_change(contact, LEFT, seen, after=seen.title))
            continue
        contact = match.contact
        if contact.archived_at is not None or contact.id in handled:
            continue
        handled.add(contact.id)
        writes = last.get(contact.id)
        human = human_date(match.updated, writes)
        current = match.link is None or match.link.is_current
        if not seen.working:
            if current and newer(seen.as_of, work_state(match.updated, writes)):
                if match.link is None:
                    # Kontakt z Atlasa bez wiersza powiązania: firma główna dostaje
                    # swój jedyny wiersz z ``is_primary``, inna firma zwykły.
                    if contact.company_id == company_id:
                        await set_primary_company(db, contact, company_id)
                        match.link = await db.get(
                            SalesCompanyContact, (company_id, contact.id)
                        )
                    else:
                        match.link = SalesCompanyContact(
                            company_id=company_id, contact_id=contact.id
                        )
                        db.add(match.link)
                match.link.is_current = False
                match.link.ended_at = seen.left_on
                changes.append(
                    _change(contact, LEFT, seen, before=_title_here(match), human=human)
                )
            continue
        if not current:
            # Wraca tylko źródło z datą publikacji nowszą niż odejście albo człowiek;
            # odczyt Cognism to stan profilu, który bywa nieaktualny.
            if seen.source != BOT or not newer(
                seen.as_of, work_state(match.updated, writes)
            ):
                continue
            match.link.is_current = True
            match.link.ended_at = None
            changes.append(_change(contact, BACK, seen, after=seen.title, human=human))
        if not seen.title:
            continue
        title_now = _title_here(match)
        if same_title(title_now, seen.title):
            continue
        if title_now and not newer(seen.as_of, title_state(match.updated, writes)):
            continue
        _set_title(match, company_id, seen.title)
        changes.append(
            _change(
                contact, TITLE, seen, before=title_now, after=seen.title, human=human
            )
        )
        map_updates.append((match.marks | person, seen.title))
    await _map_titles(db, company_id, map_updates, now)
    await db.flush()
    return changes


async def record(
    db: AsyncSession,
    run: SalesSignalRun,
    company_id: int,
    source: str,
    changes: list[dict[str, Any]],
    now: datetime,
) -> None:
    """Wiersz historii karty: zmiany kontaktów z jednego biegu dla jednej firmy."""

    if not changes:
        return
    db.add(
        SalesBotResult(
            run_id=run.id,
            kind=KIND,
            company_id=company_id,
            payload={"source": source, "changes": changes},
            fingerprint=result_fingerprint(KIND, run.id, company_id),
            status="accepted",
            decided_at=now,
            updated_at=now,
        )
    )
