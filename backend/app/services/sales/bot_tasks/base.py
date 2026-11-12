"""Zadanie bota researchu (Grok Bot): jeden rodzaj biegu = jeden ``BotTask``.

Rodzaj mówi botowi, co ma zrobić (``task_text``), w jakim kształcie odesłać raport
(``report_format``), czym ten raport sprawdzić (``report_model``) i co z nim zrobić
w NEXUSIE (``ingest``). Nowy rodzaj to nowy moduł w tym pakiecie i wpis w
``REGISTRY`` (``__init__.py``): bez migracji, bo ``sales_signal_runs.kind`` zna już
rodzaje z 0684, i bez zmiany rutyny bota, bo polecenie v2 wykonuje to, co przyszło
w ``task``.

Zasady dla każdego rodzaju:

* **Do bota idą tylko nazwy i domeny firm** (``firms``) oraz pola, które rodzaj
  sam wkłada do ``request`` (``request_model``). Każde pole ``request`` ma w module
  rodzaju uzasadnienie, po co bot go potrzebuje; komputery bota stoją w USA.
  Tekst pytania od handlowca przejdzie przed wysyłką przez filtr danych osobowych.
* **Raport to dane niezaufane:** ``extra="forbid"``, limity długości i liczby
  pozycji, linki tylko http(s) (``SourceUrl``), firma tylko z listy biegu.
* **Wynik do decyzji handlowca** idzie do ``sales_bot_results`` (``save_results``),
  nie od razu na kartę firmy. Przyjęcie (``accept``) jest per rodzaj; domyślnie
  rodzaj go nie ma i trasa odpowiada 409.
* **Podsumowanie ``ingest`` i logi to same liczby:** repo i logi Actions są publiczne.

Reguły: ``docs/claude/sprzedaz/sygnaly-grok-bot.md`` („Zadania bota”).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Awaitable, Callable, Optional

from pydantic import AfterValidator, BaseModel
from sqlalchemy import literal_column
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesBotResult, SalesSignalRun

# Te same pomocniki co w raporcie sygnałów: jedna reguła linków i czyszczenia tekstu.
from app.services.sales.signals import _clean, _required_text, _required_url

#: Link źródła: tylko http(s), goła domena dostaje ``https://``, najwyżej 1000 znaków.
SourceUrl = Annotated[str, AfterValidator(_required_url)]
#: Tekst na ekran bez znaków sterujących; pusty po czyszczeniu to 422, nie 500.
RequiredText = Annotated[str, AfterValidator(_required_text)]
CleanText = Annotated[str, AfterValidator(_clean)]

NO_ACCEPT_DETAIL = "Ten rodzaj nie ma jeszcze akcji."
MAX_FINGERPRINT = 200


@dataclass(frozen=True)
class TaskContext:
    """Co rodzaj widzi, pisząc polecenie: firmy z biegu i zlecenie po walidacji."""

    firms: tuple[dict[str, Any], ...]
    request: dict[str, Any]


class AcceptRefused(Exception):
    """Wyniku nie da się przyjąć; trasa zamienia to na 409 z tym komunikatem."""


async def refuse_accept(
    db: AsyncSession,
    result: SalesBotResult,
    user_id: int,
    now: datetime,
    choice: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    raise AcceptRefused(NO_ACCEPT_DETAIL)


def numbers_only(summary: dict[str, Any]) -> dict[str, Any]:
    """Odpowiedź dla bota: same liczby z podsumowania, bez nazw firm."""

    out: dict[str, Any] = {}
    for key, value in summary.items():
        if isinstance(value, (int, float)):  # także bool
            out[key] = value
        elif isinstance(value, dict):
            nested = numbers_only(value)
            if nested:
                out[key] = nested
    return out


@dataclass(frozen=True)
class BotTask:
    kind: str
    #: Polecenie dla bota po polsku; trafia do ``task`` w treści webhooka.
    task_text: Callable[[SalesSignalRun, TaskContext], str]
    #: Zwięzły przykład raportu; bot odsyła treść w tym kształcie i nic więcej.
    report_format: Callable[[], dict[str, Any]]
    #: Walidacja raportu (``extra="forbid"``, limity, ``SourceUrl``).
    report_model: type[BaseModel]
    #: Zapis raportu; zwraca podsumowanie do ``sales_signal_runs.report``.
    ingest: Callable[
        [AsyncSession, SalesSignalRun, Any, datetime], Awaitable[dict[str, Any]]
    ]
    #: Bieg bez firm (np. pytanie, szukanie nowych centrów) ma ``False``.
    needs_firms: bool = True
    #: Pola zlecenia dla bota; bez modelu rodzaj nie przyjmuje żadnych.
    request_model: Optional[type[BaseModel]] = None
    #: Powody odrzuceń leadów i znane linki (``rejected``, ``seen_urls``).
    lead_feedback: bool = False
    #: Odpowiedź trasy dla bota z podsumowania ``ingest``.
    reply: Callable[[dict[str, Any]], dict[str, Any]] = numbers_only
    #: Przyjęcie wyniku z ``sales_bot_results``; domyślnie 409. Ostatni argument
    #: to wybór handlowca z treści żądania (``fields``, ``reject``), może być pusty.
    accept: Callable[
        [AsyncSession, SalesBotResult, int, datetime, Optional[dict[str, Any]]],
        Awaitable[dict[str, Any]],
    ] = refuse_accept

    def validate_request(self, request: Optional[dict[str, Any]]) -> dict[str, Any]:
        """Zlecenie po walidacji; rodzaj bez ``request_model`` przyjmuje tylko puste."""

        if self.request_model is None:
            if request:
                raise ValueError("Ten rodzaj biegu nie przyjmuje pól zlecenia.")
            return {}
        model = self.request_model.model_validate(request or {})
        return model.model_dump(mode="json", exclude_none=True)


def mark_received(run: SalesSignalRun, summary: dict[str, Any], now: datetime) -> None:
    run.status = "received"
    run.received_at = now
    run.token_hash = None
    run.report = summary


def result_fingerprint(kind: str, *parts: object) -> str:
    """Odcisk wyniku: ten sam wynik z kolejnego biegu nie tworzy drugiego wiersza."""

    raw = "|".join(str(part).lower() for part in parts)
    return f"{kind}|{hashlib.sha256(raw.encode()).hexdigest()[:48]}"[:MAX_FINGERPRINT]


async def save_results(
    db: AsyncSession, run: SalesSignalRun, rows: list[dict[str, Any]], now: datetime
) -> int:
    """Zapisz wyniki do decyzji; zwraca liczbę nowych.

    Wiersz: ``company_id`` (albo ``None``), ``payload``, ``fingerprint`` (albo
    ``None``). Ponowny wynik odświeża treść tylko, gdy nikt jeszcze o nim nie
    zdecydował: przyjęcie ani odrzucenie handlowca nie wraca do ``new``.
    """

    new = 0
    for row in rows:
        statement = insert(SalesBotResult).values(
            run_id=run.id,
            kind=run.kind,
            company_id=row.get("company_id"),
            payload=row.get("payload") or {},
            fingerprint=row.get("fingerprint"),
            status="new",
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_sales_bot_results_fingerprint",
            set_={
                "run_id": statement.excluded.run_id,
                "payload": statement.excluded.payload,
                "updated_at": now,
            },
            where=SalesBotResult.status == "new",
        ).returning(literal_column("(xmax = 0)"))
        # Konflikt z wynikiem po decyzji nic nie zwraca; ``xmax = 0`` tylko przy wstawieniu.
        inserted = (await db.execute(statement)).scalar_one_or_none()
        new += int(bool(inserted))
    return new
