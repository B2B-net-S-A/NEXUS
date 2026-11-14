"""Rozrachunki (K4b) — zestawienie kontrahentów na dzień i karta konta.

Liczy na pozycjach z ``settlements.load_items`` (żywe dokumenty, D2, „na
dzień”). Zestawienie: otwarte kwoty Wn (należności) i Ma (zobowiązania) per
konto kontrahenta, po terminie i najstarszy termin, wiekowanie obu stron
(przedziały ``settlements.AGING`` i „bez terminu”) oraz podgląd automatu.
Karta konta: pozycje otwarte i rozliczone z rozliczeniami (z czym, kiedy,
jak i kto). Kontrahent konta — z zapisów, a gdy ich brak, z kartoteki po
koncie rozrachunkowym (``revenue_account`` / ``cost_account``) — to drugie
tylko dla Płac (D2: konto osoby z zespołu nie zdradza nazwiska).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_ledger import FinanceCounterparty
from app.models.ledger import LedgerDocument, LedgerLine, LedgerSettlement
from app.models.user import User
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import settlements as core
from app.services.ledger.documents import Viewer
from app.services.ledger.settings import BankSettings
from app.services.ledger.settlements import Item, aging_key, overdue_days

METHOD_LABELS: dict[str, str] = {
    "bank": "z wyciągu",
    "correction": "korekta faktury",
    "zero": "saldo zerowe",
    "manual": "ręcznie",
}
ACCOUNTS_MAX = 500
SETTLED_MAX = 200
SEARCH_MAX = 80
NOT_SETTLEMENT_ACCOUNT = (
    "Konto {account} nie prowadzi rozrachunków z kontrahentami — rozrachunki są "
    "na analityce kont ze słownikiem „kontrahent” (np. 200-NNN)."
)


async def _names(
    db: AsyncSession, items: Iterable[Item], *, fallback: bool
) -> dict[str, dict[str, Any]]:
    """Konto → kontrahent z widocznych zapisów; ``fallback`` — też z kartoteki po koncie.

    Kartoteka po koncie tylko dla Płac (D2): konto osoby z zespołu z samymi
    PK spoza Płac pokazałoby osobie bez Płac nazwisko z kartoteki.
    """

    ids: dict[str, int] = {}
    accounts: set[str] = set()
    for item in items:
        accounts.add(item.account)
        if item.counterparty_id and item.account not in ids:
            ids[item.account] = item.counterparty_id
    missing = accounts - set(ids) if fallback else set()
    parties: dict[int, FinanceCounterparty] = {}
    wanted = set(ids.values())
    if wanted:
        rows = await db.scalars(
            select(FinanceCounterparty).where(FinanceCounterparty.id.in_(wanted))
        )
        parties = {party.id: party for party in rows}
    by_account: dict[str, FinanceCounterparty] = {}
    if missing:
        rows = await db.scalars(
            select(FinanceCounterparty).where(
                or_(
                    FinanceCounterparty.revenue_account.in_(missing),
                    FinanceCounterparty.cost_account.in_(missing),
                )
            )
        )
        for party in rows:
            for account in (party.revenue_account, party.cost_account):
                if account in missing:
                    by_account.setdefault(account, party)
    out: dict[str, dict[str, Any]] = {}
    for account in accounts:
        party = parties.get(ids[account]) if account in ids else by_account.get(account)
        out[account] = {
            "counterparty_id": party.id if party else None,
            "name": party.name if party else "",
            "nip": (party.id_value if party and party.id_type == "nip" else None),
        }
    return out


async def _authors(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
    return {user_id: name or "—" for user_id, name in rows.all()}


def _item_payload(item: Item, as_of: date) -> dict[str, Any]:
    return {
        "line_id": item.line_id,
        "document_id": item.document_id,
        "doc_type": item.doc_type,
        "number": item.number,
        "op_date": item.op_date.isoformat(),
        "due_on": item.due_on.isoformat() if item.due_on else None,
        "overdue_days": overdue_days(item.due_on, as_of) if item.remaining else 0,
        "description": item.description,
        "direction": item.direction,
        "value": item.value,
        "remaining": item.remaining,
        "currency": item.currency,
        "amount_cur": item.amount_cur,
        "remaining_cur": item.remaining_cur,
    }


# ── Zestawienie ─────────────────────────────────────────────────────────────


def _empty_aging() -> list[dict[str, Any]]:
    return [
        {"key": key, "label": label, "amount": 0, "count": 0}
        for key, label, _ in core.AGING
    ] + [{"key": core.NO_DUE[0], "label": core.NO_DUE[1], "amount": 0, "count": 0}]


async def overview(
    db: AsyncSession,
    viewer: Viewer,
    bank_settings: BankSettings,
    *,
    as_of: date,
    side: str = "all",
    overdue_only: bool = False,
    needle: Optional[str] = None,
) -> dict[str, Any]:
    """Kontrahenci z otwartymi pozycjami na dzień, wiekowanie i podgląd automatu."""

    parents = await core.load_parents(db)
    items = await core.load_items(db, viewer, parents=parents, as_of=as_of)
    names = await _names(db, items, fallback=viewer.payroll)
    rows: dict[str, dict[str, Any]] = {}
    aging = {"debit": _empty_aging(), "credit": _empty_aging()}
    aging_index = {row["key"]: index for index, row in enumerate(aging["debit"])}
    totals = {
        side_: {"open": 0, "overdue": 0, "count": 0} for side_ in ("debit", "credit")
    }
    for item in items:
        row = rows.setdefault(
            item.account,
            {
                "account": item.account,
                **names.get(item.account, {"counterparty_id": None, "name": ""}),
                "debit_open": 0,
                "credit_open": 0,
                "debit_overdue": 0,
                "credit_overdue": 0,
                "open_items": 0,
                "max_overdue_days": 0,
                "oldest_due": None,
            },
        )
        remaining = item.remaining
        late = overdue_days(item.due_on, as_of)
        row[f"{item.direction}_open"] += remaining
        row["open_items"] += 1
        totals[item.direction]["open"] += remaining
        totals[item.direction]["count"] += 1
        if late:
            row[f"{item.direction}_overdue"] += remaining
            totals[item.direction]["overdue"] += remaining
            if late > row["max_overdue_days"]:
                row["max_overdue_days"] = late
                row["oldest_due"] = item.due_on.isoformat() if item.due_on else None
        bucket = aging[item.direction][aging_index[aging_key(item.due_on, as_of)]]
        bucket["amount"] += remaining
        bucket["count"] += 1
    listed = list(rows.values())
    if side == "receivable":
        listed = [row for row in listed if row["debit_open"]]
    elif side == "payable":
        listed = [row for row in listed if row["credit_open"]]
    if overdue_only:
        listed = [
            row for row in listed if row["debit_overdue"] or row["credit_overdue"]
        ]
    text_ = " ".join((needle or "").split()).casefold()[:SEARCH_MAX]
    if text_:
        listed = [
            row
            for row in listed
            if text_ in row["account"].casefold()
            or text_ in (row["name"] or "").casefold()
            or text_ in (row.get("nip") or "")
        ]
    for row in listed:
        row["balance"] = row["debit_open"] - row["credit_open"]
    listed.sort(
        key=lambda row: (
            -(row["debit_overdue"] + row["credit_overdue"]),
            -(row["debit_open"] + row["credit_open"]),
            row["account"],
        )
    )
    auto = await core.auto_counts(db, viewer, bank_settings)
    return {
        "as_of": as_of.isoformat(),
        "accounts_configured": bool(parents),
        "totals": {"receivable": totals["debit"], "payable": totals["credit"]},
        "aging": {"receivable": aging["debit"], "payable": aging["credit"]},
        "accounts": listed[:ACCOUNTS_MAX],
        "accounts_total": len(listed),
        "truncated": len(listed) > ACCOUNTS_MAX,
        "auto": auto,
        "can_settle": viewer.approver,
    }


async def _fx_documents(
    db: AsyncSession,
    viewer: Viewer,
    account: str,
    *,
    as_of: date,
    live: set[int],
) -> list[dict[str, Any]]:
    """Różnice kursowe konta (K4c-1): numer, stan, kwota i czy ich rozliczenie
    jeszcze obowiązuje — storno faktury albo wpłaty po zaksięgowaniu różnicy
    zostawia ją bez pary, a saldo konta przestaje się zgadzać z pozycjami."""

    query = (
        select(LedgerDocument, LedgerLine)
        .join(LedgerLine, LedgerLine.document_id == LedgerDocument.id)
        .where(
            LedgerDocument.source_type == core.FX_SOURCE,
            LedgerDocument.reversed_by_id.is_(None),
            LedgerDocument.op_date <= as_of,
            LedgerLine.account == account,
        )
        .order_by(LedgerDocument.op_date, LedgerDocument.id)
    )
    if not viewer.payroll:
        query = query.where(LedgerDocument.sensitivity.is_(None))
    out: list[dict[str, Any]] = []
    for doc, line in (await db.execute(query)).all():
        settlement_id = int(doc.source_id) if (doc.source_id or "").isdigit() else 0
        out.append(
            {
                "id": doc.id,
                "number": doc.number,
                "status": doc.status,
                "op_date": doc.op_date.isoformat(),
                "amount": abs(line.amount),
                "kind": "loss" if line.side == "credit" else "gain",
                "orphan": settlement_id not in live,
            }
        )
    return out


async def account_detail(
    db: AsyncSession, viewer: Viewer, account: str, *, as_of: date
) -> dict[str, Any]:
    """Pozycje konta kontrahenta na dzień: otwarte, rozliczone i rozliczenia."""

    parents = await core.load_parents(db)
    if not core.is_settlement_account(account, parents):
        raise LedgerError(NOT_SETTLEMENT_ACCOUNT.format(account=account), status=404)
    items = await core.load_items(
        db,
        viewer,
        parents=parents,
        as_of=as_of,
        accounts=[account],
        open_only=False,
    )
    by_line = {item.line_id: item for item in items}
    settlements: list[LedgerSettlement] = []
    if by_line:
        settlements = list(
            await db.scalars(
                select(LedgerSettlement)
                .where(
                    LedgerSettlement.removed_at.is_(None),
                    LedgerSettlement.settled_on <= as_of,
                    LedgerSettlement.debit_line_id.in_(by_line),
                    LedgerSettlement.credit_line_id.in_(by_line),
                )
                .order_by(LedgerSettlement.settled_on, LedgerSettlement.id)
            )
        )
    authors = await _authors(
        db, {row.created_by for row in settlements if row.created_by}
    )
    per_line: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in settlements:
        for own, other in (
            (row.debit_line_id, row.credit_line_id),
            (row.credit_line_id, row.debit_line_id),
        ):
            partner = by_line[other]
            mine = row.amount
            if own == row.credit_line_id and row.credit_amount is not None:
                mine = row.credit_amount
            per_line[own].append(
                {
                    "id": row.id,
                    "amount": mine,
                    "currency": row.currency,
                    "amount_cur": row.amount_cur,
                    "settled_on": row.settled_on.isoformat(),
                    "method": row.method,
                    "method_label": METHOD_LABELS[row.method],
                    "by": authors.get(row.created_by or 0, ""),
                    "other": {
                        "line_id": partner.line_id,
                        "document_id": partner.document_id,
                        "doc_type": partner.doc_type,
                        "number": partner.number,
                        "op_date": partner.op_date.isoformat(),
                    },
                }
            )
    names = await _names(db, items, fallback=viewer.payroll) if items else {}
    open_items = [
        item for item in items if item.remaining > 0 or (item.remaining_cur or 0) > 0
    ]
    settled = [item for item in items if item not in open_items]
    fx_docs = await _fx_documents(
        db, viewer, account, as_of=as_of, live={row.id for row in settlements}
    )
    debit_open = sum(item.remaining for item in open_items if item.direction == "debit")
    credit_open = sum(
        item.remaining for item in open_items if item.direction == "credit"
    )

    def payload(item: Item) -> dict[str, Any]:
        return {
            **_item_payload(item, as_of),
            "settlements": per_line.get(item.line_id, []),
        }

    party = names.get(account, {"counterparty_id": None, "name": "", "nip": None})
    return {
        "account": account,
        **party,
        "as_of": as_of.isoformat(),
        "debit_open": debit_open,
        "credit_open": credit_open,
        "balance": debit_open - credit_open,
        "open": [payload(item) for item in open_items],
        "settled": [payload(item) for item in settled[-SETTLED_MAX:]],
        "settled_total": len(settled),
        "fx_documents": fx_docs,
        "can_settle": viewer.approver,
    }
