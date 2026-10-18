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
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_sales_invoice import ClientSalesInvoice
from app.services.client_invoicing import billing, clients, ledger, matching, payments
from app.services.client_invoicing.billing import BillingRow, money, plain
from app.services.client_invoicing.ledger import ZERO, Chain, ChainCheck

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
) -> dict[str, Any]:
    head = chain.head
    reason = chain.match_reason
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
        "overdue_days": chain.overdue_days(today),
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
    invoiced = money(sum((chain.net for chain, _ in attached), ZERO))
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
) -> dict[str, Any]:
    """Wiersze „do faktury” z fakturami i faktury miesiąca (klient albo wszyscy)."""

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
        chain_payload(chain, checks[chain.head.id], today, names=names, labels=labels)
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


async def overdue(
    db: AsyncSession, *, client_ids: Optional[Collection[int]], today: date
) -> list[dict[str, Any]]:
    chains = [
        chain
        for chain in await ledger.open_chains(db, client_ids=client_ids)
        if chain.overdue_days(today) > 0
    ]
    names = await clients.names(
        db, {c.head.client_id for c in chains if c.head.client_id}
    )
    rows = await ledger.rows_by_period(db, chains)
    out = []
    for chain in sorted(chains, key=lambda c: (-c.overdue_days(today), c.head.id)):
        result = ledger.check(chain, rows.get(chain.period or (0, 0), {}))
        out.append(chain_payload(chain, result, today, names=names))
    return out


async def client_view(
    db: AsyncSession, *, client_id: int, year: int, month: int, today: date
) -> dict[str, Any]:
    members = await clients.family(db, [client_id])
    payload = await month_view(
        db, year=year, month=month, client_ids=members, today=today
    )
    late = await overdue(db, client_ids=members, today=today)
    payload["overdue"] = late
    payload["summary"]["overdue"] = len(late)
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
    chains = await ledger.open_chains(db, client_ids=None)
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
                "to_pay": _amount(chain.to_pay),
                "currency": chain.head.currency,
            }
            for chain in chains
            if chain.head.currency == line.currency
            and chain.to_pay == money(line.amount)
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
    payload = chain_payload(
        chain,
        ledger.check(chain, row_map),
        today,
        names=names,
        labels=_labels(row_map.values()),
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


__all__ = [
    "COST_STATUS_LABELS",
    "KIND_LABELS",
    "ROW_STATUS_LABELS",
    "assignment_options",
    "chain_for",
    "chain_payload",
    "client_summary",
    "client_view",
    "credits_view",
    "invoice_detail",
    "line_payload",
    "month_view",
    "overdue",
    "row_payload",
    "row_status",
]
