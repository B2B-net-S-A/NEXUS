"""Research do oceny potencjału: co dzieje się w firmie i jak wygląda jej IT.

Bieg rodzaju ``briefing`` z firmami w trybie ``potential`` (przycisk „Oceń
potencjał” na karcie firmy, pętla przed pierwszym spotkaniem), jak haczyk:
bez nowego rodzaju biegu i bez migracji. Bot odsyła ``potential`` w tym samym
raporcie co punkty; NEXUS zapisuje research w ``sales_bot_results`` (rodzaj
``potential``, stan ``pending``), a ocenę pisze potem model z rejestru AI
(``services/sales/potential.py``).

Do bota idą tylko nazwa, domena, NIP i KRS firmy, jak przy każdym biegu. Raport
nie ma pól osób: decydentów pokazuje mapa decydentów, nie ten research.
Ogłoszenia o pracę wolno czytać tylko w tym trybie (decyzja Artura z 23.11.2026,
„wszystko co się da”): portale z ogłoszeniami i publiczne oferty pracy, bez
logowania i bez profili osób.

Reguły: ``docs/claude/sprzedaz/ocena-potencjalu.md``.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesSignalRun
from app.services.sales.bot_tasks.base import (
    CleanText,
    RequiredText,
    SourceUrl,
    result_fingerprint,
    save_results,
)

#: Tryb firmy w biegu ``briefing`` i rodzaj wyniku w ``sales_bot_results``.
POTENTIAL = "potential"
MAX_FIRMS = 5
MAX_EVENTS = 10
MAX_JOBS = 20
MAX_STACK = 10
#: Zdarzenia z ostatnich 18 miesięcy, ogłoszenia z ostatniego roku.
EVENT_WINDOW_DAYS = 548
JOB_WINDOW_DAYS = 365

#: Linie oferty, do których bot przypisuje zdarzenie (klucze stałe, etykiety na ekranie).
OFFER_LINES: dict[str, str] = {
    "specialists": "Specjaliści (body leasing, zespoły)",
    "security": "Cyberbezpieczeństwo",
    "cloud": "Chmura i infrastruktura",
    "ai": "AI i dane",
    "qa": "QA i testy",
    "elevate": "Dynaminds Elevate",
    "qms": "QMS i szkolenia",
}
OfferLine = Literal["specialists", "security", "cloud", "ai", "qa", "elevate", "qms"]

_MONTH = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
_PKD = re.compile(r"^\d{2}\.\d{2}\.[A-Z]$")


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: ``RRRR-MM-DD`` albo ``RRRR-MM``, gdy źródło podaje tylko miesiąc.
    date: str = Field(min_length=7, max_length=10)
    text: RequiredText = Field(min_length=1, max_length=300)
    url: SourceUrl = Field(min_length=1, max_length=1000)
    line: Optional[OfferLine] = None

    @field_validator("line", mode="before")
    @classmethod
    def _line(cls, value: Any) -> Optional[str]:
        return value if value in OFFER_LINES else None

    @field_validator("date")
    @classmethod
    def _date(cls, value: str) -> str:
        if not _MONTH.match(value):
            raise ValueError("data RRRR-MM-DD albo RRRR-MM")
        return value


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: RequiredText = Field(min_length=1, max_length=120)
    tech: CleanText = Field(default="", max_length=200)
    contract: CleanText = Field(default="", max_length=40)
    published: Optional[date] = None
    url: SourceUrl = Field(min_length=1, max_length=1000)
    active: Optional[bool] = None

    @field_validator("published", mode="before")
    @classmethod
    def _published(cls, value: Any) -> Optional[date]:
        """Data spoza formatu (pusta, sam miesiąc) to brak daty, nie błąd raportu."""

        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value or "").strip())
        except ValueError:
            return None


class StackItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: RequiredText = Field(min_length=1, max_length=200)
    url: SourceUrl = Field(min_length=1, max_length=1000)


class ReportPotential(BaseModel):
    """Research jednej firmy; bez pól osób i kontaktów."""

    model_config = ConfigDict(extra="forbid")

    company_ref: int
    #: Przeważające PKD z KRS, np. ``21.20.Z``; podstawa testu KSC w NEXUSIE.
    pkd: Optional[str] = Field(default=None, max_length=8)
    employees: CleanText = Field(default="", max_length=80)
    revenue: CleanText = Field(default="", max_length=120)
    group: CleanText = Field(default="", max_length=200)
    facts_url: Optional[SourceUrl] = Field(default=None, max_length=1000)
    events: list[Event] = Field(default_factory=list, max_length=MAX_EVENTS)
    jobs: list[Job] = Field(default_factory=list, max_length=MAX_JOBS)
    stack: list[StackItem] = Field(default_factory=list, max_length=MAX_STACK)

    @model_validator(mode="before")
    @classmethod
    def _drop_bad_items(cls, data: Any) -> Any:
        """Zły element (bez źródła, zła data) odpada sam; raport i reszta zostają.

        Przy pięciu firmach w biegu jedno złe ogłoszenie nie może zabrać researchu
        wszystkich. Pola spoza modelu na poziomie firmy dalej dają 422 (``forbid``).
        """

        if not isinstance(data, dict):
            return data
        out = dict(data)
        for key, model in (("events", Event), ("jobs", Job), ("stack", StackItem)):
            items = out.get(key)
            if not isinstance(items, list):
                continue
            kept = []
            for item in items:
                try:
                    model.model_validate(item)
                except ValidationError:
                    continue
                kept.append(item)
            out[key] = kept
        return out

    @field_validator("pkd", mode="before")
    @classmethod
    def _pkd(cls, value: Any) -> Optional[str]:
        text = str(value or "").strip().upper().replace(" ", "")
        return text if _PKD.match(text) else None


def potential_refs(run: SalesSignalRun) -> set[int]:
    allowed = {int(ref) for ref in run.company_ids}
    return {
        int(ref)
        for ref, mode in (run.modes or {}).items()
        if mode == POTENTIAL and int(ref) in allowed
    }


def _event_day(value: str) -> date:
    parts = [int(p) for p in value.split("-")]
    return date(parts[0], parts[1], parts[2] if len(parts) > 2 else 1)


def plan(
    run: SalesSignalRun, items: list[ReportPotential], *, today: date
) -> tuple[list[dict[str, Any]], int]:
    """Wiersze do zapisu i liczba odrzuconych (firma spoza trybu, drugi raz).

    Zdarzenie starsze niż 18 miesięcy albo z przyszłości i ogłoszenie starsze
    niż rok odpadają po cichu: research zostaje, bez nich.
    """

    allowed = potential_refs(run)
    oldest_event = today - timedelta(days=EVENT_WINDOW_DAYS)
    oldest_job = today - timedelta(days=JOB_WINDOW_DAYS)
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    dropped = 0
    for item in items:
        if item.company_ref not in allowed or item.company_ref in seen:
            dropped += 1
            continue
        seen.add(item.company_ref)
        events = []
        for event in item.events:
            try:
                day = _event_day(event.date)
            except ValueError:
                continue
            if oldest_event <= day <= today + timedelta(days=1):
                events.append(event.model_dump(mode="json"))
        jobs = [
            job.model_dump(mode="json")
            for job in item.jobs
            if job.published is None or oldest_job <= job.published <= today
        ]
        research = {
            "pkd": item.pkd,
            "employees": item.employees,
            "revenue": item.revenue,
            "group": item.group,
            "facts_url": item.facts_url,
            "events": sorted(events, key=lambda e: e["date"], reverse=True),
            "jobs": jobs,
            "stack": [s.model_dump(mode="json") for s in item.stack],
        }
        rows.append(
            {
                "company_id": item.company_ref,
                "payload": {"state": "pending", "research": research},
                "fingerprint": result_fingerprint(POTENTIAL, item.company_ref, run.id),
            }
        )
    return rows, dropped


async def save(
    db: AsyncSession,
    run: SalesSignalRun,
    items: list[ReportPotential],
    *,
    today: date,
    now: datetime,
) -> dict[str, Any]:
    rows, dropped = plan(run, items, today=today)
    await save_results(db, run, rows, now, kind=POTENTIAL)
    return {"potential": len(rows), "potential_dropped": dropped}


def task_text(refs: list[int]) -> str:
    lines = ", ".join(f"{key} ({label})" for key, label in OFFER_LINES.items())
    return (
        f'Dla firm z mode = "potential" (ref {", ".join(map(str, refs))}) nie pisz '
        "punktów w briefings ani haczyków. Handlowiec firmy IT ocenia, czy ta firma "
        "może kupić od nas usługi IT. Dla każdej takiej firmy dopisz do potential "
        "research firmy, bez informacji o osobach:\n"
        "- pkd: przeważające PKD z KRS (np. 21.20.Z); employees: liczba pracowników "
        "albo przedział z rokiem; revenue: przychód z rokiem; group: właściciel albo "
        "grupa kapitałowa; facts_url: źródło tych danych. Gdy czegoś nie ma, zostaw puste.\n"
        "- events: do 10 zdarzeń z ostatnich 18 miesięcy, które mogą tworzyć potrzebę "
        "IT: zmiana właściciela, fuzja, nowy zarząd lub szef IT, ekspansja, nowe zakłady "
        "albo produkty, wdrożenia ERP/CRM/MES, migracja do chmury, incydenty "
        "bezpieczeństwa, kary UODO, nowe obowiązki (NIS2/KSC, DORA, AI Act), dotacje na "
        "cyfryzację, intensywna rekrutacja IT. Każde z datą (RRRR-MM-DD albo RRRR-MM), "
        f"adresem źródła i linią naszej oferty (line), jedną z: {lines}.\n"
        "- jobs: do 20 aktualnych ogłoszeń o pracę w IT tej firmy (stanowisko, "
        "technologie, typ umowy, data publikacji, adres, czy aktywne). W tym zadaniu "
        "wolno czytać portale z ogłoszeniami (pracuj.pl, justjoin.it, theprotocol.it, "
        "nofluffjobs) i publiczne oferty pracy na LinkedInie bez logowania. Nie "
        "otwieraj profili osób.\n"
        "- stack: do 10 faktów o technologiach i dostawcach IT firmy (ERP, chmura, "
        "systemy branżowe, aplikacje), każdy ze źródłem.\n"
        "Firmę, której nie udało się sprawdzić, pomiń. W checked_firms podaj liczbę "
        "rzeczywiście sprawdzonych firm."
    )


def report_format() -> dict[str, Any]:
    return {
        "company_ref": "<ref z firms, mode potential>",
        "pkd": "21.20.Z",
        "employees": "...",
        "revenue": "...",
        "group": "...",
        "facts_url": "https://...",
        "events": [
            {
                "date": "RRRR-MM-DD",
                "text": "...",
                "url": "https://...",
                "line": "security",
            }
        ],
        "jobs": [
            {
                "title": "...",
                "tech": "...",
                "contract": "B2B|UoP",
                "published": "RRRR-MM-DD",
                "url": "https://...",
                "active": True,
            }
        ],
        "stack": [{"text": "...", "url": "https://..."}],
    }
