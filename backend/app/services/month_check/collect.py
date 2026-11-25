"""Wejście kontroli miesiąca z bazy (``rules.Inputs``).

* **Pozycja faktury do klienta → osoba** — jak historia stawek z KSeF
  (``contract_rate_history.collect.match_item``): numer osoby u klienta
  (Nordea, ``client_external_ids``), potem pełne imię i nazwisko osoby
  z kontraktem u klienta trwającym w miesiącu, a gdy żadna pozycja faktury nie
  nazywa nikogo — jedyny kontrakt z zamówień, do których NEXUS przypiął fakturę
  (BNP: numer zamówienia). Faktura to stan po korektach (pozycje „przed
  korektą” zdejmują pozycje, „po” dochodzą).
* **Faktura konsultanta → osoba** — zakupy z KSeF (``approval_documents``):
  NIP sprzedawcy = NIP osoby (``candidates.nip``, uzupełnia go sam
  ``contractor_nip``), a bez niego pełne imię i nazwisko w nazwie sprzedawcy
  (jedna osoba z kontraktem w NEXUSIE). Do tego faktury już przypięte przez
  rozliczenia (``client_contractor_invoices`` ``known``/``confirmed``)
  z miesiącem z rozliczenia.
* **Klient bez nazwisk** — faktura zbiorcza (``cl.collective_invoice``) albo
  klient, którego faktury w miesiącu nie nazywają nikogo.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.client_settlement import ClientContractorInvoice
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.hr_approval import ApprovalDocument
from app.services.client_invoicing import requirements
from app.services.client_invoicing.unknown_refs import marked_people, same_person
from app.services.client_settlements.contractor_invoices import clean_nip
from app.services.contract_rate_history import collect as rh
from app.services.contract_rate_history import infer
from app.services.hr.calendar import month_days, holiday_name
from app.services.month_check import rules

logger = logging.getLogger(__name__)

PLN = "PLN"
#: Faktura konsultanta po końcu kontraktu: spóźniona albo zła data końca.
RECENT_END = timedelta(days=62)
BOUND_STATES = ("known", "confirmed")
#: Historia faktur konsultanta: od tylu miesięcy przed oknem.
HISTORY_MONTHS = 4


#: „NazwiskoID: M1” — numer osoby sklejony z nazwiskiem (Nordea).
_GLUED_ID = re.compile(r"(?<=[^\sA-Z])ID\s*:")


def match_line(
    world: rh.World, names: dict[int, str], client_id: int, month: str, text: str
) -> Optional[int]:
    """Kontrakt osoby z pozycji faktury do klienta albo ``None``.

    Najpierw reguła historii stawek (numer osoby, pełne imię i nazwisko), potem
    osoba po znaczniku „Contractor”/„Konsultant” ze skrótem podwójnego nazwiska
    albo literówką (``unknown_refs.same_person``) — jedna osoba z kontraktem
    u klienta trwającym w miesiącu.
    """

    text = _GLUED_ID.sub(" ID:", text)
    found = rh.match_item(world, client_id, month, text)
    if found is not None:
        return found
    marked = marked_people(text)
    if len(marked) != 1:
        return None
    live = [
        c
        for c in world.by_client.get(client_id, [])
        if c.live_in(month) and same_person(names.get(c.candidate_id, ""), marked[0])
    ]
    return (
        live[0].id
        if len({c.candidate_id for c in live}) == 1 and len(live) == 1
        else None
    )


def working_days(month: str) -> int:
    year, mon = int(month[:4]), int(month[5:7])
    return sum(
        1 for d in month_days(year, mon) if d.weekday() < 5 and holiday_name(d) is None
    )


def _first(month: str) -> date:
    return infer.month_start(month)


def _last(month: str) -> date:
    return rh.month_last(month)


def _unit_hours_factor(unit: Any) -> Optional[Decimal]:
    value = unit.value if isinstance(unit, RateUnit) else unit
    if value == RateUnit.hourly.value:
        return Decimal(1)
    if value == RateUnit.daily.value:
        return Decimal(1) / rules.HOURS_PER_DAY
    return None


def chain_items(
    root: ClientSalesInvoice, corrections: Iterable[ClientSalesInvoice]
) -> list[dict]:
    """Pozycje faktury po wszystkich korektach (jak audyt 25.11.2026)."""

    state = [
        dict(i)
        for i in root.items or []
        if isinstance(i, dict) and not i.get("before_correction")
    ]
    for cor in sorted(corrections, key=lambda r: (r.issue_date, r.id)):
        items = [i for i in cor.items or [] if isinstance(i, dict)]
        for before in (i for i in items if i.get("before_correction")):
            name, net = before.get("name") or "", str(before.get("net"))
            index = next(
                (
                    n
                    for n, cur in enumerate(state)
                    if (cur.get("name") or "") == name and str(cur.get("net")) == net
                ),
                None,
            )
            if index is None:
                index = next(
                    (
                        n
                        for n, cur in enumerate(state)
                        if (cur.get("name") or "") == name
                    ),
                    None,
                )
            if index is not None:
                state.pop(index)
        state.extend(dict(i) for i in items if not i.get("before_correction"))
    return state


def _root_of(
    invoice: ClientSalesInvoice, by_id: dict[int, ClientSalesInvoice]
) -> ClientSalesInvoice:
    seen: set[int] = set()
    current = invoice
    while (
        current.invoice_kind == "correction"
        and current.corrects_invoice_id
        and current.id not in seen
    ):
        seen.add(current.id)
        nxt = by_id.get(current.corrects_invoice_id)
        if nxt is None:
            break
        current = nxt
    return current


async def _canonical(db: AsyncSession) -> dict[int, int]:
    rows = (await db.execute(select(Client.id, Client.merged_into_client_id))).all()
    parent = {int(i): (int(m) if m else None) for i, m in rows}
    out: dict[int, int] = {}
    for cid in parent:
        cur, seen = cid, set()
        while parent.get(cur) and cur not in seen:
            seen.add(cur)
            cur = parent[cur]
        out[cid] = cur
    return out


async def load_inputs(
    db: AsyncSession, today: date, months: Optional[list[str]] = None
) -> tuple[rules.Inputs, dict[str, Any]]:
    """Wejście reguły i surowe liczniki (do pomiaru) dla zamkniętych miesięcy."""

    months = months or rules.closed_months(today)
    first, last = months[0], months[-1]
    window = [rules.shift(first, -1)] + list(months) + [rules.shift(last, 1)]
    canon = await _canonical(db)

    contracts = (
        await db.scalars(
            select(Contract)
            .where(
                Contract.candidate_id.is_not(None),
                Contract.voided_at.is_(None),
                Contract.status != ContractStatus.void,
            )
            .options(selectinload(Contract.candidate_rate_schedule))
        )
    ).all()
    rows: dict[int, rh.ContractRow] = {}
    unit_of: dict[int, Optional[Decimal]] = {}
    currency_of: dict[int, str] = {}
    cost_steps: dict[int, tuple[infer.Step, ...]] = {}
    for c in contracts:
        steps = rh._steps(c.candidate_rate_schedule)
        rows[c.id] = rh.ContractRow(
            id=c.id,
            candidate_id=c.candidate_id,
            client_id=canon.get(c.client_id, c.client_id),
            start_date=c.start_date,
            end_date=c.end_date,
            hourly_pln=False,
            cost_schedule=steps,
            cost_scalar=Decimal(c.rate_candidate)
            if c.rate_candidate is not None
            else None,
        )
        unit_of[c.id] = _unit_hours_factor(c.rate_unit)
        currency_of[c.id] = c.rate_candidate_currency or c.currency or PLN
        cost_steps[c.id] = steps
    world = await rh.load_world(db)
    names = {
        int(i): f"{a or ''} {b or ''}".strip()
        for i, a, b in (
            await db.execute(
                select(Candidate.id, Candidate.name, Candidate.lastname).where(
                    Candidate.id.in_({c.candidate_id for c in rows.values()})
                )
            )
        ).all()
    }
    world = rh.World(
        contracts=rows,
        person_tokens=world.person_tokens,
        person_numbers={
            (canon.get(cl, cl), no): ids
            for (cl, no), ids in world.person_numbers.items()
        },
    )

    # Zamówienia: czy kontrakt ma pozycję w miesiącu.
    orders = (
        await db.execute(
            select(
                ClientOrder.contract_id, ClientOrder.start_date, ClientOrder.end_date
            ).where(
                ClientOrder.contract_id.is_not(None),
                ClientOrder.status != ClientOrderStatus.cancelled,
            )
        )
    ).all()
    order_spans: dict[int, list[tuple[Optional[date], Optional[date]]]] = defaultdict(
        list
    )
    for contract_id, start, end in orders:
        order_spans[int(contract_id)].append((start, end))

    def has_order(contract_id: int, month: str) -> bool:
        lo, hi = _first(month), _last(month)
        return any(
            (s is None or s <= hi) and (e is None or e >= lo)
            for s, e in order_spans.get(contract_id, [])
        )

    context: dict[tuple[int, str], rules.Context] = {}
    for cand, cs in world.by_candidate.items():
        for month in window:
            live = [c for c in cs if c.live_in(month)]
            if live:
                one = live[0] if len(live) == 1 else None
                rate = None
                if one is not None and unit_of.get(one.id) is not None:
                    lo, hi = _first(month), _last(month)
                    changes = any(
                        lo < s.effective_from <= hi for s in cost_steps.get(one.id, ())
                    )
                    base = infer.rate_on(one.cost_schedule, one.cost_scalar, lo)
                    if base is not None and not changes:
                        rate = base * unit_of[one.id]
                context[(cand, month)] = rules.Context(
                    live=tuple(c.id for c in live),
                    contract_id=one.id if one else None,
                    client_id=one.client_id if one else None,
                    rate=rate,
                    rate_currency=currency_of.get(one.id, PLN) if one else PLN,
                    has_order=bool(one and has_order(one.id, month)),
                )
                continue
            ended = [
                c
                for c in cs
                if c.end_date
                and c.end_date < _first(month)
                and _first(month) - c.end_date <= RECENT_END
            ]
            if ended:
                last_c = max(ended, key=lambda c: c.end_date)
                context[(cand, month)] = rules.Context(
                    contract_id=last_c.id, client_id=last_c.client_id, recent=True
                )

    sales, unnamed, unassigned, sales_stats = await _sales(
        db, world, names, canon, window
    )
    costs, cost_stats = await _costs(db, world, rules.shift(first, -HISTORY_MONTHS))
    collective = await _collective_clients(
        db,
        {s.client_id for s in sales} | {cl for m in unnamed.values() for cl in m},
        months,
    )
    for month, ids in collective.items():
        unnamed[month] = unnamed.get(month, set()) | ids
    data = rules.Inputs(
        months=tuple(months),
        today=today,
        sales=tuple(sales),
        costs=tuple(costs),
        context=context,
        unnamed_clients={m: frozenset(v) for m, v in unnamed.items()},
        working_days={m: working_days(m) for m in months},
        unassigned_sales=frozenset(unassigned),
    )
    return data, {
        "sales": sales_stats,
        "costs": cost_stats,
        "collective": {m: sorted(v) for m, v in collective.items()},
    }


async def _sales(
    db: AsyncSession,
    world: rh.World,
    names: dict[int, str],
    canon: dict[int, int],
    window: list[str],
) -> tuple[
    list[rules.SaleLine], dict[str, set[int]], set[tuple[int, str]], dict[str, int]
]:
    years = sorted({int(m[:4]) for m in window})
    invoices = (
        await db.scalars(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.period_year.between(years[0], years[-1]),
                ClientSalesInvoice.match_status != "ignored",
            )
        )
    ).all()
    by_id = {i.id: i for i in invoices}
    # Korekty spoza okresu (inna data) też dociągamy po fakturze korygowanej.
    extra = (
        await db.scalars(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.corrects_invoice_id.in_(list(by_id) or [0]),
                ClientSalesInvoice.id.not_in(list(by_id) or [0]),
            )
        )
    ).all()
    for inv in extra:
        by_id[inv.id] = inv
    chains: dict[int, list[ClientSalesInvoice]] = defaultdict(list)
    roots: dict[int, ClientSalesInvoice] = {}
    for inv in by_id.values():
        root = _root_of(inv, by_id)
        roots[root.id] = root
        if inv is not root:
            chains[root.id].append(inv)
    links = await rh._linked_contracts(db, years[0], years[-1])

    lines: list[rules.SaleLine] = []
    named_clients: dict[str, set[int]] = defaultdict(set)
    seen_clients: dict[str, set[int]] = defaultdict(set)
    stats = {
        "invoices": 0,
        "items": 0,
        "items_with_person": 0,
        "unassigned_invoices": 0,
        "unassigned_lines_by_person": 0,
    }
    unassigned: set[tuple[int, str]] = set()
    for root in roots.values():
        if not root.period_year or not root.period_month:
            continue
        month = f"{root.period_year}-{int(root.period_month):02d}"
        if month not in window:
            continue
        numbers = [root.invoice_number] + [
            c.invoice_number
            for c in sorted(chains.get(root.id, []), key=lambda r: r.issue_date)
        ]
        number = " / ".join(n for n in numbers if n)
        items = chain_items(root, chains.get(root.id, []))
        if root.client_id is None:
            # Faktura w „Nieznani nabywcy”: pozycja z pełnym imieniem i nazwiskiem
            # osoby z jednym trwającym kontraktem idzie do klienta tego kontraktu
            # (jak NIP nabywcy z osób, ``buyer_proof``); reszta tylko wstrzymuje
            # sprawę „koszt bez sprzedaży” tej osoby.
            stats["unassigned_invoices"] += 1
            for item in items:
                person = rh.match_seller(
                    world, _GLUED_ID.sub(" ID:", str(item.get("name") or ""))
                )
                if person is None:
                    continue
                live = [
                    c for c in world.by_candidate.get(person, []) if c.live_in(month)
                ]
                if len(live) != 1:
                    unassigned.add((person, month))
                    continue
                stats["unassigned_lines_by_person"] += 1
                lines.append(
                    _line(world, live[0].id, live[0].client_id, month, number, item)
                )
            continue
        client = canon.get(root.client_id, root.client_id)
        stats["invoices"] += 1
        seen_clients[month].add(client)
        hits = []
        for item in items:
            text = str(item.get("name") or "")
            stats["items"] += 1
            hits.append((match_line(world, names, client, month, text), item))
        linked = set(links.get(root.id, ()))
        for cor in chains.get(root.id, []):
            linked |= set(links.get(cor.id, ()))
        live_links = {
            c
            for c in linked
            if c in world.contracts and world.contracts[c].live_in(month)
        }
        if hits and all(cid is None for cid, _ in hits) and len(live_links) == 1:
            only = next(iter(live_links))
            hits = [(only, item) for _, item in hits]
        for contract_id, item in hits:
            if contract_id is None:
                continue
            stats["items_with_person"] += 1
            named_clients[month].add(client)
            lines.append(_line(world, contract_id, client, month, number, item))
    unnamed = {m: seen_clients[m] - named_clients.get(m, set()) for m in seen_clients}
    return lines, unnamed, unassigned, stats


def _line(
    world: rh.World,
    contract_id: int,
    client_id: int,
    month: str,
    number: str,
    item: dict,
) -> rules.SaleLine:
    per_unit = rh.unit_hours(item.get("unit"))
    qty = rh.dec(item.get("quantity"))
    return rules.SaleLine(
        candidate_id=world.contracts[contract_id].candidate_id,
        contract_id=contract_id,
        client_id=client_id,
        month=month,
        invoice_number=number,
        hours=(qty * per_unit) if (qty is not None and per_unit is not None) else None,
        net=rh.dec(item.get("net")) or Decimal(0),
    )


async def _costs(
    db: AsyncSession, world: rh.World, from_month: str
) -> tuple[list[rules.CostDoc], dict[str, int]]:
    people_with_contract = set(world.by_candidate)
    nip_rows = (
        await db.execute(
            select(Candidate.id, Candidate.nip).where(
                Candidate.nip.is_not(None), Candidate.id.in_(people_with_contract)
            )
        )
    ).all()
    by_nip: dict[str, set[int]] = defaultdict(set)
    for cid, nip in nip_rows:
        clean = clean_nip(nip)
        if clean:
            by_nip[clean].add(int(cid))
    issued_from = _first(from_month)
    stats = {"documents": 0, "by_nip": 0, "by_name": 0, "bound": 0, "unbound": 0}
    docs: list[rules.CostDoc] = []
    seen: set[str] = set()
    bound = (
        await db.execute(
            select(ClientContractorInvoice, Contract.candidate_id)
            .join(Contract, Contract.id == ClientContractorInvoice.contract_id)
            .where(
                ClientContractorInvoice.nip_state.in_(BOUND_STATES),
                ClientContractorInvoice.issue_date >= issued_from,
                ClientContractorInvoice.net_amount.is_not(None),
            )
        )
    ).all()
    for inv, cand in bound:
        seen.add(inv.ksef_number)
        stats["bound"] += 1
        docs.append(
            rules.CostDoc(
                candidate_id=int(cand),
                number=inv.invoice_number or inv.ksef_number,
                issue_date=inv.issue_date,
                net=Decimal(inv.net_amount),
                currency=inv.currency or PLN,
                correction=(inv.invoice_type or "").lower().startswith("kor"),
                fixed_month=inv.period_month,
            )
        )
    approval = (
        await db.scalars(
            select(ApprovalDocument).where(
                ApprovalDocument.source == "ksef",
                ApprovalDocument.issue_date >= issued_from,
                ApprovalDocument.net_amount.is_not(None),
            )
        )
    ).all()
    for doc in approval:
        if doc.ksef_number and doc.ksef_number in seen:
            continue
        stats["documents"] += 1
        owners = by_nip.get(clean_nip(doc.seller_nip) or "", set())
        cand: Optional[int] = next(iter(owners)) if len(owners) == 1 else None
        if cand is not None:
            stats["by_nip"] += 1
        else:
            cand = rh.match_seller(world, doc.seller_name or "")
            if cand is not None:
                stats["by_name"] += 1
        if cand is None:
            stats["unbound"] += 1
            continue
        docs.append(
            rules.CostDoc(
                candidate_id=cand,
                number=doc.invoice_number or doc.ksef_number or str(doc.id),
                issue_date=doc.issue_date,
                net=Decimal(doc.net_amount),
                currency=doc.currency or PLN,
                correction=(doc.ksef_invoice_type or "").lower().startswith("kor"),
            )
        )
    return docs, stats


async def _collective_clients(
    db: AsyncSession, client_ids: set[int], months: list[str]
) -> dict[str, set[int]]:
    out: dict[str, set[int]] = defaultdict(set)
    for client_id in sorted(client_ids):
        for month in months:
            try:
                found = await requirements.load(db, client_id, month)
            except Exception:  # noqa: BLE001 — brak reguł = zwykły klient
                logger.warning("month_check: reguły klienta %s niedostępne", client_id)
                continue
            if found.collective_invoice:
                out[month].add(client_id)
    return dict(out)
