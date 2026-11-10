"""Przekazanie spotkania: dzwoniący umawia, prowadzący prowadzi i daje werdykt.

Decyzje Artura z 10.11.2026 (pakiet „Przekazanie i werdykt”):

* **Szansa powstaje z umówionego spotkania.** „Umów spotkanie” zakłada ją w lejku
  Sprzedaż na etapie „Spotkanie kwalifikujące” z opiekunem = prowadzący. Osoba,
  która umówiła, zostaje autorem szansy (``created_by_user_id``).
* **Moduł podpowiada, nie blokuje.** Bez terminu, osoby i odpowiedzi zapis też
  przechodzi; potrzebna jest tylko firma i prowadzący.
* **Werdykt po spotkaniu** jednym kliknięciem: kwalifikuje się, nie teraz, nie nasz
  klient, nie odbyło się. Daje go opiekun szansy albo administrator.
* **Bez kontroli pracy.** Liczby tygodniowe widzi tylko osoba, której dotyczą.

Stan przekazania leży w ``custom_fields["handoff"]`` szansy, bez nowej tabeli:
jedna szansa ma jedno przekazanie, a import z Atlasa nie rusza ``custom_fields``
wiersza zmienionego w NEXUSIE. Zapis trzyma blokadę wiersza szansy, bo to odczyt
JSON-a, zmiana i nadpisanie. Każdy krok zostawia wiersz w historii szansy
(``field = 'handoff'`` albo ``'handoff_verdict'``), z samym rodzajem kroku w wartości;
z tych wierszy liczą się tygodnie osoby, która umawia.

Termin jest też zwykłą aktywnością ``meeting`` przy szansie, żeby szansa miała krok
(``next_step.py``), a odbyte spotkanie było dotykiem (``touch.py``). Gdy to samo
spotkanie przyjdzie z kalendarza, zastępuje ten wpis (``meeting_autopin.py``),
a termin czytamy odtąd z kalendarza.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityContact,
    SalesPipeline,
    SalesPipelineStage,
)
from app.models.user import User
from app.services import sales_schema as schema
from app.services.company_names import normalize_company_name
from app.services.sales import client_gate, history
from app.services.sales import companies as company_service
from app.services.sales.contacts import (
    ensure_new_person_not_objected,
    set_primary_company,
)
from app.services.sales.handoff_hosts import ensure_host
from app.services.sales.handoff_state import (
    DEFAULT_DURATION,
    HELD_VERDICTS,
    VerdictKind,
    block,
    clean,
    moment,
    morning,
    next_business_day,
    store,
    to_utc,
    user_id_of,
)
from app.services.sales.lifecycle import apply_stage
from app.services.sales.meeting_decisions import is_outlook
from app.services.sales.outlook_activities import raise_last_activity
from app.services.sales_schema import OpportunityEventKind

#: ``sales_opportunities.source`` i ``sales_companies.source`` z formularza.
HANDOFF_SOURCE = "handoff"
HISTORY_FIELD = "handoff"
VERDICT_FIELD = "handoff_verdict"
MEETING_STAGE_KEY = "qualifying-meeting"
QUALIFIED_STAGE_KEY = "qualified"
NOT_A_FIT_STAGE_KEY = "not-qualified"
#: „Nie teraz” bez daty wraca po tylu dniach.
NOT_NOW_DEFAULT_DAYS = 30
#: Spotkanie z kalendarza w tym oknie od terminu przekazania to to samo spotkanie.
ADOPT_WINDOW = timedelta(minutes=15)

NOT_FOUND_DETAIL = "Nie ma takiej szansy."
NO_HANDOFF_DETAIL = "Ta szansa nie ma przekazanego spotkania."
CLOSED_DETAIL = "Ta szansa jest już zamknięta."
VERDICT_GIVEN_DETAIL = "To spotkanie ma już werdykt."
FOREIGN_DETAIL = (
    "To nie Twoja szansa. Spotkanie przekazuje jej opiekun albo administrator."
)
VERDICT_OWNER_DETAIL = (
    "Werdykt daje osoba prowadząca spotkanie (opiekun szansy) albo administrator."
)
TERM_OWNER_DETAIL = (
    "Termin zmienia osoba, która umówiła spotkanie, prowadzący albo administrator."
)
HOST_CHANGE_DETAIL = "Prowadzącego zmienia opiekun szansy albo administrator."
COMPANY_MISSING_DETAIL = "Wybierz firmę z kartoteki sprzedaży albo wpisz nową."
PIPELINE_DETAIL = "Spotkanie przekazujemy tylko w lejku Sprzedaż."
OTHER_COMPANY_DETAIL = "Ta osoba nie należy do tej firmy."
NO_TERM_DETAIL = "Najpierw ustaw termin spotkania."
CALENDAR_TERM_DETAIL = (
    "Ten termin pochodzi z kalendarza. Zmień go w Outlooku, a NEXUS pokaże nowy "
    "po synchronizacji."
)
DUPLICATE_DETAIL = "Karta o tej nazwie już jest w kartotece sprzedaży."


class NewCompany(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=500)
    website_url: Optional[str] = Field(default=None, max_length=500)
    domain: Optional[str] = Field(default=None, max_length=255)
    #: Zapisz mimo karty o tej samej nazwie (dwie spółki o tej samej nazwie istnieją).
    allow_duplicate: bool = False

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Podaj nazwę firmy.")
        return value

    @field_validator("website_url")
    @classmethod
    def _http_only(cls, value: Optional[str]) -> Optional[str]:
        return company_service.http_url(value)


class NewContact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=255)
    title: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=60)

    @field_validator("full_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Podaj imię i nazwisko.")
        return value

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: Optional[str]) -> Optional[str]:
        value = (value or "").strip()
        if not value:
            return None
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Adres e-mail wygląda na niepełny.")
        return value.lower()


class BookRequest(BaseModel):
    """Formularz „Umów spotkanie”: firma i prowadzący wystarczą, reszta to podpowiedź."""

    model_config = ConfigDict(extra="forbid")

    company_id: Optional[int] = None
    new_company: Optional[NewCompany] = None
    #: Istniejąca szansa: przekazanie jej prowadzącemu albo ponowne umówienie.
    opportunity_id: Optional[int] = None
    #: Domena dla karty, która jej nie ma (z maila osoby albo ze strony www).
    company_domain: Optional[str] = Field(default=None, max_length=255)
    contact_id: Optional[int] = None
    new_contact: Optional[NewContact] = None
    host_user_id: int
    meeting_at: Optional[datetime] = None
    duration_minutes: int = Field(default=DEFAULT_DURATION, ge=15, le=240)
    service: Optional[str] = Field(default=None, max_length=120)
    problem: Optional[str] = Field(default=None, max_length=1000)
    decision_maker: Optional[str] = Field(default=None, max_length=1000)
    timing: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _one_company_one_person(self) -> "BookRequest":
        sources = (self.company_id, self.new_company, self.opportunity_id)
        if sum(source is not None for source in sources) != 1:
            raise ValueError("Wskaż firmę z kartoteki, nową firmę albo szansę.")
        if self.contact_id is not None and self.new_contact is not None:
            raise ValueError("Wskaż jedną osobę.")
        return self


class TermRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_at: Optional[datetime] = None
    duration_minutes: int = Field(default=DEFAULT_DURATION, ge=15, le=240)


class VerdictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: VerdictKind
    #: Powód zamknięcia („Nie nasz klient”) albo dopisek do „Nie teraz”.
    reason: Optional[str] = Field(default=None, max_length=500)
    #: „Nie teraz”: kiedy wrócić; bez daty za ``NOT_NOW_DEFAULT_DAYS`` dni.
    return_on: Optional[date] = None


@dataclass(frozen=True)
class Booked:
    opportunity: SalesOpportunity
    company: SalesCompany
    created: bool


# ── Zapis: umówienie spotkania ────────────────────────────────────────────


async def lock(db: AsyncSession, opportunity_id: int) -> SalesOpportunity:
    opportunity = await db.scalar(
        select(SalesOpportunity)
        .where(SalesOpportunity.id == opportunity_id)
        .with_for_update()
    )
    if opportunity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return opportunity


def _ensure_open(opportunity: SalesOpportunity) -> None:
    if opportunity.status != "open" or opportunity.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=CLOSED_DETAIL)


def _pending(opportunity: SalesOpportunity) -> dict[str, Any]:
    """Blok przekazania, które czeka na spotkanie albo werdykt."""

    data = block(opportunity)
    if data is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NO_HANDOFF_DETAIL)
    _ensure_open(opportunity)
    if data.get("verdict"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=VERDICT_GIVEN_DETAIL)
    return data


def ensure_can_give_verdict(
    opportunity: SalesOpportunity, user_id: int, *, admin: bool
) -> None:
    if admin or opportunity.owner_user_id in (None, user_id):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail=VERDICT_OWNER_DETAIL)


def ensure_can_set_term(
    opportunity: SalesOpportunity, user_id: int, *, admin: bool
) -> None:
    booker = user_id_of((block(opportunity) or {}).get("booked_by"))
    if admin or user_id in (opportunity.owner_user_id, booker):
        return
    if opportunity.owner_user_id is None:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail=TERM_OWNER_DETAIL)


async def _sales_stages(
    db: AsyncSession, pipeline_id: Optional[int] = None
) -> list[SalesPipelineStage]:
    query = select(SalesPipelineStage).order_by(
        SalesPipelineStage.position, SalesPipelineStage.id
    )
    if pipeline_id is not None:
        query = query.where(SalesPipelineStage.pipeline_id == pipeline_id)
    else:
        query = query.join(
            SalesPipeline, SalesPipeline.id == SalesPipelineStage.pipeline_id
        ).where(SalesPipeline.key == schema.DEFAULT_PIPELINE_KEY)
    return list((await db.execute(query)).scalars())


def _stage(stages: list[SalesPipelineStage], key: str) -> SalesPipelineStage:
    stage = next((item for item in stages if item.key == key), None)
    if stage is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=PIPELINE_DETAIL)
    return stage


async def _refuse_client(
    db: AsyncSession, company: Optional[SalesCompany], new: Optional[NewCompany]
) -> None:
    """Klient NEXUSA nie dostaje szansy: temat idzie do jego Delivery Leada."""

    key = (
        company.normalized_name
        if company is not None
        else normalize_company_name(new.name if new is not None else "")
    )
    if key == client_gate.OWN_COMPANY_KEY:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=client_gate.OWN_COMPANY_REFUSAL
        )
    identity = client_gate.CompanyIdentity(
        company_id=company.id if company is not None else 0,
        client_id=company.client_id if company is not None else None,
        normalized_name=key,
    )
    matches = await client_gate.match_companies(db, [identity])
    if identity.company_id in matches:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=matches[identity.company_id].refusal
        )


async def _new_company(
    db: AsyncSession, new: NewCompany, contact: Optional[NewContact], user_id: int
) -> SalesCompany:
    if not new.allow_duplicate:
        found = await company_service.find_duplicates(db, name=new.name, nip=None)
        if found:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "sales_company_duplicate",
                    "message": DUPLICATE_DETAIL,
                    "duplicates": [
                        {"id": item.id, "name": item.name, "nip": item.nip}
                        for item in found
                    ],
                },
            )
    company = SalesCompany(
        name=new.name,
        normalized_name=normalize_company_name(new.name) or new.name.lower(),
        website_url=new.website_url,
        domain=(
            company_service.mail_domain(new.domain)
            or company_service.mail_domain(new.website_url)
            or company_service.mail_domain(contact.email if contact else None)
        ),
        source=HANDOFF_SOURCE,
        owner_user_id=user_id,
        created_by_user_id=user_id,
    )
    db.add(company)
    await db.flush()
    return company


def _in_company(company_id: int):
    linked = select(SalesCompanyContact.contact_id).where(
        SalesCompanyContact.company_id == company_id
    )
    return or_(SalesContact.company_id == company_id, SalesContact.id.in_(linked))


async def _contact(
    db: AsyncSession, company: SalesCompany, payload: BookRequest, user_id: int
) -> Optional[SalesContact]:
    """Osoba ze spotkania jako kontakt firmy: wskazana, rozpoznana albo nowa."""

    if payload.contact_id is not None:
        contact = await db.scalar(
            select(SalesContact).where(
                SalesContact.id == payload.contact_id,
                SalesContact.archived_at.is_(None),
                _in_company(company.id),
            )
        )
        if contact is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail=OTHER_COMPANY_DETAIL
            )
        return contact
    new = payload.new_contact
    if new is None:
        return None
    await ensure_new_person_not_objected(
        db, new.full_name, {"company_id": company.id, "phone": new.phone}
    )
    same_person = [func.lower(SalesContact.full_name) == new.full_name.lower()]
    if new.email:
        same_person.append(func.lower(func.btrim(SalesContact.email)) == new.email)
    known = await db.scalar(
        select(SalesContact)
        .where(
            SalesContact.archived_at.is_(None),
            _in_company(company.id),
            or_(*same_person),
        )
        .order_by(SalesContact.id)
        .limit(1)
    )
    if known is not None:
        # Ta sama osoba już jest w firmie: dopisujemy tylko to, czego brakuje.
        known.title = known.title or clean(new.title)
        known.email = known.email or new.email
        if not (known.phone or known.mobile_phone) and known.do_not_contact_at is None:
            known.mobile_phone = clean(new.phone)
        return known
    contact = SalesContact(
        full_name=new.full_name,
        title=clean(new.title),
        email=new.email,
        mobile_phone=clean(new.phone),
        company_id=company.id,
        source="manual",
        created_by_user_id=user_id,
    )
    db.add(contact)
    await db.flush()
    await set_primary_company(db, contact, company.id)
    return contact


async def _meeting_activity(
    db: AsyncSession, opportunity: SalesOpportunity, data: dict[str, Any]
) -> Optional[SalesActivity]:
    activity_id = user_id_of(data.get("meeting_activity_id"))
    if activity_id is None:
        return None
    activity = await db.get(SalesActivity, activity_id)
    if (
        activity is None
        or activity.kind != "meeting"
        or activity.opportunity_id != opportunity.id
    ):
        # Wpis usunięto albo odpięto: przekazanie zostaje, termin jest w bloku.
        return None
    return activity


async def _sync_meeting(
    db: AsyncSession, opportunity: SalesOpportunity, data: dict[str, Any], now: datetime
) -> None:
    """Termin z bloku jako aktywność przy szansie; spotkania z Outlooka nie ruszamy."""

    activity = await _meeting_activity(db, opportunity, data)
    if activity is not None and is_outlook(activity):
        return
    meeting_at = moment(data.get("meeting_at"))
    if meeting_at is None:
        if activity is not None:
            await db.delete(activity)
        data["meeting_activity_id"] = None
        return
    if activity is None:
        activity = SalesActivity(
            kind="meeting",
            company_id=opportunity.company_id,
            opportunity_id=opportunity.id,
        )
        db.add(activity)
    company_name = await db.scalar(
        select(SalesCompany.name).where(SalesCompany.id == opportunity.company_id)
    )
    activity.subject = f"Spotkanie kwalifikujące: {company_name or ''}"[:500]
    activity.contact_id = opportunity.primary_contact_id
    activity.occurred_at = meeting_at
    activity.duration_minutes = int(data.get("duration_minutes") or DEFAULT_DURATION)
    activity.done_at = meeting_at if meeting_at <= now else None
    # Autor spotkania to osoba, której to spotkanie jest, jak przy synchronizacji
    # kalendarza: po nim „Mój dzień” i KPI wiedzą, czyje ono jest.
    activity.created_by_user_id = opportunity.owner_user_id
    await db.flush()
    data["meeting_activity_id"] = activity.id


def _title(service: Optional[str]) -> str:
    text = clean(service)
    return (f"{text}: spotkanie kwalifikujące" if text else "Spotkanie kwalifikujące")[
        :255
    ]


async def book(
    db: AsyncSession,
    payload: BookRequest,
    *,
    user_id: int,
    admin: bool,
    now: datetime,
) -> Booked:
    """Zapisz umówione spotkanie; wywołujący robi commit."""

    host = await ensure_host(db, payload.host_user_id)
    opportunity: Optional[SalesOpportunity] = None
    company: Optional[SalesCompany] = None
    if payload.opportunity_id is not None:
        opportunity = await lock(db, payload.opportunity_id)
        _ensure_open(opportunity)
        booker = user_id_of((block(opportunity) or {}).get("booked_by"))
        owns = admin or opportunity.owner_user_id in (None, user_id)
        if not owns and user_id != booker:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=FOREIGN_DETAIL)
        if not owns and host.id != opportunity.owner_user_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=HOST_CHANGE_DETAIL)
        company = await db.get(SalesCompany, opportunity.company_id)
    elif payload.company_id is not None:
        company = await db.get(SalesCompany, payload.company_id)
        if company is None or company.archived_at is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail=COMPANY_MISSING_DETAIL
            )
    if opportunity is None:
        await _refuse_client(db, company, payload.new_company)

    stages = await _sales_stages(db)
    meeting_stage = _stage(stages, MEETING_STAGE_KEY)
    if opportunity is not None and opportunity.pipeline_id != meeting_stage.pipeline_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=PIPELINE_DETAIL
        )

    if company is None:
        assert payload.new_company is not None  # pilnuje walidator żądania
        company = await _new_company(
            db, payload.new_company, payload.new_contact, user_id
        )
    elif not company.domain:
        company.domain = company_service.mail_domain(payload.company_domain)
    contact = await _contact(db, company, payload, user_id)

    created = opportunity is None
    if opportunity is None:
        opportunity = SalesOpportunity(
            company_id=company.id,
            pipeline_id=meeting_stage.pipeline_id,
            stage_id=meeting_stage.id,
            title=_title(payload.service),
            source=HANDOFF_SOURCE,
            primary_contact_id=contact.id if contact is not None else None,
            owner_user_id=host.id,
            created_by_user_id=user_id,
        )
        apply_stage(opportunity, meeting_stage, stages, now=now)
        db.add(opportunity)
        await db.flush()
        history.record_created(db, opportunity, user_id=user_id)
    else:
        before = history.snapshot(opportunity)
        opportunity.owner_user_id = host.id
        current = next((s for s in stages if s.id == opportunity.stage_id), None)
        if current is not None and current.position < meeting_stage.position:
            # Lead staje się spotkaniem; dalszych etapów nie cofamy.
            apply_stage(opportunity, meeting_stage, stages, now=now)
        if contact is not None and opportunity.primary_contact_id is None:
            opportunity.primary_contact_id = contact.id
        history.record_changes(db, opportunity, before, user_id=user_id)
    if contact is not None and (
        await db.get(SalesOpportunityContact, (opportunity.id, contact.id)) is None
    ):
        db.add(
            SalesOpportunityContact(
                opportunity_id=opportunity.id, contact_id=contact.id
            )
        )

    previous = block(opportunity) or {}
    data: dict[str, Any] = {
        "booked_by": user_id_of(previous.get("booked_by"))
        or (user_id if created else opportunity.created_by_user_id or user_id),
        "booked_at": now.isoformat(),
        "service": clean(payload.service) or previous.get("service"),
        "problem": clean(payload.problem) or previous.get("problem"),
        "decision_maker": clean(payload.decision_maker)
        or previous.get("decision_maker"),
        "timing": clean(payload.timing) or previous.get("timing"),
        "meeting_at": (
            to_utc(payload.meeting_at).isoformat() if payload.meeting_at else None
        ),
        "duration_minutes": payload.duration_minutes,
        "meeting_activity_id": previous.get("meeting_activity_id"),
        "confirmed_at": None,
        "verdict": None,
    }
    await _sync_meeting(db, opportunity, data, now)
    store(opportunity, data)
    history.record(
        db,
        opportunity_id=opportunity.id,
        user_id=user_id,
        kind=OpportunityEventKind.updated,
        field=HISTORY_FIELD,
        new_value="booked",
    )
    return Booked(opportunity=opportunity, company=company, created=created)


# ── Zapis: termin, potwierdzenie, werdykt ─────────────────────────────────


def _record(db: AsyncSession, opportunity_id: int, user_id: int, step: str) -> None:
    history.record(
        db,
        opportunity_id=opportunity_id,
        user_id=user_id,
        kind=OpportunityEventKind.updated,
        field=HISTORY_FIELD,
        new_value=step,
    )


async def set_term(
    db: AsyncSession,
    opportunity: SalesOpportunity,
    payload: TermRequest,
    *,
    user_id: int,
    now: datetime,
) -> None:
    """Ustaw albo zmień termin; potwierdzenie u klienta trzeba wtedy powtórzyć."""

    data = _pending(opportunity)
    activity = await _meeting_activity(db, opportunity, data)
    if activity is not None and is_outlook(activity):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=CALENDAR_TERM_DETAIL)
    data["meeting_at"] = (
        to_utc(payload.meeting_at).isoformat() if payload.meeting_at else None
    )
    data["duration_minutes"] = payload.duration_minutes
    data["confirmed_at"] = None
    await _sync_meeting(db, opportunity, data, now)
    store(opportunity, data)
    _record(db, opportunity.id, user_id, "term")


async def confirm(
    db: AsyncSession, opportunity: SalesOpportunity, *, user_id: int, now: datetime
) -> None:
    """Klient potwierdził termin. Samo kliknięcie niczego do klienta nie wysyła."""

    data = _pending(opportunity)
    if await _effective_term(db, opportunity, data) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NO_TERM_DETAIL)
    data["confirmed_at"] = now.isoformat()
    data["confirmed_by"] = user_id
    store(opportunity, data)
    _record(db, opportunity.id, user_id, "confirmed")


async def _effective_term(
    db: AsyncSession, opportunity: SalesOpportunity, data: dict[str, Any]
) -> Optional[datetime]:
    activity = await _meeting_activity(db, opportunity, data)
    if activity is not None and is_outlook(activity) and activity.occurred_at:
        return activity.occurred_at
    return moment(data.get("meeting_at"))


def _task(
    opportunity: SalesOpportunity,
    *,
    subject: str,
    due_on: date,
    assignee_id: Optional[int],
    author_id: int,
) -> SalesActivity:
    return SalesActivity(
        kind="task",
        subject=subject[:500],
        due_at=morning(due_on),
        company_id=opportunity.company_id,
        opportunity_id=opportunity.id,
        assignee_user_id=assignee_id or author_id,
        created_by_user_id=author_id,
    )


def _move(
    opportunity: SalesOpportunity,
    stages: list[SalesPipelineStage],
    key: str,
    now: datetime,
) -> None:
    """Te same skutki co ``POST /move``: status, daty i kwalifikacja idą za etapem."""

    target = _stage(stages, key)
    current = next((s for s in stages if s.id == opportunity.stage_id), None)
    forward_only = target.outcome == "open"
    if forward_only and current is not None and current.position >= target.position:
        return
    apply_stage(opportunity, target, stages, now=now)
    if target.outcome != "lost":
        opportunity.lost_reason = None


async def give_verdict(
    db: AsyncSession,
    opportunity: SalesOpportunity,
    payload: VerdictRequest,
    *,
    user_id: int,
    now: datetime,
) -> None:
    """Werdykt po spotkaniu: przesuwa szansę i wraca do osoby, która umówiła."""

    data = _pending(opportunity)
    stages = await _sales_stages(db, opportunity.pipeline_id)
    company_name = (
        await db.scalar(
            select(SalesCompany.name).where(SalesCompany.id == opportunity.company_id)
        )
        or ""
    )
    activity = await _meeting_activity(db, opportunity, data)
    from_calendar = activity is not None and is_outlook(activity)
    before = history.snapshot(opportunity)
    reason = clean(payload.reason)
    return_on: Optional[date] = None

    if payload.kind in HELD_VERDICTS:
        planned = await _effective_term(db, opportunity, data)
        held_at = planned if planned is not None and planned <= now else now
        if not from_calendar:
            # Spotkanie odbyło się, więc zostaje po nim ślad także bez terminu.
            data["meeting_at"] = held_at.isoformat()
            await _sync_meeting(db, opportunity, data, now)
        raise_last_activity(db, opportunity, held_at, user_id=user_id)
    elif activity is not None and not from_calendar:
        # Nie odbyło się: wpis terminu nie może liczyć się jako spotkanie.
        await db.delete(activity)
        data["meeting_activity_id"] = None

    if payload.kind == "qualified":
        _move(opportunity, stages, QUALIFIED_STAGE_KEY, now)
    elif payload.kind == "not_a_fit":
        _move(opportunity, stages, NOT_A_FIT_STAGE_KEY, now)
        opportunity.lost_reason = reason
    elif payload.kind == "not_now":
        return_on = payload.return_on or (
            business_date(now) + timedelta(days=NOT_NOW_DEFAULT_DAYS)
        )
        note = f" ({reason})" if reason else ""
        db.add(
            _task(
                opportunity,
                subject=f"Wrócić do rozmowy po „nie teraz”: {company_name}{note}",
                due_on=return_on,
                assignee_id=opportunity.owner_user_id,
                author_id=user_id,
            )
        )
        if (
            opportunity.keep_open_until is None
            or opportunity.keep_open_until < return_on
        ):
            opportunity.keep_open_until = return_on
    else:
        booker_id = user_id_of(data.get("booked_by"))
        booker = await db.get(User, booker_id) if booker_id is not None else None
        db.add(
            _task(
                opportunity,
                subject=f"Spotkanie się nie odbyło, umów nowy termin: {company_name}",
                due_on=next_business_day(business_date(now)),
                assignee_id=(
                    booker.id
                    if booker is not None and booker.is_active
                    else opportunity.owner_user_id
                ),
                author_id=user_id,
            )
        )

    history.record_changes(db, opportunity, before, user_id=user_id)
    data["verdict"] = {
        "kind": payload.kind,
        "at": now.isoformat(),
        "by": user_id,
        "reason": reason,
        "return_on": return_on.isoformat() if return_on is not None else None,
    }
    store(opportunity, data)
    history.record(
        db,
        opportunity_id=opportunity.id,
        user_id=user_id,
        kind=OpportunityEventKind.updated,
        field=VERDICT_FIELD,
        new_value=payload.kind,
    )


async def adopt_calendar_meeting(
    db: AsyncSession, opportunity: SalesOpportunity, activity: SalesActivity
) -> bool:
    """Spotkanie z kalendarza przypięte do szansy staje się terminem przekazania.

    Tylko gdy pasuje do tego, co umówiono: ten sam termin (``ADOPT_WINDOW``) albo
    przekazanie bez terminu i spotkanie po dniu umówienia. Wpis terminu z formularza
    znika, żeby jedno spotkanie nie było dwoma wierszami.
    """

    data = block(opportunity)
    if data is None or data.get("verdict") or activity.occurred_at is None:
        return False
    current = await _meeting_activity(db, opportunity, data)
    if current is not None and (current.id == activity.id or is_outlook(current)):
        return False
    planned = moment(data.get("meeting_at"))
    if planned is not None and abs(planned - activity.occurred_at) > ADOPT_WINDOW:
        return False
    booked_at = moment(data.get("booked_at"))
    if planned is None and booked_at is not None and activity.occurred_at < booked_at:
        return False
    if current is not None:
        await db.delete(current)
    data["meeting_at"] = activity.occurred_at.isoformat()
    data["meeting_activity_id"] = activity.id
    if activity.duration_minutes:
        data["duration_minutes"] = activity.duration_minutes
    store(opportunity, data)
    return True


def planned_term(opportunity: SalesOpportunity) -> Optional[datetime]:
    """Termin z formularza dla przekazania, które czeka na spotkanie."""

    data = block(opportunity)
    if data is None or data.get("verdict"):
        return None
    return moment(data.get("meeting_at"))
