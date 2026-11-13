"""Plan kont księgi (K1): tabela kont z E2 (``finance_accounts``) z syntetyką.

Jeden plan kont dla dekretu faktur (E2) i księgi NEXUSA. K1 dokłada konto
nadrzędne, typ konta, słownik analityki i pozycję sprawozdania; rodzaj
``other`` mają konta spoza dekretu faktur. Numeru konta się nie zmienia
(nowy numer = nowe konto), kont się nie kasuje — wyłącza się je, jak w E2.

Konta użytego w aktywnej regule dekretu E2 nie wyłącza się i nie zmienia mu
się rodzaju (409), bo reguła dawałaby dekret na złe konto.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_posting import FinanceAccount, FinancePostingRule
from app.models.ledger import LedgerLine
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.posting import ACCOUNT_KIND_LABELS, clean_account
from app.services.ledger import engine
from app.services.ledger_schema import (
    ACCOUNT_DICTIONARIES,
    ACCOUNT_KINDS,
    ACCOUNT_TYPES,
    REPORT_LINE_MAX,
)
from app.services.finance_posting_schema import ACCOUNT_NAME_MAX

FIELDS = (
    "name",
    "kind",
    "account_type",
    "parent_number",
    "dictionary",
    "report_line",
    "active",
)


def _children(numbers: set[str]) -> set[str]:
    return {
        "-".join(number.split("-")[:cut])
        for number in numbers
        for cut in range(1, len(number.split("-")))
    }


def account_payload(
    row: FinanceAccount, *, has_children: bool, used: int, in_rules: int
) -> dict[str, Any]:
    return {
        "id": row.id,
        "number": row.number,
        "name": row.name,
        "kind": row.kind,
        "kind_label": ACCOUNT_KIND_LABELS.get(row.kind, row.kind),
        "active": row.active,
        "parent_number": row.parent_number,
        "account_type": row.account_type,
        "account_type_label": engine.ACCOUNT_TYPE_LABELS.get(
            row.account_type or "", None
        ),
        "dictionary": row.dictionary,
        "dictionary_label": engine.DICTIONARY_LABELS.get(row.dictionary or "", None),
        "report_line": row.report_line,
        "class": row.number[:1],
        "has_children": has_children,
        "postable": row.active and not has_children and not row.dictionary,
        "used": used,
        "in_rules": in_rules,
    }


async def _rule_usage(db: AsyncSession) -> dict[str, int]:
    usage: dict[str, int] = {}
    rows = await db.execute(
        select(FinancePostingRule.cost_account, FinancePostingRule.vat_account).where(
            FinancePostingRule.active.is_(True)
        )
    )
    for cost, vat in rows.all():
        for number in (cost, vat):
            if number:
                usage[number] = usage.get(number, 0) + 1
    return usage


async def _line_usage(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(
        select(LedgerLine.account, func.count()).group_by(LedgerLine.account)
    )
    return {account: int(count) for account, count in rows.all()}


async def list_chart(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(select(FinanceAccount).order_by(FinanceAccount.number))
    ).all()
    parents = _children({row.number for row in rows})
    rules = await _rule_usage(db)
    lines = await _line_usage(db)
    used: dict[str, int] = {}
    for account, count in lines.items():
        used[account] = used.get(account, 0) + count
        for cut in range(1, len(account.split("-"))):
            prefix = "-".join(account.split("-")[:cut])
            used[prefix] = used.get(prefix, 0) + count
    return [
        account_payload(
            row,
            has_children=row.number in parents,
            used=used.get(row.number, 0),
            in_rules=rules.get(row.number, 0),
        )
        for row in rows
    ]


def _choice(
    value: Optional[str], allowed: tuple[str, ...], label: str
) -> Optional[str]:
    if value in (None, ""):
        return None
    if value not in allowed:
        raise LedgerError(f"Niepoprawna wartość: {label}.", status=422)
    return value


def _name(raw: Optional[str]) -> str:
    name = " ".join((raw or "").split())
    if not name:
        raise LedgerError("Podaj nazwę konta.", status=422)
    return name[:ACCOUNT_NAME_MAX]


async def _parent(db: AsyncSession, number: str, raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    parent = clean_account(raw, "Konto nadrzędne")
    if not number.startswith(f"{parent}-"):
        raise LedgerError(
            f"Konto nadrzędne {parent} musi być początkiem numeru {number} (np. {parent}-1).",
            status=422,
        )
    exists = await db.scalar(
        select(FinanceAccount.id).where(FinanceAccount.number == parent)
    )
    if exists is None:
        raise LedgerError(
            f"Konta nadrzędnego {parent} nie ma w planie kont.", status=422
        )
    return parent


async def create_account(
    db: AsyncSession, body: dict[str, Any], *, actor_id: int
) -> FinanceAccount:
    number = clean_account(body.get("number"), "Numer konta")
    if await db.scalar(
        select(FinanceAccount.id).where(FinanceAccount.number == number)
    ):
        raise LedgerError(f"Konto {number} już jest w planie kont.")
    kind = _choice(body.get("kind") or "other", ACCOUNT_KINDS, "rodzaj konta")
    report_line = (
        " ".join(str(body.get("report_line") or "").split())[:REPORT_LINE_MAX] or None
    )
    row = FinanceAccount(
        number=number,
        name=_name(body.get("name")),
        kind=kind,
        active=True,
        parent_number=await _parent(db, number, body.get("parent_number")),
        account_type=_choice(body.get("account_type"), ACCOUNT_TYPES, "typ konta"),
        dictionary=_choice(
            body.get("dictionary"), ACCOUNT_DICTIONARIES, "słownik analityki"
        ),
        report_line=report_line,
        updated_by=actor_id,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise LedgerError(f"Konto {number} już jest w planie kont.") from exc
    return row


async def update_account(
    db: AsyncSession, account_id: int, changes: dict[str, Any], *, actor_id: int
) -> FinanceAccount:
    row = await db.get(FinanceAccount, account_id, with_for_update=True)
    if row is None:
        raise LedgerError("Nie ma takiego konta w planie.", status=404)
    in_rules = await db.scalar(
        select(func.count())
        .select_from(FinancePostingRule)
        .where(
            FinancePostingRule.active.is_(True),
            or_(
                FinancePostingRule.cost_account == row.number,
                FinancePostingRule.vat_account == row.number,
            ),
        )
    )
    if "name" in changes:
        row.name = _name(changes["name"])
    if "kind" in changes:
        kind = _choice(changes["kind"], ACCOUNT_KINDS, "rodzaj konta") or row.kind
        if kind != row.kind and in_rules:
            raise LedgerError(
                f"Konto {row.number} jest w aktywnej regule dekretu — najpierw zmień regułę.",
                status=409,
            )
        row.kind = kind
    if "account_type" in changes:
        row.account_type = _choice(changes["account_type"], ACCOUNT_TYPES, "typ konta")
    if "parent_number" in changes:
        row.parent_number = await _parent(db, row.number, changes["parent_number"])
    if "dictionary" in changes:
        row.dictionary = _choice(
            changes["dictionary"], ACCOUNT_DICTIONARIES, "słownik analityki"
        )
    if "report_line" in changes:
        row.report_line = (
            " ".join(str(changes["report_line"] or "").split())[:REPORT_LINE_MAX]
            or None
        )
    if "active" in changes and changes["active"] is not None:
        if not changes["active"] and in_rules:
            raise LedgerError(
                f"Konto {row.number} jest w aktywnej regule dekretu — najpierw ją zmień.",
                status=409,
            )
        row.active = bool(changes["active"])
    row.updated_by = actor_id
    await db.flush()
    return row
