"""Treść korekt z KSeF i biała lista VAT dla faktur kontraktorów (rozliczenia E4).

Faktury kontraktorów zapisujemy z samych metadanych (``contractor_invoices``),
a kontrole łańcucha korekt (``invoice_chain``) potrzebują pozycji ze stanem
przed i po oraz danych faktury korygowanej — te są tylko w XML-u FA. Dlatego
pobieramy XML **wyłącznie** dla korekt i faktur, które one korygują (zwykle
kilka w miesiącu), po pobraniach Płac w tym samym przebiegu KSeF i najwyżej
``MAX_DOWNLOADS`` na przebieg (produkcja: 64 pobrania na godzinę na token
spółki, Płace biorą do 40). Chwilowa niedostępność = próba w kolejnym
przebiegu (do ``MAX_ATTEMPTS``), 429 przerywa przebieg jak u Płac.

Pobrana korekta dziedziczy kontrakt i miesiąc faktury, którą (pośrednio)
koryguje: korekta z listopada do faktury za październik należy do października.

Biała lista: status sprzedawcy na dzień wystawienia przez ``hr/white_list``
(tryb ``WHITE_LIST_MODE``, pamięć dnia, ślad zapytań). Wynik zapisujemy przy
fakturze, więc ten sam NIP i dzień nie idzie do MF drugi raz; wykaz ma limit
100 zapytań dziennie, z którego bierzemy najwyżej ``WHITELIST_DAILY_SHARE``
(reszta zostaje dla Płac). Brak odpowiedzi to ``state='error'`` z kodem
i „nie sprawdzono” na karcie, nigdy blokada.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_settlement import ClientContractorInvoice
from app.services.client_settlements import invoice_chain
from app.services.hr import white_list
from app.services.hr.ksef import fa
from app.services.hr.ksef.client import KsefApiError

logger = logging.getLogger(__name__)

MAX_DOWNLOADS = 10
MAX_ATTEMPTS = 24
#: Korekty starsze niż pół roku nie wracają na karty rozliczeń.
LOOKBACK = timedelta(days=200)
TRANSIENT = frozenset({"not_ready", "unavailable", "rate_limited"})
WHITELIST_PER_RUN = 20
WHITELIST_DAILY_SHARE = 60

REJECTED = "rejected"


def _waiting(row: ClientContractorInvoice) -> bool:
    return row.details is None or row.details.get("state") == "pending"


async def _recent(db: AsyncSession, today: date) -> list[ClientContractorInvoice]:
    rows = await db.scalars(
        select(ClientContractorInvoice)
        .where(
            ClientContractorInvoice.nip_state != REJECTED,
            or_(
                ClientContractorInvoice.issue_date.is_(None),
                ClientContractorInvoice.issue_date >= today - LOOKBACK,
            ),
        )
        .order_by(ClientContractorInvoice.issue_date, ClientContractorInvoice.id)
    )
    return list(rows)


def to_fetch(rows: list[ClientContractorInvoice]) -> list[ClientContractorInvoice]:
    """Korekty bez treści, potem faktury, które pobrane korekty wskazują."""

    by_ksef = {r.ksef_number: r for r in rows}
    wanted = [r for r in rows if invoice_chain.is_correction(r) and _waiting(r)]
    for row in rows:
        if (
            not invoice_chain.is_correction(row)
            or (row.details or {}).get("state") != "ok"
        ):
            continue
        for ref in row.details.get("corrected") or []:
            parent = by_ksef.get(str((ref or {}).get("ksef_number") or ""))
            if parent is not None and _waiting(parent) and parent not in wanted:
                wanted.append(parent)
    return wanted


def details_from(parsed: fa.ParsedInvoice) -> dict[str, Any]:
    return {
        "state": "ok",
        "form": parsed.form,
        "type": parsed.invoice_type,
        "items": parsed.items,
        "corrected": list(parsed.corrected),
        "reason": parsed.correction_reason,
        # Rachunki z „Platnosc/RachunekBankowy” — podpowiedź do przelewu (E3).
        "accounts": list(parsed.accounts),
    }


async def _download(source: Any, row: ClientContractorInvoice) -> None:
    attempts = int((row.details or {}).get("attempts") or 0) + 1
    try:
        xml = await source.download_invoice(row.ksef_number)
    except KsefApiError as exc:
        if exc.category in TRANSIENT and attempts < MAX_ATTEMPTS:
            row.details = {"state": "pending", "attempts": attempts}
            if exc.category == "rate_limited":
                raise
            return
        row.details = {"state": "failed", "error": f"ksef:{exc.category}"}
        return
    try:
        parsed = fa.parse_invoice(xml)
    except fa.InvoiceParseError as exc:
        row.details = {"state": "failed", "error": f"parse:{exc.code}"}
        return
    if parsed.seller_nip != row.seller_nip:
        row.details = {"state": "failed", "error": "seller_mismatch"}
        return
    row.details = details_from(parsed)


def follow_parents(rows: list[ClientContractorInvoice]) -> int:
    """Korekta przechodzi do kontraktu i miesiąca faktury, którą koryguje."""

    by_ksef = {r.ksef_number: r for r in rows}
    moved = 0
    for row in rows:
        if (
            not invoice_chain.is_correction(row)
            or (row.details or {}).get("state") != "ok"
        ):
            continue
        top, seen = row, {row.id}
        while True:
            parent = invoice_chain.parent_of(top, by_ksef, rows)
            if (
                parent is None
                or parent.id in seen
                or parent.seller_nip != row.seller_nip
            ):
                break
            top, seen = parent, seen | {parent.id}
        if top is row or top.contract_id is None:
            continue
        if (row.contract_id, row.period_month) != (top.contract_id, top.period_month):
            row.contract_id, row.period_month = top.contract_id, top.period_month
            moved += 1
    return moved


async def fetch_details(
    db: AsyncSession, source: Any, *, today: date, budget: int
) -> dict[str, int]:
    """Pobiera XML korekt i faktur korygowanych; zwraca liczniki (``downloads``)."""

    counts = {"downloads": 0, "moved": 0}
    rows = await _recent(db, today)
    limit = min(budget, MAX_DOWNLOADS)
    # Dwa kroki: korekta wskazuje fakturę korygowaną dopiero po pobraniu.
    tried: set[int] = set()
    for _ in range(2):
        for row in to_fetch(rows):
            if counts["downloads"] >= limit:
                break
            if row.id in tried:
                continue
            tried.add(row.id)
            counts["downloads"] += 1
            await _download(source, row)
    counts["moved"] = follow_parents(rows)
    await db.flush()
    return counts


def _whitelist_waiting(row: ClientContractorInvoice) -> bool:
    return row.issue_date is not None and (
        row.vat_whitelist is None or row.vat_whitelist.get("state") != "ok"
    )


def _result(
    entry: Optional[white_list.WhiteListEntry], on_date: date
) -> dict[str, Any]:
    return {
        "state": "ok",
        "status": (entry.vat_status or "unknown") if entry else "absent",
        "on_date": on_date.isoformat(),
        "request_id": entry.request_id if entry else None,
    }


async def check_whitelist(
    db: AsyncSession, *, today: date, now: datetime
) -> dict[str, int]:
    """Status sprzedawców na białej liście VAT dla faktur bez wyniku."""

    counts = {"whitelist": 0, "whitelist_errors": 0}
    if white_list.current_mode() == "off":
        return counts
    rows = await _recent(db, today)
    known: dict[tuple[str, date], dict[str, Any]] = {
        (r.seller_nip, r.issue_date): r.vat_whitelist
        for r in rows
        if r.issue_date is not None and (r.vat_whitelist or {}).get("state") == "ok"
    }
    asked = 0
    for row in rows:
        if not _whitelist_waiting(row):
            continue
        key = (row.seller_nip, row.issue_date)
        if key in known:
            row.vat_whitelist = known[key]
            continue
        used = white_list.usage()["used"]["search"]
        if asked >= WHITELIST_PER_RUN or used >= WHITELIST_DAILY_SHARE:
            break
        asked += 1
        try:
            entry = await white_list.search(db, row.seller_nip, row.issue_date)
        except white_list.WhiteListError as exc:
            row.vat_whitelist = {
                "state": "error",
                "code": exc.code,
                "checked_at": now.isoformat(),
            }
            counts["whitelist_errors"] += 1
            if exc.code in {"unavailable", "quota_exceeded", "disabled"}:
                break
            continue
        known[key] = row.vat_whitelist = _result(entry, row.issue_date)
        counts["whitelist"] += 1
    await db.flush()
    return counts
