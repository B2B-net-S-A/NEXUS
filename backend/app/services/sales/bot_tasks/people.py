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
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.sales import (
    SalesBotResult,
    SalesCompany,
    SalesOpportunity,
    SalesPipeline,
    SalesSignalRun,
)
from app.services.sales import research_import
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
from app.services.sales.research_file import (
    TO_VERIFY,
    ResearchRow,
    level_from_title,
    person_key,
    valid_email,
    valid_link,
    valid_phone,
)

logger = logging.getLogger(__name__)

KIND = "people"
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
)
