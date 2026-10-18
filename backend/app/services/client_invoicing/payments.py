"""Zapłata faktur do klientów z uznań na wyciągu (E8) i ręczne „opłacono”.

Ten sam wyciąg (MT940 albo CAMT.053) Płace wgrywają po wypłaty dla zespołu
(``services/hr/bank/statements.py`` — obciążenia), a Finanse mogą go wgrać
u siebie. Obciążenia zostają tamtej ścieżce; tutaj idą wyłącznie UZNANIA.

Dopasowanie uznania do faktury (łańcuch: pierwotna + korekty), od
najpewniejszego:

1. **numer KSeF w tytule** — faktura o tym numerze,
2. **numer faktury w tytule** (także pole ``/INV/`` przelewu w mechanizmie
   podzielonej płatności) — całym słowem, jedna faktura w tej walucie.

Wskazana faktura: kwota równa pozostałej do zapłaty → opłacona; mniejsza →
wpłata częściowa (klient sam wskazał fakturę); MPP z ``/VAT/`` — kwota
uznania + VAT z tytułu równa pozostałej (VAT trafia na rachunek VAT) →
opłacona, zapisujemy całość. Większa niż do zapłaty albo faktura już
opłacona → „do sprawdzenia” (``unmatched``) z powodem.

Bez numeru w tytule: kwota równa pozostałej do zapłaty dokładnie jednej
faktury → „do sprawdzenia” z podpowiedzią (Finanse potwierdzają jednym
kliknięciem). Uznania, które nie dotyczą żadnej faktury (zwroty, odsetki,
wpłaty spoza sprzedaży), nie trafiają do bazy — liczymy je tylko.

Ten sam plik drugi raz nic nie zmienia (skrót pliku + numer pozycji,
``uq_client_sales_invoice_payments_statement``); ta sama operacja na innym
pliku (wyciąg dzienny i miesięczny) zostaje jako ``ignored`` z powodem.
Wynik importu niesie same liczby — bez kwot i nazw klientów, bo widzą go
też Płace. Wyciąg wgrany przez Płace bez modułu Finanse NIE dopasowuje uznań
(``count_credits``): zapłatę faktury klienta stwierdzają Finanse, a liczniki
„dopasowane / do sprawdzenia” mówiłyby, czy numer faktury z tytułu istnieje.
Takie uznania czekają na wyciąg wgrany przez Finanse (ten sam plik dopisze je
wtedy normalnie).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoicePayment,
)
from app.services.client_invoicing import ledger
from app.services.client_invoicing import settings as module_settings
from app.services.client_invoicing.billing import money
from app.services.client_invoicing.ledger import ZERO, Chain
from app.services.client_sales_invoices_schema import (
    COUNTERPARTY_MAX_LENGTH,
    CURRENCIES,
    REASON_MAX_LENGTH,
    TITLE_MAX_LENGTH,
)
from app.services.hr.bank.parsed import ParsedStatement, StatementLine
from app.services.hr.bank.titles import ksef_numbers_in

logger = logging.getLogger(__name__)

DUPLICATE_REASON = "Ta sama operacja była już na wcześniej wgranym wyciągu."
REASON_LABELS: dict[str, str] = {
    "amount_exceeds": "Kwota większa niż pozostało do zapłaty faktury.",
    "already_paid": "Faktura była już opłacona — sprawdź, czy to nie podwójna zapłata.",
    "currency_differs": "Waluta wpłaty inna niż waluta faktury.",
    "ambiguous": "Tytuł pasuje do kilku faktur — wybierz właściwą.",
    "amount_only": "W tytule nie ma numeru faktury — kwota pasuje do jednej faktury.",
}

_MPP_VAT = re.compile(r"/VAT/\s*(\d+(?:[.,]\d{1,2})?)\s*/", re.IGNORECASE)
_MPP_INV = re.compile(r"/INV/\s*([^/]+?)\s*(?:/|$)", re.IGNORECASE)


@dataclass(frozen=True)
class OpenInvoice:
    """Faktura (łańcuch) w kształcie potrzebnym do dopasowania wpłaty."""

    invoice_id: int
    currency: str
    to_pay: Decimal
    ksef_numbers: tuple[str, ...]
    invoice_numbers: tuple[str, ...]


@dataclass(frozen=True)
class CreditDecision:
    invoice_id: Optional[int]
    related: bool
    reason: str
    #: Kwota zapisywana jako zapłata (MPP: uznanie + VAT z tytułu).
    amount: Optional[Decimal] = None
    hint_invoice_id: Optional[int] = None


@dataclass
class CreditResult:
    disabled: bool = False
    credits: int = 0
    matched: int = 0
    unmatched: int = 0
    duplicates: int = 0
    known: int = 0
    skipped: int = 0
    error: bool = False
    #: Importujący bez modułu Finanse — uznania tylko policzone.
    restricted: bool = False
    paid_invoice_ids: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "disabled": self.disabled,
            "credits": self.credits,
            "matched": self.matched,
            "unmatched": self.unmatched,
            "duplicates": self.duplicates,
            "known": self.known,
            "skipped": self.skipped,
            "error": self.error,
            "restricted": self.restricted,
        }


# ── Czyste reguły ────────────────────────────────────────────────────────────


def open_invoice(chain: Chain) -> OpenInvoice:
    return OpenInvoice(
        invoice_id=chain.head.id,
        currency=chain.head.currency,
        to_pay=chain.to_pay,
        ksef_numbers=tuple(i.ksef_number for i in chain.invoices if i.ksef_number),
        invoice_numbers=tuple(
            i.invoice_number for i in chain.invoices if i.invoice_number
        ),
    )


def mpp_vat(title: str) -> Optional[Decimal]:
    found = _MPP_VAT.search(title or "")
    if not found:
        return None
    try:
        return money(Decimal(found.group(1).replace(",", ".")))
    except InvalidOperation:
        return None


def _number_pattern(number: str) -> Optional[re.Pattern[str]]:
    parts = number.split()
    if not parts:
        return None
    body = r"\s*".join(re.escape(part) for part in parts)
    return re.compile(r"(?<![0-9A-Za-z])" + body + r"(?![0-9A-Za-z])", re.IGNORECASE)


def _number_in_title(
    invoice: OpenInvoice, title: str, mpp_number: Optional[str]
) -> bool:
    for number in invoice.invoice_numbers:
        if mpp_number and " ".join(number.split()).lower() == mpp_number.lower():
            return True
        pattern = _number_pattern(number)
        if pattern is not None and pattern.search(title or ""):
            return True
    return False


def _settle(
    found: OpenInvoice, amount: Decimal, title: str, how: str
) -> CreditDecision:
    if found.to_pay <= ZERO:
        return CreditDecision(
            None, True, "already_paid", hint_invoice_id=found.invoice_id
        )
    if amount <= found.to_pay:
        vat = mpp_vat(title)
        if (
            amount < found.to_pay
            and vat is not None
            and money(amount + vat) == found.to_pay
        ):
            return CreditDecision(
                found.invoice_id, True, f"{how}_mpp", money(amount + vat)
            )
        return CreditDecision(found.invoice_id, True, how, amount)
    return CreditDecision(
        None, True, "amount_exceeds", hint_invoice_id=found.invoice_id
    )


def decide_credit(
    line: StatementLine, invoices: Sequence[OpenInvoice]
) -> CreditDecision:
    """Dopasowanie jednego uznania (czysta funkcja — testy bez bazy)."""

    amount = money(line.amount)
    title = line.title or ""
    numbers = set(ksef_numbers_in(title))
    if numbers:
        by_ksef = [i for i in invoices if numbers & set(i.ksef_numbers)]
        if len(by_ksef) == 1:
            found = by_ksef[0]
            if found.currency != line.currency:
                return CreditDecision(
                    None, True, "currency_differs", hint_invoice_id=found.invoice_id
                )
            return _settle(found, amount, title, "ksef")
        if len(by_ksef) > 1:
            return CreditDecision(None, True, "ambiguous")

    mpp = _MPP_INV.search(title)
    mpp_number = " ".join(mpp.group(1).split()) if mpp else None
    by_number = [i for i in invoices if _number_in_title(i, title, mpp_number)]
    same = [i for i in by_number if i.currency == line.currency]
    if len(same) == 1:
        return _settle(same[0], amount, title, "invoice_number")
    if len(same) > 1:
        open_ = [i for i in same if i.to_pay > ZERO]
        if len(open_) == 1:
            return _settle(open_[0], amount, title, "invoice_number")
        return CreditDecision(None, True, "ambiguous")
    if by_number:
        return CreditDecision(
            None, True, "currency_differs", hint_invoice_id=by_number[0].invoice_id
        )

    equal = [
        i
        for i in invoices
        if i.currency == line.currency and i.to_pay > ZERO and i.to_pay == amount
    ]
    if len(equal) == 1:
        return CreditDecision(
            None, True, "amount_only", hint_invoice_id=equal[0].invoice_id
        )
    return CreditDecision(None, False, "unrelated")


# ── Import ───────────────────────────────────────────────────────────────────


async def _seen_elsewhere(db: AsyncSession, line: StatementLine, sha: str) -> bool:
    if not line.bank_ref:
        return False
    found = await db.scalar(
        select(func.count())
        .select_from(ClientSalesInvoicePayment)
        .where(
            ClientSalesInvoicePayment.kind == "statement_line",
            ClientSalesInvoicePayment.statement_sha256 != sha,
            ClientSalesInvoicePayment.statement_line_ref.endswith(
                f":{line.bank_ref[:48]}", autoescape=True
            ),
            ClientSalesInvoicePayment.amount == money(line.amount),
            ClientSalesInvoicePayment.booked_on == line.booked_on,
        )
    )
    return bool(found)


async def _all_chains(db: AsyncSession) -> list[Chain]:
    return await ledger.build_chains(
        db, list(await db.scalars(select(ClientSalesInvoice)))
    )


def credit_lines(parsed: ParsedStatement) -> list[StatementLine]:
    """Uznania w walutach faktur — jedyne pozycje wyciągu, które tu dotyczą."""

    return [
        line
        for line in parsed.lines
        if line.direction == "credit" and line.currency in CURRENCIES
    ]


def count_credits(parsed: ParsedStatement) -> CreditResult:
    """Same liczby, bez dopasowania — dla importującego bez modułu Finanse."""

    return CreditResult(credits=len(credit_lines(parsed)), restricted=True)


async def import_credits(
    db: AsyncSession,
    parsed: ParsedStatement,
    *,
    sha: str,
    actor_id: Optional[int],
    require_enabled: bool = True,
) -> CreditResult:
    """Uznania z wyciągu → zapłaty faktur do klientów (bez commita)."""

    result = CreditResult()
    if require_enabled and not await module_settings.is_enabled(db):
        result.disabled = True
        return result
    credits = credit_lines(parsed)
    result.credits = len(credits)
    if not credits:
        return result
    known_refs = set(
        await db.scalars(
            select(ClientSalesInvoicePayment.statement_line_ref).where(
                ClientSalesInvoicePayment.kind == "statement_line",
                ClientSalesInvoicePayment.statement_sha256 == sha,
            )
        )
    )
    chains = {chain.head.id: chain for chain in await _all_chains(db)}
    invoices = {head: open_invoice(chain) for head, chain in chains.items()}
    for line in credits:
        if line.line_ref in known_refs:
            result.known += 1
            continue
        decision = decide_credit(line, list(invoices.values()))
        if not decision.related:
            result.skipped += 1
            continue
        payment = ClientSalesInvoicePayment(
            kind="statement_line",
            amount=money(line.amount),
            currency=line.currency,
            booked_on=line.booked_on,
            title=(line.title or "")[:TITLE_MAX_LENGTH] or None,
            counterparty_name=(line.counterparty_name or "")[:COUNTERPARTY_MAX_LENGTH]
            or None,
            statement_sha256=sha,
            statement_format=parsed.format,
            statement_line_ref=line.line_ref,
            created_by=actor_id,
        )
        if await _seen_elsewhere(db, line, sha):
            payment.match_status = "ignored"
            payment.reason = DUPLICATE_REASON
            db.add(payment)
            result.duplicates += 1
            continue
        if decision.invoice_id is None:
            payment.match_status = "unmatched"
            payment.invoice_id = None
            payment.reason = REASON_LABELS.get(decision.reason)
            db.add(payment)
            result.unmatched += 1
            continue
        payment.match_status = "matched"
        payment.invoice_id = decision.invoice_id
        payment.amount = decision.amount or money(line.amount)
        if decision.reason.endswith("_mpp"):
            payment.reason = "Podzielona płatność: VAT na rachunku VAT."
        db.add(payment)
        await db.flush()
        chain = chains[decision.invoice_id]
        chain.payments.append(payment)
        invoices[decision.invoice_id] = open_invoice(chain)
        result.matched += 1
        result.paid_invoice_ids.append(decision.invoice_id)
    await db.flush()
    logger.info(
        "[client-invoicing] uznania z wyciągu %s: %s", sha[:12], result.as_dict()
    )
    return result


# ── Decyzje Finansów ─────────────────────────────────────────────────────────


class PaymentError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _unmatched_line(
    db: AsyncSession, payment_id: int
) -> ClientSalesInvoicePayment:
    payment = await db.scalar(
        select(ClientSalesInvoicePayment)
        .where(
            ClientSalesInvoicePayment.id == payment_id,
            ClientSalesInvoicePayment.kind == "statement_line",
        )
        .with_for_update()
    )
    if payment is None:
        raise PaymentError("Nie ma takiej wpłaty z wyciągu.", 404)
    if payment.match_status != "unmatched":
        raise PaymentError("Ta wpłata jest już rozstrzygnięta.", 409)
    return payment


async def assign_credit(
    db: AsyncSession, payment_id: int, invoice_id: int, *, actor_id: int
) -> ClientSalesInvoicePayment:
    """„Przypisz” wpłatę z wyciągu do faktury (Finanse)."""

    payment = await _unmatched_line(db, payment_id)
    invoice = await db.get(ClientSalesInvoice, invoice_id)
    if invoice is None:
        raise PaymentError("Nie ma takiej faktury.", 404)
    if invoice.currency != payment.currency:
        raise PaymentError("Waluta wpłaty jest inna niż waluta faktury.")
    payment.invoice_id = invoice.id
    payment.match_status = "matched"
    payment.resolved_by = actor_id
    payment.resolved_at = _now()
    await db.flush()
    return payment


async def ignore_credit(
    db: AsyncSession, payment_id: int, *, reason: str, actor_id: int
) -> ClientSalesInvoicePayment:
    note = " ".join((reason or "").split())
    if len(note) < 3:
        raise PaymentError("Podaj powód pominięcia (co najmniej 3 znaki).")
    payment = await _unmatched_line(db, payment_id)
    payment.match_status = "ignored"
    payment.reason = note[:REASON_MAX_LENGTH]
    payment.resolved_by = actor_id
    payment.resolved_at = _now()
    await db.flush()
    return payment


async def mark_paid(
    db: AsyncSession,
    invoice_id: int,
    *,
    amount: Decimal,
    paid_on: date,
    reason: str,
    actor_id: int,
) -> ClientSalesInvoicePayment:
    """Ręczne „opłacono” (kompensata, wpłata spoza wyciągu) — z powodem."""

    note = " ".join((reason or "").split())
    if len(note) < 3:
        raise PaymentError("Podaj powód (co najmniej 3 znaki).")
    invoice = await db.get(ClientSalesInvoice, invoice_id)
    if invoice is None:
        raise PaymentError("Nie ma takiej faktury.", 404)
    value = money(Decimal(amount))
    if value <= ZERO:
        raise PaymentError("Kwota musi być większa od zera.")
    payment = ClientSalesInvoicePayment(
        kind="manual",
        invoice_id=invoice.id,
        match_status="matched",
        amount=value,
        currency=invoice.currency,
        booked_on=paid_on,
        reason=note[:REASON_MAX_LENGTH],
        created_by=actor_id,
        resolved_by=actor_id,
        resolved_at=_now(),
    )
    db.add(payment)
    await db.flush()
    return payment


async def unmatched_credits(db: AsyncSession) -> list[ClientSalesInvoicePayment]:
    return list(
        await db.scalars(
            select(ClientSalesInvoicePayment)
            .where(
                ClientSalesInvoicePayment.kind == "statement_line",
                ClientSalesInvoicePayment.match_status == "unmatched",
            )
            .order_by(
                ClientSalesInvoicePayment.booked_on.desc(), ClientSalesInvoicePayment.id
            )
        )
    )


__all__ = [
    "CreditDecision",
    "CreditResult",
    "OpenInvoice",
    "PaymentError",
    "REASON_LABELS",
    "assign_credit",
    "count_credits",
    "credit_lines",
    "decide_credit",
    "ignore_credit",
    "import_credits",
    "mark_paid",
    "mpp_vat",
    "open_invoice",
    "unmatched_credits",
]
