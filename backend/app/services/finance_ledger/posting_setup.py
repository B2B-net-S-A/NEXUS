"""Plan kont i reguły dekretu (E2): lista, dodanie, zmiana, wyłączenie.

Kont i reguł się nie kasuje, tylko wyłącza — zasiew przy starcie dokłada
brakujące konta wzorcowe po numerze i regułę domyślną kontraktora, gdy
kategoria nie ma żadnej reguły ogólnej. Numer konta jest stały (nowy numer =
nowe konto). Konta użytego w aktywnej regule nie wyłącza się (409), żeby
reguła nie dawała dekretu na wyłączone konto. Konta reguły muszą być w planie,
aktywne i właściwego rodzaju (koszt, VAT).
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_ledger import FinanceCounterparty
from app.models.finance_posting import FinanceAccount, FinancePostingRule
from app.services.finance_ledger import posting
from app.services.finance_ledger.costs import CATEGORY_LABELS, LedgerError
from app.services.finance_posting_schema import (
    ACCOUNT_KINDS,
    ACCOUNT_NAME_MAX,
    DEDUCTIONS,
    REGISTERS,
    SERVICE_MAX,
)
from app.services.finance_ledger_schema import CATEGORIES

RULE_FIELDS = (
    "cost_account",
    "vat_account",
    "deduction",
    "register",
    "doc_type",
    "service_label",
    "description_template",
    "active",
)


# ── Plan kont ────────────────────────────────────────────────────────────────


def account_payload(row: FinanceAccount, used_by: int = 0) -> dict[str, Any]:
    return {
        "id": row.id,
        "number": row.number,
        "name": row.name,
        "kind": row.kind,
        "kind_label": posting.ACCOUNT_KIND_LABELS[row.kind],
        "active": row.active,
        "rules": used_by,
    }


def _name(raw: Optional[str]) -> str:
    name = " ".join((raw or "").split())
    if not name:
        raise LedgerError("Podaj nazwę konta.", status=422)
    return name[:ACCOUNT_NAME_MAX]


def _kind(raw: Optional[str]) -> str:
    if raw not in ACCOUNT_KINDS:
        raise LedgerError("Wybierz rodzaj konta.", status=422)
    return raw


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


async def list_accounts(db: AsyncSession) -> list[dict[str, Any]]:
    usage = await _rule_usage(db)
    rows = await db.scalars(select(FinanceAccount).order_by(FinanceAccount.number))
    return [account_payload(row, usage.get(row.number, 0)) for row in rows]


async def create_account(
    db: AsyncSession, body: dict[str, Any], *, actor_id: int
) -> FinanceAccount:
    number = posting.clean_account(body.get("number"), "Numer konta")
    if await db.scalar(
        select(FinanceAccount.id).where(FinanceAccount.number == number)
    ):
        raise LedgerError(f"Konto {number} już jest w planie kont.")
    row = FinanceAccount(
        number=number,
        name=_name(body.get("name")),
        kind=_kind(body.get("kind")),
        active=True,
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
    if "name" in changes:
        row.name = _name(changes["name"])
    kind_change = "kind" in changes and changes["kind"] != row.kind
    switching_off = changes.get("active") is False and row.active
    if kind_change or switching_off:
        used = (await _rule_usage(db)).get(row.number, 0)
        if used:
            raise LedgerError(
                f"Konto {row.number} jest w aktywnej regule dekretu — najpierw "
                "zmień albo wyłącz regułę."
            )
    if "kind" in changes:
        row.kind = _kind(changes["kind"])
    if "active" in changes and changes["active"] is not None:
        row.active = bool(changes["active"])
    row.updated_by = actor_id
    await db.flush()
    return row


# ── Reguły dekretu ───────────────────────────────────────────────────────────


def rule_payload(row: FinancePostingRule, party: Optional[str]) -> dict[str, Any]:
    label = CATEGORY_LABELS[row.category]
    return {
        "id": row.id,
        "category": row.category,
        "category_label": label,
        "counterparty_id": row.counterparty_id,
        "counterparty_name": party,
        "label": f"{label} · {party}" if party else label,
        "cost_account": row.cost_account,
        "vat_account": row.vat_account,
        "deduction": row.deduction,
        "deduction_label": posting.DEDUCTION_LABELS[row.deduction],
        "register": row.register,
        "register_label": posting.REGISTER_LABELS[row.register],
        "doc_type": row.doc_type,
        "service_label": row.service_label,
        "description_template": row.description_template,
        "active": row.active,
    }


async def _party_names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(
        select(FinanceCounterparty.id, FinanceCounterparty.name).where(
            FinanceCounterparty.id.in_(ids)
        )
    )
    return {row.id: row.name for row in rows.all()}


async def list_rules(db: AsyncSession) -> list[dict[str, Any]]:
    rows = list(
        await db.scalars(
            select(FinancePostingRule).order_by(
                FinancePostingRule.category,
                FinancePostingRule.counterparty_id.is_not(None),
                FinancePostingRule.id,
            )
        )
    )
    names = await _party_names(
        db, {row.counterparty_id for row in rows if row.counterparty_id}
    )
    return [rule_payload(row, names.get(row.counterparty_id or 0)) for row in rows]


async def rule_view(db: AsyncSession, row: FinancePostingRule) -> dict[str, Any]:
    names = await _party_names(
        db, {row.counterparty_id} if row.counterparty_id else set()
    )
    return rule_payload(row, names.get(row.counterparty_id or 0))


async def _plan_account(
    db: AsyncSession, raw: Optional[str], kind: str, label: str
) -> str:
    number = posting.clean_account(raw, label)
    account = await db.scalar(
        select(FinanceAccount).where(FinanceAccount.number == number)
    )
    if account is None or not account.active:
        raise LedgerError(
            f"{label}: konta {number} nie ma w planie kont albo jest wyłączone.",
            status=422,
        )
    if account.kind != kind:
        raise LedgerError(
            f"{label}: konto {number} ma w planie rodzaj "
            f"„{posting.ACCOUNT_KIND_LABELS[account.kind]}”, potrzebny "
            f"„{posting.ACCOUNT_KIND_LABELS[kind]}”.",
            status=422,
        )
    return number


async def _apply_rule(
    db: AsyncSession, row: FinancePostingRule, values: dict[str, Any]
) -> None:
    if "deduction" in values:
        if values["deduction"] not in DEDUCTIONS:
            raise LedgerError("Wybierz odliczenie VAT (100% albo brak).", status=422)
        row.deduction = values["deduction"]
    if "register" in values:
        if values["register"] not in REGISTERS:
            raise LedgerError("Wybierz rejestr (Zakup albo Sprzedaż).", status=422)
        row.register = values["register"]
    if "cost_account" in values:
        row.cost_account = await _plan_account(
            db, values["cost_account"], "cost", "Konto kosztu"
        )
    if "vat_account" in values:
        raw = values["vat_account"]
        row.vat_account = (
            await _plan_account(db, raw, "vat", "Konto VAT") if raw else None
        )
    if row.deduction == "full" and not row.vat_account:
        raise LedgerError("Przy odliczeniu 100% podaj konto VAT.", status=422)
    if "doc_type" in values:
        row.doc_type = posting.clean_doc_type(values["doc_type"])
    if "service_label" in values:
        service = " ".join((values["service_label"] or "").split())
        if not service:
            raise LedgerError(
                "Podaj nazwę usługi do opisu (np. Usługi IT).", status=422
            )
        row.service_label = service[:SERVICE_MAX]
    if "description_template" in values:
        row.description_template = posting.validate_template(
            values["description_template"]
        )
    if "active" in values and values["active"] is not None:
        row.active = bool(values["active"])


async def create_rule(
    db: AsyncSession, body: dict[str, Any], *, actor_id: int
) -> FinancePostingRule:
    category = body.get("category")
    if category not in CATEGORIES:
        raise LedgerError("Wybierz kategorię.", status=422)
    party_id = body.get("counterparty_id")
    if party_id is not None and await db.get(FinanceCounterparty, party_id) is None:
        raise LedgerError("Nie ma takiego kontrahenta w kartotece.", status=422)
    duplicate = await db.scalar(
        select(FinancePostingRule.id).where(
            FinancePostingRule.category == category,
            FinancePostingRule.counterparty_id == party_id
            if party_id is not None
            else FinancePostingRule.counterparty_id.is_(None),
        )
    )
    if duplicate:
        raise LedgerError("Taka reguła już jest (także wyłączona) — zmień istniejącą.")
    row = FinancePostingRule(
        category=category,
        counterparty_id=party_id,
        deduction=body.get("deduction") or "full",
        register=body.get("register") or "purchase",
        doc_type="FVZ",
        service_label="",
        description_template="",
        cost_account="",
        active=True,
        updated_by=actor_id,
    )
    values = {
        "doc_type": "FVZ",
        "description_template": "{usługa} {MM}/{RRRR}",
        **{key: body[key] for key in RULE_FIELDS if key in body},
    }
    values.setdefault("cost_account", None)
    values.setdefault("service_label", None)
    values.setdefault("vat_account", None)
    await _apply_rule(db, row, values)
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise LedgerError("Taka reguła już jest — zmień istniejącą.") from exc
    return row


async def update_rule(
    db: AsyncSession, rule_id: int, changes: dict[str, Any], *, actor_id: int
) -> FinancePostingRule:
    row = await db.get(FinancePostingRule, rule_id, with_for_update=True)
    if row is None:
        raise LedgerError("Nie ma takiej reguły.", status=404)
    await _apply_rule(
        db, row, {key: changes[key] for key in RULE_FIELDS if key in changes}
    )
    row.updated_by = actor_id
    await db.flush()
    return row


async def counterparty_options(db: AsyncSession, q: str) -> list[dict[str, Any]]:
    """Podpowiedź kontrahenta do reguły (nazwa albo NIP)."""

    needle = " ".join((q or "").split())
    if len(needle) < 2:
        return []
    pattern = f"%{needle}%"
    rows = await db.execute(
        select(
            FinanceCounterparty.id,
            FinanceCounterparty.name,
            FinanceCounterparty.id_value,
            FinanceCounterparty.cost_account,
        )
        .where(
            or_(
                FinanceCounterparty.name.ilike(pattern),
                FinanceCounterparty.id_value.ilike(pattern),
            )
        )
        .order_by(FinanceCounterparty.name)
        .limit(20)
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "id_value": row.id_value,
            "cost_account": row.cost_account,
        }
        for row in rows.all()
    ]
