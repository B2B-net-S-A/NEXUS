"""Rodzaj ``lists`` (Bot Listy L3–L4): firmy pod kampanię z rejestr.io i researchu.

Decyzje Artura z 13.11.2026: Bot Listy dosypuje listę z bazy NEXUSA, a gdy brief
ma źródło „rejestr.io” albo „research” i paczka nie jest pełna, zleca botowi
firmy z segmentu. Wynik trafia do kampanii **od razu**, przez bramki importu listy
(``calling_import.apply_import``): klient NEXUSA, sprzeciw, cudzy rekord, NIP już
wczytany, brak telefonu. Do rejestr.io bot korzysta z dostępu ustawionego przez
Artura w rutynie (jego decyzja i ryzyko); w NEXUSIE nie ma haseł ani instrukcji
logowania.

Co idzie do bota (``ListsRequest``) i dlaczego:
- ``campaign_id`` — numer kampanii w NEXUSIE; bot go nie używa, NEXUS po nim
  przyjmuje raport do właściwej kampanii;
- ``pkd``, ``regions``, ``sizes``, ``triggers``, ``roles``, ``count`` — segment z
  briefu, bez danych osób;
- ``exclude_nips`` — NIP-y firm dzwonionych w ostatnich 6 miesiącach, żeby bot nie
  szukał ich drugi raz (NIP i KRS mogą iść do bota: decyzja Artura 13.11.2026);
- ``like`` — L4: firmy, z którymi kampania umówiła spotkanie (nazwa, NIP, domena,
  branża, miasto), żeby bot znalazł podobne.

Reguły: ``docs/claude/sprzedaz/bot-listy-kampanie.md`` („L3–L4”).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesSignalRun
from app.services.sales.bot_tasks.base import (
    BotTask,
    CleanText,
    RequiredText,
    SourceUrl,
    TaskContext,
)
from app.services.sales.bot_tasks.enrich import normalize_nip

logger = logging.getLogger(__name__)

KIND = "lists"
MAX_FIRMS = 50
MAX_EXCLUDED = 300
MAX_LIKE = 10
SOURCE_LABELS = {"rejestr": "rejestr.io", "research": "research"}


class LikeFirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=300)
    nip: Optional[str] = Field(default=None, max_length=10)
    domain: Optional[str] = Field(default=None, max_length=255)
    industry: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=120)


class ListsRequest(BaseModel):
    """Zlecenie dla bota; uzasadnienie każdego pola w opisie modułu."""

    model_config = ConfigDict(extra="forbid")

    campaign_id: int = Field(gt=0)
    pkd: list[str] = Field(default_factory=list, max_length=15)
    regions: list[str] = Field(default_factory=list, max_length=16)
    sizes: list[str] = Field(default_factory=list, max_length=4)
    triggers: list[str] = Field(default_factory=list, max_length=4)
    roles: list[str] = Field(default_factory=list, max_length=5)
    sources: list[Literal["rejestr", "research"]] = Field(min_length=1, max_length=2)
    count: int = Field(ge=1, le=MAX_FIRMS)
    exclude_nips: list[str] = Field(default_factory=list, max_length=MAX_EXCLUDED)
    like: list[LikeFirm] = Field(default_factory=list, max_length=MAX_LIKE)


class ListPerson(BaseModel):
    """Osoba tylko z opublikowanego źródła (zarząd w KRS, strona firmy)."""

    model_config = ConfigDict(extra="forbid")

    full_name: RequiredText = Field(max_length=200)
    title: CleanText = Field(default="", max_length=200)
    source_url: SourceUrl = Field(max_length=1000)


class ListTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: RequiredText = Field(max_length=400)
    url: SourceUrl = Field(max_length=1000)
    published: Optional[date] = None


class ListFirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: RequiredText = Field(max_length=300)
    nip: Optional[CleanText] = Field(default=None, max_length=20)
    krs: Optional[CleanText] = Field(default=None, max_length=20)
    domain: Optional[CleanText] = Field(default=None, max_length=255)
    website: Optional[CleanText] = Field(default=None, max_length=500)
    city: CleanText = Field(default="", max_length=120)
    pkd: CleanText = Field(default="", max_length=200)
    employees: CleanText = Field(default="", max_length=40)
    #: Telefon i e-mail firmy (centrala, biuro) tylko z własnym źródłem.
    phone: Optional[CleanText] = Field(default=None, max_length=60)
    phone_source: Optional[SourceUrl] = Field(default=None, max_length=1000)
    email: Optional[CleanText] = Field(default=None, max_length=255)
    email_source: Optional[SourceUrl] = Field(default=None, max_length=1000)
    person: Optional[ListPerson] = None
    trigger: Optional[ListTrigger] = None
    source: Literal["rejestr", "research"]
    source_url: SourceUrl = Field(max_length=1000)

    @field_validator("nip")
    @classmethod
    def _nip(cls, value: Optional[str]) -> Optional[str]:
        # Zły NIP nie przekreśla firmy: odpada sam numer.
        return normalize_nip(value) if value else None


class ListsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    firms: list[ListFirm] = Field(default_factory=list, max_length=MAX_FIRMS)


def _task_text(run: SalesSignalRun, ctx: TaskContext) -> str:
    request = ctx.request
    like = (
        " Pole like to firmy, z którymi ta kampania umówiła spotkanie: szukaj firm "
        "podobnych (ta sama branża PKD, podobna wielkość i region), ale nie tych samych."
        if request.get("like")
        else ""
    )
    return (
        "Lista firms jest pusta: szukasz sam firm do kampanii telefonicznej "
        "firmy dostarczającej specjalistów IT. Segment jest w request: kody PKD "
        "(pkd), województwa (regions), wielkość w osobach (sizes), wyzwalacze "
        "(triggers: board_change — zmiana w zarządzie w ostatnich 6 miesiącach, "
        "it_center — nowe albo rosnące centrum IT, acquisition — przejęcie, hiring — "
        "rekrutacje IT) i stanowiska osób, do których dzwonimy (roles). Źródła "
        "(sources): rejestr — rejestr.io (wyszukiwarka organizacji i profile firm, "
        "w ramach dostępu tej rutyny), research — strony firm, komunikaty, prasa. "
        f"Znajdź najwyżej {request.get('count', 20)} firm z Polski. Pomiń firmy "
        "z NIP-em z exclude_nips. Dla każdej: nazwa, NIP, KRS, domena i strona, "
        "miasto, PKD, liczba osób, telefon i e-mail firmy (centrala, biuro) tylko "
        "wtedy, gdy są opublikowane, każde z adresem źródła (phone_source, "
        "email_source). Osobę (person) podaj tylko, gdy jest wymieniona z imienia "
        "i nazwiska na otwartym źródle (zarząd w KRS, strona firmy), z linkiem; "
        "bez LinkedIna i bez zgadywania e-maili i telefonów. Gdy firma spełnia "
        "wyzwalacz, opisz go jednym zdaniem w trigger z adresem i datą. source to "
        "rejestr albo research, source_url to strona, z której wziąłeś firmę."
        f"{like}"
    )


def _report_format() -> dict[str, Any]:
    return {
        "firms": [
            {
                "company": "...",
                "nip": "0000000000",
                "krs": "0000000000",
                "domain": "firma.pl",
                "website": "https://www.firma.pl",
                "city": "...",
                "pkd": "62.01.Z",
                "employees": "250-999",
                "phone": "+48 ...",
                "phone_source": "https://...",
                "email": "biuro@firma.pl",
                "email_source": "https://...",
                "person": {
                    "full_name": "...",
                    "title": "...",
                    "source_url": "https://...",
                },
                "trigger": {
                    "text": "...",
                    "url": "https://...",
                    "published": "RRRR-MM-DD",
                },
                "source": "rejestr|research",
                "source_url": "https://...",
            }
        ]
    }


async def _ingest(
    db: AsyncSession, run: SalesSignalRun, report: ListsReport, now: datetime
) -> dict[str, Any]:
    # Import tu, nie na górze: bot_lists importuje rejestr zadań (cykl modułów).
    from app.services.sales import bot_lists

    campaign_id = int((run.request or {}).get("campaign_id") or 0)
    result = await bot_lists.ingest_firms(db, campaign_id, report.firms, now=now)
    logger.info(
        "bot_lists lists run=%s campaign=%s firms=%d added=%d",
        run.id,
        campaign_id,
        len(report.firms),
        result.added,
    )
    return {
        "firms": len(report.firms),
        "added": result.added,
        "skipped": result.skipped,
    }


LISTS = BotTask(
    kind=KIND,
    task_text=_task_text,
    report_format=_report_format,
    report_model=ListsReport,
    ingest=_ingest,
    needs_firms=False,
    request_model=ListsRequest,
)
