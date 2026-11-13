"""Sprzedaż → „Mój dzień”: co handlowiec ma dziś zrobić, po kolei.

Cztery sekcje, liczone dla jednej osoby:

* **Spotkania dziś**: jej spotkania z kalendarza firmy (``Europe/Warsaw``), jedno
  wydarzenie to jeden wiersz, choć synchronizacja dała je przy kilku firmach.
* **Odpowiedz**: ostatni prawdziwy mail od klienta firmy z jej otwartą szansą, na
  który od ``REPLY_AFTER_BUSINESS_DAYS`` dni roboczych nikt nie zareagował. Reakcją
  jest mail wychodzący (także bez odpowiedzi na ten wątek), telefon, spotkanie
  i zaplanowany krok, również na drugiej karcie tej samej firmy.
* **Zaległe kroki**: jej zadania i telefony sprzed dziś, do ``OVERDUE_WINDOW_DAYS``
  dni; starsze są jednym licznikiem, bo ich lista przykryłaby dzisiejszą pracę.
* **Oferty bez ruchu**: jej szanse na etapie „Oferta wysłana”, których ostatni
  dotyk (``touch.py``) jest starszy niż ``OFFER_IDLE_DAYS`` dni i bez kroku w przyszłości
  (``next_step.py``).

Logi nie dostają stąd niczego: kwoty i nazwy firm mają zostać na ekranie.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import (
    DEFAULT_TZ,
    business_date,
    is_business_day,
    local_day_bounds,
)
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityContact,
    SalesPipelineStage,
)
from app.services import sales_schema as schema
from app.services.sales import next_step
from app.services.sales.kpi import OFFER_STAGE_KEY
from app.services.sales.meeting_autopin import auto_pinned
from app.services.sales.meeting_decisions import is_outlook
from app.services.sales.touch import last_touch_at, not_cancelled, touched_at

REPLY_WINDOW_DAYS = 21
REPLY_AFTER_BUSINESS_DAYS = 2
OVERDUE_WINDOW_DAYS = 60
OFFER_IDLE_DAYS = 14
OFFERS_PREVIEW = 10
#: Ile osób bez numeru podpowiadamy w „Uzupełnij numer”.
PEOPLE_WITHOUT_PHONE_LIMIT = 8
PREP_CONTACTS = 5
PREP_HISTORY = 2
PREP_HISTORY_FETCH = 8
SUBJECT_PREVIEW = 200

OUTLOOK_MAIL_SOURCE = "msgraph-mail"
COMPANY_DO_NOT_CONTACT = "do_not_contact"
#: Maile, których nikt nie napisał. Przedrostki kalendarza mają dwukropek, bo bez niego
#: to zwykły mail, np. „Zaproszenie do złożenia ofert” od klienta.
AUTO_SUBJECT = re.compile(
    r"^\s*(?:"
    r"(?:accepted|tentative|declined|canceled|cancelled|invitation|updated invitation"
    r"|new time proposed|meeting forward notification"
    r"|zaakceptowano|wstępnie zaakceptowano|wstępna akceptacja|odrzucono"
    r"|odwołano|odwołanie|anulowano|zaproszenie)\s*:"
    r"|automatic reply|automatyczna odpowiedź|odpowiedź automatyczna"
    r"|out of office|autoreply|auto-reply|poza biurem"
    r"|informacja o nieobecności|nieobecność\s*(?::|$)"
    r"|undeliverable|niedostarczon"
    r")"
    r"|meeting recap",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DayPerson:
    id: int
    name: str
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


@dataclass(frozen=True)
class DayRef:
    id: int
    title: str


@dataclass(frozen=True)
class DayRow:
    key: str
    section: str
    company_id: int
    company_name: str
    subject: Optional[str]
    at: datetime
    days: int = 0
    amount: Optional[Decimal] = None
    currency: str = "PLN"
    opportunity: Optional[DayRef] = None
    activity_id: Optional[int] = None
    kind: Optional[str] = None
    open_opportunities: int = 0
    duration_minutes: Optional[int] = None
    web_link: Optional[str] = None
    do_not_contact: bool = False
    person: Optional[DayPerson] = None
    people_without_phone: tuple[DayPerson, ...] = ()
    #: Spotkanie z kalendarza przypięte do szansy przez automat (``meeting_autopin``).
    auto_pinned: bool = False
    #: Spotkanie z Outlooka przy firmie bez otwartej szansy: po nim „Załóż szansę”.
    can_create_opportunity: bool = False


@dataclass(frozen=True)
class PrepHistoryItem:
    kind: str
    direction: Optional[str]
    at: datetime
    subject: Optional[str]
    days: int = 0


@dataclass(frozen=True)
class MeetingPrep:
    activity_id: int
    company_id: int
    company_name: str
    subject: Optional[str]
    at: datetime
    duration_minutes: Optional[int]
    open_opportunities: int
    can_create_opportunity: bool
    history: tuple[PrepHistoryItem, ...] = ()
    contacts: tuple[DayPerson, ...] = ()


@dataclass(frozen=True)
class MyDay:
    today: date
    meetings: list[DayRow] = field(default_factory=list)
    reply: list[DayRow] = field(default_factory=list)
    overdue: list[DayRow] = field(default_factory=list)
    offers: list[DayRow] = field(default_factory=list)
    older_tasks: int = 0
    prep: Optional[MeetingPrep] = None


@dataclass(frozen=True)
class _Opp:
    id: int
    company_id: int
    company_name: str
    company_status: str
    title: str
    value: Optional[Decimal]
    currency: str
    stage_key: str
    primary_contact_id: Optional[int]
    touched_at: datetime
    row: SalesOpportunity


def is_auto_subject(subject: Optional[str]) -> bool:
    return bool(subject and AUTO_SUBJECT.search(subject))


def business_days_after(day: date, today: date) -> int:
    """Ile dni roboczych minęło po ``day``, do ``today`` włącznie."""

    zone = ZoneInfo(DEFAULT_TZ)
    count = 0
    current = day + timedelta(days=1)
    while current <= today:
        if is_business_day(datetime.combine(current, time(12), tzinfo=zone)):
            count += 1
        current += timedelta(days=1)
    return count


def _amount_order(row: DayRow) -> tuple[bool, Decimal, datetime]:
    return (row.amount is None, -(row.amount or Decimal(0)), row.at)


def _first_word(name: Optional[str]) -> str:
    return (name or "").split(" ")[0]


def _usable_name(name: str) -> bool:
    return "@" not in name


def _phone(contact: SalesContact) -> Optional[str]:
    return (contact.mobile_phone or contact.phone or "").strip() or None


def _reachable(contact: SalesContact) -> bool:
    return contact.archived_at is None and contact.do_not_contact_at is None


def _person(contact: SalesContact) -> DayPerson:
    return DayPerson(
        id=contact.id,
        name=contact.full_name,
        title=contact.title,
        phone=_phone(contact),
        email=contact.email,
    )


class _Contacts:
    """Osoby firm z kolejki: kogo pokazać w wierszu i komu dopisać numer."""

    def __init__(self) -> None:
        self.by_id: dict[int, SalesContact] = {}
        self.of_company: dict[int, list[SalesContact]] = {}
        self.of_opportunity: dict[int, list[int]] = {}
        self.history: dict[int, list[int]] = {}

    @classmethod
    async def load(
        cls,
        db: AsyncSession,
        company_ids: set[int],
        opportunity_ids: set[int],
    ) -> "_Contacts":
        book = cls()
        if not company_ids:
            return book
        link_rows = (
            await db.execute(
                select(SalesContact, SalesCompanyContact.company_id)
                .join(
                    SalesCompanyContact,
                    SalesCompanyContact.contact_id == SalesContact.id,
                )
                .where(
                    SalesCompanyContact.company_id.in_(company_ids),
                    SalesCompanyContact.is_current.is_(True),
                )
            )
        ).all()
        primary = (
            await db.execute(
                select(SalesContact).where(SalesContact.company_id.in_(company_ids))
            )
        ).scalars()
        seen: set[tuple[int, int]] = set()
        pairs = [(contact, company_id) for contact, company_id in link_rows]
        pairs += [(contact, contact.company_id) for contact in primary]
        for contact, company_id in pairs:
            book.by_id[contact.id] = contact
            if (company_id, contact.id) not in seen:
                seen.add((company_id, contact.id))
                book.of_company.setdefault(company_id, []).append(contact)
        for contacts in book.of_company.values():
            contacts.sort(key=lambda item: (not item.is_executive, -item.id))

        for opportunity_id, contact_id in (
            await db.execute(
                select(
                    SalesOpportunityContact.opportunity_id,
                    SalesOpportunityContact.contact_id,
                )
                .where(SalesOpportunityContact.opportunity_id.in_(opportunity_ids))
                .order_by(SalesOpportunityContact.contact_id.desc())
            )
        ).all():
            book.of_opportunity.setdefault(opportunity_id, []).append(contact_id)

        happened = func.coalesce(SalesActivity.occurred_at, SalesActivity.created_at)
        for company_id, contact_id in (
            await db.execute(
                select(SalesActivity.company_id, SalesActivity.contact_id)
                .where(
                    SalesActivity.company_id.in_(company_ids),
                    SalesActivity.contact_id.is_not(None),
                )
                .group_by(SalesActivity.company_id, SalesActivity.contact_id)
                .order_by(func.max(happened).desc())
            )
        ).all():
            book.history.setdefault(company_id, []).append(contact_id)

        extra = {
            contact_id for ids in book.of_opportunity.values() for contact_id in ids
        } - set(book.by_id)
        if extra:
            for contact in (
                await db.execute(select(SalesContact).where(SalesContact.id.in_(extra)))
            ).scalars():
                book.by_id[contact.id] = contact
        return book

    def _candidates(
        self,
        company_id: int,
        opportunity_id: Optional[int],
        primary_contact_id: Optional[int],
        contact_id: Optional[int],
    ) -> list[SalesContact]:
        company_people = [item.id for item in self.of_company.get(company_id, [])]
        opportunity_people = self.of_opportunity.get(opportunity_id or -1, [])
        # Tylko ludzie firmy albo szansy: historia niesie też uczestników kalendarza,
        # a zapis rozmowy z kimś spoza firmy kończy się 422 (``calls._contact_in_company``).
        belonging = {*company_people, *opportunity_people}
        order: list[Optional[int]] = [
            contact_id,
            primary_contact_id,
            *opportunity_people,
            *self.history.get(company_id, []),
            *company_people,
        ]
        seen: set[int] = set()
        found: list[SalesContact] = []
        for item in order:
            if item is None or item in seen or item not in belonging:
                continue
            seen.add(item)
            contact = self.by_id.get(item)
            if contact is not None and _reachable(contact):
                found.append(contact)
        return found

    def pick(
        self,
        company_id: int,
        *,
        opportunity_id: Optional[int] = None,
        primary_contact_id: Optional[int] = None,
        contact_id: Optional[int] = None,
    ) -> tuple[Optional[DayPerson], tuple[DayPerson, ...]]:
        """Osoba wiersza: pierwsza z numerem, potem pierwsza bez numeru."""

        candidates = self._candidates(
            company_id, opportunity_id, primary_contact_id, contact_id
        )
        with_phone = next((item for item in candidates if _phone(item)), None)
        named = next(
            (item for item in candidates if _usable_name(item.full_name)), None
        )
        chosen = with_phone or named
        without_phone = tuple(
            _person(item)
            for item in self.of_company.get(company_id, [])
            if _reachable(item) and not _phone(item) and _usable_name(item.full_name)
        )[:PEOPLE_WITHOUT_PHONE_LIMIT]
        return (_person(chosen) if chosen else None), without_phone

    def company_people(self, company_id: int) -> tuple[DayPerson, ...]:
        people = [
            item
            for item in self.of_company.get(company_id, [])
            if _reachable(item) and _usable_name(item.full_name)
        ]
        people.sort(key=lambda item: not _phone(item))
        return tuple(_person(item) for item in people[:PREP_CONTACTS])


async def _my_opportunities(
    db: AsyncSession, user_id: int, now: datetime
) -> list[_Opp]:
    touch = last_touch_at(now).label("touch")
    rows = (
        await db.execute(
            select(
                SalesOpportunity,
                SalesPipelineStage.key,
                SalesCompany.name,
                SalesCompany.status,
                touch,
            )
            .join(
                SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id
            )
            .join(SalesCompany, SalesCompany.id == SalesOpportunity.company_id)
            .where(
                SalesOpportunity.owner_user_id == user_id,
                SalesOpportunity.status == "open",
                SalesOpportunity.archived_at.is_(None),
            )
            .order_by(SalesOpportunity.value.desc().nulls_last(), SalesOpportunity.id)
        )
    ).all()
    return [
        _Opp(
            id=opp.id,
            company_id=opp.company_id,
            company_name=name,
            company_status=status,
            title=opp.title,
            value=opp.value,
            currency=opp.currency,
            stage_key=key,
            primary_contact_id=opp.primary_contact_id,
            touched_at=touched,
            row=opp,
        )
        for opp, key, name, status, touched in rows
    ]


async def _open_counts(db: AsyncSession, company_ids: set[int]) -> dict[int, int]:
    if not company_ids:
        return {}
    rows = await db.execute(
        select(SalesOpportunity.company_id, func.count())
        .where(
            SalesOpportunity.company_id.in_(company_ids),
            SalesOpportunity.status == "open",
            SalesOpportunity.archived_at.is_(None),
        )
        .group_by(SalesOpportunity.company_id)
    )
    return {company_id: count for company_id, count in rows.all()}


def _meeting_identity(activity: SalesActivity) -> tuple[str, str]:
    if activity.external_id:
        return (activity.external_source or "", activity.external_id)
    return ("id", str(activity.id))


def _meetings_between(
    start_utc: datetime, end_utc: datetime, user_id: Optional[int]
) -> list[Any]:
    """Spotkania osoby z kalendarza (także termin z „Umów spotkanie”, którego autorem
    jest prowadzący); ``None``: spotkania każdej osoby ze Sprzedaży.

    Spotkanie przy szansie osoby też jest jej (lista dzwoniących 13.11.2026: termin
    wpisany przez dzwoniącego albo zsynchronizowany z cudzej skrzynki ma autora
    innego niż opiekun, a „Mój dzień” opiekuna go nie pokazywał).
    """

    return [
        SalesActivity.kind == "meeting",
        or_(
            SalesActivity.created_by_user_id == user_id,
            SalesActivity.opportunity_id.in_(
                select(SalesOpportunity.id).where(
                    SalesOpportunity.owner_user_id == user_id
                )
            ),
        )
        if user_id is not None
        else SalesActivity.created_by_user_id.is_not(None),
        SalesActivity.occurred_at >= start_utc,
        SalesActivity.occurred_at <= end_utc,
        *not_cancelled(),
    ]


async def meeting_company_ids(
    db: AsyncSession, start_utc: datetime, end_utc: datetime
) -> list[int]:
    """Firmy ze spotkaniami w przedziale, po kolei; bez automatów (teczka bota)."""

    rows = (
        await db.execute(
            select(SalesActivity.company_id, SalesActivity.subject)
            .join(SalesCompany, SalesCompany.id == SalesActivity.company_id)
            .where(
                *_meetings_between(start_utc, end_utc, None),
                SalesCompany.archived_at.is_(None),
            )
            .order_by(SalesActivity.occurred_at, SalesActivity.id)
        )
    ).all()
    chosen: list[int] = []
    for company_id, subject in rows:
        if not is_auto_subject(subject) and company_id not in chosen:
            chosen.append(company_id)
    return chosen


async def _meeting_rows(
    db: AsyncSession, user_id: int, now: datetime
) -> tuple[list[DayRow], dict[int, SalesActivity]]:
    day = local_day_bounds(now)
    rows = (
        await db.execute(
            select(SalesActivity, SalesCompany.name, SalesOpportunity.title)
            .join(SalesCompany, SalesCompany.id == SalesActivity.company_id)
            .outerjoin(
                SalesOpportunity, SalesOpportunity.id == SalesActivity.opportunity_id
            )
            .where(*_meetings_between(day.start_utc, day.end_utc, user_id))
            .order_by(SalesActivity.occurred_at, SalesActivity.id)
        )
    ).all()
    wanted = [row for row in rows if not is_auto_subject(row[0].subject)]
    open_by_company = await _open_counts(db, {row[0].company_id for row in wanted})

    # Ta sama minuta i wydarzenie przy kilku firmach: zostaje karta z decyzją do podjęcia.
    def preference(item: Any) -> tuple[bool, bool, int]:
        activity = item[0]
        return (
            activity.opportunity_id is None,
            open_by_company.get(activity.company_id, 0) == 0,
            activity.company_id,
        )

    chosen: dict[tuple[str, str], Any] = {}
    for item in wanted:
        identity = _meeting_identity(item[0])
        if identity not in chosen or preference(item) < preference(chosen[identity]):
            chosen[identity] = item

    pinned_ids = [
        item[0].id for item in chosen.values() if item[0].opportunity_id is not None
    ]
    pinned_by_automat = (
        set(
            (
                await db.scalars(
                    select(SalesActivity.id).where(
                        SalesActivity.id.in_(pinned_ids),
                        auto_pinned(SalesActivity.id),
                    )
                )
            ).all()
        )
        if pinned_ids
        else set()
    )

    result: list[DayRow] = []
    activities: dict[int, SalesActivity] = {}
    for activity, company_name, opportunity_title in sorted(
        chosen.values(), key=lambda item: (item[0].occurred_at, item[0].id)
    ):
        activities[activity.id] = activity
        result.append(
            DayRow(
                key=f"meeting-{activity.id}",
                section="meetings",
                company_id=activity.company_id,
                company_name=company_name,
                subject=activity.subject,
                at=activity.occurred_at,
                activity_id=activity.id,
                opportunity=(
                    DayRef(activity.opportunity_id, opportunity_title)
                    if activity.opportunity_id is not None
                    else None
                ),
                open_opportunities=open_by_company.get(activity.company_id, 0),
                duration_minutes=activity.duration_minutes,
                auto_pinned=activity.id in pinned_by_automat,
                can_create_opportunity=(
                    activity.opportunity_id is None
                    and open_by_company.get(activity.company_id, 0) == 0
                    and is_outlook(activity)
                ),
            )
        )
    return result, activities


def _closing_moment(day_start: datetime) -> Any:
    """Kiedy aktywność zamknęła wątek; NULL, gdy to nie reakcja na maila."""

    activity = SalesActivity
    happened = func.coalesce(activity.occurred_at, activity.created_at)
    return case(
        (and_(activity.kind == "email", activity.direction == "out"), happened),
        (
            and_(
                activity.kind == "call",
                or_(
                    activity.done_at.is_not(None),
                    and_(activity.occurred_at.is_not(None), activity.due_at.is_(None)),
                ),
            ),
            happened,
        ),
        (and_(activity.kind == "meeting", *not_cancelled()), happened),
        (
            and_(
                activity.kind.in_(schema.TASK_KINDS),
                activity.done_at.is_(None),
                activity.due_at >= day_start,
            ),
            activity.created_at,
        ),
    )


async def _sibling_companies(
    db: AsyncSession, mails: Sequence[Any]
) -> dict[int, set[int]]:
    """Druga karta tej samej firmy: ten sam mail i to samo pierwsze słowo nazwy."""

    external_ids = {mail.external_id for mail in mails if mail.external_id}
    if not external_ids:
        return {}
    rows = (
        await db.execute(
            select(
                SalesActivity.external_id,
                SalesActivity.company_id,
                SalesCompany.normalized_name,
            )
            .join(SalesCompany, SalesCompany.id == SalesActivity.company_id)
            .where(
                SalesActivity.external_source == OUTLOOK_MAIL_SOURCE,
                SalesActivity.external_id.in_(external_ids),
            )
        )
    ).all()
    copies: dict[str, list[tuple[int, Optional[str]]]] = {}
    names: dict[int, Optional[str]] = {}
    for external_id, company_id, name in rows:
        copies.setdefault(external_id, []).append((company_id, name))
        names[company_id] = name
    siblings: dict[int, set[int]] = {}
    for mail in mails:
        own = _first_word(names.get(mail.company_id))
        siblings[mail.company_id] = {
            company_id
            for company_id, name in copies.get(mail.external_id or "", [])
            if own and _first_word(name) == own
        } | {mail.company_id}
    return siblings


async def _reply_rows(
    db: AsyncSession, opportunities: list[_Opp], today: date, day_start: datetime
) -> list[DayRow]:
    biggest: dict[int, _Opp] = {}
    for opp in opportunities:
        biggest.setdefault(opp.company_id, opp)
    if not biggest:
        return []
    happened = func.coalesce(SalesActivity.occurred_at, SalesActivity.created_at)
    inbound = (
        await db.execute(
            select(
                SalesActivity.id,
                SalesActivity.company_id,
                SalesActivity.external_id,
                SalesActivity.subject,
                SalesActivity.web_link,
                SalesActivity.contact_id,
                happened.label("at"),
            )
            .where(
                SalesActivity.kind == "email",
                SalesActivity.external_source == OUTLOOK_MAIL_SOURCE,
                SalesActivity.direction == "in",
                SalesActivity.company_id.in_(biggest),
                happened >= day_start - timedelta(days=REPLY_WINDOW_DAYS),
            )
            .order_by(SalesActivity.external_id, SalesActivity.company_id)
        )
    ).all()
    one_copy: dict[Any, Any] = {}
    for mail in inbound:
        if not is_auto_subject(mail.subject):
            one_copy.setdefault(mail.external_id or f"id:{mail.id}", mail)
    last_mail: dict[int, Any] = {}
    for mail in one_copy.values():
        known = last_mail.get(mail.company_id)
        if known is None or (mail.at, mail.id) > (known.at, known.id):
            last_mail[mail.company_id] = mail
    waiting = [
        mail
        for mail in last_mail.values()
        if business_days_after(business_date(mail.at), today)
        >= REPLY_AFTER_BUSINESS_DAYS
    ]
    if not waiting:
        return []
    siblings = await _sibling_companies(db, waiting)
    scope = set().union(*siblings.values()) if siblings else set(last_mail)
    scope |= {mail.company_id for mail in waiting}
    closing = _closing_moment(day_start).label("closing")
    closed_at = dict(
        (
            await db.execute(
                select(SalesActivity.company_id, func.max(closing))
                .where(SalesActivity.company_id.in_(scope), closing.is_not(None))
                .group_by(SalesActivity.company_id)
            )
        ).all()
    )
    rows: list[DayRow] = []
    for mail in waiting:
        companies = siblings.get(mail.company_id, {mail.company_id})
        moments = [closed_at[c] for c in companies if c in closed_at]
        if moments and max(moments) > mail.at:
            continue
        opp = biggest[mail.company_id]
        rows.append(
            DayRow(
                key=f"reply-{mail.id}",
                section="reply",
                company_id=mail.company_id,
                company_name=opp.company_name,
                subject=mail.subject,
                at=mail.at,
                days=(today - business_date(mail.at)).days,
                amount=opp.value,
                currency=opp.currency,
                opportunity=DayRef(opp.id, opp.title),
                activity_id=mail.id,
                web_link=mail.web_link,
                do_not_contact=opp.company_status == COMPANY_DO_NOT_CONTACT,
            )
        )
    rows.sort(key=_amount_order)
    return rows


async def _overdue_rows(
    db: AsyncSession, user_id: int, today: date, day_start: datetime
) -> tuple[list[DayRow], int]:
    threshold = day_start - timedelta(days=OVERDUE_WINDOW_DAYS)
    open_or_none = or_(
        SalesActivity.opportunity_id.is_(None),
        and_(SalesOpportunity.status == "open", SalesOpportunity.archived_at.is_(None)),
    )
    base = (
        select(
            SalesActivity,
            SalesCompany.name,
            SalesCompany.status,
            SalesOpportunity.title,
            SalesOpportunity.value,
            SalesOpportunity.currency,
            SalesOpportunity.primary_contact_id,
        )
        .join(SalesCompany, SalesCompany.id == SalesActivity.company_id)
        .outerjoin(
            SalesOpportunity, SalesOpportunity.id == SalesActivity.opportunity_id
        )
        .where(
            SalesActivity.kind.in_(schema.TASK_KINDS),
            SalesActivity.done_at.is_(None),
            SalesActivity.assignee_user_id == user_id,
            SalesActivity.due_at < day_start,
            open_or_none,
        )
    )
    older = await db.scalar(
        select(func.count()).select_from(
            base.where(SalesActivity.due_at < threshold).subquery()
        )
    )
    rows = (await db.execute(base.where(SalesActivity.due_at >= threshold))).all()
    result = [
        DayRow(
            key=f"overdue-{activity.id}",
            section="overdue",
            company_id=activity.company_id,
            company_name=name,
            subject=activity.subject or (activity.body or "")[:SUBJECT_PREVIEW] or None,
            at=activity.due_at,
            days=(today - business_date(activity.due_at)).days,
            amount=value,
            currency=currency or "PLN",
            opportunity=(
                DayRef(activity.opportunity_id, title)
                if activity.opportunity_id is not None
                else None
            ),
            activity_id=activity.id,
            kind=activity.kind,
            do_not_contact=status == COMPANY_DO_NOT_CONTACT,
        )
        for activity, name, status, title, value, currency, _ in rows
    ]
    result.sort(key=_amount_order)
    return result, int(older or 0)


async def _offer_rows(
    db: AsyncSession,
    opportunities: list[_Opp],
    now: datetime,
    today: date,
    day_start: datetime,
) -> list[DayRow]:
    idle_before = day_start - timedelta(days=OFFER_IDLE_DAYS)
    idle = [
        opp
        for opp in opportunities
        if opp.stage_key == OFFER_STAGE_KEY and opp.touched_at < idle_before
    ]
    signals = await next_step.load_signals(db, [opp.row for opp in idle], now=now)
    rows = [
        DayRow(
            key=f"offer-{opp.id}",
            section="offers",
            company_id=opp.company_id,
            company_name=opp.company_name,
            subject=opp.title,
            at=opp.touched_at,
            days=(today - business_date(opp.touched_at)).days,
            amount=opp.value,
            currency=opp.currency,
            opportunity=DayRef(opp.id, opp.title),
            do_not_contact=opp.company_status == COMPANY_DO_NOT_CONTACT,
        )
        for opp in idle
        if signals[opp.id].next_step is None
    ]
    rows.sort(key=_amount_order)
    return rows


def _with_person(
    row: DayRow,
    book: _Contacts,
    primary_ids: dict[int, Optional[int]],
    activity_contacts: dict[int, Optional[int]],
) -> DayRow:
    if row.do_not_contact:
        return row
    opportunity_id = row.opportunity.id if row.opportunity else None
    person, without_phone = book.pick(
        row.company_id,
        opportunity_id=opportunity_id,
        primary_contact_id=primary_ids.get(opportunity_id or -1),
        contact_id=activity_contacts.get(row.activity_id or -1),
    )
    return replace(row, person=person, people_without_phone=without_phone)


async def _prep(
    db: AsyncSession,
    meetings: list[DayRow],
    activities: dict[int, SalesActivity],
    book: _Contacts,
    now: datetime,
    today: date,
) -> Optional[MeetingPrep]:
    if not meetings:
        return None
    upcoming = [
        row
        for row in meetings
        if row.at + timedelta(minutes=row.duration_minutes or 0) >= now
    ]
    row = upcoming[0] if upcoming else meetings[-1]
    activity = activities[row.activity_id or -1]
    touched = touched_at()
    entries = (
        await db.execute(
            select(
                SalesActivity.id,
                SalesActivity.kind,
                SalesActivity.direction,
                SalesActivity.external_id,
                touched.label("at"),
                func.coalesce(
                    SalesActivity.subject,
                    func.left(SalesActivity.body, SUBJECT_PREVIEW),
                ).label("subject"),
            )
            .where(
                SalesActivity.company_id == row.company_id,
                SalesActivity.kind != "task",
                touched < now,
                next_step.not_system_entry(),
            )
            .order_by(touched.desc(), SalesActivity.id.desc())
            .limit(PREP_HISTORY_FETCH)
        )
    ).all()
    history: list[PrepHistoryItem] = []
    seen: set[str] = set()
    for entry in entries:
        identity = entry.external_id or f"id:{entry.id}"
        if entry.id == activity.id or identity in seen:
            continue
        seen.add(identity)
        history.append(
            PrepHistoryItem(
                kind=entry.kind,
                direction=entry.direction,
                at=entry.at,
                subject=entry.subject,
                days=(today - business_date(entry.at)).days,
            )
        )
    return MeetingPrep(
        activity_id=activity.id,
        company_id=row.company_id,
        company_name=row.company_name,
        subject=row.subject,
        at=row.at,
        duration_minutes=row.duration_minutes,
        open_opportunities=row.open_opportunities,
        can_create_opportunity=(
            row.open_opportunities == 0
            and activity.opportunity_id is None
            and is_outlook(activity)
        ),
        history=tuple(history[:PREP_HISTORY]),
        contacts=book.company_people(row.company_id),
    )


async def load_my_day(db: AsyncSession, user_id: int, *, now: datetime) -> MyDay:
    """Kolejka jednej osoby na ``now``; dzień i progi w kalendarzu firmy."""

    today = business_date(now)
    day_start = local_day_bounds(now).start_utc
    opportunities = await _my_opportunities(db, user_id, now)
    meetings, meeting_activities = await _meeting_rows(db, user_id, now)
    reply = await _reply_rows(db, opportunities, today, day_start)
    overdue, older_tasks = await _overdue_rows(db, user_id, today, day_start)
    offers = await _offer_rows(db, opportunities, now, today, day_start)

    primary_ids = {opp.id: opp.primary_contact_id for opp in opportunities}
    activity_ids = [
        row.activity_id for row in (*reply, *overdue) if row.activity_id is not None
    ]
    activity_contacts: dict[int, Optional[int]] = {}
    if activity_ids:
        activity_contacts = dict(
            (
                await db.execute(
                    select(SalesActivity.id, SalesActivity.contact_id).where(
                        SalesActivity.id.in_(activity_ids)
                    )
                )
            ).all()
        )
    rows = [*meetings, *reply, *overdue, *offers]
    book = await _Contacts.load(
        db,
        {row.company_id for row in rows},
        {row.opportunity.id for row in rows if row.opportunity},
    )
    return MyDay(
        today=today,
        meetings=[
            _with_person(row, book, primary_ids, activity_contacts) for row in meetings
        ],
        reply=[
            _with_person(row, book, primary_ids, activity_contacts) for row in reply
        ],
        overdue=[
            _with_person(row, book, primary_ids, activity_contacts) for row in overdue
        ],
        offers=[
            _with_person(row, book, primary_ids, activity_contacts) for row in offers
        ],
        older_tasks=older_tasks,
        prep=await _prep(db, meetings, meeting_activities, book, now, today),
    )
