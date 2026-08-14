"""Linie konsultantów zamówienia wielo-konsultantowego: budżet MD i jego zużycie.

Linia = zwykłe ``ClientOrder`` wpięte w ``ClientOrderGroup``, więc niesie już
kontrakt, kandydata, daty i status. Ten moduł dokłada to, czego wcześniej nie
było: budżet MD, jego topnienie z miesięcznych raportów i zamianę kontraktora.

Trzy reguły, na których stoi cała reszta:

1. **``md_remaining`` jest WYLICZANE, nie modyfikowane przyrostowo.**
   ``md_total - Σ konsumpcji + md_manual_adjustment``, przeliczane od zera przy
   każdej zmianie. To jest mechanizm idempotencji importu: powtórka miesiąca
   nadpisuje wiersz konsumpcji i przelicza pozostałość, zamiast odjąć MD drugi
   raz. Odejmowanie „na bieżąco" wymagałoby pamiętania, co już odjęto — czyli
   i tak tych samych wierszy, tylko z ryzykiem rozjazdu.

2. **Dopasowanie po nazwisku nigdy nie zgaduje.** Arkusz z Finansów nie ma
   numeru zamówienia. Jedno trafienie → zastosuj; zero → „brak aktywnego
   zamówienia"; więcej niż jedno → „wymaga przypisania" i czeka na człowieka.
   Automatyczny wybór „pierwszej lepszej" linii odjąłby MD nie temu klientowi
   i wyszedłby dopiero na fakturze.

3. **Zamiana kontraktora działa od dnia zamiany w przód.** Przelicza wyłącznie
   MD POZOSTAŁE; MD zaraportowane wcześniej rozlicza się stawką poprzednika,
   więc wpisy konsumpcji sprzed daty zamiany zostają nietknięte.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import Candidate
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup, ClientOrderGroupEvent
from app.models.contract import Contract
from app.models.md_consumption import (
    CONSUMPTION_SOURCE_IMPORT,
    ClientOrderMdConsumption,
)
from app.services.candidate_identity_quarantine import normalize_person_name_part
from app.services.multi_consultant_orders import (
    format_md,
    is_multi_consultant_client,
    quantize_md,
)

ZERO = Decimal("0")


# ── Miesiąc raportu ─────────────────────────────────────────────────────────


def month_bounds(period_month: str) -> tuple[date, date]:
    """``'2026-07'`` → (1 lipca, 31 lipca). Rzuca ``ValueError`` na śmieciach."""
    try:
        year_s, month_s = period_month.split("-")
        year, month = int(year_s), int(month_s)
        first = date(year, month, 1)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Miesiąc musi być w formacie RRRR-MM (np. 2026-07)") from exc
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first, last


# ── Dopasowanie po imieniu i nazwisku ───────────────────────────────────────


def name_tokens(full_name: str | None) -> frozenset[str]:
    """Nazwisko → zbiór znormalizowanych tokenów.

    Zbiór, a nie lista, bo arkusze zapisują ludzi raz jako „Jan Kowalski", raz
    jako „Kowalski Jan" — a to ta sama osoba. Normalizacja tokenów zdejmuje
    diakrytyki i wielkość liter (reużyta z modułu tożsamości kandydata, więc
    „Michał" i „Michal" nie rozjeżdżają się tutaj inaczej niż tam).
    """
    if not full_name:
        return frozenset()
    tokens = {
        normalized
        for part in str(full_name).split()
        if (normalized := normalize_person_name_part(part))
    }
    return frozenset(tokens)


def candidate_name_tokens(candidate: Candidate | None) -> frozenset[str]:
    if candidate is None:
        return frozenset()
    return name_tokens(f"{candidate.name or ''} {candidate.lastname or ''}")


# ── Odczyt linii ────────────────────────────────────────────────────────────


def _line_query():
    """Linie MD z kompletem relacji potrzebnych do prezentacji.

    ``selectinload`` na kontrakcie i kandydacie jest OBOWIĄZKOWY: w async
    SQLAlchemy leniwe doczytanie relacji leci ``MissingGreenlet`` — 500 bez
    nagłówków CORS, czyli w przeglądarce „Network Error" bez żadnej wskazówki.
    """
    return (
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
            selectinload(ClientOrder.md_consumptions),
            selectinload(ClientOrder.predecessor)
            .selectinload(ClientOrder.contract)
            .selectinload(Contract.candidate),
        )
        .where(ClientOrder.order_group_id.isnot(None))
    )


async def lines_for_group(db: AsyncSession, group_id: int) -> list[ClientOrder]:
    result = await db.execute(
        _line_query()
        .where(ClientOrder.order_group_id == group_id)
        .order_by(ClientOrder.start_date.asc().nullsfirst(), ClientOrder.id.asc())
    )
    return list(result.scalars())


@dataclass(frozen=True)
class LineMatch:
    """Kandydat na dopasowanie wiersza importu."""

    order: ClientOrder
    group: ClientOrderGroup
    consultant_name: str


async def active_md_lines(db: AsyncSession, period_month: str) -> list[LineMatch]:
    """Wszystkie AKTYWNE linie MD obowiązujące w danym miesiącu.

    Linia obowiązuje w miesiącu, jeśli jej okres zachodzi na ten miesiąc
    choćby jednym dniem — miesiąc rozliczeniowy dzieli się między poprzednika
    i następcę dokładnie w miesiącu zamiany kontraktora, więc porównanie
    z jednym dniem (np. pierwszym) gubiłoby jedną ze stron.

    Filtr po liście klientów jest tutaj celowo, nie tylko w widoku: klient
    zdjęty z ``MULTI_CONSULTANT_ORDER_CLIENT_IDS`` przestaje pokazywać te
    linie w interfejsie, więc import nie może dalej po cichu odejmować im MD —
    powstałby stan niewidoczny i niemożliwy do poprawienia z aplikacji.
    """
    first, last = month_bounds(period_month)
    result = await db.execute(
        _line_query()
        .options(selectinload(ClientOrder.order_group))
        .where(
            ClientOrder.md_total.isnot(None),
            ClientOrder.status == ClientOrderStatus.active,
            (ClientOrder.start_date.is_(None)) | (ClientOrder.start_date <= last),
            (ClientOrder.end_date.is_(None)) | (ClientOrder.end_date >= first),
        )
    )
    matches: list[LineMatch] = []
    for order in result.scalars():
        group = order.order_group
        if group is None or not is_multi_consultant_client(order.client_id):
            continue
        candidate = order.contract.candidate if order.contract else None
        display = (
            f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            if candidate
            else ""
        )
        matches.append(LineMatch(order=order, group=group, consultant_name=display))
    return matches


def match_by_name(
    candidates: Iterable[LineMatch], reported_name: str
) -> list[LineMatch]:
    """Linie, których konsultant odpowiada nazwisku z arkusza."""
    wanted = name_tokens(reported_name)
    if not wanted:
        return []
    return [m for m in candidates if name_tokens(m.consultant_name) == wanted]


# ── Budżet MD ───────────────────────────────────────────────────────────────


async def consumed_md(db: AsyncSession, order_id: int) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(ClientOrderMdConsumption.md_reported), 0)).where(
            ClientOrderMdConsumption.order_id == order_id
        )
    )
    return Decimal(str(total or 0))


async def recompute_remaining(db: AsyncSession, order: ClientOrder) -> Decimal:
    """Przelicz ``md_remaining`` od zera i zapisz na linii.

    Jedyny writer tego pola. Wartość może zejść do zera i poniżej —
    przekroczony budżet jest faktem handlowym, więc nie jest tu ścinany;
    sygnalizuje go interfejs kolorem.
    """
    if order.md_total is None:
        order.md_remaining = None
        return ZERO
    consumed = await consumed_md(db, order.id)
    adjustment = Decimal(str(order.md_manual_adjustment or 0))
    remaining = quantize_md(Decimal(str(order.md_total)) - consumed + adjustment)
    order.md_remaining = remaining
    return remaining


async def upsert_consumption(
    db: AsyncSession,
    *,
    order: ClientOrder,
    period_month: str,
    md_reported: Decimal,
    source: str = CONSUMPTION_SOURCE_IMPORT,
    import_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> tuple[ClientOrderMdConsumption, Decimal, Decimal]:
    """Zapisz zużycie za miesiąc i przelicz pozostałość.

    Zwraca ``(wiersz, poprzednie_md, nowa_pozostałość)``. Nadpisanie zamiast
    dodania nowego wiersza to właśnie to, co czyni powtórny import tego samego
    miesiąca bezpiecznym (UNIQUE ``(order_id, period_month)`` pilnuje tego
    także wtedy, gdy dwa importy trafią równolegle).
    """
    month_bounds(period_month)  # walidacja kształtu, zanim cokolwiek zapiszemy
    value = quantize_md(md_reported)

    existing = await db.scalar(
        select(ClientOrderMdConsumption).where(
            ClientOrderMdConsumption.order_id == order.id,
            ClientOrderMdConsumption.period_month == period_month,
        )
    )
    previous = Decimal(str(existing.md_reported)) if existing else ZERO
    if existing is None:
        existing = ClientOrderMdConsumption(
            order_id=order.id,
            period_month=period_month,
            md_reported=value,
            source=source,
            import_id=import_id,
            created_by_user_id=user_id,
        )
        db.add(existing)
    else:
        existing.md_reported = value
        existing.source = source
        existing.import_id = import_id
        existing.created_by_user_id = user_id
    await db.flush()

    remaining = await recompute_remaining(db, order)
    return existing, previous, remaining


# ── Historia ────────────────────────────────────────────────────────────────


def record_event(
    db: AsyncSession,
    *,
    group_id: int,
    event_type: str,
    description: str,
    order_id: Optional[int] = None,
    payload: Optional[dict] = None,
    user_id: Optional[int] = None,
) -> ClientOrderGroupEvent:
    event = ClientOrderGroupEvent(
        group_id=group_id,
        order_id=order_id,
        event_type=event_type,
        description=description,
        payload=payload,
        created_by_user_id=user_id,
    )
    db.add(event)
    return event


def consultant_display_name(order: ClientOrder) -> str:
    candidate = order.contract.candidate if order.contract else None
    if candidate is None:
        return "—"
    return f"{candidate.name or ''} {candidate.lastname or ''}".strip() or "—"


def describe_import(
    order: ClientOrder, period_month: str, md_reported: Decimal, previous: Decimal
) -> str:
    who = consultant_display_name(order)
    if previous and previous != md_reported:
        return (
            f"Import MD za {period_month}: {who} — {format_md(md_reported)} MD "
            f"(nadpisano wcześniejsze {format_md(previous)} MD). "
            f"Pozostało {format_md(order.md_remaining)} MD."
        )
    return (
        f"Import MD za {period_month}: {who} — {format_md(md_reported)} MD. "
        f"Pozostało {format_md(order.md_remaining)} MD."
    )
