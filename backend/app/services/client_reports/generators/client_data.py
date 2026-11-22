"""Odczyty i proste przeliczenia wspólne dla raportów kwotowych klienta.

Zamówienia, zużycie MD i faktury sprzedaży z KSeF. Funkcje ``async`` czytają
bazę (zapytania z parametrami), reszta to czyste przeliczenia testowane bez
bazy w ``tests/test_client_reports_generators.py``.

Reguły wspólne:

* wartość zamówienia to ``total_value``, a gdy jej brak — ``md_total ×
  md_rate_revenue``; bez obu wartość jest pusta (generator zgłasza to w
  kontrolach), bo zgadywanie z budżetu grupy dublowałoby kwotę na każdej linii;
* zamówienia anulowane i szkice (do uzupełnienia, bez potwierdzenia klienta)
  nie wchodzą do raportów;
* miesiąc należy do okresu, gdy jego pierwszy dzień leży w okresie — rok umowy
  od 27.02 to miesiące 03…02, bez podwójnego lutego (zużycie MD i okres
  usługi faktury są miesięczne);
* korekta faktury w KSeF niesie różnicę (ujemną albo dodatnią), więc obrót to
  zwykła suma ``net_amount`` faktur i korekt.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import Boolean, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

NO_ROLE = "bez roli"
NO_CURRENCY = "—"
CENT = Decimal("0.01")

UNIT_LABELS = {"hourly": "godz.", "daily": "MD", "monthly": "mies."}
INVOICE_TYPE_LABELS = {"VAT": "faktura", "KOR": "korekta", "ZAL": "zaliczkowa"}


# ----------------------------------------------------------------- zamówienia


@dataclass(frozen=True)
class OrderRow:
    order_id: int
    order_number: Optional[str]
    title: Optional[str]
    description: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    order_type: Optional[str]
    rate_unit: Optional[str]
    total_value: Optional[Decimal]
    md_total: Optional[Decimal]
    md_rate_revenue: Optional[Decimal]
    rate_client: Optional[Decimal]
    currency: Optional[str]
    project: Optional[str]
    person: Optional[str]


_ORDERS_SQL = text(
    """
    SELECT o.id, g.order_number, o.title, o.description, o.start_date, o.end_date,
           o.order_type, o.rate_unit::text, o.total_value, o.md_total,
           o.md_rate_revenue, o.rate_client,
           coalesce(o.currency, o.rate_client_currency) AS currency,
           coalesce(nullif(trim(k.project_name), ''), jk.title, jo.title) AS project,
           nullif(trim(concat_ws(' ', c.name, c.lastname)), '') AS person
      FROM client_orders o
      LEFT JOIN client_order_groups g ON g.id = o.order_group_id
      LEFT JOIN contracts k ON k.id = o.contract_id
      LEFT JOIN candidates c ON c.id = k.candidate_id
      LEFT JOIN jobs jk ON jk.id = k.job_id
      LEFT JOIN jobs jo ON jo.id = o.job_id
     WHERE o.client_id = :client_id
       AND o.status::text NOT IN ('cancelled', 'draft')
       AND o.start_date IS NOT NULL
       AND o.start_date <= :end
       AND (o.start_date >= :start
            OR (:include_active AND (o.end_date IS NULL OR o.end_date >= :start)))
     ORDER BY o.start_date, g.order_number NULLS LAST, o.id
    """
).bindparams(bindparam("include_active", type_=Boolean))


async def orders_in_period(
    db: AsyncSession,
    client_id: int,
    start: date,
    end: date,
    *,
    include_active: bool = False,
) -> list[OrderRow]:
    """Zamówienia ze startem w okresie; z ``include_active`` też trwające w nim."""
    result = await db.execute(
        _ORDERS_SQL,
        {
            "client_id": client_id,
            "start": start,
            "end": end,
            "include_active": include_active,
        },
    )
    return [OrderRow(*row) for row in result.all()]


def order_value(order: OrderRow) -> Optional[Decimal]:
    if order.total_value is not None:
        return Decimal(order.total_value)
    if order.md_total is not None and order.md_rate_revenue is not None:
        return Decimal(order.md_total) * Decimal(order.md_rate_revenue)
    return None


def order_mode(order_type: Optional[str]) -> str:
    """„ryczałt” dla zamówienia kosztowego, „T&M” dla MD, okresowego i starych bez typu.

    Zamówienie kosztowe (``cost``) rozlicza budżet kwotowy grupy — z punktu
    widzenia klienta to stała kwota. MD, okresowe (godziny albo dni) i stare
    zamówienia bez typu rozliczają faktycznie przepracowany czas.
    """
    return "ryczałt" if order_type == "cost" else "T&M"


def order_unit_price(order: OrderRow) -> tuple[Optional[Decimal], Optional[str]]:
    """Cena jednostkowa i jednostka: zamówienie MD po stawce przychodowej za MD."""
    if order.order_type == "md" and order.md_rate_revenue is not None:
        return Decimal(order.md_rate_revenue), UNIT_LABELS["daily"]
    if order.rate_client is not None:
        return Decimal(order.rate_client), UNIT_LABELS.get(
            order.rate_unit or "", order.rate_unit
        )
    if order.md_rate_revenue is not None:
        return Decimal(order.md_rate_revenue), UNIT_LABELS["daily"]
    return None, None


def order_label(order: OrderRow) -> str:
    return order.order_number or order.title or f"zamówienie {order.order_id}"


def totals_by_currency(
    items: Iterable[tuple[Optional[str], Optional[Decimal]]],
) -> dict[str, Decimal]:
    """Suma kwot per waluta; pozycje bez kwoty pomija, bez waluty liczy pod „—”."""
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for currency, amount in items:
        if amount is None:
            continue
        totals[(currency or NO_CURRENCY).upper()] += Decimal(amount)
    return dict(sorted(totals.items()))


# ------------------------------------------------------------------ zużycie MD


def period_months(start: date, end: date) -> list[str]:
    """Miesiące ``YYYY-MM``, których pierwszy dzień leży w ``[start, end]``."""
    year, month = start.year, start.month
    if start.day > 1:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    out: list[str] = []
    while date(year, month, 1) <= end:
        out.append(f"{year}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


@dataclass(frozen=True)
class MdRow:
    order_id: int
    person: Optional[str]
    role: Optional[str]
    md: Decimal


_MD_SQL = text(
    """
    SELECT o.id, nullif(trim(concat_ws(' ', c.name, c.lastname)), '') AS person,
           coalesce(jk.title, jo.title) AS role,
           sum(m.md_reported) AS md
      FROM client_order_md_consumptions m
      JOIN client_orders o ON o.id = m.order_id
      LEFT JOIN contracts k ON k.id = o.contract_id
      LEFT JOIN candidates c ON c.id = k.candidate_id
      LEFT JOIN jobs jk ON jk.id = k.job_id
      LEFT JOIN jobs jo ON jo.id = o.job_id
     WHERE o.client_id = :client_id
       AND m.period_month BETWEEN :first_month AND :last_month
       AND m.md_reported IS NOT NULL
     GROUP BY 1, 2, 3
    """
)


async def md_in_period(
    db: AsyncSession, client_id: int, start: date, end: date
) -> list[MdRow]:
    """Zaraportowane MD klienta za miesiące okresu (każdy status zużycia się liczy)."""
    months = period_months(start, end)
    if not months:
        return []
    result = await db.execute(
        _MD_SQL,
        {"client_id": client_id, "first_month": months[0], "last_month": months[-1]},
    )
    return [MdRow(row[0], row[1], row[2], Decimal(row[3] or 0)) for row in result.all()]


def md_grouped(rows: Iterable[MdRow], key: str) -> list[tuple[str, Decimal]]:
    """MD zsumowane po ``role`` (profil) albo ``person``; malejąco, potem alfabetycznie."""
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        label = getattr(row, key) or (NO_ROLE if key == "role" else "(bez osoby)")
        sums[label] += row.md
    return sorted(
        ((k, v) for k, v in sums.items() if v), key=lambda item: (-item[1], item[0])
    )


# ----------------------------------------------------------- faktury sprzedaży


@dataclass(frozen=True)
class InvoiceRow:
    invoice_number: Optional[str]
    invoice_type: Optional[str]
    invoice_kind: Optional[str]
    issue_date: Optional[date]
    service_month: Optional[date]
    currency: Optional[str]
    net_amount: Decimal
    #: Data sprzedaży z faktury — dzień kursu NBP przy przeliczaniu obrotu.
    sale_date: Optional[date] = None
    #: Pozycje z KSeF (ilość, cena przed rabatem, netto) — obrót rabatu
    #: liczy się z usług przed rabatem (``client_invoicing.rebate.service_base``).
    items: tuple[dict[str, Any], ...] = ()

    @property
    def is_correction(self) -> bool:
        return self.invoice_kind == "correction" or self.invoice_type == "KOR"


# Dwa pełne napisy zamiast sklejania wspólnego początku: SQL jest stały,
# parametry idą przez bind (Semgrep nie przepuszcza konkatenacji w text()).
_INVOICES_BY_ISSUE_SQL = text(
    """
    SELECT invoice_number, invoice_type, invoice_kind, issue_date,
           coalesce(make_date(period_year, period_month, 1),
                    date_trunc('month', issue_date)::date) AS service_month,
           upper(currency), coalesce(net_amount, 0), sale_date, items
      FROM client_sales_invoices
     WHERE client_id = :client_id
       AND issue_date BETWEEN :start AND :end
     ORDER BY issue_date, invoice_number
    """
)

_INVOICES_BY_SERVICE_SQL = text(
    """
    SELECT invoice_number, invoice_type, invoice_kind, issue_date,
           coalesce(make_date(period_year, period_month, 1),
                    date_trunc('month', issue_date)::date) AS service_month,
           upper(currency), coalesce(net_amount, 0), sale_date, items
      FROM client_sales_invoices
     WHERE client_id = :client_id
       AND coalesce(make_date(period_year, period_month, 1),
                    date_trunc('month', issue_date)::date) BETWEEN :start AND :end
     ORDER BY service_month, issue_date, invoice_number
    """
)


async def sales_invoices(
    db: AsyncSession,
    client_id: int,
    start: date,
    end: date,
    *,
    by_service_month: bool = False,
) -> list[InvoiceRow]:
    """Faktury sprzedaży z KSeF do klienta: po dacie wystawienia albo po miesiącu usługi.

    Miesiąc usługi (``period_year``/``period_month``) wchodzi, gdy jego pierwszy
    dzień leży w okresie — ta sama reguła co przy zużyciu MD.
    """
    sql = _INVOICES_BY_SERVICE_SQL if by_service_month else _INVOICES_BY_ISSUE_SQL
    result = await db.execute(sql, {"client_id": client_id, "start": start, "end": end})
    return [
        InvoiceRow(
            r[0], r[1], r[2], r[3], r[4], r[5], Decimal(r[6]), r[7], tuple(r[8] or ())
        )
        for r in result.all()
    ]


def invoice_type_label(invoice: InvoiceRow) -> str:
    if invoice.is_correction:
        return INVOICE_TYPE_LABELS["KOR"]
    return INVOICE_TYPE_LABELS.get(
        invoice.invoice_type or "", invoice.invoice_type or "faktura"
    )


def cents(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def sheet_amount(value: Optional[Decimal]) -> Optional[float]:
    """Kwota do komórki arkusza: liczba z groszami, nie tekst."""
    return None if value is None else float(cents(value))


def sheet_number(value: Optional[Decimal]) -> Optional[float]:
    return (
        None
        if value is None
        else float(Decimal(value).quantize(Decimal("0.001")).normalize())
    )
