"""Grok Zbieracz (``collect``): polecenie, raport surowych pozycji, zapis.

Do Zbieracza idą tylko: profil tematów (``PROFILE_TOPICS``), lista źródeł
i data ``since``. Żadnych danych firmy (kontraktów, płac, faktur, nazw klientów
i osób): komputery bota stoją w USA. Zbieracz niczego nie ocenia, odsyła surowe
pozycje: źródło, tytuł, link, data, numer aktu albo druku, etap, krótki cytat.

Raport to dane niezaufane: ``extra="forbid"``, limity, linki tylko http(s),
numer aktu i druku w stałym wzorze. Zapis pozycji jako ``pending``; numery
sprawdza potem bramka (``gate.verify_pending``) poza żądaniem bota.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.law_radar import LawRadarItem, LawRadarRun
from app.services.law_radar import gate, schema
from app.services.sales.bot_tasks.base import CleanText, RequiredText, SourceUrl

logger = logging.getLogger(__name__)

KIND = "collect"
MAX_ITEMS = 200
DEFAULT_LOOKBACK_DAYS = 3

#: Źródła Zbieracza: klucz raportu → co bot ma przeczytać.
SOURCE_GUIDE: tuple[tuple[str, str], ...] = (
    (
        "sejm",
        "API Sejmu: Dziennik Ustaw i Monitor Polski (ELI, api.sejm.gov.pl/eli/acts/DU/… "
        "i /MP/…) oraz procesy legislacyjne X kadencji (api.sejm.gov.pl/sejm/term10/processes)",
    ),
    (
        "rcl",
        "Rządowe Centrum Legislacji: projekty ustaw i rozporządzeń (legislacja.gov.pl)",
    ),
    ("zus", "ZUS: komunikaty, wyjaśnienia, zmiany składek (zus.pl)"),
    (
        "mf",
        "Ministerstwo Finansów: podatki.gov.pl, KSeF (ksef.podatki.gov.pl), objaśnienia "
        "podatkowe, komunikaty o MPP i JPK",
    ),
    ("eureka", "Interpretacje ogólne i indywidualne (eureka.mf.gov.pl)"),
    ("pip", "Państwowa Inspekcja Pracy: stanowiska i komunikaty (pip.gov.pl)"),
    ("uodo", "UODO: decyzje, wytyczne i komunikaty (uodo.gov.pl)"),
    ("nsa", "Orzeczenia NSA i WSA (orzeczenia.nsa.gov.pl)"),
    ("eurlex", "EUR-Lex: rozporządzenia i dyrektywy UE (eur-lex.europa.eu)"),
    ("advisor", "Alerty doradców podatkowych, kancelarii i firm audytorskich"),
    ("x", "Serwis X: konta ministerstw, ZUS, KAS, UODO, PIP i doradców"),
    (
        "lex",
        "LEX (sip.lex.pl): zaloguj się do LEX (sip.lex.pl) loginem zapisanym w Vault; "
        "z LEX odsyłasz tylko tytuł, link i cytat do 500 znaków",
    ),
    (
        "gofin",
        "Gofin (www.gofin.pl, Serwis Głównego Księgowego, Gazeta Podatkowa): zaloguj się "
        "loginem zapisanym w Vault; z Gofina odsyłasz tylko tytuł, link i cytat do 500 znaków",
    ),
    ("other", "Inne oficjalne źródło, gdy żadne z powyższych nie pasuje"),
)

#: Profil tematów firmy (bez danych firmy): to, czego Zbieracz szuka.
PROFILE_TOPICS: tuple[str, ...] = (
    "Estoński CIT (ryczałt od dochodów spółek) i ukryte zyski",
    "VAT, KSeF, mechanizm podzielonej płatności (MPP), JPK_V7 i JPK_VAT",
    "CIT, JPK_KR_PD i inne struktury JPK dla ksiąg",
    "Płace: ZUS, PIT, płaca minimalna, PPK, zwolnienia i ulgi",
    "Kodeks pracy, kontrole PIP, umowy B2B a stosunek pracy, staż pracy",
    "Jawność wynagrodzeń, rekrutacja, AI Act w rekrutacji",
    "Umowy B2B z kontraktorami, DORA, RODO, KRS, PKD, e-Doręczenia",
)

SourceKey = Literal[schema.SOURCES]  # type: ignore[valid-type]


def _optional_text(value: Optional[str]) -> Optional[str]:
    return value or None


class CollectItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: SourceKey
    title: RequiredText = Field(min_length=1, max_length=schema.ITEM_TITLE_MAX)
    url: SourceUrl = Field(min_length=1, max_length=schema.URL_MAX)
    published: date
    act_ref: Optional[str] = Field(default=None, pattern=schema.ACT_REF_PATTERN)
    print_no: Optional[str] = Field(default=None, pattern=schema.PRINT_NO_PATTERN)
    stage: Optional[CleanText] = Field(default=None, max_length=schema.STAGE_TEXT_MAX)
    quote: Optional[CleanText] = Field(default=None, max_length=schema.QUOTE_MAX)

    @field_validator("stage", "quote")
    @classmethod
    def _empty_is_none(cls, value: Optional[str]) -> Optional[str]:
        return _optional_text(value)

    @field_validator("url")
    @classmethod
    def _plain_host(cls, value: str) -> str:
        """Bez ``\\`` i danych logowania w adresie: host musi być tym, co zobaczy
        przeglądarka (inaczej obca strona udawałaby urzędową)."""

        if not gate.host_of(value):
            raise ValueError("Adres źródła ma nieprawidłowy host.")
        return value


class CollectReport(BaseModel):
    """Jeden raport na bieg: surowe pozycje, bez oceny."""

    model_config = ConfigDict(extra="forbid")

    items: list[CollectItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    #: LEX poprosił o kod 2FA albo weryfikację urządzenia i bot go pominął.
    lex_skipped: bool = False
    #: Gofin nie wpuścił bota (brak loginu w Vault, kod, blokada) i bot go pominął.
    gofin_skipped: bool = False


def build_request(since: date) -> dict[str, Any]:
    return {
        "since": since.isoformat(),
        "topics": list(PROFILE_TOPICS),
        "sources": [key for key, _ in SOURCE_GUIDE],
        "max_items": MAX_ITEMS,
    }


def task_text(request: dict[str, Any]) -> str:
    since = request.get("since", "")
    sources = "\n".join(f"- {key}: {text}" for key, text in SOURCE_GUIDE)
    topics = "\n".join(f"- {topic}" for topic in request.get("topics", PROFILE_TOPICS))
    return (
        "Jesteś Zbieraczem radaru przepisów. Przejrzyj źródła i zbierz zmiany w prawie "
        f"opublikowane albo zmienione od {since} (włącznie), które dotyczą tematów z listy.\n\n"
        f"Źródła (klucz: co czytać):\n{sources}\n\n"
        f"Tematy:\n{topics}\n\n"
        "Zasady:\n"
        "- Odsyłasz surowe pozycje, bez oceny i bez wniosków dla firmy.\n"
        "- Każdą pozycję potwierdź otwarciem źródła: podaj adres strony (url) i datę "
        "publikacji albo zmiany (published).\n"
        "- Tylko pozycje opublikowane albo zmienione od daty since.\n"
        "- Numer aktu (act_ref) podaj tylko, gdy widzisz go w źródle, w postaci "
        "DU/RRRR/POZ albo MP/RRRR/POZ (np. DU/2026/473). Numer druku Sejmu (print_no) "
        "tylko cyframi. Nigdy nie zgaduj numerów: bez numeru w źródle zostaw pole puste.\n"
        "- stage: etap tak, jak podaje źródło (np. „projekt”, „I czytanie”, „Senat”, "
        "„opublikowano”). quote: krótki cytat ze źródła, najwyżej 500 znaków.\n"
        "- Z LEX-u odsyłasz tylko tytuł, link i cytat do 500 znaków (source = lex), "
        "bez kopiowania komentarzy i opracowań.\n"
        "- Gdy LEX poprosi o kod logowania albo weryfikację urządzenia, nie czekaj na "
        "człowieka: pomiń LEX, przejrzyj pozostałe źródła i ustaw lex_skipped = true.\n"
        "- Z Gofina odsyłasz tylko tytuł, link i cytat do 500 znaków (source = gofin), "
        "bez kopiowania artykułów, porad i odpowiedzi ekspertów. Gdy Gofin nie wpuści "
        "(brak loginu w Vault, kod, weryfikacja albo blokada), pomiń go i ustaw "
        "gofin_skipped = true.\n"
        "- Nie zapisuj nazwisk osób prywatnych ani danych kontaktowych.\n"
        f"- Najwyżej {request.get('max_items', MAX_ITEMS)} pozycji. Ta sama zmiana "
        "z kilku źródeł może być kilkoma pozycjami.\n"
        "- Gdy nic nie znajdziesz, odeślij pustą listę items."
    )


def report_format() -> dict[str, Any]:
    return {
        "items": [
            {
                "source": "sejm",
                "title": "Ustawa z dnia 11 marca 2026 r. o zmianie ustawy o Państwowej Inspekcji Pracy oraz niektórych innych ustaw",
                "url": "https://api.sejm.gov.pl/eli/acts/DU/2026/473",
                "published": "2026-04-08",
                "act_ref": "DU/2026/473",
                "print_no": None,
                "stage": "opublikowano",
                "quote": "Krótki cytat ze źródła, najwyżej 500 znaków.",
            }
        ],
        "lex_skipped": False,
        "gofin_skipped": False,
    }


def plan_items(report: CollectReport) -> tuple[list[dict[str, Any]], int]:
    """Wiersze do zapisu (bez powtórek w raporcie) i liczba powtórek."""

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    for item in report.items:
        key = gate.fingerprint(item.url, item.act_ref, item.print_no, item.published)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        rows.append(
            {
                "fingerprint": key,
                "source": item.source,
                "klass": gate.classify(item.source, item.url),
                "gate": "pending",
                "title": item.title,
                "url": item.url,
                "published": item.published,
                "act_ref": item.act_ref,
                "print_no": item.print_no,
                "stage": item.stage,
                "quote": item.quote,
            }
        )
    return rows, duplicates


async def ingest(
    db: AsyncSession, run: LawRadarRun, report: CollectReport, *, now: datetime
) -> dict[str, Any]:
    """Zapisz nowe pozycje jako ``pending``; znane z wcześniejszych biegów pomija."""

    from app.services.law_radar.runs import mark_received

    rows, duplicates = plan_items(report)
    new = 0
    by_class = {klass: 0 for klass in schema.CLASSES}
    for values in rows:
        statement = (
            insert(LawRadarItem)
            .values(**values, run_id=run.id)
            .on_conflict_do_nothing(constraint="uq_law_radar_items_fingerprint")
            .returning(LawRadarItem.id)
        )
        if (await db.execute(statement)).scalar_one_or_none() is not None:
            new += 1
            by_class[values["klass"]] += 1
    summary = {
        "items_in": len(report.items),
        "new": new,
        "known": len(rows) - new,
        "duplicates": duplicates,
        "by_class": by_class,
        "lex_skipped": report.lex_skipped,
        "gofin_skipped": report.gofin_skipped,
    }
    mark_received(run, summary, now)
    logger.info(
        "law_radar run=%s collect received items=%d new=%d known=%d duplicates=%d",
        run.id,
        len(report.items),
        new,
        len(rows) - new,
        duplicates,
    )
    return summary
