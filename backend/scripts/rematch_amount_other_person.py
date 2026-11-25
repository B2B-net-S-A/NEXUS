"""Faktury dopasowane po kwocie do zamówienia innej osoby — ponowne dopasowanie.

Jednorazowo po wdrożeniu reguły ``amount_other_person`` (audyt luk 25.11.2026,
decyzja Artura). Automat nie wraca do faktur ``matched``, więc przypisania sprzed
reguły zostałyby na złej osobie: kwota pasowała przypadkiem, a pozycja
„Contractor …” nazywa kogoś innego niż osoba z powiązanego zamówienia.

Bierze tylko ``match_method='amount'`` (ręcznych i wystawionych w NEXUSIE nie
rusza). Domyślnie podgląd (bez zapisu). ``--apply`` kasuje powiązania faktury
i puszcza ``matching.auto_match``: faktura trafia do zamówienia osoby z pozycji
albo czeka na Finanse z powodem ``amount_other_person``; korekty idą za nią.
Wynik: JSON z id faktur i decyzją, bez nazwisk i kwot.
"""

import argparse
import asyncio
import json
from collections import Counter

from sqlalchemy import delete, or_, select

from app.core.database import AsyncSessionLocal, engine
from app.models.candidate import Candidate
from app.models.client_order import ClientOrder
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.contract import Contract
from app.services.client_invoicing import matching
from app.services.client_invoicing.unknown_refs import same_person


async def _linked_people(db, invoice_id: int) -> list[str]:
    mine = ClientSalesInvoiceLink.invoice_id == invoice_id
    order_ids = select(ClientSalesInvoiceLink.order_id).where(mine)
    group_ids = select(ClientSalesInvoiceLink.order_group_id).where(mine)
    rows = await db.execute(
        select(Candidate.name, Candidate.lastname)
        .join(Contract, Contract.candidate_id == Candidate.id)
        .join(ClientOrder, ClientOrder.contract_id == Contract.id)
        .where(
            or_(
                ClientOrder.id.in_(order_ids),
                ClientOrder.order_group_id.in_(group_ids),
            )
        )
        .distinct()
    )
    return [f"{name or ''} {lastname or ''}".strip() for name, lastname in rows]


async def _wrong_person(db) -> list[ClientSalesInvoice]:
    invoices = await db.scalars(
        select(ClientSalesInvoice)
        .where(
            ClientSalesInvoice.match_status == "matched",
            ClientSalesInvoice.match_method == "amount",
        )
        .order_by(ClientSalesInvoice.id)
    )
    wrong: list[ClientSalesInvoice] = []
    for invoice in invoices:
        marked = matching._marked_people(invoice.items or [])
        if not marked:
            continue
        people = await _linked_people(db, invoice.id)
        if not any(same_person(person, name) for person in people for name in marked):
            wrong.append(invoice)
    return wrong


async def _rematch(db, invoice: ClientSalesInvoice) -> str:
    await db.execute(
        delete(ClientSalesInvoiceLink).where(
            ClientSalesInvoiceLink.invoice_id == invoice.id
        )
    )
    invoice.match_status = "unmatched"
    invoice.match_method = None
    await db.flush()
    decision = await matching.auto_match(db, invoice)
    if not decision.matched:
        await matching.propagate_to_corrections(db, invoice)
    return decision.method or decision.reason or "unmatched"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    async with AsyncSessionLocal() as db:
        wrong = await _wrong_person(db)
        planned = [invoice.id for invoice in wrong]
        results: dict[int, str] = {}
        if args.apply:
            for invoice in wrong:
                results[invoice.id] = await _rematch(db, invoice)
            await db.commit()
        else:
            await db.rollback()
    await engine.dispose()
    print(
        json.dumps(
            {
                "planned": len(planned),
                "invoice_ids": planned,
                "applied": args.apply,
                "results": Counter(results.values()) if args.apply else None,
                "per_invoice": results if args.apply else None,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
