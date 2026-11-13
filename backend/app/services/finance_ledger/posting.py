"""Dekret faktury kosztowej do Symfonii FK (E2): reguła, wyliczenie, korekta, kontrola.

Reguła dekretu (``finance_posting_rules``) dobiera się po kategorii wpisu
i opcjonalnie kontrahencie — reguła kontrahenta wygrywa z ogólną dla tej samej
kategorii. Wynik reguły: konto kosztu, konto VAT, odliczenie (100% / brak),
rejestr, typ dokumentu i wzór opisu. Rozrachunek bierzemy zawsze z kartoteki
kontrahenta (``finance_counterparties.cost_account``): brak kontrahenta albo
konta = dekret niekompletny.

Pozycje jak w eBI24 (kwoty w groszach, faktura ma jedną sumę netto i VAT —
źródła nie niosą rozbicia na stawki):

* Wn konto kosztu: netto (odliczenie 100%) albo brutto (bez odliczenia),
* Wn konto VAT: VAT (tylko przy odliczeniu 100% i VAT ≠ 0),
* Ma rozrachunek z kontrahentem: brutto.

Korekta (brutto < 0) odwraca strony. Dekret powstaje przy przejściu do
„Zweryfikowane” i na żądanie („Przelicz”); przy „Gotowa do księgowania”
dekret wyliczany liczy się od nowa, a ręczny zostaje. Niekompletny dekret
blokuje „Gotowa do księgowania”. Po „Gotowa” i po zaksięgowaniu dekretu się
nie zmienia (najpierw „Cofnij”).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.client_settlement import ClientContractorInvoice
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.finance_posting import (
    FinanceAccount,
    FinancePostingBatch,
    FinancePostingRule,
)
from app.models.hr_approval import ApprovalDocument
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_settlement import PayrollInvoice, PayrollSettlement
from app.services.finance_ledger.costs import (
    BOOKED_DETAIL,
    CATEGORY_LABELS,
    OWN_INVOICE_DETAIL,
    LedgerError,
    _event,
    _own_entry_ids,
    _payroll_scope,
)
from app.services.finance_posting_schema import (
    ACCOUNT_MAX,
    DOC_TYPE_MAX,
    REGISTERS,
)

REGISTER_LABELS = {"purchase": "Zakup", "sale": "Sprzedaż"}
DEDUCTION_LABELS = {"full": "100%", "none": "brak"}
KIND_LABELS = {
    "cost": "Koszt",
    "vat": "VAT",
    "counterparty": "Rozrachunek z kontrahentem",
}
ACCOUNT_KIND_LABELS = {
    "cost": "koszt",
    "vat": "VAT",
    "settlement": "rozrachunek",
    "revenue": "przychód",
}
SIDE_LABELS = {"debit": "Wn", "credit": "Ma"}
POSITION_KINDS: tuple[str, ...] = ("cost", "vat", "counterparty")
SIDES: tuple[str, ...] = ("debit", "credit")
PLACEHOLDERS: tuple[str, ...] = ("usługa", "MM", "RRRR", "numer", "kontrahent")
STANDARD_RATES: tuple[int, ...] = (23, 8, 5, 0)
POSITIONS_MAX = 30
DESCRIPTION_MAX = 255
#: Dekret zmienia się tylko przed „Gotowa do księgowania”.
EDITABLE_STAGES: tuple[str, ...] = ("new", "verified")

ACCOUNT_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z\-./]*")
DOC_TYPE_RE = re.compile(r"[0-9A-Z]{1,%d}" % DOC_TYPE_MAX)
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_CENT = Decimal("0.01")

NOT_COMPUTED = (
    "Dekret jeszcze nie powstał — powstaje przy weryfikacji albo po „Przelicz”."
)
NO_COUNTERPARTY = (
    "Sprzedawcy nie ma w kartotece kontrahentów — zaimportuj kartotekę z eBI24."
)
NO_AMOUNTS = "Faktura nie ma kwoty netto ani VAT — popraw dekret ręcznie."
NOT_EDITABLE = (
    "Dekret zmieniasz przed „Gotowa do księgowania” — najpierw cofnij fakturę o krok."
)


# ── Wartości (bez bazy) ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class AccountView:
    number: str
    name: str
    kind: str
    active: bool


@dataclass(frozen=True)
class RuleView:
    id: int
    category: str
    counterparty_id: Optional[int]
    cost_account: str
    vat_account: Optional[str]
    deduction: str
    register: str
    doc_type: str
    service_label: str
    description_template: str
    active: bool = True


@dataclass(frozen=True)
class DecreeInput:
    category: str
    counterparty_id: Optional[int]
    counterparty_name: Optional[str]
    counterparty_account: Optional[str]
    currency: str
    net: Optional[Decimal]
    vat: Optional[Decimal]
    gross: Optional[Decimal]
    invoice_number: Optional[str]
    #: Pierwszy dzień miesiąca usługi (źródło, potem data wystawienia, wpływu).
    period: Optional[date]


def grosze(value: Decimal) -> int:
    return int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(amount: int) -> str:
    """Grosze → ``"1234.56"`` (API i pliki)."""

    sign = "-" if amount < 0 else ""
    return f"{sign}{abs(amount) // 100}.{abs(amount) % 100:02d}"


def money_pl(amount: int) -> str:
    """Grosze → ``"1 234,56 zł"`` (komunikaty)."""

    sign = "-" if amount < 0 else ""
    whole = f"{abs(amount) // 100:,}".replace(",", " ")
    return f"{sign}{whole},{abs(amount) % 100:02d} zł"


def vat_rate(net: Optional[Decimal], vat: Optional[Decimal]) -> Optional[str]:
    """Stawka z sumy netto i VAT, gdy pasuje do stawki ustawowej (±0,5 pp)."""

    if net is None or vat is None or net == 0:
        return None
    if vat == 0:
        return "0"
    ratio = abs(Decimal(vat) / Decimal(net) * 100)
    for rate in STANDARD_RATES:
        if abs(ratio - rate) <= Decimal("0.5"):
            return str(rate)
    return None


def clean_account(raw: Optional[str], label: str = "Konto") -> str:
    value = (raw or "").replace(" ", "")
    if not value:
        raise LedgerError(f"{label}: podaj numer konta.", status=422)
    if len(value) > ACCOUNT_MAX or not ACCOUNT_RE.fullmatch(value):
        raise LedgerError(
            f"{label}: niepoprawny numer konta „{(raw or '')[:40]}”.", status=422
        )
    return value


def clean_doc_type(raw: Optional[str]) -> str:
    value = (raw or "").strip().upper()
    if not DOC_TYPE_RE.fullmatch(value):
        raise LedgerError(
            f"Typ dokumentu: od 1 do {DOC_TYPE_MAX} liter albo cyfr (np. FVZ).",
            status=422,
        )
    return value


def validate_template(template: str) -> str:
    value = " ".join((template or "").split())
    if not value:
        raise LedgerError("Podaj wzór opisu (np. {usługa} {MM}/{RRRR}).", status=422)
    unknown = [name for name in _PLACEHOLDER.findall(value) if name not in PLACEHOLDERS]
    if unknown:
        allowed = ", ".join(f"{{{name}}}" for name in PLACEHOLDERS)
        raise LedgerError(
            f"Nieznane pole we wzorze: {{{unknown[0]}}}. Dozwolone: {allowed}.",
            status=422,
        )
    return value


def render_description(
    template: str,
    *,
    service: str,
    period: Optional[date],
    number: Optional[str],
    counterparty: Optional[str],
) -> str:
    """Opis z wzoru (``{usługa} {MM}/{RRRR}`` → „Usługi IT 10/2026”)."""

    values = {
        "usługa": service,
        "MM": f"{period.month:02d}" if period else "",
        "RRRR": f"{period.year}" if period else "",
        "numer": number or "",
        "kontrahent": counterparty or "",
    }
    text_ = _PLACEHOLDER.sub(
        lambda match: values.get(match.group(1), match.group(0)), template
    )
    return " ".join(text_.split())[:DESCRIPTION_MAX]


def match_rule(
    rules: Iterable[RuleView], category: str, counterparty_id: Optional[int]
) -> Optional[RuleView]:
    """Reguła kontrahenta wygrywa z ogólną tej samej kategorii; tylko aktywne."""

    general: Optional[RuleView] = None
    for rule in rules:
        if not rule.active or rule.category != category:
            continue
        if counterparty_id is not None and rule.counterparty_id == counterparty_id:
            return rule
        if rule.counterparty_id is None:
            general = rule
    return general


def _amounts(inp: DecreeInput) -> Optional[tuple[Decimal, Decimal, Decimal]]:
    net, vat, gross = inp.net, inp.vat, inp.gross
    if net is None and vat is None:
        return None
    if gross is None:
        if net is None or vat is None:
            return None
        gross = net + vat
    if net is None:
        net = gross - vat
    if vat is None:
        vat = gross - net
    return Decimal(net), Decimal(vat), Decimal(gross)


def _rule_problems(rule: RuleView, plan: dict[str, AccountView]) -> list[str]:
    problems = []
    wanted = [("cost", rule.cost_account)]
    if rule.deduction == "full" and rule.vat_account:
        wanted.append(("vat", rule.vat_account))
    for kind, number in wanted:
        account = plan.get(number)
        if account is None or not account.active:
            problems.append(
                f"Konta {number} z reguły nie ma w planie kont albo jest wyłączone."
            )
        elif account.kind != kind:
            problems.append(
                f"Konto {number} z reguły ma w planie rodzaj "
                f"„{ACCOUNT_KIND_LABELS[account.kind]}”, a reguła używa go jako "
                f"„{ACCOUNT_KIND_LABELS[kind]}”."
            )
    return problems


def compute(
    inp: DecreeInput,
    rules: Iterable[RuleView],
    plan: dict[str, AccountView],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Dekret z reguły; to, czego nie da się wyliczyć, trafia do ``problems``."""

    base: dict[str, Any] = {
        "manual": False,
        "computed_at": now.isoformat(),
        "currency": inp.currency,
        "period": inp.period.isoformat() if inp.period else None,
    }
    rule = match_rule(rules, inp.category, inp.counterparty_id)
    if rule is None:
        label = CATEGORY_LABELS.get(inp.category, inp.category)
        return {
            **base,
            "rule_id": None,
            "register": "purchase",
            "doc_type": "",
            "description": "",
            "positions": [],
            "problems": [
                f"Brak aktywnej reguły dekretu dla kategorii „{label}” — dodaj ją "
                "w „Plan kont”."
            ],
        }
    problems = _rule_problems(rule, plan)
    if inp.counterparty_id is None:
        problems.append(NO_COUNTERPARTY)
    elif not inp.counterparty_account:
        problems.append(
            f"Kontrahent „{inp.counterparty_name or '—'}” nie ma konta "
            "rozrachunkowego w kartotece — uzupełnij je w „Kontrahenci”."
        )
    if inp.currency != "PLN":
        problems.append(
            f"Faktura w {inp.currency} — wpisz pozycje w PLN ręcznie (po kursie NBP)."
        )
    positions: list[dict[str, Any]] = []
    amounts = _amounts(inp)
    if amounts is None:
        problems.append(NO_AMOUNTS)
    else:
        net, vat, gross = amounts
        rate = vat_rate(net, vat)
        debit, credit = ("credit", "debit") if gross < 0 else ("debit", "credit")
        cost = gross if rule.deduction == "none" else net
        candidates = [
            {
                "kind": "cost",
                "account": rule.cost_account,
                "side": debit,
                "amount": grosze(abs(cost)),
                "vat_rate": rate,
                "deduction": rule.deduction,
            }
        ]
        if rule.deduction == "full":
            candidates.append(
                {
                    "kind": "vat",
                    "account": rule.vat_account,
                    "side": debit,
                    "amount": grosze(abs(vat)),
                    "vat_rate": rate,
                    "deduction": "full",
                }
            )
        candidates.append(
            {
                "kind": "counterparty",
                "account": inp.counterparty_account,
                "side": credit,
                "amount": grosze(abs(gross)),
                "vat_rate": None,
                "deduction": None,
            }
        )
        positions = [item for item in candidates if item["amount"] != 0]
    return {
        **base,
        "rule_id": rule.id,
        "register": rule.register,
        "doc_type": rule.doc_type,
        "description": render_description(
            rule.description_template,
            service=rule.service_label,
            period=inp.period,
            number=inp.invoice_number,
            counterparty=inp.counterparty_name,
        ),
        "positions": positions,
        "problems": problems,
    }


def totals(positions: Iterable[dict[str, Any]]) -> tuple[int, int]:
    debit = credit = 0
    for item in positions:
        if item.get("side") == "debit":
            debit += int(item.get("amount") or 0)
        else:
            credit += int(item.get("amount") or 0)
    return debit, credit


def check(decree: Optional[dict[str, Any]], plan: dict[str, AccountView]) -> list[str]:
    """Co blokuje „Gotowa do księgowania” (pusta lista = dekret kompletny)."""

    if not decree:
        return [NOT_COMPUTED]
    stored = list(decree.get("problems") or [])
    issues = list(stored)
    positions = decree.get("positions") or []
    if not positions:
        return issues or ["Dekret nie ma pozycji."]
    for item in positions:
        number = item.get("account")
        kind = item.get("kind")
        if not number:
            if not stored:
                issues.append(f"Pozycja „{KIND_LABELS.get(kind, kind)}” nie ma konta.")
            continue
        if kind not in ("cost", "vat"):
            continue
        account = plan.get(number)
        if account is None or not account.active:
            issues.append(f"Konta {number} nie ma w planie kont albo jest wyłączone.")
        elif account.kind != kind:
            issues.append(
                f"Konto {number} ma w planie rodzaj "
                f"„{ACCOUNT_KIND_LABELS[account.kind]}”, a pozycja to "
                f"„{KIND_LABELS[kind]}”."
            )
    debit, credit = totals(positions)
    if debit != credit:
        issues.append(
            f"Suma Wn ({money_pl(debit)}) różni się od sumy Ma ({money_pl(credit)})."
        )
    return list(dict.fromkeys(issues))


def _amount_of(raw: Any) -> int:
    try:
        value = Decimal(str(raw).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise LedgerError(f"Niepoprawna kwota „{str(raw)[:20]}”.", status=422) from exc
    if not value.is_finite() or value <= 0:
        raise LedgerError("Kwota pozycji musi być większa od zera.", status=422)
    if value != value.quantize(_CENT):
        raise LedgerError(
            "Kwota pozycji ma najwyżej dwa miejsca po przecinku.", status=422
        )
    return grosze(value)


def manual_decree(
    body: dict[str, Any],
    plan: dict[str, AccountView],
    *,
    previous: Optional[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Dekret wpisany ręcznie; zły bilans albo konto = ``LedgerError`` 422."""

    register = body.get("register")
    if register not in REGISTERS:
        raise LedgerError("Wybierz rejestr (Zakup albo Sprzedaż).", status=422)
    raw_positions = body.get("positions") or []
    if not raw_positions:
        raise LedgerError("Dekret musi mieć co najmniej jedną pozycję.", status=422)
    if len(raw_positions) > POSITIONS_MAX:
        raise LedgerError(f"Dekret ma najwyżej {POSITIONS_MAX} pozycji.", status=422)
    positions = []
    for index, raw in enumerate(raw_positions, start=1):
        kind = raw.get("kind")
        side = raw.get("side")
        if kind not in POSITION_KINDS or side not in SIDES:
            raise LedgerError(
                f"Pozycja {index}: nieznany rodzaj albo strona.", status=422
            )
        number = clean_account(raw.get("account"), f"Pozycja {index}")
        if kind in ("cost", "vat"):
            account = plan.get(number)
            if account is None or not account.active:
                raise LedgerError(
                    f"Pozycja {index}: konta {number} nie ma w planie kont albo "
                    "jest wyłączone.",
                    status=422,
                )
            if account.kind != kind:
                raise LedgerError(
                    f"Pozycja {index}: konto {number} ma w planie rodzaj "
                    f"„{ACCOUNT_KIND_LABELS[account.kind]}”.",
                    status=422,
                )
        deduction = raw.get("deduction")
        rate = raw.get("vat_rate")
        positions.append(
            {
                "kind": kind,
                "account": number,
                "side": side,
                "amount": _amount_of(raw.get("amount")),
                "vat_rate": str(rate)[:8] if rate not in (None, "") else None,
                "deduction": deduction if deduction in ("full", "none") else None,
            }
        )
    debit, credit = totals(positions)
    if debit != credit:
        raise LedgerError(
            f"Suma Wn ({money_pl(debit)}) różni się od sumy Ma ({money_pl(credit)}).",
            status=422,
        )
    previous = previous or {}
    return {
        "manual": True,
        "computed_at": now.isoformat(),
        "currency": "PLN",
        "period": previous.get("period"),
        "rule_id": previous.get("rule_id"),
        "register": register,
        "doc_type": clean_doc_type(body.get("doc_type")),
        "description": " ".join((body.get("description") or "").split())[
            :DESCRIPTION_MAX
        ],
        "positions": positions,
        "problems": [],
    }


def first_issue(issues: list[str]) -> str:
    more = len(issues) - 1
    suffix = f" (i jeszcze {more})" if more > 0 else ""
    return f"Dekret niekompletny: {issues[0]}{suffix}"


# ── Baza ─────────────────────────────────────────────────────────────────────


@dataclass
class Context:
    plan: dict[str, AccountView]
    rules: list[RuleView]
    inputs: dict[int, DecreeInput]


async def load_plan(db: AsyncSession) -> dict[str, AccountView]:
    rows = await db.scalars(select(FinanceAccount))
    return {
        row.number: AccountView(row.number, row.name, row.kind, row.active)
        for row in rows
    }


async def load_rules(db: AsyncSession) -> list[RuleView]:
    rows = await db.scalars(
        select(FinancePostingRule).where(FinancePostingRule.active.is_(True))
    )
    return [
        RuleView(
            id=row.id,
            category=row.category,
            counterparty_id=row.counterparty_id,
            cost_account=row.cost_account,
            vat_account=row.vat_account,
            deduction=row.deduction,
            register=row.register,
            doc_type=row.doc_type,
            service_label=row.service_label,
            description_template=row.description_template,
            active=row.active,
        )
        for row in rows
    ]


def _month_start(value: Optional[date]) -> Optional[date]:
    return value.replace(day=1) if value else None


async def load_inputs(
    db: AsyncSession, entries: Iterable[FinanceCostEntry]
) -> dict[int, DecreeInput]:
    """Kwoty, numer i miesiąc usługi ze źródeł, kontrahent z kartoteki."""

    entries = list(entries)
    by_type: dict[str, dict[int, FinanceCostEntry]] = {}
    for entry in entries:
        by_type.setdefault(entry.source_type, {})[entry.source_id] = entry
    sources: dict[tuple[str, int], tuple[Any, ...]] = {}
    if ids := by_type.get("payroll_invoice"):
        rows = await db.execute(
            select(
                PayrollInvoice.id,
                PayrollInvoice.currency,
                PayrollInvoice.net_amount,
                PayrollInvoice.vat_amount,
                PayrollInvoice.gross_amount,
                PayrollInvoice.invoice_number,
                PayrollInvoice.issue_date,
                PayrollPeriod.year,
                PayrollPeriod.month,
            )
            .outerjoin(
                PayrollSettlement, PayrollSettlement.id == PayrollInvoice.settlement_id
            )
            .outerjoin(PayrollPeriod, PayrollPeriod.id == PayrollSettlement.period_id)
            .where(PayrollInvoice.id.in_(list(ids)))
        )
        for row in rows.all():
            period = date(int(row.year), int(row.month), 1) if row.year else None
            sources[("payroll_invoice", row.id)] = (
                row.currency,
                row.net_amount,
                row.vat_amount,
                row.gross_amount,
                row.invoice_number,
                period or _month_start(row.issue_date),
            )
    if ids := by_type.get("contractor_invoice"):
        rows = await db.execute(
            select(
                ClientContractorInvoice.id,
                ClientContractorInvoice.currency,
                ClientContractorInvoice.net_amount,
                ClientContractorInvoice.vat_amount,
                ClientContractorInvoice.gross_amount,
                ClientContractorInvoice.invoice_number,
                ClientContractorInvoice.issue_date,
                ClientContractorInvoice.period_month,
            ).where(ClientContractorInvoice.id.in_(list(ids)))
        )
        for row in rows.all():
            period = None
            if row.period_month and len(row.period_month) == 7:
                period = date(int(row.period_month[:4]), int(row.period_month[5:7]), 1)
            sources[("contractor_invoice", row.id)] = (
                row.currency,
                row.net_amount,
                row.vat_amount,
                row.gross_amount,
                row.invoice_number,
                period or _month_start(row.issue_date),
            )
    if ids := by_type.get("approval_document"):
        rows = await db.execute(
            select(
                ApprovalDocument.id,
                ApprovalDocument.currency,
                ApprovalDocument.net_amount,
                ApprovalDocument.vat_amount,
                ApprovalDocument.gross_amount,
                ApprovalDocument.invoice_number,
                ApprovalDocument.issue_date,
            ).where(ApprovalDocument.id.in_(list(ids)))
        )
        for row in rows.all():
            sources[("approval_document", row.id)] = (
                row.currency,
                row.net_amount,
                row.vat_amount,
                row.gross_amount,
                row.invoice_number,
                _month_start(row.issue_date),
            )
    party_ids = {e.counterparty_id for e in entries if e.counterparty_id is not None}
    parties: dict[int, tuple[str, Optional[str]]] = {}
    if party_ids:
        rows = await db.execute(
            select(
                FinanceCounterparty.id,
                FinanceCounterparty.name,
                FinanceCounterparty.cost_account,
            ).where(FinanceCounterparty.id.in_(party_ids))
        )
        parties = {row.id: (row.name, row.cost_account) for row in rows.all()}
    result: dict[int, DecreeInput] = {}
    for entry in entries:
        source = sources.get((entry.source_type, entry.source_id))
        currency, net, vat, gross, number, period = source or (
            "PLN",
            None,
            None,
            None,
            None,
            None,
        )
        name, account = parties.get(entry.counterparty_id or 0, (None, None))
        result[entry.id] = DecreeInput(
            category=entry.category,
            counterparty_id=entry.counterparty_id if name is not None else None,
            counterparty_name=name,
            counterparty_account=account,
            currency=currency or "PLN",
            net=net,
            vat=vat,
            gross=gross,
            invoice_number=number,
            period=period or _month_start(business_date(entry.received_at)),
        )
    return result


async def load_context(
    db: AsyncSession, entries: Iterable[FinanceCostEntry]
) -> Context:
    entries = list(entries)
    return Context(
        plan=await load_plan(db),
        rules=await load_rules(db),
        inputs=await load_inputs(db, entries),
    )


def refresh(entry: FinanceCostEntry, ctx: Context, *, now: datetime) -> None:
    """Dekret wyliczany liczy się od nowa; ręczny zostaje."""

    if entry.decree and entry.decree.get("manual"):
        return
    entry.decree = compute(ctx.inputs[entry.id], ctx.rules, ctx.plan, now=now)


def ensure_ready(entry: FinanceCostEntry, ctx: Context, *, now: datetime) -> None:
    """Przed „Gotowa do księgowania”: świeży dekret i kontrola (409 z powodem)."""

    refresh(entry, ctx, now=now)
    issues = check(entry.decree, ctx.plan)
    if issues:
        raise LedgerError(first_issue(issues))


async def _editable_entry(
    db: AsyncSession, entry_id: int, *, actor_id: int, payroll: bool
) -> FinanceCostEntry:
    entry = await db.scalar(
        select(FinanceCostEntry)
        .where(FinanceCostEntry.id == entry_id, *_payroll_scope(payroll))
        .with_for_update()
    )
    if entry is None:
        raise LedgerError("Nie ma takiej faktury w kolejce.", status=404)
    if entry.id in await _own_entry_ids(db, [entry], actor_id):
        raise LedgerError(OWN_INVOICE_DETAIL, status=403)
    if entry.stage == "booked":
        raise LedgerError(BOOKED_DETAIL)
    if entry.stage not in EDITABLE_STAGES:
        raise LedgerError(NOT_EDITABLE)
    return entry


async def recalculate(
    db: AsyncSession, entry_id: int, *, actor_id: int, now: datetime, payroll: bool
) -> None:
    """„Przelicz”: dekret z reguły od nowa (także w miejsce ręcznego)."""

    entry = await _editable_entry(db, entry_id, actor_id=actor_id, payroll=payroll)
    ctx = await load_context(db, [entry])
    was_manual = bool(entry.decree and entry.decree.get("manual"))
    entry.decree = compute(ctx.inputs[entry.id], ctx.rules, ctx.plan, now=now)
    _event(
        db,
        entry,
        "decree",
        actor_id=actor_id,
        now=now,
        detail={"manual": False, "was_manual": was_manual},
    )
    await db.flush()


async def set_manual(
    db: AsyncSession,
    entry_id: int,
    body: dict[str, Any],
    *,
    actor_id: int,
    now: datetime,
    payroll: bool,
) -> None:
    entry = await _editable_entry(db, entry_id, actor_id=actor_id, payroll=payroll)
    plan = await load_plan(db)
    entry.decree = manual_decree(body, plan, previous=entry.decree, now=now)
    debit, _ = totals(entry.decree["positions"])
    _event(
        db,
        entry,
        "decree",
        actor_id=actor_id,
        now=now,
        detail={"manual": True, "total": money(debit)},
    )
    await db.flush()


def positions_payload(
    positions: Iterable[dict[str, Any]], plan: dict[str, AccountView]
) -> list[dict[str, Any]]:
    result = []
    for item in positions:
        account = plan.get(item.get("account") or "")
        result.append(
            {
                "kind": item.get("kind"),
                "kind_label": KIND_LABELS.get(item.get("kind"), item.get("kind")),
                "account": item.get("account"),
                "account_name": account.name if account else None,
                "side": item.get("side"),
                "side_label": SIDE_LABELS.get(item.get("side"), item.get("side")),
                "amount": money(int(item.get("amount") or 0)),
                "vat_rate": item.get("vat_rate"),
                "deduction": item.get("deduction"),
                "deduction_label": DEDUCTION_LABELS.get(item.get("deduction") or ""),
            }
        )
    return result


async def section(
    db: AsyncSession, entry: FinanceCostEntry, *, own: bool
) -> dict[str, Any]:
    """„Dekret do Symfonii FK” na karcie faktury (M2)."""

    plan = await load_plan(db)
    decree = entry.decree or {}
    positions = decree.get("positions") or []
    debit, credit = totals(positions)
    rule = None
    if decree.get("rule_id"):
        row = await db.get(FinancePostingRule, decree["rule_id"])
        if row is not None:
            name = None
            if row.counterparty_id:
                name = await db.scalar(
                    select(FinanceCounterparty.name).where(
                        FinanceCounterparty.id == row.counterparty_id
                    )
                )
            label = CATEGORY_LABELS.get(row.category, row.category)
            rule = {"id": row.id, "label": f"{label} · {name}" if name else label}
    batch = None
    if entry.batch_id:
        row = await db.get(FinancePostingBatch, entry.batch_id)
        if row is not None:
            batch = {"id": row.id, "number": row.number, "status": row.status}
    register = decree.get("register")
    return {
        "computed": bool(entry.decree),
        "manual": bool(decree.get("manual")),
        "computed_at": decree.get("computed_at"),
        "register": register,
        "register_label": REGISTER_LABELS.get(register or ""),
        "doc_type": decree.get("doc_type") or None,
        "description": decree.get("description") or None,
        "currency": decree.get("currency"),
        "rule": rule,
        "positions": positions_payload(positions, plan),
        "debit_total": money(debit),
        "credit_total": money(credit),
        "balanced": debit == credit and debit > 0,
        "issues": check(entry.decree, plan),
        "editable": entry.stage in EDITABLE_STAGES and not own,
        "batch": batch,
    }
