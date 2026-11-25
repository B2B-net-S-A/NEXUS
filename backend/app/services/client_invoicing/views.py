"""Odczyty modułu: zakładka „Faktury” klienta, lista Finansów, zaległości, wpłaty.

Kwoty wychodzą jako tekst dziesiętny z kropką (jak w module Płac). Zakres
klientów i prawo do kwot sprawdza warstwa tras (``api/client_sales_invoices``);
tu funkcje dostają już dozwolony zbiór klientów.

Stan wiersza „do faktury” (zamówienie w miesiącu):

* ``not_invoiced`` — brak faktury z KSeF; ``sheet`` — brak faktury z KSeF,
  ale arkusz Finansów (import) ma kwotę „Faktura” (zapas),
* ``ok`` / ``accepted`` — faktury zgodne co do grosza / różnica uznana,
* ``partial`` — faktury zgodne, ale nie na całość (np. faktura na jedną
  z dwóch osób zamówienia),
* ``difference`` — różnica do sprawdzenia przez Finanse,
* ``unknown`` — kwoty „do faktury” nie da się policzyć (brak zużycia MD).

Zamówienie kosztowe (wiersz z ``budget``) nie ma kwoty „do faktury”: ``ok`` —
faktury mieszczą się w tym, co zostało z budżetu przed tym miesiącem,
``difference`` — ponad budżet (różnica = nadwyżka), do sprawdzenia przez Finanse.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client, ClientStatus
from app.models.client_buyer_number import ClientBuyerNumber
from app.models.client_sales_invoice import ClientSalesInvoice
from app.services.client_identity import (
    client_display_name,
    visible_client_predicates,
)
from app.services.client_invoicing import (
    billing,
    clients,
    ledger,
    matching,
    payment_proof,
    payments,
    receivables,
)
from app.services.client_invoicing.billing import BillingRow, money, plain
from app.services.client_invoicing.ledger import ZERO, Chain, ChainCheck
from app.services.client_invoicing.payment_proof import Proof, Verdict
from app.services.order_client_identity import is_eu_buyer_number

ROW_STATUS_LABELS = {
    "not_invoiced": "jeszcze nie wystawiona",
    "sheet": "wg arkusza Finansów",
    "ok": "zgodna",
    "accepted": "różnica uznana",
    "partial": "część pozycji bez faktury",
    "difference": "różnica do sprawdzenia",
    "unknown": "czeka na zużycie MD",
}
#: Zamówienie kosztowe porównuje fakturę z budżetem, nie z kwotą „do faktury”.
COST_STATUS_LABELS = {
    "ok": "mieści się w budżecie",
    "difference": "ponad budżet — do sprawdzenia",
}
KIND_LABELS = {"md": "MD", "cost": "kosztowe", "periodic": "okresowe"}
_SEVERITY = {"difference": 3, "unknown": 2, "partial": 1}


def _amount(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format(money(Decimal(value)), "f")


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def _period_text(period: Optional[tuple[int, int]]) -> Optional[str]:
    return billing.month_key(*period) if period else None


def line_payload(line: billing.BillingLine) -> dict[str, Any]:
    return {
        "order_id": line.order_id,
        "consultant": line.consultant,
        "basis": line.basis,
        "unit": line.unit,
        "quantity": plain(line.quantity),
        "unit_price": plain(line.unit_price),
        "net": _amount(line.net),
        "currency": line.currency,
        "note": line.note,
        "sheet_invoiced": _amount(line.sheet_invoiced),
    }


def chain_payload(
    chain: Chain,
    result: ChainCheck,
    today: date,
    *,
    names: Optional[dict[int, str]] = None,
    labels: Optional[dict[str, str]] = None,
    verdict: Optional[Verdict] = None,
) -> dict[str, Any]:
    """Faktura (łańcuch) do ekranu; ``verdict`` z ``payment_proof`` — bez niego
    termin za sobą bez zapłaty to brak danych, nigdy zaległość."""

    head = chain.head
    reason = chain.match_reason
    if verdict is None:
        verdict = Verdict(unknown=chain.overdue_days(today) > 0)
    return {
        "id": head.id,
        "invoice_number": head.invoice_number,
        "ksef_number": head.ksef_number,
        "invoice_kind": head.invoice_kind,
        "issue_date": _iso(head.issue_date),
        "due_date": _iso(head.due_date),
        "period": _period_text(chain.period),
        "period_source": head.period_source,
        "currency": head.currency,
        "net": _amount(chain.net),
        "gross": _amount(chain.gross),
        "client_id": head.client_id,
        "client_name": (names or {}).get(head.client_id) if head.client_id else None,
        "buyer_name": head.buyer_name,
        "buyer_nip": head.buyer_nip,
        "buyer_foreign_id": head.buyer_foreign_id,
        "buyer_number_kind": _number_kind(matching.buyer_number(head)),
        "corrections": [
            {
                "id": c.id,
                "invoice_number": c.invoice_number,
                "ksef_number": c.ksef_number,
                "issue_date": _iso(c.issue_date),
                "net": _amount(c.net_amount),
                "gross": _amount(c.gross_amount),
            }
            for c in chain.corrections
        ],
        "match_status": chain.match_status,
        "match_method": head.match_method,
        "match_reason": reason,
        "match_reason_text": matching.REASON_LABELS.get(reason or "")
        if reason
        else None,
        "ignore_reason": head.ignore_reason,
        "targets": [
            {
                "group_id": link.order_group_id,
                "order_id": link.order_id,
                "label": (labels or {}).get(
                    f"g{link.order_group_id}"
                    if link.order_group_id is not None
                    else f"o{link.order_id}"
                ),
            }
            for link in chain.links
        ],
        "check": result.status,
        "check_basis": result.basis,
        "expected": _amount(result.expected),
        "difference": _amount(result.difference),
        "difference_accepted": (
            {
                "amount": _amount(head.difference_accepted_amount),
                "reason": head.difference_reason,
                "at": head.difference_accepted_at.isoformat()
                if head.difference_accepted_at
                else None,
            }
            if head.difference_accepted_amount is not None
            else None
        ),
        "payment_status": chain.payment_status,
        "paid": _amount(chain.paid),
        "to_pay": _amount(chain.to_pay),
        "paid_on": _iso(chain.paid_on),
        # „Po terminie” tylko z dowodem z wyciągów (``payment_proof``): dni do
        # ostatniego dnia ich ciągłości. Bez dowodu — brak danych z powodem.
        "overdue_days": verdict.overdue_days,
        "payment_unknown": verdict.unknown,
        "payment_unknown_reason": verdict.reason,
        "payment_account": verdict.account,
        "statements_until": _iso(verdict.until),
    }


def _row_keys_for(chain: Chain, rows: dict[str, BillingRow]) -> set[str]:
    line_rows = {
        line.order_id: row.key
        for row in rows.values()
        if row.group_id is not None
        for line in row.lines
        if line.order_id
    }
    line_rows.update(
        {order_id: row.key for row in rows.values() for order_id in row.member_ids}
    )
    keys: set[str] = set()
    for link in chain.links:
        if link.order_group_id is not None:
            key = f"g{link.order_group_id}"
            if key in rows:
                keys.add(key)
        elif f"o{link.order_id}" in rows:
            keys.add(f"o{link.order_id}")
        elif link.order_id in line_rows:
            keys.add(line_rows[link.order_id])
    return keys


def row_status(
    row: BillingRow, attached: list[tuple[Chain, ChainCheck]], single: bool
) -> tuple[str, Optional[Decimal], Optional[Decimal]]:
    """(stan, zafakturowano netto, różnica) wiersza „do faktury”."""

    if not attached:
        return ("sheet" if row.sheet_invoiced else "not_invoiced"), None, None
    invoiced = money(sum((chain.order_net for chain, _ in attached), ZERO))
    checks = {result.status for _, result in attached}
    if row.budget is not None:
        return _budget_status(row.budget.available, attached, single, invoiced, checks)
    expected = row.expected_net
    difference = money(invoiced - expected) if single and expected is not None else None
    if "difference" in checks:
        return "difference", invoiced, difference
    if "unknown" in checks or (single and expected is None):
        return "unknown", invoiced, None
    # Uznane różnice faktur tłumaczą różnicę wiersza; reszta to brak faktury.
    accepted = _accepted(attached)
    if single and difference is not None and difference != accepted:
        return "partial", invoiced, difference
    return ("accepted" if "accepted" in checks else "ok"), invoiced, difference


def _accepted(attached: list[tuple[Chain, ChainCheck]]) -> Decimal:
    return money(
        sum(
            (
                result.difference or ZERO
                for _, result in attached
                if result.status == "accepted"
            ),
            ZERO,
        )
    )


def _budget_status(
    available: Decimal,
    attached: list[tuple[Chain, ChainCheck]],
    single: bool,
    invoiced: Decimal,
    checks: set[str],
) -> tuple[str, Optional[Decimal], Optional[Decimal]]:
    """Zamówienie kosztowe: suma faktur wiersza a reszta budżetu przed miesiącem.

    Każda faktura z osobna może się zmieścić, a razem już nie — dlatego przy
    wierszu liczy się suma (gdy faktury dotyczą tylko tego zamówienia).
    """

    over = money(invoiced - available) if single else None
    if "difference" in checks:
        return "difference", invoiced, over
    if "unknown" in checks:
        return "unknown", invoiced, None
    if over is not None and over > ZERO and over != _accepted(attached):
        return "difference", invoiced, over
    return ("accepted" if "accepted" in checks else "ok"), invoiced, None


def row_payload(
    row: BillingRow, attached: list[tuple[Chain, ChainCheck]], single: bool
) -> dict[str, Any]:
    status, invoiced, difference = row_status(row, attached, single)
    labels = COST_STATUS_LABELS if row.budget is not None else {}
    return {
        "key": row.key,
        "kind": row.kind,
        "kind_label": KIND_LABELS.get(row.kind, row.kind),
        "group_id": row.group_id,
        "order_id": row.order_id,
        "client_id": row.client_id,
        "order_number": row.order_number,
        "currency": row.currency,
        "expected_net": _amount(row.expected_net),
        "missing": row.missing,
        "sheet_invoiced": _amount(row.sheet_invoiced),
        "budget": {
            "amount": _amount(row.budget.amount),
            "available": _amount(row.budget.available),
        }
        if row.budget is not None
        else None,
        "lines": [line_payload(line) for line in row.lines],
        "invoice_ids": [chain.head.id for chain, _ in attached],
        "status": status,
        "status_label": labels.get(status, ROW_STATUS_LABELS[status]),
        "invoiced_net": _amount(invoiced),
        "difference": _amount(difference),
    }


def _labels(rows: Iterable[BillingRow]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for row in rows:
        labels[row.key] = row.order_number
        for line in row.lines:
            if line.order_id and row.group_id is not None:
                labels[f"o{line.order_id}"] = f"{row.order_number} · {line.consultant}"
    return labels


def _totals(values: Iterable[tuple[str, Optional[Decimal]]]) -> list[dict[str, str]]:
    sums: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for currency, value in values:
        if value is not None:
            sums[currency] += value
    return [
        {"currency": currency, "amount": _amount(amount) or "0.00"}
        for currency, amount in sorted(sums.items())
    ]


async def month_view(
    db: AsyncSession,
    *,
    year: int,
    month: int,
    client_ids: Optional[Collection[int]],
    today: date,
    proof: Optional[Proof] = None,
) -> dict[str, Any]:
    """Wiersze „do faktury” z fakturami i faktury miesiąca (klient albo wszyscy)."""

    proof = proof or await payment_proof.load(db)
    rows = await billing.billing_rows(db, year=year, month=month, client_ids=client_ids)
    row_map = {row.key: row for row in rows}
    chains = await ledger.chains_for_period(
        db, year=year, month=month, client_ids=client_ids
    )
    by_row: dict[str, list[tuple[Chain, ChainCheck]]] = defaultdict(list)
    single: dict[str, bool] = defaultdict(lambda: True)
    checks: dict[int, ChainCheck] = {}
    for chain in chains:
        result = ledger.check(chain, row_map)
        checks[chain.head.id] = result
        keys = (
            _row_keys_for(chain, row_map) if chain.match_status == "matched" else set()
        )
        for key in keys:
            by_row[key].append((chain, result))
            if len(keys) > 1:
                single[key] = False
    names = await clients.names(
        db,
        {row.client_id for row in rows}
        | {c.head.client_id for c in chains if c.head.client_id},
    )
    labels = _labels(rows)
    row_items = [
        row_payload(row, by_row.get(row.key, []), single[row.key]) for row in rows
    ]
    for item in row_items:
        item["client_name"] = names.get(item["client_id"])
    invoice_items = [
        chain_payload(
            chain,
            checks[chain.head.id],
            today,
            names=names,
            labels=labels,
            verdict=proof.verdict(chain, today),
        )
        for chain in chains
    ]
    statuses = defaultdict(int)
    for item in row_items:
        statuses[item["status"]] += 1
    return {
        "period": billing.month_key(year, month),
        "rows": row_items,
        "invoices": invoice_items,
        "summary": {
            "rows": len(row_items),
            "not_invoiced": statuses["not_invoiced"] + statuses["sheet"],
            "invoiced": len(row_items) - statuses["not_invoiced"] - statuses["sheet"],
            "differences": statuses["difference"],
            "unknown": statuses["unknown"],
            # Bez kwoty „do faktury” — tych zamówień nie ma w sumie netto.
            "cost": sum(1 for row in rows if row.budget is not None),
            "unmatched_invoices": sum(
                1 for item in invoice_items if item["match_status"] == "unmatched"
            ),
            "expected": _totals((row.currency, row.expected_net) for row in rows),
            "invoiced_net": _totals(
                (chain.head.currency, chain.net)
                for chain in chains
                if chain.match_status == "matched"
            ),
        },
    }


@dataclass(frozen=True)
class Late:
    """Łańcuch z terminem za sobą i jego werdykt (``payment_proof``)."""

    chain: Chain
    verdict: Verdict
    #: Nieopłacony VAT faktury walutowej (w walucie faktury), ``receivables.vat_gap``.
    vat: Optional[Decimal] = None
    vat_pln: Optional[Decimal] = None
    rate: Optional[receivables.Rate] = None

    @property
    def proven(self) -> bool:
        return self.verdict.overdue_days > 0


async def late_chains(
    db: AsyncSession,
    chains: Iterable[Chain],
    *,
    day: date,
    proof: Proof,
) -> list[Late]:
    """Werdykty łańcuchów z terminem przed ``day``; VAT w PLN z dowodem z rachunku PLN."""

    late = [chain for chain in chains if chain.overdue_days(day) > 0]
    gaps = {chain.head.id: receivables.vat_gap(chain) for chain in late}
    rates = await receivables.rates(
        db, [chain for chain in late if gaps[chain.head.id] is not None]
    )
    out = []
    for chain in late:
        vat = gaps[chain.head.id]
        if vat is None:
            out.append(Late(chain, proof.verdict(chain, day)))
            continue
        rate = rates.get(chain.head.id)
        vat_pln = receivables.to_pln(vat, rate)
        verdict = proof.verdict(chain, day, currency="PLN", amount=vat_pln)
        out.append(Late(chain, verdict, vat, vat_pln, rate))
    return out


def vat_payload(item: Late) -> Optional[dict[str, Any]]:
    if item.vat is None:
        return None
    return {
        "vat": _amount(item.vat),
        "currency": item.chain.head.currency,
        "vat_pln": _amount(item.vat_pln),
        "rate": str(item.rate.rate) if item.rate else None,
        "rate_date": _iso(item.rate.day) if item.rate else None,
        "rate_source": item.rate.source if item.rate else None,
    }


def late_payload(
    item: Late,
    today: date,
    *,
    names: dict[int, str],
    rows: dict[tuple[int, int], dict[str, BillingRow]],
) -> dict[str, Any]:
    chain = item.chain
    payload = chain_payload(
        chain,
        ledger.check(chain, rows.get(chain.period or (0, 0), {})),
        today,
        names=names,
        verdict=item.verdict,
    )
    payload["vat_pln_unpaid"] = vat_payload(item)
    payload["escalation"] = receivables.escalation(item.verdict.overdue_days)
    return payload


def vat_summary(items: Iterable[Late]) -> dict[str, Any]:
    """Faktury walutowe z dowodem, że VAT w PLN nie wpłynął."""

    proven = [item for item in items if item.vat is not None and item.proven]
    known = [item.vat_pln for item in proven if item.vat_pln is not None]
    return {
        "count": len(proven),
        "total_pln": _amount(money(sum(known, ZERO))) if known else None,
        "without_rate": len(proven) - len(known),
    }


async def overdue(
    db: AsyncSession,
    *,
    client_ids: Optional[Collection[int]],
    today: date,
    proof: Optional[Proof] = None,
) -> dict[str, Any]:
    """Zaległości z dowodem z wyciągów i liczba faktur bez danych o zapłacie.

    Zapłatę NEXUS zna tylko z uznań na wyciągach (E8), ręcznego „opłacono”
    i lustra eBI24. 19.11.2026 firma miała 2 741 faktur „po terminie”, żadnej
    z datą zapłaty, bo wyciągi były z jednego dnia. Teraz faktura jest na liście
    tylko wtedy, gdy ``payment_proof`` to udowodni (rachunek odbioru w Księdze,
    ciągłe wyciągi od wystawienia do dnia po terminie, bez kompensaty i bez
    wpłaty do sprawdzenia); reszta jest w ``payment_unknown`` z powodami
    (``docs/claude/zamowienia/faktury-do-klientow-z-ksef.md``). Faktura walutowa
    z wpłaconym netto i bez VAT idzie z wyciągów rachunku PLN i ma
    ``vat_pln_unpaid`` (``docs/claude/zamowienia/monity-i-naleznosci-po-terminie.md``).
    """

    proof = proof or await payment_proof.load(db)
    items = await late_chains(
        db, await ledger.open_chains(db, client_ids=client_ids), day=today, proof=proof
    )
    proven = sorted(
        (item for item in items if item.proven),
        key=lambda i: (-i.verdict.overdue_days, i.chain.head.id),
    )
    names = await clients.names(
        db, {i.chain.head.client_id for i in proven if i.chain.head.client_id}
    )
    rows = await ledger.rows_by_period(db, [item.chain for item in proven])
    unknown = [item.verdict for item in items if item.verdict.unknown]
    return {
        "invoices": [
            late_payload(item, today, names=names, rows=rows) for item in proven
        ],
        "payment_unknown": len(unknown),
        "payment_unknown_reasons": payment_proof.reasons_summary(unknown),
        "vat_pln_unpaid": vat_summary(items),
    }


async def client_view(
    db: AsyncSession, *, client_id: int, year: int, month: int, today: date
) -> dict[str, Any]:
    members = await clients.family(db, [client_id])
    proof = await payment_proof.load(db)
    payload = await month_view(
        db, year=year, month=month, client_ids=members, today=today, proof=proof
    )
    late = await overdue(db, client_ids=members, today=today, proof=proof)
    payload["overdue"] = late["invoices"]
    payload["summary"]["overdue"] = len(late["invoices"])
    payload["summary"]["payment_unknown"] = late["payment_unknown"]
    payload["summary"]["payment_unknown_reasons"] = late["payment_unknown_reasons"]
    return payload


async def client_summary(
    db: AsyncSession, *, year: int, month: int, today: date
) -> list[dict[str, Any]]:
    """„Do faktury” wszystkich klientów w miesiącu — przegląd Finansów."""

    payload = await month_view(db, year=year, month=month, client_ids=None, today=today)
    grouped: dict[int, dict[str, Any]] = {}
    for item in payload["rows"]:
        entry = grouped.setdefault(
            item["client_id"],
            {
                "client_id": item["client_id"],
                "client_name": item.get("client_name"),
                "rows": 0,
                "statuses": defaultdict(int),
                "expected": [],
                "incomplete": False,
            },
        )
        entry["rows"] += 1
        # Niepełna suma = brak zużycia MD albo stawki; kosztowe mają kwotę od Finansów.
        entry["incomplete"] = entry["incomplete"] or item["missing"] > 0
        entry["statuses"][item["status"]] += 1
        entry["expected"].append((item["currency"], item["expected_net"]))
    out = []
    for entry in grouped.values():
        out.append(
            {
                "client_id": entry["client_id"],
                "client_name": entry["client_name"],
                "rows": entry["rows"],
                "statuses": dict(entry["statuses"]),
                "expected": _totals(
                    (currency, Decimal(value) if value is not None else None)
                    for currency, value in entry["expected"]
                ),
                "incomplete": entry["incomplete"],
            }
        )
    return sorted(out, key=lambda e: (e["client_name"] or "").lower())


async def credits_view(db: AsyncSession, *, today: date) -> list[dict[str, Any]]:
    """Wpłaty z wyciągu do sprawdzenia, z podpowiedzią faktur o tej kwocie."""

    lines = await payments.unmatched_credits(db)
    if not lines:
        return []
    # Bez zapłat z eBI24: uznanie z wyciągu je zastępuje (``payments.own_to_pay``).
    chains = await ledger.open_chains(db, client_ids=None, own=True)
    names = await clients.names(
        db, {c.head.client_id for c in chains if c.head.client_id}
    )
    out = []
    for line in lines:
        hints = [
            {
                "invoice_id": chain.head.id,
                "invoice_number": chain.head.invoice_number,
                "client_name": names.get(chain.head.client_id)
                if chain.head.client_id
                else chain.head.buyer_name,
                "to_pay": _amount(chain.own_to_pay),
                "currency": chain.head.currency,
            }
            for chain in chains
            if chain.head.currency == line.currency
            and chain.own_to_pay == money(line.amount)
        ][:5]
        out.append(
            {
                "id": line.id,
                "booked_on": _iso(line.booked_on),
                "amount": _amount(line.amount),
                "currency": line.currency,
                "title": line.title or "",
                "counterparty_name": line.counterparty_name,
                "reason": line.reason,
                "hints": hints,
            }
        )
    return out


async def chain_for(db: AsyncSession, invoice_id: int) -> Optional[Chain]:
    invoice = await db.get(ClientSalesInvoice, invoice_id)
    if invoice is None:
        return None
    for chain in await ledger.build_chains(db, [invoice]):
        if invoice.id in {i.id for i in chain.invoices}:
            return chain
    return None


async def invoice_detail(
    db: AsyncSession, chain: Chain, *, today: date
) -> dict[str, Any]:
    rows = await ledger.rows_by_period(db, [chain])
    row_map = rows.get(chain.period or (0, 0), {})
    names = await clients.names(
        db, [chain.head.client_id] if chain.head.client_id else []
    )
    proof = await payment_proof.load(db)
    payload = chain_payload(
        chain,
        ledger.check(chain, row_map),
        today,
        names=names,
        labels=_labels(row_map.values()),
        verdict=proof.verdict(chain, today),
    )
    payload["items"] = chain.head.items
    payload["order_refs"] = chain.head.order_refs
    payload["payments"] = [
        {
            "id": p.id,
            "kind": p.kind,
            "amount": _amount(p.amount),
            "booked_on": _iso(p.booked_on),
            "title": p.title,
            "reason": p.reason,
        }
        for p in chain.payments
    ]
    return payload


async def buyer_number_view(
    db: AsyncSession, invoice: ClientSalesInvoice, client_id: int
) -> dict[str, Any]:
    """Numer nabywcy względem klienta wybranego w „Przypisz”."""

    number = matching.buyer_number(invoice)
    check = await clients.check_buyer_number(db, client_id, number)
    known = await clients.names(
        db, [cid for cid in (check.client_id, check.owner_id) if cid is not None]
    )
    waiting = (
        await matching.waiting_for_number(db, check.number)
        if check.state in ("add", "differs")
        else 0
    )
    waits_itself = (
        invoice.match_status == "unmatched" and invoice.match_reason == "unknown_buyer"
    )
    return {
        "state": check.state,
        "number": check.number,
        "kind": _number_kind(number) or "nip",
        "client_name": known.get(check.client_id) if check.client_id else None,
        "existing": check.existing,
        "owner_name": known.get(check.owner_id) if check.owner_id else None,
        "other_waiting": max(waiting - int(waits_itself), 0),
    }


async def assignment_options(
    db: AsyncSession, *, client_id: int, year: int, month: int
) -> list[dict[str, Any]]:
    """Zamówienia klienta w miesiącu do „Przypisz” (całe zamówienie albo osoba)."""

    members = await clients.family(db, [client_id])
    rows = await billing.billing_rows(db, year=year, month=month, client_ids=members)
    out = []
    for row in rows:
        out.append(
            {
                "group_id": row.group_id,
                "order_id": row.order_id,
                "label": row.order_number,
                "kind": row.kind,
                "expected_net": _amount(row.expected_net),
                "currency": row.currency,
            }
        )
        if row.group_id is not None:
            for line in row.lines:
                if line.order_id:
                    out.append(
                        {
                            "group_id": None,
                            "order_id": line.order_id,
                            "label": f"{row.order_number} · {line.consultant}",
                            "kind": row.kind,
                            "expected_net": _amount(line.net),
                            "currency": line.currency,
                        }
                    )
    return out


# ── Nieznani nabywcy ─────────────────────────────────────────────────────────


def _name_key(name: Optional[str]) -> str:
    return " ".join((name or "").casefold().split())


async def _suggestions_by_name(db: AsyncSession) -> dict[str, list[Client]]:
    """Klienci po nazwie: prawnej, wyświetlanej i źródłowej, bez nieaktywnych."""

    found: dict[str, dict[int, Client]] = defaultdict(dict)
    for client in await db.scalars(
        select(Client).where(
            *visible_client_predicates(), Client.status != ClientStatus.inactive
        )
    ):
        for name in (client.legal_name, client.display_name, client.name):
            key = _name_key(name)
            if key:
                found[key][client.id] = client
    return {key: list(by_id.values()) for key, by_id in found.items()}


def _suggestion(
    name: Optional[str], by_name: dict[str, list[Client]]
) -> Optional[dict[str, Any]]:
    """Podpowiedź tylko jednoznaczna: dwóch klientów o tej nazwie to nie podpowiedź."""

    matches = by_name.get(_name_key(name), [])
    if len(matches) != 1:
        return None
    client = matches[0]
    return {
        "client_id": client.id,
        "client_name": client_display_name(client),
        "state": "differs" if (client.nip or "").strip() else "add",
    }


def _number_kind(number: Optional[str]) -> Optional[str]:
    if number is None:
        return None
    if number.isdigit():
        return "nip"
    return "vat_ue" if is_eu_buyer_number(number) else "foreign_id"


def _invoice_period_rows(
    invoices: Iterable[ClientSalesInvoice],
) -> tuple[list[dict[str, str]], Optional[date], Optional[date], Optional[str]]:
    """Sumy netto per waluta, zakres dat i najnowsza nazwa nabywcy."""

    ordered = sorted(invoices, key=lambda invoice: (invoice.issue_date, invoice.id))
    return (
        _totals((invoice.currency, invoice.net_amount) for invoice in ordered),
        ordered[0].issue_date if ordered else None,
        ordered[-1].issue_date if ordered else None,
        next(
            (invoice.buyer_name for invoice in reversed(ordered) if invoice.buyer_name),
            None,
        ),
    )


async def unknown_buyers(db: AsyncSession) -> dict[str, Any]:
    """Kolejka „Nieznani nabywcy”: faktury bez klienta ze wszystkich miesięcy, po numerze."""

    invoices = list(
        await db.scalars(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.match_status == "unmatched",
                ClientSalesInvoice.match_reason == "unknown_buyer",
            )
        )
    )
    by_number: dict[Optional[str], list[ClientSalesInvoice]] = defaultdict(list)
    for invoice in invoices:
        by_number[matching.buyer_number(invoice)].append(invoice)
    by_name = await _suggestions_by_name(db)
    buyers = []
    for number, group in by_number.items():
        totals, first_date, last_date, buyer_name = _invoice_period_rows(group)
        buyers.append(
            {
                "number": number,
                "kind": _number_kind(number),
                "buyer_name": buyer_name,
                "invoices": len(group),
                "totals": totals,
                "first_date": _iso(first_date),
                "last_date": _iso(last_date),
                "assignable": clients.is_registry_key(number),
                "suggestion": _suggestion(buyer_name, by_name),
            }
        )
    buyers.sort(key=lambda b: (-b["invoices"], (b["buyer_name"] or "").lower()))
    return {
        "buyers": buyers,
        "summary": {
            "invoices": len(invoices),
            "buyers": sum(1 for buyer in buyers if buyer["number"] is not None),
            "with_suggestion": sum(1 for buyer in buyers if buyer["suggestion"]),
            "totals": _totals((inv.currency, inv.net_amount) for inv in invoices),
        },
    }


async def extra_buyer_numbers(db: AsyncSession) -> list[dict[str, Any]]:
    """Dodatkowe numery nabywcy (0779) z nazwą klienta i liczbą faktur u niego."""

    rows = list(
        await db.scalars(
            select(ClientBuyerNumber).order_by(
                ClientBuyerNumber.created_at.desc(), ClientBuyerNumber.id.desc()
            )
        )
    )
    known = await clients.names(db, [row.client_id for row in rows])
    number = func.coalesce(
        ClientSalesInvoice.buyer_nip, ClientSalesInvoice.buyer_foreign_id
    )
    counts: dict[str, int] = {}
    if rows:
        found = await db.execute(
            select(number, func.count())
            .where(number.in_([row.number for row in rows]))
            .group_by(number)
        )
        counts = {key: int(count) for key, count in found.all()}
    return [
        {
            "id": row.id,
            "client_id": row.client_id,
            "client_name": known.get(row.client_id),
            "number": row.number,
            "kind": _number_kind(row.number) or "nip",
            "source": row.source,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "invoices": counts.get(row.number, 0),
        }
        for row in rows
    ]


async def waiting_for_number_view(
    db: AsyncSession, number: Optional[str]
) -> dict[str, Any]:
    """Ramka w formularzu klienta: ile faktur z KSeF czeka na ten numer."""

    invoices = list(
        await db.scalars(
            select(ClientSalesInvoice).where(
                *matching.waiting_for_number_filters(number or "")
            )
        )
    )
    totals, first_date, last_date, buyer_name = _invoice_period_rows(invoices)
    return {
        "number": number,
        "invoices": len(invoices),
        "totals": totals,
        "first_date": _iso(first_date),
        "last_date": _iso(last_date),
        "buyer_name": buyer_name,
    }


__all__ = [
    "COST_STATUS_LABELS",
    "KIND_LABELS",
    "ROW_STATUS_LABELS",
    "assignment_options",
    "buyer_number_view",
    "chain_for",
    "chain_payload",
    "client_summary",
    "client_view",
    "credits_view",
    "extra_buyer_numbers",
    "invoice_detail",
    "line_payload",
    "month_view",
    "overdue",
    "row_payload",
    "row_status",
    "unknown_buyers",
    "waiting_for_number_view",
]
