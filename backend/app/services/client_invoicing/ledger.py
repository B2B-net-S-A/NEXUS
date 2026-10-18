"""Faktura z korektami jako jedna całość: kwoty, porównanie z „do faktury”, zapłata.

Łańcuch = faktura pierwotna i wszystkie jej korekty (``corrects_invoice_id``
w górę do pierwotnej). Netto i brutto łańcucha to suma — korekta niesie
różnicę, także ujemną. Powiązania z zamówieniami ma pierwotna; korekta bez
pierwotnej w NEXUSIE jest własnym łańcuchem.

Porównanie (``ChainCheck``): oczekiwane = suma „do faktury” powiązanych
zamówień w miesiącu powiązania (całe zamówienie albo pozycja jednej osoby).
Stany: ``ok`` (zgodna co do grosza), ``accepted`` (Finanse uznały TĘ różnicę),
``difference`` (do sprawdzenia), ``unknown`` (kwoty „do faktury” nie da się
policzyć — np. brak zużycia MD), ``unmatched`` / ``ignored``.

Zamówienie kosztowe nie ma kwoty „do faktury” (ustalają ją Finanse), więc
porównanie idzie z budżetem (``basis='budget'``): faktura jest zgodna, gdy
jej część na zamówienia kosztowe (netto minus „do faktury” powiązanych
zamówień MD i okresowych) mieści się w tym, co zostało z budżetu przed tym
miesiącem; nadwyżka nad budżetem (albo część ujemna) to różnica do
sprawdzenia przez Finanse.

Zapłata: suma uznań i ręcznych „opłacono” przypisanych do faktur łańcucha;
„Zapłacono” w samej fakturze liczy się jako zapłata całości. Po terminie =
termin z faktury pierwotnej minął, a do zapłaty zostało więcej niż zero.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoiceLink,
    ClientSalesInvoicePayment,
)
from app.services.client_invoicing import billing, clients
from app.services.client_invoicing.billing import BillingRow, money

ZERO = Decimal("0.00")
_MAX_CORRECTION_DEPTH = 5


@dataclass
class Chain:
    head: ClientSalesInvoice
    corrections: list[ClientSalesInvoice] = field(default_factory=list)
    links: list[ClientSalesInvoiceLink] = field(default_factory=list)
    payments: list[ClientSalesInvoicePayment] = field(default_factory=list)

    @property
    def invoices(self) -> list[ClientSalesInvoice]:
        return [self.head, *self.corrections]

    @property
    def net(self) -> Decimal:
        return money(sum((Decimal(i.net_amount) for i in self.invoices), ZERO))

    @property
    def gross(self) -> Decimal:
        return money(sum((Decimal(i.gross_amount) for i in self.invoices), ZERO))

    @property
    def paid(self) -> Decimal:
        if self.head.paid_in_invoice_on is not None:
            return self.gross
        return money(sum((Decimal(p.amount) for p in self.payments), ZERO))

    @property
    def to_pay(self) -> Decimal:
        return money(self.gross - self.paid)

    @property
    def paid_on(self) -> Optional[date]:
        if self.head.paid_in_invoice_on is not None:
            return self.head.paid_in_invoice_on
        days = [p.booked_on for p in self.payments if p.booked_on]
        return max(days) if days else None

    @property
    def payment_status(self) -> str:
        """``paid`` | ``partial`` | ``unpaid`` | ``overpaid`` | ``none`` (do zapłaty ≤ 0)."""

        if self.gross <= ZERO:
            return "none"
        if self.paid <= ZERO:
            return "unpaid"
        if self.paid < self.gross:
            return "partial"
        return "paid" if self.paid == self.gross else "overpaid"

    def overdue_days(self, today: date) -> int:
        due = self.head.due_date
        if due is None or self.to_pay <= ZERO or today <= due:
            return 0
        return (today - due).days

    @property
    def period(self) -> Optional[tuple[int, int]]:
        if self.links:
            return (int(self.links[0].period_year), int(self.links[0].period_month))
        if self.head.period_year is not None:
            return (int(self.head.period_year), int(self.head.period_month))
        return None

    @property
    def match_status(self) -> str:
        if self.head.match_status == "matched" and not self.links:
            return "unmatched"
        return self.head.match_status

    @property
    def match_reason(self) -> Optional[str]:
        if self.head.match_status == "matched" and not self.links:
            return "order_removed"
        return self.head.match_reason

    def targets(self) -> set[str]:
        return {
            f"g{link.order_group_id}"
            if link.order_group_id is not None
            else f"o{link.order_id}"
            for link in self.links
        }


@dataclass(frozen=True)
class ChainCheck:
    status: str
    expected: Optional[Decimal]
    difference: Optional[Decimal]
    #: ``amount`` — z kwotą „do faktury”; ``budget`` — z resztą budżetu kosztowego.
    basis: str = "amount"


def _cost_row(
    link: ClientSalesInvoiceLink, rows: dict[str, BillingRow]
) -> Optional[BillingRow]:
    """Wiersz zamówienia kosztowego, którego dotyczy powiązanie (całe albo osoba)."""

    if link.order_group_id is not None:
        row = rows.get(f"g{link.order_group_id}")
        return row if row is not None and row.budget is not None else None
    if link.order_id is None:
        return None
    return next(
        (
            row
            for row in rows.values()
            if row.budget is not None and int(link.order_id) in row.member_ids
        ),
        None,
    )


def _expected_for_link(
    link: ClientSalesInvoiceLink, rows: dict[str, BillingRow]
) -> tuple[bool, Optional[Decimal]]:
    """(zamówienie ma wiersz w miesiącu, oczekiwana kwota)."""

    if link.order_group_id is not None:
        row = rows.get(f"g{link.order_group_id}")
        return (row is not None, row.expected_net if row else None)
    row = rows.get(f"o{link.order_id}")
    if row is not None:
        return True, row.expected_net
    for candidate in rows.values():
        line = candidate.line_for(int(link.order_id)) if link.order_id else None
        if line is not None:
            return True, line.net
    return False, None


def check(chain: Chain, rows: dict[str, BillingRow]) -> ChainCheck:
    """Porównanie łańcucha z „do faktury” (``rows`` — wiersze miesiąca powiązania)."""

    status = chain.match_status
    if status != "matched":
        return ChainCheck(status, None, None)
    total = ZERO
    budgets: dict[str, Decimal] = {}
    for link in chain.links:
        cost = _cost_row(link, rows)
        if cost is not None:
            budgets[cost.key] = cost.budget.available
            continue
        present, value = _expected_for_link(link, rows)
        if not present:
            # Zamówienie bez pozycji w tym miesiącu: do faktury 0.
            continue
        if value is None:
            return ChainCheck("unknown", None, None)
        total += value
    if budgets:
        return _budget_check(chain, money(total), money(sum(budgets.values(), ZERO)))
    expected = money(total)
    difference = money(chain.net - expected)
    if difference == ZERO:
        return ChainCheck("ok", expected, difference)
    return _difference(chain, expected, difference, "amount")


def _difference(
    chain: Chain, expected: Optional[Decimal], difference: Decimal, basis: str
) -> ChainCheck:
    accepted = chain.head.difference_accepted_amount
    if accepted is not None and money(Decimal(accepted)) == difference:
        return ChainCheck("accepted", expected, difference, basis)
    return ChainCheck("difference", expected, difference, basis)


def _budget_check(chain: Chain, fixed: Decimal, available: Decimal) -> ChainCheck:
    """Część faktury na zamówienia kosztowe a reszta ich budżetu."""

    cost_part = money(chain.net - fixed)
    if cost_part < ZERO:
        return _difference(chain, None, cost_part, "budget")
    over = money(cost_part - available)
    if over > ZERO:
        return _difference(chain, None, over, "budget")
    return ChainCheck("ok", None, ZERO, "budget")


def _root(invoice: ClientSalesInvoice, by_id: dict[int, ClientSalesInvoice]) -> int:
    current = invoice
    for _ in range(_MAX_CORRECTION_DEPTH):
        parent = (
            by_id.get(current.corrects_invoice_id)
            if current.corrects_invoice_id
            else None
        )
        if parent is None:
            return current.id
        current = parent
    return current.id


async def _with_relatives(
    db: AsyncSession, invoices: list[ClientSalesInvoice]
) -> dict[int, ClientSalesInvoice]:
    """Dociąga pierwotne i korekty wybranych faktur (kilka poziomów)."""

    by_id = {invoice.id: invoice for invoice in invoices}
    for _ in range(_MAX_CORRECTION_DEPTH):
        parents = {
            i.corrects_invoice_id
            for i in by_id.values()
            if i.corrects_invoice_id and i.corrects_invoice_id not in by_id
        }
        children = list(
            await db.scalars(
                select(ClientSalesInvoice).where(
                    or_(
                        ClientSalesInvoice.id.in_(parents or {0}),
                        ClientSalesInvoice.corrects_invoice_id.in_(set(by_id)),
                    )
                )
            )
        )
        fresh = [i for i in children if i.id not in by_id]
        if not fresh:
            break
        by_id.update({i.id: i for i in fresh})
    return by_id


async def build_chains(
    db: AsyncSession, invoices: Iterable[ClientSalesInvoice]
) -> list[Chain]:
    by_id = await _with_relatives(db, list(invoices))
    chains: dict[int, Chain] = {}
    for invoice in sorted(by_id.values(), key=lambda i: (i.issue_date, i.id)):
        root = _root(invoice, by_id)
        chain = chains.get(root)
        if chain is None:
            chain = chains[root] = Chain(head=by_id[root])
        if invoice.id != root:
            chain.corrections.append(invoice)
    heads = list(chains)
    if heads:
        for link in await db.scalars(
            select(ClientSalesInvoiceLink)
            .where(ClientSalesInvoiceLink.invoice_id.in_(heads))
            .order_by(ClientSalesInvoiceLink.id)
        ):
            chains[link.invoice_id].links.append(link)
        root_of = {invoice_id: _root(by_id[invoice_id], by_id) for invoice_id in by_id}
        for payment in await db.scalars(
            select(ClientSalesInvoicePayment)
            .where(
                ClientSalesInvoicePayment.invoice_id.in_(list(by_id)),
                ClientSalesInvoicePayment.match_status == "matched",
            )
            .order_by(ClientSalesInvoicePayment.id)
        ):
            chains[root_of[payment.invoice_id]].payments.append(payment)
    return sorted(
        chains.values(), key=lambda c: (c.head.issue_date, c.head.id), reverse=True
    )


async def chains_for_period(
    db: AsyncSession,
    *,
    year: int,
    month: int,
    client_ids: Optional[Collection[int]],
) -> list[Chain]:
    """Łańcuchy z miesiącem usługi (faktury albo powiązania) w danym miesiącu."""

    linked = select(ClientSalesInvoiceLink.invoice_id).where(
        ClientSalesInvoiceLink.period_year == year,
        ClientSalesInvoiceLink.period_month == month,
    )
    query = select(ClientSalesInvoice).where(
        or_(
            tuple_(ClientSalesInvoice.period_year, ClientSalesInvoice.period_month)
            == (year, month),
            ClientSalesInvoice.id.in_(linked),
        )
    )
    if client_ids is not None:
        query = query.where(
            ClientSalesInvoice.client_id.in_(sorted(client_ids) or [-1])
        )
    chains = await build_chains(db, list(await db.scalars(query)))
    # Korekta z innego miesiąca dociągnęła pierwotną: zostają łańcuchy tego miesiąca.
    return [chain for chain in chains if chain.period == (year, month)]


async def open_chains(
    db: AsyncSession, *, client_ids: Optional[Collection[int]]
) -> list[Chain]:
    """Łańcuchy z czymkolwiek do zapłaty (do zaległości i dopasowania uznań)."""

    query = select(ClientSalesInvoice).where(
        ClientSalesInvoice.paid_in_invoice_on.is_(None)
    )
    if client_ids is not None:
        query = query.where(
            ClientSalesInvoice.client_id.in_(sorted(client_ids) or [-1])
        )
    chains = await build_chains(db, list(await db.scalars(query)))
    return [chain for chain in chains if chain.to_pay > ZERO]


async def rows_by_period(
    db: AsyncSession,
    chains: Iterable[Chain],
) -> dict[tuple[int, int], dict[str, BillingRow]]:
    """Wiersze „do faktury” potrzebne do porównania łańcuchów (per miesiąc i klient)."""

    wanted: dict[tuple[int, int], set[int]] = defaultdict(set)
    for chain in chains:
        if chain.match_status == "matched" and chain.period and chain.head.client_id:
            wanted[chain.period].add(int(chain.head.client_id))
    out: dict[tuple[int, int], dict[str, BillingRow]] = {}
    for (year, month), ids in wanted.items():
        members = await clients.family(db, ids)
        rows = await billing.billing_rows(
            db, year=year, month=month, client_ids=members
        )
        out[(year, month)] = {row.key: row for row in rows}
    return out


__all__ = [
    "Chain",
    "ChainCheck",
    "build_chains",
    "chains_for_period",
    "check",
    "open_chains",
    "rows_by_period",
]
