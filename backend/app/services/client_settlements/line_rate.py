"""Stawka linii zamówienia a stawka kontraktu i ostatniej faktury za osobę.

Próba IX–X 2026: jedna z trzech linii zamówień osoby miała stawkę przychodową
niższą niż kontrakt i niż wszystkie faktury Finansów za tę osobę (linię wpisano
ze stawką innej osoby z tego samego zamówienia klienta). „Do faktury” liczy się
ze stawki linii, więc kwota wyszła za nisko, a rozliczenie dostało „Bez uwag”.

Kontrola tylko ostrzega (decyzja z 24.11.2026: danych nie poprawiamy sami):
Finanse widzą uwagę „Stawka klienta” na karcie rozliczenia, a Delivery Lead
klienta kartę w panelu „Moi klienci” (``rule_settlement_rate_mismatch``).

* Porównujemy w zł za MD stawkę, którą liczy rozliczenie (linia wyceniona na
  pierwszy dzień miesiąca, ``priced_one``), ze stawką klienta z kontraktu na ten
  dzień i z ceną z ostatniej faktury sprzedaży za tę osobę u tego klienta
  (okres faktury nie późniejszy niż miesiąc rozliczenia).
* Inna waluta niż złoty po którejkolwiek stronie = bez porównania (bez kursu).
* Kontrakt godzinowy: różnica do 4 zł/MD to zaokrąglenie stawki godzinowej
  w pełnych złotych (jak w raporcie rozjazdów stawek). Cena godzinowa z faktury
  jest dokładna: × 8 h daje do 0,10 zł/MD różnicy.
* Faktura sprzed zmiany stawki w kontrakcie nie jest wzorem: po aneksie stara
  cena z faktury różni się od nowej linii, a to jest dobra zmiana.
* Pozycja „szt.” bez jednostki czasu nie mówi, za ile MD jest cena — pomijamy.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import Text, and_, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import Candidate
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.contract import Contract, RateUnit
from app.services.client_invoicing.matching import person_named_in
from app.services.client_settlements.engine import OrderState, Result
from app.services.order_rate_snapshots import contract_rate_in_unit

#: Klucz w danych przy kontrolach (``service.meta_of``) i w uwadze karty.
META_KEY = "rate_mismatch"
RULE_KEY = "order.line_rate"
GROUP_TITLE = "Stawka klienta"
HOURS_PER_MD = Decimal("8")
#: Różnica poniżej grosza to reszta z przeliczenia.
TOLERANCE = Decimal("0.01")
#: Stawka godzinowa kontraktu w pełnych złotych: do 0,50 zł/h, czyli 4 zł/MD.
HOURLY_ROUNDING = Decimal("4.00")
#: Cena godzinowa z faktury jest dokładna co do grosza: × 8 h to do 0,08 zł/MD.
#: Większa różnica to inna stawka (próba IX–X: faktura o 0,50 zł/h niższa).
INVOICE_HOURLY_ROUNDING = Decimal("0.10")
#: Ile faktur klienta za okres do miesiąca rozliczenia przeglądamy na osobę.
INVOICES_BACK = 12

_MD_UNITS = ("md", "osobodzień", "osobodzien", "dzień", "dzien", "dni")
_HOUR_UNIT = re.compile(r"^(h|godz|godzina|godziny|godzin|rbh)\W*$")


@dataclass(frozen=True)
class InvoicePrice:
    number: str
    period: str
    #: Ceny tej osoby na fakturze w zł za MD (nadgodziny mają osobną cenę).
    prices: tuple[Decimal, ...]
    #: Cena pozycji z największą liczbą jednostek: ta idzie do uwagi.
    main: Decimal
    hourly: bool


@dataclass(frozen=True)
class Reference:
    contract: Optional[Decimal] = None
    contract_hourly: bool = False
    invoice: Optional[InvoicePrice] = None
    #: Stawka kontraktu na pierwszy dzień okresu faktury.
    contract_at_invoice: Optional[Decimal] = None


def _plain(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):f}"


def _fmt(value: Decimal) -> str:
    text = f"{value.quantize(Decimal('0.01')):,.2f}".replace(",", " ")
    text = text.replace(".", ",")
    return text[:-3] if text.endswith(",00") else text


def _close(a: Decimal, b: Decimal, tolerance: Decimal) -> bool:
    return abs(a - b) <= tolerance


def judge(line: OrderState, ref: Reference) -> Optional[dict[str, Any]]:
    """Rozjazd stawki jednej linii albo ``None``. Bez bazy."""

    rate = line.rate_revenue
    if rate is None or rate <= 0:
        return None
    rate = Decimal(rate)
    contract_tol = HOURLY_ROUNDING if ref.contract_hourly else TOLERANCE
    contract_off = ref.contract is not None and not _close(
        rate, ref.contract, contract_tol
    )
    invoice = ref.invoice
    invoice_off = False
    if invoice is not None:
        raised = (
            ref.contract is not None
            and ref.contract_at_invoice is not None
            and not _close(ref.contract, ref.contract_at_invoice, TOLERANCE)
        )
        tol = INVOICE_HOURLY_ROUNDING if invoice.hourly else TOLERANCE
        invoice_off = not raised and not any(
            _close(rate, price, tol) for price in invoice.prices
        )
    if not contract_off and not invoice_off:
        return None
    return {
        "order_id": line.order_id,
        "number": line.number,
        "line": _plain(rate),
        "contract": _plain(ref.contract) if contract_off and ref.contract else None,
        "invoice": _plain(invoice.main) if invoice_off and invoice else None,
        "invoice_number": invoice.number if invoice_off and invoice else None,
        "invoice_period": invoice.period if invoice_off and invoice else None,
    }


def describe(item: dict[str, Any]) -> tuple[str, str]:
    """Tytuł i opis uwagi na karcie rozliczenia (Finanse, z kwotami)."""

    number = item.get("number") or "bez numeru"
    title = f"Stawka linii zamówienia {number}: {_fmt(Decimal(item['line']))} zł/MD"
    against: list[str] = []
    if item.get("contract"):
        against.append(f"kontrakt {_fmt(Decimal(item['contract']))} zł/MD")
    if item.get("invoice"):
        period = str(item.get("invoice_period") or "")
        when = f" za {period[5:7]}.{period[:4]}" if len(period) == 7 else ""
        against.append(
            f"ostatnia faktura za tę osobę ({item.get('invoice_number')}{when}) "
            f"{_fmt(Decimal(item['invoice']))} zł/MD"
        )
    detail = (
        "Inna stawka: "
        + ", ".join(against)
        + ". „Do faktury” liczy się ze stawki linii. Sprawdź stawkę z Delivery Leadem "
        "klienta i popraw linię zamówienia przed fakturą; po zmianie rozliczenie "
        "przeliczy się samo."
    )
    return title, detail


def with_mismatches(result: Result, found: Sequence[dict[str, Any]]) -> Result:
    """Wynik z uwagą „Stawka klienta”; „Bez uwag” przechodzi w „Z uwagami”."""

    if not found:
        return result
    checks = []
    for item in found:
        title, detail = describe(item)
        checks.append(
            {"state": "warn", "title": title, "detail": detail, "rule": RULE_KEY}
        )
    return replace(
        result,
        status="warnings" if result.status == "ok" else result.status,
        checks=[*result.checks, {"title": GROUP_TITLE, "checks": checks}],
        meta={**(result.meta or {}), META_KEY: [dict(item) for item in found]},
    )


def _unit_price(item: dict[str, Any]) -> Optional[tuple[Decimal, Decimal, bool]]:
    """(cena za MD, liczba jednostek, godzinowa) pozycji albo ``None``."""

    if not isinstance(item, dict) or item.get("before_correction"):
        return None
    unit = str(item.get("unit") or "").strip().lower()
    try:
        price = Decimal(str(item.get("unit_price")))
        quantity = Decimal(str(item.get("quantity") or "0"))
    except (InvalidOperation, ValueError):
        return None
    if price <= 0 or quantity <= 0:
        return None
    if unit.rstrip(".") in _MD_UNITS:
        return price, quantity, False
    if _HOUR_UNIT.match(unit):
        return price * HOURS_PER_MD, quantity, True
    return None


def invoice_price(
    invoices: Iterable[ClientSalesInvoice], person: str
) -> Optional[InvoicePrice]:
    """Ceny osoby z najnowszej faktury, która ją wymienia z jednostką czasu.

    ``invoices`` od najnowszej (okres, potem data wystawienia)."""

    for invoice in invoices:
        if (invoice.currency or "PLN").upper() != "PLN":
            continue
        found: list[tuple[Decimal, Decimal, bool]] = []
        for item in invoice.items or []:
            if not isinstance(item, dict):
                continue
            if not person_named_in(person, str(item.get("name") or "")):
                continue
            priced = _unit_price(item)
            if priced is not None:
                found.append(priced)
        if not found:
            continue
        main = max(found, key=lambda f: f[1])
        return InvoicePrice(
            number=invoice.invoice_number,
            period=f"{invoice.period_year}-{invoice.period_month:02d}",
            prices=tuple(f[0] for f in found),
            main=main[0],
            hourly=main[2],
        )
    return None


def _contract_md(contract: Contract, day: date) -> Optional[Decimal]:
    """Stawka klienta z kontraktu w zł/MD; miesięczna i obca waluta = ``None``."""

    if (contract.resolved_rate_client_currency or "PLN").upper() != "PLN":
        return None
    if contract.rate_unit not in (RateUnit.hourly.value, RateUnit.daily.value):
        return None
    rate = contract.effective_client_rate(day)
    if rate is None or rate <= 0 or not contract.rate_unit:
        return None
    return contract_rate_in_unit(rate, contract, RateUnit.daily)


def _fold_ascii(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _invoices(
    db: AsyncSession, client_id: int, month: str, lastname: str
) -> list[ClientSalesInvoice]:
    year, mon = (int(x) for x in month.split("-"))
    text = cast(ClientSalesInvoice.items, Text)
    names = {_like(lastname), _like(_fold_ascii(lastname))}
    return list(
        await db.scalars(
            select(ClientSalesInvoice)
            .where(
                ClientSalesInvoice.client_id == client_id,
                ClientSalesInvoice.period_year.is_not(None),
                ClientSalesInvoice.period_month.is_not(None),
                or_(
                    ClientSalesInvoice.period_year < year,
                    and_(
                        ClientSalesInvoice.period_year == year,
                        ClientSalesInvoice.period_month <= mon,
                    ),
                ),
                or_(*(text.ilike(f"%{name}%", escape="\\") for name in names)),
            )
            .order_by(
                ClientSalesInvoice.period_year.desc(),
                ClientSalesInvoice.period_month.desc(),
                ClientSalesInvoice.issue_date.desc(),
                ClientSalesInvoice.id.desc(),
            )
            .limit(INVOICES_BACK)
        )
    )


async def reference(
    db: AsyncSession, contract_id: int, client_id: int, month: str
) -> Reference:
    contract = await db.scalar(
        select(Contract)
        .options(selectinload(Contract.client_rate_schedule))
        .where(Contract.id == contract_id)
    )
    if contract is None:
        return Reference()
    year, mon = (int(x) for x in month.split("-"))
    first = date(year, mon, 1)
    contract_md = _contract_md(contract, first)
    hourly = (
        bool(contract.rate_unit) and RateUnit(contract.rate_unit) == RateUnit.hourly
    )
    invoice = None
    candidate = (
        await db.get(Candidate, contract.candidate_id)
        if contract.candidate_id
        else None
    )
    lastname = (candidate.lastname or "").strip() if candidate else ""
    person = f"{candidate.name or ''} {lastname}".strip() if candidate else ""
    if len(lastname) >= 2 and len(person.split()) >= 2:
        invoice = invoice_price(await _invoices(db, client_id, month, lastname), person)
    at_invoice = None
    if invoice is not None:
        inv_year, inv_mon = (int(x) for x in invoice.period.split("-"))
        at_invoice = _contract_md(contract, date(inv_year, inv_mon, 1))
    return Reference(
        contract=contract_md,
        contract_hourly=hourly,
        invoice=invoice,
        contract_at_invoice=at_invoice,
    )


async def check(
    db: AsyncSession,
    *,
    contract_id: int,
    client_id: int,
    month: str,
    lines: Sequence[OrderState],
    result: Result,
) -> Result:
    """Wynik przeliczenia z uwagą o stawce linii, gdy któraś się rozjeżdża."""

    priced = [line for line in lines if line.rate_revenue is not None]
    if not priced or result.status == "checking":
        return result
    ref = await reference(db, contract_id, client_id, month)
    found = [item for line in priced if (item := judge(line, ref)) is not None]
    return with_mismatches(result, found)


def mismatches_of(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Rozjazdy stawek zapisane przy ostatnim przeliczeniu."""

    return [
        item
        for item in meta.get(META_KEY) or []
        if isinstance(item, dict) and item.get("order_id")
    ]
