"""Rodzaj ``people``: bot buduje mapy decydentów firm (decyzja Artura 12.11.2026).

NEXUS wysyła botowi tylko nazwę i domenę firmy; bot może ODESŁAĆ osoby. Zasady
z decyzji, wymuszane modelem raportu, a nie samym poleceniem:

* osoba tylko z publicznego źródła, które bot otworzył, z linkiem i datą,
* e-mail i telefon tylko z własnym linkiem źródła, na którym są wydrukowane;
  kontakt bez źródła albo w złym kształcie odpada z ostrzeżeniem przy osobie
  (bot mógł go zgadnąć z wzorca), a osoba zostaje,
* LinkedIn tylko jako link do profilu (http(s), ``linkedin.com``) ze strony,
  którą bot otworzył; danych z LinkedIna bot nie zbiera.

Wynik to jeden wiersz ``sales_bot_results`` na firmę z listą osób. Przegląd
i zapis idą przez maszynę importu listy z researchu (``research_import``):
osoby zamieniają się w te same wiersze, które daje plik, z pochodzeniem
„Grok Bot”, linkiem i datą źródła, więc handlowiec widzi te same stany
(„Już na mapie”, poziom, ostrzeżenia), a przyjęte osoby przechodzą przez
``DecisionPersonCreate`` z punktem zapisu na wiersz.

Osoba trafia do wyników raz na firmę: już na mapie konta albo zaproponowana
w poprzednim wyniku (także odrzuconym) nie wraca, żeby cotygodniowy bieg nie
podsuwał tych samych ludzi po decyzji handlowca.

Reguły: ``docs/claude/sprzedaz/mapy-decydentow-od-bota.md``.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional, Sequence
from urllib.parse import urlsplit

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StrictBool,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.sales import (
    SalesBotResult,
    SalesCallRecord,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
    SalesOpportunity,
    SalesPipeline,
    SalesSignalRun,
)
from app.services.company_names import normalize_company_name
from app.services.sales import client_gate, company_aliases, research_import
from app.services.sales.bot_tasks.base import (
    AcceptRefused,
    BotTask,
    RequiredText,
    SourceUrl,
    TaskContext,
    result_fingerprint,
    save_results,
)
from app.services.sales.decision_map import (
    IT_FACTORIES_PIPELINE_KEY,
    decision_entries,
)
from app.services.sales.calling_file import phone_digits
from app.services.sales.companies import mail_domain
from app.services.sales.factories import COMPANY_DO_NOT_CONTACT
from app.services.sales.research_file import (
    TO_VERIFY,
    ResearchRow,
    level_from_title,
    person_key,
    site_domain,
    valid_email,
    valid_link,
    valid_phone,
)

logger = logging.getLogger(__name__)

KIND = "people"
COGNISM_SOURCE = "cognism"
COGNISM_MAP_KEY = "bot_decision_map"
COGNISM_SUPPRESSIONS_KEY = "bot_decision_map_suppressions"
COGNISM_MAX_FIRMS = 5
COGNISM_MAX_PEOPLE = 5
#: Pochodzenie osoby na mapie i w historii szansy (pole „Skąd lista” importu).
ORIGIN = "Grok Bot"
MAX_PEOPLE = 15
#: Bieg ręczny to jedna firma, tygodniowy najwyżej ``MAX_WEEKLY_FIRMS``.
MAX_REPORT_FIRMS = 25
MAX_WEEKLY_FIRMS = 20
AREAS: tuple[str, ...] = (
    "it",
    "data",
    "ai",
    "engineering",
    "procurement",
    "hr",
    "management",
    "other",
)
#: Wynik zamknięty dla wiersza: osoba dodana, już na mapie albo firma odmawia.
HANDLED = frozenset(
    {
        research_import.ADDED,
        research_import.ON_MAP,
        research_import.CLIENT,
        research_import.BLOCKED,
        research_import.OWN_COMPANY,
    }
)
NOT_PEOPLE_DETAIL = "To nie jest wynik z osobami od bota."
NO_COMPANY_DETAIL = "Firma z tego wyniku nie istnieje albo jest w archiwum."
CHOOSE_DETAIL = "Ta marka ma kilka kart. Przejrzyj wynik i wskaż kartę firmy."

EMAIL_DROPPED = "pominięto e-mail (bez źródła albo niepełny)"
PHONE_DROPPED = "pominięto telefon (bez źródła albo nie wygląda na numer)"
LINKEDIN_DROPPED = "pominięto LinkedIn (tylko link do profilu)"


class PeopleRequest(BaseModel):
    """Źródło wybiera NEXUS. Brak wartości oznacza dotychczasowy research publiczny."""

    model_config = ConfigDict(extra="forbid")

    source: Optional[Literal["cognism"]] = None


# ── Raport ────────────────────────────────────────────────────────────────


def _linkedin(value: Optional[str]) -> Optional[str]:
    url = valid_link(value, 512)
    if url is None:
        return None
    host = url.split("://", 1)[1].split("/", 1)[0].lower()
    return url if host == "linkedin.com" or host.endswith(".linkedin.com") else None


class BotPerson(BaseModel):
    """Osoba z raportu; kontakt bez własnego źródła odpada, osoba zostaje."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: RequiredText = Field(max_length=255)
    title: RequiredText = Field(max_length=255)
    area: Literal[AREAS] = "other"  # type: ignore[valid-type]
    level_hint: Optional[int] = Field(default=None, ge=1, le=3)
    source_url: SourceUrl = Field(max_length=1000)
    published: Optional[date] = None
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=50)
    linkedin_url: Optional[str] = Field(default=None, max_length=1000)
    email_source_url: Optional[str] = Field(default=None, max_length=1000)
    phone_source_url: Optional[str] = Field(default=None, max_length=1000)

    _warnings: list[str] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _contacts_only_with_source(self) -> "BotPerson":
        warnings: list[str] = []
        email_source = valid_link(self.email_source_url, 1000)
        email = valid_email(self.email)
        if self.email and not (email and email_source):
            warnings.append(EMAIL_DROPPED)
        self.email, self.email_source_url = (
            (email, email_source) if email and email_source else (None, None)
        )
        phone_source = valid_link(self.phone_source_url, 1000)
        phone = valid_phone(self.phone)
        if self.phone and not (phone and phone_source):
            warnings.append(PHONE_DROPPED)
        self.phone, self.phone_source_url = (
            (phone, phone_source) if phone and phone_source else (None, None)
        )
        linkedin = _linkedin(self.linkedin_url)
        if self.linkedin_url and not linkedin:
            warnings.append(LINKEDIN_DROPPED)
        self.linkedin_url = linkedin
        self._warnings = warnings
        return self

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)


class FirmPeople(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_ref: int
    people: list[BotPerson] = Field(default_factory=list, max_length=MAX_PEOPLE)


class PeopleReport(BaseModel):
    """Raport ``people``: osoby per firma; firma tylko z listy biegu."""

    model_config = ConfigDict(extra="forbid")

    checked_firms: int = Field(default=0, ge=0, le=MAX_REPORT_FIRMS)
    firms: list[FirmPeople] = Field(default_factory=list, max_length=MAX_REPORT_FIRMS)
    no_people: list[int] = Field(default_factory=list, max_length=MAX_REPORT_FIRMS)


def _task_text(run: SalesSignalRun, ctx: TaskContext) -> str:
    return (
        "Dla każdej firmy z listy firms znajdź osoby decyzyjne w obszarach IT, "
        "dane, AI, inżynieria, zakupy, HR i zarząd, najwyżej "
        f"{MAX_PEOPLE} na firmę. Podawaj tylko osoby wymienione z imienia "
        "i nazwiska na publicznych źródłach, które sam otworzyłeś: strona firmy, "
        "komunikaty prasowe, agendy konferencji, publiczne wywiady, publiczne "
        "rejestry. Przy każdej osobie podaj source_url tej strony i published "
        "(data publikacji). E-mail i telefon podaj tylko wtedy, gdy są wydrukowane "
        "na publicznym źródle, razem z email_source_url albo phone_source_url tej "
        "strony. Nigdy nie zgaduj adresów e-mail z wzorców i nie wymyślaj numerów. "
        "Nie zbieraj danych z LinkedIna; linkedin_url podaj tylko, gdy link do "
        "profilu jest na stronie, którą otworzyłeś. Nigdzie się nie loguj. "
        f"area: jedno z {', '.join(AREAS)}. level_hint: 1 zarząd i VP (Chief, "
        "CTO, prezes, członek zarządu), 2 Head, Director, dyrektor, 3 pozostali. "
        "Firmy, w których nie znalazłeś nikogo, wpisz do no_people."
    )


def _report_format() -> dict[str, Any]:
    return {
        "checked_firms": "<liczba sprawdzonych firm>",
        "firms": [
            {
                "company_ref": "<ref z firms>",
                "people": [
                    {
                        "full_name": "...",
                        "title": "...",
                        "area": "|".join(AREAS),
                        "level_hint": "1|2|3",
                        "source_url": "https://...",
                        "published": "RRRR-MM-DD",
                        "email": "<tylko gdy wydrukowany na źródle>",
                        "email_source_url": "https://...",
                        "phone": "<tylko gdy wydrukowany na źródle>",
                        "phone_source_url": "https://...",
                        "linkedin_url": "<tylko link ze strony, którą otworzyłeś>",
                    }
                ],
            }
        ],
        "no_people": ["<ref firmy bez osób>"],
    }


# ── Zapis wyników ─────────────────────────────────────────────────────────


def person_marks(name: Optional[str], email: Optional[str]) -> set[str]:
    """Znaki osoby do wykrywania powtórzeń: imię i nazwisko oraz e-mail."""

    marks = set()
    key = person_key(name)
    if key:
        marks.add(f"n:{key}")
    if email:
        marks.add(f"e:{email.strip().lower()}")
    return marks


def _payload_person(line: int, person: BotPerson, *, today: date) -> dict[str, Any]:
    published = person.published
    warnings = person.warnings
    if published is not None and published > today + timedelta(days=1):
        # Data z przyszłości to błąd odczytu, nie data źródła.
        published = None
    return {
        "line": line,
        "full_name": person.full_name,
        "title": person.title,
        "area": person.area,
        "level_hint": person.level_hint,
        "source_url": person.source_url,
        "published": published.isoformat() if published else None,
        "email": person.email,
        "email_source_url": person.email_source_url,
        "phone": person.phone,
        "phone_source_url": person.phone_source_url,
        "linkedin_url": person.linkedin_url,
        "warnings": warnings,
    }


def pick_new_people(
    people: Sequence[BotPerson], *, known: set[str], today: date
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Osoby jeszcze nieznane firmie, bez powtórzeń w raporcie, z numerami wierszy."""

    seen = set(known)
    picked: list[dict[str, Any]] = []
    dropped = {"known": 0, "duplicates": 0, "contacts": 0}
    for person in people:
        marks = person_marks(person.full_name, person.email)
        if marks & known:
            dropped["known"] += 1
            continue
        if marks & seen:
            dropped["duplicates"] += 1
            continue
        seen |= marks
        dropped["contacts"] += len(person.warnings)
        picked.append(_payload_person(len(picked) + 1, person, today=today))
    return picked, dropped


async def _known_marks(
    db: AsyncSession, company_ids: Sequence[int]
) -> dict[int, set[str]]:
    """Osoby, które firma już ma: na mapie konta i w poprzednich wynikach bota."""

    known: dict[int, set[str]] = {cid: set() for cid in company_ids}
    if not company_ids:
        return known
    maps = await db.execute(
        select(SalesOpportunity.company_id, SalesOpportunity.custom_fields)
        .join(SalesPipeline, SalesPipeline.id == SalesOpportunity.pipeline_id)
        .where(
            SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY,
            SalesOpportunity.company_id.in_(company_ids),
        )
    )
    for company_id, custom_fields in maps.all():
        for entry in decision_entries(custom_fields):
            email = entry.get("email") if isinstance(entry.get("email"), str) else None
            name = entry.get("name") if isinstance(entry.get("name"), str) else None
            known[company_id] |= person_marks(name, email)
    earlier = await db.execute(
        select(SalesBotResult.company_id, SalesBotResult.payload).where(
            SalesBotResult.kind == KIND,
            SalesBotResult.company_id.in_(company_ids),
        )
    )
    for company_id, payload in earlier.all():
        for person in (payload or {}).get("people") or []:
            known[company_id] |= person_marks(
                person.get("full_name"), person.get("email")
            )
    return known


async def _ingest(
    db: AsyncSession, run: SalesSignalRun, report: PeopleReport, now: datetime
) -> dict[str, Any]:
    allowed = {int(ref) for ref in run.company_ids}
    firms: dict[int, FirmPeople] = {}
    unknown = 0
    for firm in report.firms:
        if firm.company_ref not in allowed:
            unknown += 1
            continue
        # Ta sama firma drugi raz w raporcie: osoby doklejone do pierwszej.
        if firm.company_ref in firms:
            merged = [*firms[firm.company_ref].people, *firm.people][:MAX_PEOPLE]
            firms[firm.company_ref] = FirmPeople.model_construct(
                company_ref=firm.company_ref, people=merged
            )
        else:
            firms[firm.company_ref] = firm
    existing = set(
        (
            await db.execute(
                select(SalesCompany.id).where(
                    SalesCompany.id.in_(list(firms)),
                    SalesCompany.archived_at.is_(None),
                )
            )
        ).scalars()
    )
    known = await _known_marks(db, sorted(existing))
    today = business_today()
    rows: list[dict[str, Any]] = []
    dropped = {"unknown_company": unknown, "known": 0, "duplicates": 0, "contacts": 0}
    people_total = 0
    for company_id in sorted(firms):
        if company_id not in existing:
            dropped["unknown_company"] += 1
            continue
        picked, counts = pick_new_people(
            firms[company_id].people, known=known[company_id], today=today
        )
        for key, value in counts.items():
            dropped[key] += value
        if not picked:
            continue
        people_total += len(picked)
        rows.append(
            {
                "company_id": company_id,
                "payload": {"people": picked, "outcomes": {}},
                "fingerprint": result_fingerprint(
                    KIND,
                    company_id,
                    *sorted(
                        mark
                        for person in picked
                        for mark in person_marks(person["full_name"], person["email"])
                    ),
                ),
            }
        )
    new = await save_results(db, run, rows, now)
    # Logi są publiczne: same liczby.
    logger.info(
        "sales_bot people run=%s firms=%d people=%d results_new=%d",
        run.id,
        len(firms),
        people_total,
        new,
    )
    return {
        "firms": len(firms),
        "people": people_total,
        "results": len(rows),
        "results_new": new,
        "no_people": len(report.no_people),
        "dropped": dropped,
    }


# ── Przegląd i przyjęcie ──────────────────────────────────────────────────


def _people(result: SalesBotResult) -> list[dict[str, Any]]:
    return [p for p in (result.payload or {}).get("people") or [] if p.get("line")]


def decided_lines(result: SalesBotResult) -> dict[int, str]:
    outcomes = (result.payload or {}).get("outcomes") or {}
    return {int(line): str(value) for line, value in outcomes.items()}


def open_count(result: SalesBotResult) -> int:
    done = {line for line, value in decided_lines(result).items() if value in HANDLED}
    return sum(1 for person in _people(result) if int(person["line"]) not in done)


def _level(person: dict[str, Any]) -> int:
    hint = person.get("level_hint")
    return int(hint) if hint in (1, 2, 3) else level_from_title(person.get("title"))


def to_rows(result: SalesBotResult, company: SalesCompany) -> list[ResearchRow]:
    """Osoby z wyniku jako wiersze importu listy z researchu (ten sam przegląd)."""

    return [
        ResearchRow(
            line=int(person["line"]),
            company=company.name,
            name=person["full_name"],
            title=person.get("title"),
            email=person.get("email"),
            phone=person.get("phone"),
            linkedin_url=person.get("linkedin_url"),
            source_url=person.get("source_url"),
            domain=company.domain or None,
            confidence=TO_VERIFY,
            decision_level=_level(person),
            warnings=tuple(person.get("warnings") or ()),
        )
        for person in _people(result)
    ]


def pin(
    company: research_import.CompanyPlan, company_id: int
) -> research_import.CompanyPlan:
    """Cel to karta, o którą pytano bota, gdy reguły importu na to pozwalają.

    Klient NEXUSA i nasza firma zostają odmową. Inna karta tej marki z kontem
    w lejku zostawia wybór człowiekowi, tak jak przy pliku.
    """

    if company.state in (research_import.CLIENT, research_import.OWN_COMPANY):
        return company
    card = next((c for c in company.cards if c.id == company_id), None)
    if card is None:
        return company
    if card.client is not None:
        return dataclasses.replace(
            company, state=research_import.CLIENT, company_id=None, client=card.client
        )
    others = [c for c in company.cards if c.account is not None and c.id != card.id]
    if card.account is None and others:
        return dataclasses.replace(
            company, state=research_import.CHOOSE, company_id=None
        )
    if card.blocked:
        return dataclasses.replace(
            company, state=research_import.BLOCKED, company_id=None
        )
    state = research_import.ACCOUNT if card.account else research_import.CARD
    return dataclasses.replace(company, state=state, company_id=card.id)


async def review_plan(
    db: AsyncSession, result: SalesBotResult
) -> tuple[research_import.Plan, dict[int, Optional[str]]]:
    """Plan przeglądu wyniku i daty źródeł per wiersz."""

    company = await _company(db, result)
    rows = to_rows(result, company)
    plan = await research_import.plan(db, rows)
    plan = research_import.Plan(
        companies=[pin(item, company.id) for item in plan.companies], rows=plan.rows
    )
    published = {int(p["line"]): p.get("published") for p in _people(result)}
    return plan, published


async def _company(db: AsyncSession, result: SalesBotResult) -> SalesCompany:
    company = (
        await db.get(SalesCompany, result.company_id)
        if result.company_id is not None
        else None
    )
    if company is None or company.archived_at is not None:
        raise AcceptRefused(NO_COMPANY_DETAIL)
    return company


@dataclasses.dataclass(frozen=True)
class Pick:
    """Wiersz wyniku do zapisu: poziom i karta wskazane na ekranie."""

    line: int
    decision_level: Optional[int] = None
    company_id: Optional[int] = None


async def apply(
    db: AsyncSession,
    result: SalesBotResult,
    picks: Sequence[Pick],
    *,
    user_id: int,
    owner_user_id: int,
    now: datetime,
) -> list[research_import.Outcome]:
    """Zapis wybranych osób na mapę i stan wyniku (``partial`` albo ``accepted``).

    Treść osoby bierze się z wyniku, nie z żądania: ekran wybiera tylko poziom
    i kartę, więc kontakt bez źródła nie trafi na mapę bocznymi drzwiami.
    Commit robi wywołujący.
    """

    if result.kind != KIND:
        raise AcceptRefused(NOT_PEOPLE_DETAIL)
    company = await _company(db, result)
    by_line = {int(p["line"]): p for p in _people(result)}
    people = [
        research_import.Person(
            line=pick.line,
            company=company.name,
            name=person["full_name"],
            title=person.get("title"),
            email=person.get("email"),
            phone=person.get("phone"),
            linkedin_url=person.get("linkedin_url"),
            source_url=person.get("source_url"),
            domain=company.domain or None,
            confidence=TO_VERIFY,
            decision_level=pick.decision_level or _level(person),
            company_id=pick.company_id,
            source_published=person.get("published"),
        )
        for pick in picks
        if (person := by_line.get(pick.line)) is not None
    ]
    if not people:
        return []
    try:
        outcomes = await research_import.accept(
            db,
            people,
            user_id=user_id,
            owner_user_id=owner_user_id,
            source_label=ORIGIN,
            today=business_today(),
            now=now,
        )
    except research_import.NoPipelineError as exc:
        raise AcceptRefused(str(exc)) from exc
    decided = {
        **{str(k): v for k, v in decided_lines(result).items()},
        **{str(o.line): o.result for o in outcomes},
    }
    result.payload = {**(result.payload or {}), "outcomes": decided}
    result.status = "accepted" if open_count(result) == 0 else "partial"
    result.decided_by_user_id = user_id
    result.decided_at = now
    result.updated_at = now
    return outcomes


async def _accept_all(
    db: AsyncSession, result: SalesBotResult, user_id: int, now: datetime
) -> dict[str, Any]:
    """Przyjęcie z listy wyników: wszystkie otwarte osoby na kartę z wyniku."""

    plan, _ = await review_plan(db, result)
    target = plan.companies[0] if plan.companies else None
    if target is not None and target.state == research_import.CHOOSE:
        raise AcceptRefused(CHOOSE_DETAIL)
    company_id = (
        target.company_id
        if target is not None and target.company_id is not None
        else result.company_id
    )
    done = {line for line, value in decided_lines(result).items() if value in HANDLED}
    picks = [
        Pick(line=int(person["line"]), company_id=company_id)
        for person in _people(result)
        if int(person["line"]) not in done
    ]
    outcomes = await apply(
        db, result, picks, user_id=user_id, owner_user_id=user_id, now=now
    )
    return {
        "status": result.status,
        "added": sum(o.result == research_import.ADDED for o in outcomes),
        "open": open_count(result),
    }


PEOPLE = BotTask(
    kind=KIND,
    task_text=_task_text,
    report_format=_report_format,
    report_model=PeopleReport,
    ingest=_ingest,
    accept=_accept_all,
    request_model=PeopleRequest,
)


# ── Mapa firmy z Cognism ──────────────────────────────────────────────────

_PROFILE_PATH = re.compile(
    r"/search/prospects/(?:(?:contacts?|people|persons?|prospects?)/)?([A-Za-z0-9_-]{8,128})/?"
)
_CLOCK_SKEW = timedelta(minutes=5)
PhoneType = Literal["direct", "mobile"]


class CognismPerson(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: RequiredText = Field(max_length=255)
    title: RequiredText = Field(max_length=255)
    source_url: str = Field(max_length=512)
    observed_at: AwareDatetime
    active: StrictBool
    dnc: Optional[StrictBool] = None
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=60)
    phone_type: Optional[PhoneType] = None
    verified_mobile: Optional[StrictBool] = None

    @field_validator("source_url")
    @classmethod
    def _provider_profile(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.netloc.lower() != "app.cognism.com"
            or url.query
            or url.fragment
            or "?" in value
            or "#" in value
            or not _PROFILE_PATH.fullmatch(url.path)
        ):
            raise ValueError("Wymagany jest link do profilu osoby w Cognism.")
        return f"https://app.cognism.com{url.path.rstrip('/')}"


class CognismFirm(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company_ref: int = Field(gt=0)
    status: Literal["matched", "no_people", "not_found", "ambiguous", "not_processed"]
    company_name: Optional[RequiredText] = Field(default=None, max_length=500)
    company_domain: Optional[str] = Field(default=None, max_length=255)
    people: list[CognismPerson] = Field(
        default_factory=list, max_length=COGNISM_MAX_PEOPLE
    )

    @model_validator(mode="after")
    def _consistent_outcome(self) -> "CognismFirm":
        if self.status in ("matched", "no_people") and not self.company_name:
            raise ValueError("Przy dopasowaniu podaj nazwę pracodawcy z Cognism.")
        if bool(self.people) != (self.status == "matched"):
            raise ValueError("Lista osób jest wymagana wyłącznie dla matched.")
        return self


class CognismReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    firms: list[CognismFirm] = Field(max_length=COGNISM_MAX_FIRMS)


class CognismMapPerson(BaseModel):
    full_name: str
    title: str
    source_url: str
    observed_at: AwareDatetime
    source: Literal["cognism"] = COGNISM_SOURCE
    active: Literal[True] = True
    email: Optional[str] = None
    email_observed_at: Optional[AwareDatetime] = None
    phone: Optional[str] = None
    phone_type: Optional[PhoneType] = None
    phone_observed_at: Optional[AwareDatetime] = None
    verified_mobile: Optional[bool] = None


def _cognism_task_text(run: SalesSignalRun, ctx: TaskContext) -> str:
    return (
        "Korzystaj tylko z widocznych kontrolek zalogowanego Cognism. Dla każdej firmy "
        "potwierdź dokładną spółkę i domenę z profilu pracodawcy. Wybierz do pięciu "
        "aktualnych decydentów IT, danych/AI, inżynierii, zakupów i zarządu. Najpierw "
        "sprawdź Revealed. Reveal pojedynczo tylko dla dopasowanych osób, do pięciu "
        "odsłonięć na firmę z istniejącej puli kredytów. Nie kupuj kredytów, nie eksportuj "
        "i nie obchodź blokad. Gdy sesja wygasła, użyj wpisu Cognism z Vault. Jeśli "
        "logowanie się nie powiedzie albo panel wymaga MFA, CAPTCHA lub opłaty, "
        "zwróć not_processed dla niedokończonych firm. Przy "
        "niejednoznacznej spółce zwróć ambiguous; przy braku spółki not_found; przy "
        "potwierdzonej spółce bez osób no_people. Dane osoby tylko z otwartego profilu "
        "Cognism: bez zgadywania, prywatnych skrzynek i numerów centrali. Podaj dokładny "
        "adres profilu bez zapytania i datę odczytu z UTC. Telefon tylko bezpośredni "
        "lub komórkowy. Ustaw dnc=true przy fladze Do Not Call i pomiń numer. Ustaw "
        "dnc=false tylko przy widocznym numerze bez flagi; w razie wątpliwości pomiń "
        "numer i dnc. Diamond oznacza verified_mobile=true. Nie zapisuj danych w czacie."
    )


def _cognism_format() -> dict[str, Any]:
    return {
        "firms": [
            {
                "company_ref": "<ref z firms>",
                "status": "matched|no_people|not_found|ambiguous|not_processed",
                "company_name": "<dokładna nazwa pracodawcy w Cognism albo null>",
                "company_domain": "<domena profilu pracodawcy albo null>",
                "people": [
                    {
                        "full_name": "...",
                        "title": "...",
                        "source_url": "<link do otwartego profilu osoby w Cognism>",
                        "observed_at": "RRRR-MM-DDTHH:MM:SSZ",
                        "active": True,
                        "dnc": "<true|false|null>",
                        "email": "<służbowy e-mail albo null>",
                        "phone": "<bezpośredni numer albo null>",
                        "phone_type": "direct|mobile|null",
                        "verified_mobile": "<true|false|null>",
                    }
                ],
            }
        ]
    }


def _cognism_key(person: dict[str, Any]) -> str:
    return person["source_url"].rstrip("/").rsplit("/", 1)[-1]


_CONTACT_FIELDS = {
    "email": ("email_observed_at",),
    "phone": ("phone_observed_at", "phone_type", "verified_mobile"),
}


def _observation(person: dict[str, Any], field: str = "observed_at") -> datetime:
    return datetime.fromisoformat(person.get(field) or person["observed_at"])


def merge_cognism_people(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Scal mapy po identyfikatorze profilu; brak pola w nowszym odczycie go nie kasuje."""

    merged: dict[str, dict[str, Any]] = {}
    for person in [*existing, *incoming]:
        key = _cognism_key(person)
        previous = merged.get(key)
        if previous is None:
            merged[key] = dict(person)
            continue
        old, new = sorted(
            (previous, person),
            key=_observation,
        )
        combined = {
            **old,
            **{field: value for field, value in new.items() if value is not None},
        }
        for field, metadata in _CONTACT_FIELDS.items():
            available = [entry for entry in (new, old) if entry.get(field)]
            if available:
                most_recent = max(
                    available, key=lambda entry: _observation(entry, metadata[0])
                )
                for name in (field, *metadata):
                    combined[name] = most_recent.get(name)
                combined[metadata[0]] = (
                    most_recent.get(metadata[0]) or most_recent["observed_at"]
                )
        merged[key] = combined
    return list(merged.values())


def _visible_cognism_people(
    entries: list[dict[str, Any]], suppressions: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    visible = []
    for person in entries:
        blocked = {
            reason: datetime.fromisoformat(at)
            for reason, at in suppressions.get(_cognism_key(person), {}).items()
        }
        if not blocked:
            visible.append(person)
            continue
        cutoff = max(blocked.values())
        if _observation(person) <= cutoff:
            continue
        if "dnc" in blocked and (
            not person.get("phone")
            or _observation(person, "phone_observed_at") <= cutoff
        ):
            continue
        kept = dict(person)
        for field, metadata in _CONTACT_FIELDS.items():
            if kept.get(field) and _observation(kept, metadata[0]) <= cutoff:
                for name in (field, *metadata):
                    kept[name] = None
        visible.append(kept)
    return visible


def merge_cognism_company_fields(
    target: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    """Połącz tylko pola mapy; stare dane nie przywracają profilu po DNC."""

    if not (
        {COGNISM_MAP_KEY, COGNISM_SUPPRESSIONS_KEY} & (target.keys() | source.keys())
    ):
        return {}
    suppressions: dict[str, dict[str, str]] = {}
    for fields in (target, source):
        for key, observations in (fields.get(COGNISM_SUPPRESSIONS_KEY) or {}).items():
            latest = suppressions.setdefault(key, {})
            for reason, at in observations.items():
                previous = latest.get(reason)
                if previous is None or datetime.fromisoformat(
                    at
                ) > datetime.fromisoformat(previous):
                    latest[reason] = at
    entries = merge_cognism_people(
        target.get(COGNISM_MAP_KEY) or [], source.get(COGNISM_MAP_KEY) or []
    )
    return {
        COGNISM_MAP_KEY: _visible_cognism_people(entries, suppressions),
        COGNISM_SUPPRESSIONS_KEY: suppressions,
    }


def _cognism_employer_matches(company: SalesCompany, firm: CognismFirm) -> bool:
    target_names = {
        normalize_company_name(value or "")
        for value in (company.name, company.legal_name, company.normalized_name)
    } - {""}
    target_domain = mail_domain(company.domain) or mail_domain(company.website_url)
    reported_domain = site_domain(firm.company_domain)
    return normalize_company_name(firm.company_name or "") in target_names and (
        not target_domain or target_domain == reported_domain
    )


def _cognism_contact(
    person: CognismPerson, company_domain: Optional[str]
) -> CognismMapPerson:
    email = valid_email(person.email)
    if not email or not company_domain or mail_domain(email) != company_domain:
        email = None
    phone = (
        valid_phone(person.phone)
        if person.dnc is False and person.phone_type and phone_digits(person.phone)
        else None
    )
    if phone and not re.fullmatch(r"[+0-9(). -]+", phone):
        phone = None
    return CognismMapPerson(
        full_name=person.full_name,
        title=person.title,
        source_url=person.source_url,
        observed_at=person.observed_at,
        email=email,
        email_observed_at=person.observed_at if email else None,
        phone=phone,
        phone_type=person.phone_type if phone else None,
        phone_observed_at=person.observed_at if phone else None,
        verified_mobile=person.verified_mobile
        if phone and person.phone_type == "mobile"
        else None,
    )


async def _cognism_objections(
    db: AsyncSession, company_ids: set[int]
) -> tuple[set[tuple[int, str]], set[str], set[str]]:
    names: set[tuple[int, str]] = set()
    emails: set[str] = set()
    phones: set[str] = set()
    contacts = await db.execute(
        select(
            SalesContact.company_id,
            SalesContact.full_name,
            SalesContact.email,
            SalesContact.phone,
            SalesContact.mobile_phone,
        ).where(SalesContact.do_not_contact_at.is_not(None))
    )
    linked = await db.execute(
        select(SalesCompanyContact.company_id, SalesContact.full_name)
        .join(SalesContact, SalesContact.id == SalesCompanyContact.contact_id)
        .where(
            SalesCompanyContact.company_id.in_(company_ids),
            SalesContact.do_not_contact_at.is_not(None),
        )
    )
    calls = await db.execute(
        select(
            SalesCallRecord.company_id,
            SalesCallRecord.person_name,
            SalesCallRecord.email,
            SalesCallRecord.phone,
        ).where(SalesCallRecord.state == "do_not_contact")
    )
    for company_id, name in linked.all():
        if key := person_key(name):
            names.add((company_id, key))
    for company_id, name, email, *numbers in [*contacts.all(), *calls.all()]:
        if company_id in company_ids and (key := person_key(name)):
            names.add((company_id, key))
        if address := valid_email(email):
            emails.add(address)
        phones.update(number for value in numbers if (number := phone_digits(value)))
    return names, emails, phones


async def read_cognism_map(
    db: AsyncSession, company: SalesCompany
) -> list[CognismMapPerson]:
    fields = company.custom_fields or {}
    entries = _visible_cognism_people(
        fields.get(COGNISM_MAP_KEY) or [], fields.get(COGNISM_SUPPRESSIONS_KEY) or {}
    )
    if not entries or company.status == COMPANY_DO_NOT_CONTACT:
        return []
    names, emails, phones = await _cognism_objections(db, {company.id})
    return [
        CognismMapPerson.model_validate(person)
        for person in entries
        if (company.id, person_key(person["full_name"])) not in names
        and person.get("email") not in emails
        and phone_digits(person.get("phone")) not in phones
    ]


async def _ingest_cognism(
    db: AsyncSession, run: SalesSignalRun, report: CognismReport, now: datetime
) -> dict[str, Any]:
    allowed = set(run.company_ids)
    received: dict[int, CognismFirm] = {}
    processed: set[int] = set()
    ambiguous: set[int] = set()
    unknown = stored = no_people = not_found = suppressed = 0
    for firm in report.firms:
        cid = firm.company_ref
        if cid not in allowed:
            unknown += 1
        elif cid in received:
            ambiguous.add(cid)
        else:
            received[cid] = firm
    rows = await db.execute(
        select(SalesCompany)
        .where(SalesCompany.id.in_(received))
        .order_by(SalesCompany.id)
        .with_for_update()
    )
    companies = {company.id: company for company in rows.scalars()}
    clients = await client_gate.match_companies(
        db,
        [
            client_gate.CompanyIdentity(
                company.id, company.client_id, company.normalized_name
            )
            for company in companies.values()
        ],
    )
    names, emails, phones = await _cognism_objections(db, set(companies))
    for cid, firm in received.items():
        company = companies.get(cid)
        if cid in ambiguous or firm.status == "ambiguous":
            ambiguous.add(cid)
            continue
        if (
            company is None
            or company.archived_at is not None
            or company.status == COMPANY_DO_NOT_CONTACT
            or cid in clients
            or company_aliases.is_own_company(company.normalized_name)
            or firm.status == "not_processed"
        ):
            continue
        if firm.status == "not_found":
            processed.add(cid)
            not_found += 1
            continue
        if not _cognism_employer_matches(company, firm):
            ambiguous.add(cid)
            continue
        if firm.status == "no_people":
            processed.add(cid)
            no_people += 1
            continue
        domain = (
            site_domain(firm.company_domain)
            or mail_domain(company.domain)
            or mail_domain(company.website_url)
        )
        fields = company.custom_fields or {}
        existing = fields.get(COGNISM_MAP_KEY) or []
        by_key = {_cognism_key(person): person for person in existing}
        fresh: list[dict[str, Any]] = []
        removed: set[str] = set()
        provider_suppressions: dict[str, dict[str, str]] = {}
        for person in firm.people:
            if (
                not run.started_at - _CLOCK_SKEW
                <= person.observed_at
                <= now + _CLOCK_SKEW
            ):
                continue
            row = _cognism_contact(person, domain).model_dump(mode="json")
            key = _cognism_key(row)
            if not person.active or person.dnc is True:
                marks = provider_suppressions.setdefault(key, {})
                for reason, applies in (
                    ("inactive", not person.active),
                    ("dnc", person.dnc is True),
                ):
                    if not applies:
                        continue
                    previous_at = marks.get(reason)
                    if (
                        previous_at is None
                        or person.observed_at > datetime.fromisoformat(previous_at)
                    ):
                        marks[reason] = row["observed_at"]
                suppressed += 1
                continue
            previous = by_key.get(key, {})
            if (
                (cid, person_key(person.full_name)) in names
                or valid_email(person.email) in emails
                or previous.get("email") in emails
                or phone_digits(person.phone) in phones
                or phone_digits(previous.get("phone")) in phones
            ):
                removed.add(key)
                suppressed += 1
                continue
            fresh.append(row)
        if fresh or removed or provider_suppressions:
            processed.add(cid)
            merged = merge_cognism_company_fields(
                fields,
                {
                    COGNISM_MAP_KEY: fresh,
                    COGNISM_SUPPRESSIONS_KEY: provider_suppressions,
                },
            )
            visible = [
                person
                for person in merged[COGNISM_MAP_KEY]
                if _cognism_key(person) not in removed
            ]
            company.custom_fields = {**fields, **merged, COGNISM_MAP_KEY: visible}
            stored += len(
                {_cognism_key(row) for row in fresh}
                & {_cognism_key(row) for row in visible}
            )
    return {
        "firms": len(allowed),
        "processed": len(processed),
        "people": stored,
        "no_people": no_people,
        "not_found": not_found,
        "ambiguous": len(ambiguous),
        "not_processed": len(allowed - processed - ambiguous),
        "unknown_company": unknown,
        "suppressed": suppressed,
        "processed_company_ids": sorted(processed),
        "ambiguous_company_ids": sorted(ambiguous),
        "unprocessed_company_ids": sorted(allowed - processed - ambiguous),
    }


COGNISM = BotTask(
    kind=KIND,
    task_text=_cognism_task_text,
    report_format=_cognism_format,
    report_model=CognismReport,
    ingest=_ingest_cognism,
    request_model=PeopleRequest,
)
