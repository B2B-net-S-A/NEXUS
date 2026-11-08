"""Faktura na osobę bez pozycji zamówienia w miesiącu usługi (audyt C5).

Pomiar z 06.11.2026: 50 osób z faktur Nordei nie miało pozycji zamówienia
w miesiącu z faktury. Finanse widzą to tylko jako „kwota nie pasuje”, a uzupełnić
obsadę może Delivery Lead, więc to on dostaje alert.

Faktura wskazuje osobę pełnym imieniem i nazwiskiem w pozycji. Bierzemy tylko
osoby z kontraktem u tego klienta: nazwisko spoza kontraktów nie mówi, kogo DL
miałby dopisać, i taka faktura zostaje Finansom. Starsze niż
``GAP_MONTHS_BACK`` miesiące nie alarmują: obsady sprzed pół roku nikt już nie
uzupełni, a powtórka co tydzień byłaby tylko szumem.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client_order import ClientOrder
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.contract import Contract, ContractStatus
from app.services.client_invoicing import billing, clients, matching

GAP_MONTHS_BACK = 6
#: Dopasowanie nie znalazło osoby ani kwoty; pozostałe powody mówią o czym innym.
GAP_REASONS = ("no_orders", "amount_differs", "expected_unknown")


@dataclass(frozen=True)
class LineGap:
    invoice_id: int
    invoice_number: str
    client_id: int
    year: int
    month: int
    candidate_id: int
    person: str

    @property
    def entity_key(self) -> str:
        return f"invoice:{self.invoice_id}:candidate:{self.candidate_id}"


def _months_back(today: date, months: int) -> tuple[int, int]:
    index = today.year * 12 + today.month - 1 - months
    return index // 12, index % 12 + 1


def _item_names(invoice: ClientSalesInvoice) -> list[str]:
    return [
        str(item.get("name") or "")
        for item in invoice.items or []
        if isinstance(item, dict) and not item.get("before_correction")
    ]


async def _waiting_invoices(db: AsyncSession, today: date) -> list[ClientSalesInvoice]:
    year, month = _months_back(today, GAP_MONTHS_BACK)
    return list(
        await db.scalars(
            select(ClientSalesInvoice)
            .where(
                ClientSalesInvoice.match_status == "unmatched",
                ClientSalesInvoice.match_reason.in_(GAP_REASONS),
                ClientSalesInvoice.client_id.is_not(None),
                ClientSalesInvoice.invoice_kind == "original",
                ClientSalesInvoice.period_year.is_not(None),
                or_(
                    ClientSalesInvoice.period_year > year,
                    and_(
                        ClientSalesInvoice.period_year == year,
                        ClientSalesInvoice.period_month >= month,
                    ),
                ),
            )
            .order_by(ClientSalesInvoice.id)
        )
    )


async def _contract_people(
    db: AsyncSession, members: set[int]
) -> list[tuple[int, str]]:
    rows = await db.execute(
        select(Candidate.id, Candidate.name, Candidate.lastname)
        .join(Contract, Contract.candidate_id == Candidate.id)
        .where(Contract.client_id.in_(members), Contract.status != ContractStatus.void)
        .distinct()
    )
    return [
        (int(candidate_id), f"{name or ''} {lastname or ''}".strip())
        for candidate_id, name, lastname in rows
    ]


async def _order_people(
    db: AsyncSession, rows: Iterable[billing.BillingRow]
) -> list[str]:
    """Osoby z pozycji zamówień miesiąca, po zamówieniach, nie po tekście pozycji.

    Pozycja kosztowa ma nazwiska po przecinku, a wspólna pula „N os.”, więc tekst
    pozycji fałszywie mówiłby, że ktoś pozycji nie ma, i kusił do dopisania duplikatu.
    """

    order_ids = {order_id for row in rows for order_id in row.member_ids}
    order_ids |= {row.order_id for row in rows if row.order_id}
    order_ids |= {line.order_id for row in rows for line in row.lines if line.order_id}
    if not order_ids:
        return []
    rows_found = await db.execute(
        select(Candidate.name, Candidate.lastname)
        .join(Contract, Contract.candidate_id == Candidate.id)
        .join(ClientOrder, ClientOrder.contract_id == Contract.id)
        .where(ClientOrder.id.in_(order_ids))
        .distinct()
    )
    return [f"{name or ''} {lastname or ''}".strip() for name, lastname in rows_found]


async def line_gaps(db: AsyncSession, today: date) -> list[LineGap]:
    """Osoby z faktur czekających na Finanse, które nie mają pozycji w miesiącu faktury."""

    gaps: list[LineGap] = []
    people: dict[int, list[tuple[int, str]]] = {}
    lines: dict[tuple[int, int, int], list[str]] = {}
    for invoice in await _waiting_invoices(db, today):
        client_id = int(invoice.client_id)
        period = (client_id, int(invoice.period_year), int(invoice.period_month))
        members = await clients.family(db, [client_id])
        if client_id not in people:
            people[client_id] = await _contract_people(db, members)
        if period not in lines:
            rows = await billing.billing_rows(
                db, year=period[1], month=period[2], client_ids=members
            )
            lines[period] = await _order_people(db, rows)
        for item_name in _item_names(invoice):
            if any(
                matching.person_named_in(person, item_name) for person in lines[period]
            ):
                continue
            for candidate_id, person in people[client_id]:
                if matching.person_named_in(person, item_name):
                    gaps.append(
                        LineGap(
                            invoice_id=invoice.id,
                            invoice_number=invoice.invoice_number,
                            client_id=client_id,
                            year=period[1],
                            month=period[2],
                            candidate_id=candidate_id,
                            person=person,
                        )
                    )
    return list({gap.entity_key: gap for gap in gaps}.values())


__all__ = ["GAP_MONTHS_BACK", "GAP_REASONS", "LineGap", "line_gaps"]
