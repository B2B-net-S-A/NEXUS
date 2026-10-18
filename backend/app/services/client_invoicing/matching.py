"""Faktura z KSeF ↔ zamówienie klienta (E8): numer zamówienia, okres, kwota.

Kolejność, od najpewniejszego:

1. **klient** — NIP nabywcy → klient kanoniczny (``clients.nip``); brak albo
   ten sam NIP u dwóch klientów = „do przypisania”,
2. **okres** — miesiąc usługi z faktury (``period_*``),
3. **numer zamówienia** w treści faktury (zamówienia i umowy z
   ``WarunkiTransakcji``, opis dodatkowy, nazwy pozycji) — tylko numery
   zamówień TEGO klienta, całym słowem (``445`` nie trafia w ``4450``),
   numer z samych cyfr także bez zer wiodących, ``SAP 45…`` także bez
   prefiksu. Numer wiąże: faktura idzie do tego zamówienia, a różnica kwoty
   jest do sprawdzenia przez Finanse. Faktura na jedną osobę z zamówienia MD
   (kwota równa pozycji tej osoby) wiąże się z tą osobą,
4. **kwota** bez numeru — wyłącznie jednoznaczna: dokładnie jedno zamówienie
   (albo jedna osoba z zamówienia MD) z kwotą „do faktury” równą netto
   faktury co do grosza.

Wszystko inne zostaje Finansom z powodem (``REASON_LABELS``) — system nie
zgaduje. Korekta idzie za fakturą pierwotną (te same zamówienia). Ręczne
przypisanie Finansów nie jest nadpisywane przez kolejne przebiegi.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder
from app.models.client_order_group import ClientOrderGroup
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.services.client_invoicing import billing, clients
from app.services.client_invoicing.billing import BillingRow, OrderRef

MIN_NUMBER_LENGTH = 3
_DIGITS = re.compile(r"\d+")

REASON_LABELS: dict[str, str] = {
    "unknown_buyer": "NIP nabywcy nie należy do żadnego klienta w NEXUSIE.",
    "ambiguous_buyer": "Ten sam NIP ma kilku klientów — wskaż właściwego.",
    "no_period": "Faktura nie ma okresu usługi.",
    "no_orders": "Klient nie ma zamówień do zafakturowania w tym miesiącu.",
    "order_outside_period": "Numer zamówienia z faktury nie obejmuje tego miesiąca.",
    "currency_differs": "Waluta faktury inna niż waluta zamówienia.",
    "several_orders": "Faktura wymienia kilka zamówień, a kwota nie wskazuje jednego.",
    "amount_ambiguous": "Kwota pasuje do kilku zamówień — wybierz właściwe.",
    "amount_differs": "Bez numeru zamówienia, a kwota nie pasuje do żadnego zamówienia.",
    "expected_unknown": "Bez numeru zamówienia, a kwoty „do faktury” nie da się jeszcze policzyć.",
    "original_unmatched": "Korekta faktury, która czeka na przypisanie.",
    "original_missing": "Korekta faktury, której nie ma w NEXUSIE.",
    "order_removed": "Zamówienie, z którym była powiązana, zostało usunięte.",
    "reopened": "Przypisanie cofnięte — wskaż zamówienie.",
}
#: Powody, przy których kolejny przebieg próbuje dopasować jeszcze raz
#: (nowe zamówienie, import MD, dopisany NIP klienta).
RETRY_REASONS: frozenset[str] = frozenset(
    {
        "unknown_buyer",
        "no_orders",
        "order_outside_period",
        "amount_differs",
        "expected_unknown",
        "original_unmatched",
        "original_missing",
    }
)


@dataclass(frozen=True)
class Target:
    group_id: Optional[int] = None
    order_id: Optional[int] = None

    @property
    def key(self) -> str:
        return f"g{self.group_id}" if self.group_id is not None else f"o{self.order_id}"


@dataclass(frozen=True)
class Decision:
    targets: tuple[Target, ...] = ()
    method: Optional[str] = None
    reason: Optional[str] = None

    @property
    def matched(self) -> bool:
        return bool(self.targets)


def _row_target(row: BillingRow) -> Target:
    return Target(group_id=row.group_id, order_id=row.order_id)


def _pattern(value: str) -> re.Pattern[str]:
    return re.compile(
        r"(?<![0-9A-Za-z])" + re.escape(value) + r"(?![0-9A-Za-z])", re.IGNORECASE
    )


def numbers_found(texts: Iterable[str], refs: Sequence[OrderRef]) -> set[str]:
    """Klucze zamówień, których numer stoi w tekstach faktury całym słowem."""

    corpus = [text_ for text_ in texts if text_]
    digit_runs = {
        run.lstrip("0") or "0" for text_ in corpus for run in _DIGITS.findall(text_)
    }
    hits: set[str] = set()
    for ref in refs:
        for variant in ref.variants():
            value = variant.strip()
            if len(value) < MIN_NUMBER_LENGTH or not any(ch.isdigit() for ch in value):
                continue
            if value.isdigit():
                if (value.lstrip("0") or "0") in digit_runs:
                    hits.add(ref.key)
                    break
                continue
            pattern = _pattern(value)
            if any(pattern.search(text_) for text_ in corpus):
                hits.add(ref.key)
                break
    return hits


def decide(
    *,
    net: Decimal,
    currency: str,
    texts: Iterable[str],
    rows: Sequence[BillingRow],
    refs: Sequence[OrderRef],
) -> Decision:
    """Dopasowanie faktury do zamówień klienta w miesiącu (czysta funkcja)."""

    by_key = {row.key: row for row in rows}
    hits = numbers_found(texts, refs)
    if hits:
        in_period = [by_key[key] for key in sorted(hits) if key in by_key]
        if not in_period:
            return Decision(reason="order_outside_period")
        same = [row for row in in_period if row.currency == currency]
        if not same:
            return Decision(reason="currency_differs")
        if len(same) == 1:
            row = same[0]
            if row.expected_net != net and row.group_id is not None:
                person = [
                    line for line in row.lines if line.order_id and line.net == net
                ]
                if len(person) == 1:
                    return Decision(
                        (Target(order_id=person[0].order_id),), "order_number"
                    )
            return Decision((_row_target(row),), "order_number")
        expected = [row.expected_net for row in same]
        if (
            all(value is not None for value in expected)
            and sum(expected, Decimal("0")) == net
        ):
            return Decision(tuple(_row_target(row) for row in same), "order_number")
        equal = [row for row in same if row.expected_net == net]
        if len(equal) == 1:
            return Decision((_row_target(equal[0]),), "order_number")
        return Decision(reason="several_orders")

    candidates = [row for row in rows if row.currency == currency]
    if not candidates:
        return Decision(reason="no_orders" if not rows else "currency_differs")
    equal_rows = [row for row in candidates if row.expected_net == net]
    if len(equal_rows) == 1:
        return Decision((_row_target(equal_rows[0]),), "amount")
    if len(equal_rows) > 1:
        return Decision(reason="amount_ambiguous")
    equal_people = [
        line
        for row in candidates
        if row.group_id is not None
        for line in row.lines
        if line.order_id and line.net == net
    ]
    if len(equal_people) == 1:
        return Decision((Target(order_id=equal_people[0].order_id),), "amount")
    if len(equal_people) > 1:
        return Decision(reason="amount_ambiguous")
    if any(row.expected_net is None for row in candidates):
        return Decision(reason="expected_unknown")
    return Decision(reason="amount_differs")


def invoice_texts(invoice: ClientSalesInvoice) -> list[str]:
    texts = [str(value) for value in invoice.order_refs or [] if value]
    texts.extend(
        str(item.get("name") or "")
        for item in invoice.items or []
        if isinstance(item, dict) and not item.get("before_correction")
    )
    return texts


# ── Zapis ────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _replace_links(
    db: AsyncSession,
    invoice: ClientSalesInvoice,
    targets: Sequence[Target],
    period: tuple[int, int],
    actor_id: Optional[int],
) -> None:
    await db.execute(
        delete(ClientSalesInvoiceLink).where(
            ClientSalesInvoiceLink.invoice_id == invoice.id
        )
    )
    for target in targets:
        db.add(
            ClientSalesInvoiceLink(
                invoice_id=invoice.id,
                order_group_id=target.group_id,
                order_id=target.order_id,
                period_year=period[0],
                period_month=period[1],
                created_by=actor_id,
            )
        )
    await db.flush()


def _clear_difference(invoice: ClientSalesInvoice) -> None:
    invoice.difference_accepted_amount = None
    invoice.difference_reason = None
    invoice.difference_accepted_by = None
    invoice.difference_accepted_at = None


async def _follow_original(db: AsyncSession, invoice: ClientSalesInvoice) -> None:
    original = (
        await db.get(ClientSalesInvoice, invoice.corrects_invoice_id)
        if invoice.corrects_invoice_id
        else None
    )
    if original is None:
        invoice.match_status = "unmatched"
        invoice.match_method = None
        invoice.match_reason = "original_missing"
    elif original.match_status == "matched":
        invoice.match_status = "matched"
        invoice.match_method = "correction"
        invoice.match_reason = None
        invoice.client_id = invoice.client_id or original.client_id
    else:
        invoice.match_status = "unmatched"
        invoice.match_method = None
        invoice.match_reason = "original_unmatched"
    invoice.matched_at = _now() if invoice.match_status == "matched" else None


async def propagate_to_corrections(
    db: AsyncSession, original: ClientSalesInvoice
) -> int:
    """Korekty, które czekały na pierwotną, idą za jej przypisaniem."""

    corrections = list(
        await db.scalars(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.corrects_invoice_id == original.id,
                ClientSalesInvoice.match_method.is_distinct_from("manual"),
                ClientSalesInvoice.match_status != "ignored",
            )
        )
    )
    for correction in corrections:
        await _follow_original(db, correction)
    if corrections:
        await db.flush()
    return len(corrections)


async def auto_match(
    db: AsyncSession,
    invoice: ClientSalesInvoice,
    *,
    registry: Optional[clients.NipRegistry] = None,
) -> Decision:
    """Dopasowanie automatyczne; ręcznych i pominiętych nie rusza."""

    if invoice.match_status == "ignored" or invoice.match_method == "manual":
        return Decision(reason=invoice.match_reason)
    registry = registry or await clients.nip_registry(db)
    if invoice.client_id is None:
        client_id, reason = registry.resolve(invoice.buyer_nip)
        invoice.client_id = client_id
        if client_id is None:
            invoice.match_status = "unmatched"
            invoice.match_reason = reason
            await db.flush()
            return Decision(reason=reason)

    if invoice.invoice_kind == "correction":
        # Korekta idzie za pierwotną; bez pierwotnej w NEXUSIE czeka (różnica
        # kwoty sama nie wskazuje zamówienia) — Finanse mogą ją przypisać.
        await _follow_original(db, invoice)
        await db.flush()
        return Decision(method=invoice.match_method, reason=invoice.match_reason)
    if invoice.period_year is None:
        invoice.match_status = "unmatched"
        invoice.match_reason = "no_period"
        await db.flush()
        return Decision(reason="no_period")

    period = (int(invoice.period_year), int(invoice.period_month))
    members = await clients.family(db, [invoice.client_id])
    rows = await billing.billing_rows(
        db, year=period[0], month=period[1], client_ids=members
    )
    refs = await billing.order_refs(db, members)
    decision = decide(
        net=invoice.net_amount,
        currency=invoice.currency,
        texts=invoice_texts(invoice),
        rows=rows,
        refs=refs,
    )
    if decision.matched:
        await _replace_links(db, invoice, decision.targets, period, None)
        invoice.match_status = "matched"
        invoice.match_method = decision.method
        invoice.match_reason = None
        invoice.matched_by = None
        invoice.matched_at = _now()
        _clear_difference(invoice)
    else:
        invoice.match_status = "unmatched"
        invoice.match_method = None
        invoice.match_reason = decision.reason
    await db.flush()
    if decision.matched:
        await propagate_to_corrections(db, invoice)
    return decision


class MatchingError(ValueError):
    """Odmowa ręcznego przypisania — komunikat dla Finansów."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        self.status_code = status_code
        super().__init__(message)


async def _target_client(db: AsyncSession, target: Target) -> Optional[int]:
    if target.group_id is not None:
        return await db.scalar(
            select(ClientOrderGroup.client_id).where(
                ClientOrderGroup.id == target.group_id
            )
        )
    return await db.scalar(
        select(ClientOrder.client_id).where(ClientOrder.id == target.order_id)
    )


async def assign(
    db: AsyncSession,
    invoice: ClientSalesInvoice,
    *,
    targets: Sequence[Target],
    period: tuple[int, int],
    actor_id: int,
) -> None:
    """„Przypisz” — Finanse wskazują zamówienie (albo kilka) i miesiąc."""

    if not targets:
        raise MatchingError("Wskaż co najmniej jedno zamówienie.")
    if invoice.invoice_kind == "correction" and invoice.corrects_invoice_id:
        raise MatchingError(
            "Korekta idzie za fakturą pierwotną — przypisz fakturę pierwotną.", 409
        )
    owners = {await _target_client(db, target) for target in targets}
    if None in owners:
        raise MatchingError("Nie ma takiego zamówienia.", 404)
    allowed = (
        await clients.family(db, [invoice.client_id])
        if invoice.client_id is not None
        else None
    )
    if allowed is not None and not owners <= allowed:
        raise MatchingError("Zamówienie należy do innego klienta niż nabywca faktury.")
    if allowed is None:
        # Nabywca bez klienta w NEXUSIE: klienta wyznacza wskazane zamówienie.
        first = min(owner for owner in owners if owner is not None)
        if not owners <= await clients.family(db, [first]):
            raise MatchingError("Zamówienia należą do różnych klientów.")
        invoice.client_id = first
    await _replace_links(db, invoice, targets, period, actor_id)
    invoice.match_status = "matched"
    invoice.match_method = "manual"
    invoice.match_reason = None
    invoice.matched_by = actor_id
    invoice.matched_at = _now()
    invoice.ignore_reason = None
    _clear_difference(invoice)
    await db.flush()
    await propagate_to_corrections(db, invoice)


async def ignore(
    db: AsyncSession, invoice: ClientSalesInvoice, *, reason: str, actor_id: int
) -> None:
    """„Pomiń” — faktura spoza zamówień (np. sprzedaż sprzętu), z powodem."""

    note = " ".join((reason or "").split())
    if len(note) < 3:
        raise MatchingError("Podaj powód pominięcia (co najmniej 3 znaki).")
    await db.execute(
        delete(ClientSalesInvoiceLink).where(
            ClientSalesInvoiceLink.invoice_id == invoice.id
        )
    )
    invoice.match_status = "ignored"
    invoice.match_method = None
    invoice.match_reason = None
    invoice.ignore_reason = note[:500]
    invoice.matched_by = actor_id
    invoice.matched_at = _now()
    _clear_difference(invoice)
    await db.flush()


async def reopen(
    db: AsyncSession, invoice: ClientSalesInvoice, *, actor_id: int
) -> None:
    """Cofnięcie przypisania albo pominięcia — faktura wraca do „do przypisania”."""

    await db.execute(
        delete(ClientSalesInvoiceLink).where(
            ClientSalesInvoiceLink.invoice_id == invoice.id
        )
    )
    invoice.match_status = "unmatched"
    invoice.match_method = None
    invoice.match_reason = "reopened"
    invoice.ignore_reason = None
    invoice.matched_by = actor_id
    invoice.matched_at = None
    _clear_difference(invoice)
    await db.flush()
    await propagate_to_corrections(db, invoice)


async def rematch_pending(db: AsyncSession, *, limit: int = 200) -> dict[str, int]:
    """Kolejna próba dla faktur czekających z powodu, który mógł zniknąć."""

    pending = list(
        await db.scalars(
            select(ClientSalesInvoice)
            .where(
                ClientSalesInvoice.match_status == "unmatched",
                ClientSalesInvoice.match_reason.in_(sorted(RETRY_REASONS)),
            )
            .order_by(ClientSalesInvoice.issue_date.desc(), ClientSalesInvoice.id)
            .limit(limit)
        )
    )
    registry = await clients.nip_registry(db) if pending else None
    matched = 0
    for invoice in pending:
        if invoice.match_reason == "unknown_buyer":
            invoice.client_id = None
        decision = await auto_match(db, invoice, registry=registry)
        if decision.matched or invoice.match_status == "matched":
            matched += 1
    return {"retried": len(pending), "matched": matched}


__all__ = [
    "Decision",
    "MatchingError",
    "REASON_LABELS",
    "Target",
    "assign",
    "auto_match",
    "decide",
    "ignore",
    "invoice_texts",
    "numbers_found",
    "propagate_to_corrections",
    "rematch_pending",
    "reopen",
]
