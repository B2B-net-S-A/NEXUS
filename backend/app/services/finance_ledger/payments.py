"""Przelewy i zapłaty faktur kosztowych (E3) — Finanse → „Przelewy”.

Zastępuje w eBI24 eksport przelewów do banku i „Importuj → Wyciągi bankowe →
Oznacz faktury jako zapłacone”. Reguły bez bazy: ``payment_rules.py``; stan
zapłaty w kolejce: ``payment_state.py``.

* **Płatność wpisu**: rachunek odbiorcy (ręczny na karcie > z faktury KSeF,
  gdy źródło go zna > z kartoteki kontrahenta), termin (``due_date`` kolejki
  E1), kwota do zapłaty (brutto ze źródła minus zapłaty), stan
  ``unpaid / in_batch / paid / partially_paid``, data i źródło zapłaty.
* **Faktury osób zespołu** płacą Płace (rozliczenie miesiąca, lista „Dla
  Finansów”, paczka Płac). Tu ich nie płacimy: w planie paczki są tylko dla
  Płac i admina (D2) i zawsze zablokowane („zapłatę prowadzą Płace”), stan
  w kolejce czytamy z rozliczenia, „Opłacono” i rachunek = 409, a obciążenia
  z wyciągu, które rozpoznaje ścieżka Płac (``statements.decide``) albo które
  Płace już zapisały, zostają tamtej ścieżce. Faktury kontraktorów klientów
  i dokumenty wydatków nie mają w NEXUSIE innej ścieżki zapłaty.
* **Paczka**: faktury z terminem do wybranej daty (bez terminu nie trafiają —
  historia sprzed NEXUSA była płacona w eBI24), bez „Wstrzymać płatność”
  i „Duplikat”, nie zapłacone i nie w innej paczce. Jedna paczka = jedna
  waluta; w złotych plik Elixir-O albo CSV, w walucie obcej tylko CSV.
  Dwie równoległe paczki: blokada doradcza i indeks częściowy na aktywnej
  pozycji. Anulowanie zwalnia pozycje, które nie są jeszcze zapłacone.
* **Wyciąg**: obciążenia → wpisy (``decide_debit``); ten sam plik drugi raz
  nic nie dopisuje, ta sama operacja z innego pliku (wyciąg dzienny
  i miesięczny) zostaje „pominięta” z powodem.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.export_safety import safe_row
from app.core.scheduling import DEFAULT_TZ
from app.models.app_setting import AppSetting
from app.models.client_settlement import ClientContractorInvoice
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.finance_payments import (
    FinanceCostPayment,
    FinanceCostPaymentRecord,
    FinanceCounterpartyAccount,
    FinancePaymentBatch,
    FinancePaymentBatchItem,
)
from app.models.hr_settlement import PayrollInvoice, PayrollPayment, PayrollSettlement
from app.models.user import User
from app.services.finance_ledger import costs
from app.services.finance_ledger import payment_rules as rules
from app.services.finance_ledger import payment_state
from app.services.finance_payments_schema import (
    NAME_MAX,
    REASON_MAX,
    TITLE_MAX,
)
from app.services.hr import white_list
from app.services.hr.bank import elixir, statements
from app.services.hr.bank.accounts import grouped_iban
from app.services.hr.bank.parsed import StatementLine

logger = logging.getLogger(__name__)
_ZONE = ZoneInfo(DEFAULT_TZ)

SETTING_KEY = "finance_payments"
MAX_AHEAD_DAYS = 30
BULK_MAX = 500
DUPLICATE_REASON = "Ta sama operacja była już na wcześniej wgranym wyciągu."
PAYROLL_DETAIL = (
    "Zapłatę faktury osoby zespołu prowadzą Płace (rozliczenie miesiąca) — "
    "tu jej nie oznaczasz."
)
NOT_FOUND = "Nie ma takiej faktury w kolejce."
ACCOUNT_SOURCE_LABELS = {
    "manual": "wpisany na karcie",
    "ksef": "z faktury w KSeF",
    "counterparty": "z kartoteki kontrahenta",
}
#: Etapy, z których faktura może iść do zapłaty (przyjęta do kolejki).
PAYABLE_STAGES = ("new", "verified", "ready", "booked")


class PaymentError(Exception):
    def __init__(
        self,
        message: str,
        status: int = 409,
        *,
        code: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.data = data or {}

    def detail(self) -> Any:
        if self.code is None and not self.data:
            return self.message
        return {"message": self.message, "code": self.code, **self.data}


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _money_text(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else f"{rules.money(value):.2f}"


# ── Ustawienia (rachunek nadawcy) ────────────────────────────────────────────


async def load_settings(db: AsyncSession) -> dict[str, Optional[str]]:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    raw = raw if isinstance(raw, dict) else {}
    account = raw.get("sender_account")
    name = raw.get("sender_name")
    return {
        "sender_name": name if isinstance(name, str) and name.strip() else None,
        "sender_account": account if isinstance(account, str) and account else None,
    }


async def save_settings(
    db: AsyncSession, *, sender_name: str, sender_account: str, actor_id: int
) -> dict[str, Optional[str]]:
    name = " ".join((sender_name or "").split())[:NAME_MAX]
    if len(name) < 2:
        raise PaymentError("Podaj nazwę nadawcy.", 422)
    try:
        account = rules.normalize_account(sender_account)
    except rules.PaymentRuleError as exc:
        raise PaymentError(str(exc), 422) from exc
    if not rules.is_domestic(account):
        raise PaymentError("Rachunek nadawcy to rachunek krajowy (26 cyfr).", 422)
    value = {"sender_name": name, "sender_account": account}
    statement = insert(AppSetting).values(
        key=SETTING_KEY, value=value, updated_by=actor_id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor_id},
        )
    )
    return {"sender_name": name, "sender_account": account}


# ── Wiersze kolejki z danymi źródła ──────────────────────────────────────────


@dataclass(frozen=True)
class PayRow:
    entry: FinanceCostEntry
    invoice_number: Optional[str]
    ksef_number: Optional[str]
    seller_name: Optional[str]
    issue_date: Optional[date]
    currency: str
    net: Optional[Decimal]
    vat: Optional[Decimal]
    gross: Optional[Decimal]
    due: Optional[date]

    @property
    def payroll(self) -> bool:
        return self.entry.source_type == "payroll_invoice"


async def _rows(
    db: AsyncSession,
    *conditions: Any,
    payroll: bool,
    due_until: Optional[date] = None,
) -> list[PayRow]:
    src = costs._sources()
    on_source, on_counterparty = costs._joined(src)
    due = func.coalesce(FinanceCostEntry.due_date, src.c.source_due)
    if due_until is not None:
        conditions = (*conditions, due <= due_until)
    result = await db.execute(
        select(
            FinanceCostEntry,
            src.c.invoice_number,
            src.c.ksef_number,
            func.coalesce(src.c.seller_name, FinanceCounterparty.name),
            src.c.issue_date,
            src.c.currency,
            src.c.net_amount,
            src.c.vat_amount,
            src.c.gross_amount,
            due,
        )
        .join(src, on_source)
        .outerjoin(FinanceCounterparty, on_counterparty)
        .where(*costs._payroll_scope(payroll), *conditions)
        .order_by(due.nulls_last(), FinanceCostEntry.id)
    )
    return [
        PayRow(
            entry=entry,
            invoice_number=number,
            ksef_number=ksef,
            seller_name=seller,
            issue_date=issued,
            currency=currency or "PLN",
            net=net,
            vat=vat,
            gross=gross,
            due=due_on,
        )
        for entry, number, ksef, seller, issued, currency, net, vat, gross, due_on in (
            result.all()
        )
    ]


async def _payments(db: AsyncSession, ids: list[int]) -> dict[int, FinanceCostPayment]:
    if not ids:
        return {}
    return {
        row.entry_id: row
        for row in await db.scalars(
            select(FinanceCostPayment).where(FinanceCostPayment.entry_id.in_(ids))
        )
    }


async def _active_items(
    db: AsyncSession, ids: list[int]
) -> dict[int, tuple[FinancePaymentBatchItem, FinancePaymentBatch]]:
    if not ids:
        return {}
    rows = await db.execute(
        select(FinancePaymentBatchItem, FinancePaymentBatch)
        .join(
            FinancePaymentBatch,
            FinancePaymentBatch.id == FinancePaymentBatchItem.batch_id,
        )
        .where(
            FinancePaymentBatchItem.entry_id.in_(ids),
            FinancePaymentBatchItem.status == "active",
        )
    )
    return {item.entry_id: (item, batch) for item, batch in rows.all()}


async def _paid_sums(db: AsyncSession, ids: list[int]) -> dict[int, Decimal]:
    if not ids:
        return {}
    rows = await db.execute(
        select(
            FinanceCostPaymentRecord.entry_id, func.sum(FinanceCostPaymentRecord.amount)
        )
        .where(
            FinanceCostPaymentRecord.entry_id.in_(ids),
            FinanceCostPaymentRecord.match_status == "matched",
        )
        .group_by(FinanceCostPaymentRecord.entry_id)
    )
    return {int(entry_id): Decimal(total or 0) for entry_id, total in rows.all()}


@dataclass(frozen=True)
class AccountChoice:
    account: Optional[str]
    source: Optional[str]
    ksef: tuple[str, ...] = ()
    counterparty: Optional[str] = None
    manual: Optional[str] = None
    #: Rachunek ze źródła, którego nie dało się odczytać (zły format).
    invalid: bool = False


def _valid(raw: Any) -> Optional[str]:
    try:
        return rules.normalize_account(str(raw))
    except rules.PaymentRuleError:
        return None


async def _accounts(db: AsyncSession, rows: list[PayRow]) -> dict[int, AccountChoice]:
    ids = [row.entry.id for row in rows]
    manual = {
        entry_id: payment.account
        for entry_id, payment in (await _payments(db, ids)).items()
        if payment.account
    }
    contractor_ids = [
        row.entry.source_id
        for row in rows
        if row.entry.source_type == "contractor_invoice"
    ]
    ksef: dict[int, tuple[str, ...]] = {}
    if contractor_ids:
        for invoice_id, details in (
            await db.execute(
                select(
                    ClientContractorInvoice.id, ClientContractorInvoice.details
                ).where(ClientContractorInvoice.id.in_(contractor_ids))
            )
        ).all():
            found = [_valid(raw) for raw in (details or {}).get("accounts") or []]
            ksef[int(invoice_id)] = tuple(dict.fromkeys(a for a in found if a))
    party_ids = {row.entry.counterparty_id for row in rows if row.entry.counterparty_id}
    parties: dict[int, str] = {}
    if party_ids:
        parties = {
            row.counterparty_id: row.account
            for row in await db.scalars(
                select(FinanceCounterpartyAccount).where(
                    FinanceCounterpartyAccount.counterparty_id.in_(party_ids)
                )
            )
        }
    result: dict[int, AccountChoice] = {}
    for row in rows:
        entry = row.entry
        from_ksef = (
            ksef.get(entry.source_id, ())
            if entry.source_type == "contractor_invoice"
            else ()
        )
        party = parties.get(entry.counterparty_id or 0)
        own = manual.get(entry.id)
        if own:
            account, source = own, "manual"
        elif from_ksef:
            account, source = from_ksef[0], "ksef"
        elif party:
            account, source = party, "counterparty"
        else:
            account, source = None, None
        result[entry.id] = AccountChoice(
            account=account,
            source=source,
            ksef=from_ksef,
            counterparty=party,
            manual=own,
        )
    return result


async def refresh(
    db: AsyncSession, entry_ids: list[int], *, actor_id: Optional[int]
) -> None:
    """Przelicz stan zapłaty wpisów (zapłaty z wyciągu, ręczne, aktywna paczka)."""

    ids = list(dict.fromkeys(entry_ids))
    if not ids:
        return
    rows = await _rows(db, FinanceCostEntry.id.in_(ids), payroll=True)
    paid = await _paid_sums(db, ids)
    items = await _active_items(db, ids)
    payments = await _payments(db, ids)
    last = {
        int(entry_id): (booked_on, kind)
        for entry_id, booked_on, kind in (
            await db.execute(
                select(
                    FinanceCostPaymentRecord.entry_id,
                    FinanceCostPaymentRecord.booked_on,
                    FinanceCostPaymentRecord.kind,
                )
                .where(
                    FinanceCostPaymentRecord.entry_id.in_(ids),
                    FinanceCostPaymentRecord.match_status == "matched",
                )
                .order_by(
                    FinanceCostPaymentRecord.booked_on, FinanceCostPaymentRecord.id
                )
            )
        ).all()
    }
    for row in rows:
        if row.payroll:
            continue
        entry_id = row.entry.id
        total = rules.money(paid.get(entry_id, Decimal("0")))
        gross = rules.money(row.gross) if row.gross is not None else None
        if gross is not None and gross > rules.ZERO and total >= gross:
            state = "paid"
        elif entry_id in items:
            state = "in_batch"
        elif total > rules.ZERO:
            state = "partially_paid"
        else:
            state = "unpaid"
        payment = payments.get(entry_id)
        if payment is None:
            if state == "unpaid" and total == rules.ZERO:
                continue
            payment = FinanceCostPayment(entry_id=entry_id)
            db.add(payment)
        payment.state = state
        payment.paid_amount = total
        booked, kind = last.get(entry_id, (None, None))
        payment.paid_on = booked if total > rules.ZERO else None
        payment.paid_source = (
            ("statement" if kind == "statement_line" else "manual")
            if total > rules.ZERO
            else None
        )
        if actor_id is not None:
            payment.updated_by = actor_id
    await db.flush()


# ── Plan paczki ──────────────────────────────────────────────────────────────


@dataclass
class PlanItem:
    row: PayRow
    to_pay: Optional[Decimal] = None
    mode: Optional[str] = None
    mode_suggested: bool = False
    account: Optional[str] = None
    account_source: Optional[str] = None
    title_lines: list[str] = field(default_factory=list)
    white_list: dict[str, Any] = field(default_factory=lambda: {"state": "skipped"})
    block: Optional[str] = None
    acks: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    batch_id: Optional[int] = None

    @property
    def entry_id(self) -> int:
        return self.row.entry.id


def item_payload(item: PlanItem) -> dict[str, Any]:
    row = item.row
    wl_state = item.white_list.get("state", "skipped")
    return {
        "entry_id": item.entry_id,
        "invoice_number": row.invoice_number,
        "ksef_number": row.ksef_number,
        "seller_name": row.seller_name,
        "seller_nip": row.entry.seller_nip,
        "category": row.entry.category,
        "due_date": _iso(row.due),
        "currency": row.currency,
        "gross_amount": _money_text(row.gross),
        "vat_amount": _money_text(row.vat),
        "to_pay": _money_text(item.to_pay),
        "mode": item.mode,
        "mode_label": rules.MODE_LABELS.get(item.mode or ""),
        "mode_suggested": item.mode_suggested,
        "account": item.account,
        "account_source": item.account_source,
        "account_source_label": ACCOUNT_SOURCE_LABELS.get(item.account_source or ""),
        "title": " ".join(item.title_lines),
        "white_list": {
            **item.white_list,
            "label": rules.WHITE_LIST_LABELS.get(wl_state, wl_state),
        },
        "selectable": item.block is None,
        "block": item.block,
        "block_label": rules.BLOCK_LABELS.get(item.block or ""),
        "acks": [{"code": code, "label": rules.ACK_LABELS[code]} for code in item.acks],
        "hints": [
            {"code": code, "label": rules.HINT_LABELS[code]} for code in item.hints
        ],
        "batch_id": item.batch_id,
        "preselect": item.block is None and not item.acks,
    }


async def _month_net(
    db: AsyncSession, rows: list[PayRow], *, payroll: bool
) -> dict[tuple[str, int, int], Decimal]:
    keys = {
        (row.entry.seller_nip, row.issue_date.year, row.issue_date.month)
        for row in rows
        if row.entry.seller_nip and row.issue_date and row.currency == "PLN"
    }
    if not keys:
        return {}
    nips = {nip for nip, _y, _m in keys}
    others = await _rows(
        db,
        FinanceCostEntry.seller_nip.in_(nips),
        FinanceCostEntry.stage != "rejected",
        payroll=payroll,
    )
    totals: dict[tuple[str, int, int], Decimal] = defaultdict(lambda: Decimal("0"))
    for other in others:
        if other.issue_date is None or other.currency != "PLN" or other.net is None:
            continue
        if "duplicate" in (other.entry.flags or []):
            continue
        key = (other.entry.seller_nip, other.issue_date.year, other.issue_date.month)
        if key in keys:
            totals[key] += Decimal(other.net)
    return dict(totals)


async def _white_list(
    db: AsyncSession,
    nip: Optional[str],
    account: str,
    today: date,
    actor_id: Optional[int],
) -> dict[str, Any]:
    if not rules.is_domestic(account):
        return {"state": "foreign"}
    if not nip:
        return {"state": "no_nip"}
    try:
        check = await white_list.check(db, nip, account, today, actor_id=actor_id)
    except white_list.WhiteListError as exc:
        if exc.code == "disabled":
            return {"state": "off"}
        if exc.code == "invalid_nip":
            return {"state": "no_nip"}
        return {"state": "unchecked", "error": exc.code}
    return {
        "state": "listed" if check.listed else "not_listed",
        "request_id": check.request_id,
        "on_date": check.on_date.isoformat(),
    }


async def plan(
    db: AsyncSession,
    *,
    until: Optional[date] = None,
    entry_ids: Optional[list[int]] = None,
    today: date,
    actor_id: Optional[int],
    payroll: bool,
) -> list[PlanItem]:
    """Faktury do zapłaty do daty (albo wskazane) z trybem, tytułem i białą listą."""

    if entry_ids is not None:
        rows = await _rows(
            db, FinanceCostEntry.id.in_(entry_ids[:BULK_MAX]), payroll=payroll
        )
    else:
        # Bez terminu faktura nie trafia do planu: historia sprzed NEXUSA była
        # płacona w eBI24, a KSeF nie niesie terminu (wpisują go Finanse).
        rows = await _rows(
            db,
            FinanceCostEntry.stage != "rejected",
            payment_state.state_sql() != "paid",
            payroll=payroll,
            due_until=until or today,
        )
    ids = [row.entry.id for row in rows]
    accounts = await _accounts(db, rows)
    items_by_entry = await _active_items(db, ids)
    paid = await _paid_sums(db, ids)
    states = await payment_state.for_entries(db, [row.entry for row in rows])
    month_net = await _month_net(db, rows, payroll=payroll)
    items: list[PlanItem] = []
    for row in rows:
        entry = row.entry
        item = PlanItem(row=row)
        items.append(item)
        flags = set(entry.flags or [])
        active = items_by_entry.get(entry.id)
        if active is not None:
            item.batch_id = active[1].id
        if row.payroll:
            item.block = "payroll_path"
            continue
        if entry.stage not in PAYABLE_STAGES:
            item.block = "stage"
            continue
        if "hold_payment" in flags:
            item.block = "hold"
            continue
        if "duplicate" in flags:
            item.block = "duplicate"
            continue
        state = states.get(entry.id, {}).get("state")
        if state == "paid":
            item.block = "paid"
            continue
        if active is not None:
            item.block = "in_batch"
            continue
        if row.gross is None or row.gross <= 0:
            item.block = "no_amount"
            continue
        gross = rules.money(row.gross)
        item.to_pay = rules.money(gross - paid.get(entry.id, Decimal("0")))
        if item.to_pay <= rules.ZERO:
            item.block = "paid"
            continue
        try:
            mode = rules.mode_for(flags, gross, row.currency)
        except rules.PaymentRuleError as exc:
            item.block = exc.code
            continue
        item.mode, item.mode_suggested = mode.mode, mode.suggested
        choice = accounts[entry.id]
        if mode.mode == "tax_office":
            # Rachunek urzędu tylko ręcznie — nie z faktury ani kartoteki dostawcy.
            if not choice.manual:
                item.block = "tax_office_manual"
                continue
            item.account, item.account_source = choice.manual, "manual"
        else:
            item.account, item.account_source = choice.account, choice.source
        if not item.account:
            item.block = "no_account"
            continue
        if row.currency == "PLN" and not rules.is_domestic(item.account):
            item.block = "domestic_account"
            continue
        try:
            item.title_lines = rules.title_lines(
                mode=mode.mode,
                invoice_number=row.invoice_number,
                ksef_number=row.ksef_number,
                from_ksef=entry.from_ksef,
                vat_amount=row.vat,
                seller_nip=entry.seller_nip,
                today=today,
            )
        except rules.PaymentRuleError as exc:
            item.block = exc.code
            continue
        if entry.from_ksef and not row.ksef_number and today < rules.KSEF_TITLE_FROM:
            item.hints.append("ksef_from_2027")
        if mode.mode == "tax_office":
            item.white_list = {"state": "tax_office"}
        else:
            item.white_list = await _white_list(
                db, entry.seller_nip, item.account, today, actor_id
            )
        if rules.needs_white_list_ack(
            mode=mode.mode,
            currency=row.currency,
            gross=gross,
            white_list_state=item.white_list["state"],
        ):
            item.acks.append("white_list")
        if mode.suggested:
            item.acks.append("mpp_suggested")
        month_key = (
            (entry.seller_nip, row.issue_date.year, row.issue_date.month)
            if entry.seller_nip and row.issue_date
            else None
        )
        if rules.art_105a_hint(
            mode=mode.mode,
            gross=gross,
            currency=row.currency,
            month_net=month_net.get(month_key) if month_key else None,
        ):
            item.hints.append("art_105a")
    return items


def plan_summary(items: list[PlanItem]) -> dict[str, Any]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in items:
        if item.block is None and item.to_pay is not None:
            totals[item.row.currency] += item.to_pay
    return {
        "count": len(items),
        "selectable": sum(1 for item in items if item.block is None),
        "blocked": sum(1 for item in items if item.block is not None),
        "totals": {currency: _money_text(total) for currency, total in totals.items()},
    }


# ── Paczka ───────────────────────────────────────────────────────────────────


def _execution_date(raw: Optional[date], today: date) -> date:
    chosen = raw or today
    if chosen < today or chosen > today + timedelta(days=MAX_AHEAD_DAYS):
        raise PaymentError(
            f"Data wykonania: od dziś do {MAX_AHEAD_DAYS} dni naprzód.", 422
        )
    return chosen


async def create_batch(
    db: AsyncSession,
    *,
    entry_ids: list[int],
    acknowledged: list[int],
    execution_date: Optional[date],
    fmt: Optional[str],
    today: date,
    actor_id: int,
    payroll: bool,
) -> dict[str, Any]:
    wanted = list(dict.fromkeys(entry_ids))[:BULK_MAX]
    if not wanted:
        raise PaymentError("Zaznacz faktury do paczki.", 422)
    when = _execution_date(execution_date, today)
    # Dwie paczki naraz nie wezmą tej samej faktury (drugi czeka i widzi „w paczce”).
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('finance-cost-batch'))")
    )
    items = await plan(
        db, entry_ids=wanted, today=today, actor_id=actor_id, payroll=payroll
    )
    found = {item.entry_id for item in items}
    missing = [entry_id for entry_id in wanted if entry_id not in found]
    if missing:
        raise PaymentError(
            NOT_FOUND, 404, code="not_found", data={"entry_ids": missing}
        )
    blocked = [item for item in items if item.block is not None]
    if blocked:
        raise PaymentError(
            "Część faktur nie może wejść do paczki — odśwież listę.",
            code="blocked",
            data={"items": [item_payload(item) for item in blocked]},
        )
    agreed = set(acknowledged)
    unconfirmed = [item for item in items if item.acks and item.entry_id not in agreed]
    if unconfirmed:
        raise PaymentError(
            "Odhacz ostrzeżenia przy zaznaczonych fakturach (biała lista, MPP).",
            code="needs_ack",
            data={"items": [item_payload(item) for item in unconfirmed]},
        )
    currencies = {item.row.currency for item in items}
    if len(currencies) > 1:
        raise PaymentError(
            "Jedna paczka to jedna waluta — zaznacz faktury w jednej walucie.", 422
        )
    currency = currencies.pop()
    chosen = fmt or ("elixir" if currency == "PLN" else "csv")
    if chosen == "elixir" and currency != "PLN":
        raise PaymentError("Elixir to przelewy krajowe w złotych — wybierz CSV.", 422)
    if chosen == "elixir" and not (await load_settings(db))["sender_account"]:
        raise PaymentError(
            "Ustaw rachunek nadawcy (Przelewy → Rachunek nadawcy), żeby utworzyć plik Elixir.",
            code="no_sender",
        )
    batch = FinancePaymentBatch(
        currency=currency, format=chosen, execution_date=when, created_by=actor_id
    )
    db.add(batch)
    await db.flush()
    for item in items:
        row = item.row
        db.add(
            FinancePaymentBatchItem(
                batch_id=batch.id,
                entry_id=item.entry_id,
                mode=item.mode,
                amount=item.to_pay,
                vat_amount=row.vat,
                currency=row.currency,
                account=item.account,
                recipient_name=(row.seller_name or row.entry.seller_nip or "Odbiorca")[
                    :NAME_MAX
                ],
                title_lines=list(item.title_lines),
                white_list=dict(item.white_list),
                acknowledged_by=actor_id if item.acks else None,
            )
        )
    try:
        await db.flush()
    except IntegrityError as exc:
        raise PaymentError(
            "Faktura weszła już do innej paczki — odśwież listę.", code="in_batch"
        ) from exc
    await refresh(db, [item.entry_id for item in items], actor_id=actor_id)
    return await batch_detail(db, batch.id, payroll=payroll)


async def _batch(
    db: AsyncSession, batch_id: int, *, lock: bool = False
) -> FinancePaymentBatch:
    query = select(FinancePaymentBatch).where(FinancePaymentBatch.id == batch_id)
    if lock:
        query = query.with_for_update()
    batch = await db.scalar(query)
    if batch is None:
        raise PaymentError("Nie ma takiej paczki przelewów.", 404)
    return batch


async def _batch_items(
    db: AsyncSession, batch_id: int, *, payroll: bool
) -> list[tuple[FinancePaymentBatchItem, FinanceCostEntry]]:
    rows = await db.execute(
        select(FinancePaymentBatchItem, FinanceCostEntry)
        .join(FinanceCostEntry, FinanceCostEntry.id == FinancePaymentBatchItem.entry_id)
        .where(
            FinancePaymentBatchItem.batch_id == batch_id, *costs._payroll_scope(payroll)
        )
        .order_by(FinancePaymentBatchItem.id)
    )
    return list(rows.all())


def _batch_status(batch: FinancePaymentBatch, statuses: list[str]) -> str:
    if batch.status == "cancelled":
        return "cancelled"
    live = [status for status in statuses if status != "released"]
    if live and all(status == "done" for status in live):
        return "done"
    return "active"


BATCH_STATUS_LABELS = {
    "active": "Czeka na bank",
    "done": "Zapłacona",
    "cancelled": "Anulowana",
}


async def batch_detail(
    db: AsyncSession, batch_id: int, *, payroll: bool
) -> dict[str, Any]:
    batch = await _batch(db, batch_id)
    rows = await _batch_items(db, batch_id, payroll=payroll)
    src_rows = {
        row.entry.id: row
        for row in await _rows(
            db,
            FinanceCostEntry.id.in_([entry.id for _item, entry in rows] or [0]),
            payroll=payroll,
        )
    }
    status = _batch_status(batch, [item.status for item, _entry in rows])
    total = sum(
        (Decimal(item.amount) for item, _entry in rows if item.status != "released"),
        Decimal("0"),
    )
    return {
        "id": batch.id,
        "currency": batch.currency,
        "format": batch.format,
        "execution_date": _iso(batch.execution_date),
        "status": status,
        "status_label": BATCH_STATUS_LABELS[status],
        "created_at": _iso(batch.created_at),
        "count": sum(1 for item, _entry in rows if item.status != "released"),
        "total": _money_text(total),
        "items": [
            {
                "entry_id": entry.id,
                "invoice_number": src_rows[entry.id].invoice_number
                if entry.id in src_rows
                else None,
                "recipient_name": item.recipient_name,
                "account": item.account,
                "amount": _money_text(item.amount),
                "currency": item.currency,
                "mode": item.mode,
                "mode_label": rules.MODE_LABELS[item.mode],
                "title": " ".join(item.title_lines or []),
                "white_list": {
                    **(item.white_list or {}),
                    "label": rules.WHITE_LIST_LABELS.get(
                        (item.white_list or {}).get("state", ""), ""
                    ),
                },
                "acknowledged": item.acknowledged_by is not None,
                "status": item.status,
            }
            for item, entry in rows
        ],
    }


async def list_batches(db: AsyncSession, *, limit: int = 30) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(
            FinancePaymentBatch,
            User.name,
            func.count(FinancePaymentBatchItem.id).filter(
                FinancePaymentBatchItem.status != "released"
            ),
            func.sum(FinancePaymentBatchItem.amount).filter(
                FinancePaymentBatchItem.status != "released"
            ),
            func.array_agg(FinancePaymentBatchItem.status),
        )
        .outerjoin(User, User.id == FinancePaymentBatch.created_by)
        .outerjoin(
            FinancePaymentBatchItem,
            FinancePaymentBatchItem.batch_id == FinancePaymentBatch.id,
        )
        .group_by(FinancePaymentBatch.id, User.name)
        .order_by(FinancePaymentBatch.id.desc())
        .limit(limit)
    )
    out = []
    for batch, author, count, total, statuses in rows.all():
        status = _batch_status(batch, [s for s in statuses or [] if s])
        out.append(
            {
                "id": batch.id,
                "currency": batch.currency,
                "format": batch.format,
                "execution_date": _iso(batch.execution_date),
                "created_at": _iso(batch.created_at),
                "created_by_name": author,
                "count": int(count or 0),
                "total": _money_text(Decimal(total or 0)),
                "status": status,
                "status_label": BATCH_STATUS_LABELS[status],
            }
        )
    return out


CSV_COLUMNS = (
    "Rachunek odbiorcy",
    "Nazwa odbiorcy",
    "Kwota",
    "Waluta",
    "Tytuł",
    "Data wykonania",
    "Tryb",
    "Kwota VAT",
    "NIP sprzedawcy",
)


def render_csv(
    rows: list[tuple[FinancePaymentBatchItem, FinanceCostEntry]], when: date
) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for item, entry in rows:
        account = (
            grouped_iban(item.account)
            if rules.is_domestic(item.account)
            else item.account
        )
        writer.writerow(
            safe_row(
                [
                    account,
                    item.recipient_name,
                    elixir.amount_text(Decimal(item.amount)),
                    item.currency,
                    " ".join(item.title_lines or []),
                    when.isoformat(),
                    rules.MODE_LABELS[item.mode],
                    elixir.amount_text(Decimal(item.vat_amount))
                    if item.mode == "mpp" and item.vat_amount is not None
                    else "",
                    entry.seller_nip or "",
                ]
            )
        )
    return ("﻿" + buffer.getvalue()).encode("utf-8")


async def batch_file(
    db: AsyncSession, batch_id: int, *, payroll: bool, actor_id: int
) -> tuple[str, bytes, str]:
    batch = await _batch(db, batch_id)
    if batch.status == "cancelled":
        raise PaymentError("Ta paczka jest anulowana.")
    rows = [
        (item, entry)
        for item, entry in await _batch_items(db, batch_id, payroll=payroll)
        if item.status != "released"
    ]
    if not rows:
        raise PaymentError("W tej paczce nie ma przelewów.")
    stamp = batch.execution_date.isoformat()
    logger.info(
        "[finance-payments] plik paczki %s (%s, %s pozycji) pobrany przez %s",
        batch.id,
        batch.format,
        len(rows),
        actor_id,
    )
    if batch.format == "csv":
        return (
            f"przelewy-kosztow-{stamp}-{batch.id}.csv",
            render_csv(rows, batch.execution_date),
            "text/csv",
        )
    settings = await load_settings(db)
    if not settings["sender_account"]:
        raise PaymentError(
            "Ustaw rachunek nadawcy (Przelewy → Rachunek nadawcy).", code="no_sender"
        )
    sender = elixir.Sender(
        name=settings["sender_name"] or "", account=settings["sender_account"]
    )
    transfers = [
        elixir.TransferRow(
            recipient_name=item.recipient_name,
            recipient_account=item.account,
            amount=Decimal(item.amount),
            title_lines=tuple(item.title_lines or []),
            execution_date=batch.execution_date,
            classification=elixir.CLASSIFICATION_MPP
            if item.mode == "mpp"
            else elixir.CLASSIFICATION,
        )
        for item, _entry in rows
    ]
    return (
        f"przelewy-kosztow-{stamp}-{batch.id}.pli",
        elixir.render_elixir(transfers, sender),
        "text/plain; charset=windows-1250",
    )


async def cancel_batch(
    db: AsyncSession, batch_id: int, *, actor_id: int, now: datetime, payroll: bool
) -> dict[str, Any]:
    batch = await _batch(db, batch_id, lock=True)
    if batch.status == "cancelled":
        raise PaymentError("Ta paczka jest już anulowana.")
    items = list(
        await db.scalars(
            select(FinancePaymentBatchItem)
            .where(
                FinancePaymentBatchItem.batch_id == batch_id,
                FinancePaymentBatchItem.status == "active",
            )
            .with_for_update()
        )
    )
    if not items:
        raise PaymentError(
            "W tej paczce nie ma nic do anulowania — przelewy są zapłacone."
        )
    for item in items:
        item.status = "released"
    batch.status = "cancelled"
    batch.cancelled_by = actor_id
    batch.cancelled_at = now
    await db.flush()
    await refresh(db, [item.entry_id for item in items], actor_id=actor_id)
    return {"id": batch.id, "released": len(items)}


# ── Płatność jednej faktury (karta) ──────────────────────────────────────────


async def _one(db: AsyncSession, entry_id: int, *, payroll: bool) -> PayRow:
    rows = await _rows(db, FinanceCostEntry.id == entry_id, payroll=payroll)
    if not rows:
        raise PaymentError(NOT_FOUND, 404)
    return rows[0]


async def entry_card(
    db: AsyncSession, entry_id: int, *, payroll: bool
) -> dict[str, Any]:
    row = await _one(db, entry_id, payroll=payroll)
    entry = row.entry
    state = (await payment_state.for_entries(db, [entry]))[entry.id]
    base: dict[str, Any] = {
        "entry_id": entry.id,
        "path": state["path"],
        "state": state["state"],
        "state_label": state["label"],
        "due_date": _iso(row.due),
        "currency": row.currency,
        "gross_amount": _money_text(row.gross),
    }
    if row.payroll:
        settlement = (
            await db.execute(
                select(PayrollSettlement.status, PayrollSettlement.paid_at)
                .join(
                    PayrollInvoice, PayrollInvoice.settlement_id == PayrollSettlement.id
                )
                .where(PayrollInvoice.id == entry.source_id)
            )
        ).first()
        base.update(
            path_label=PAYROLL_DETAIL,
            paid_on=_iso(settlement.paid_at.astimezone(_ZONE).date())
            if settlement and settlement.paid_at
            else None,
            paid_source="other_path" if state["state"] == "paid" else None,
            paid_source_label=payment_state.SOURCE_LABELS["other_path"]
            if state["state"] == "paid"
            else None,
            settlement_status=settlement.status if settlement else None,
        )
        return base
    choice = (await _accounts(db, [row]))[entry.id]
    payment = (await _payments(db, [entry.id])).get(entry.id)
    paid = rules.money((await _paid_sums(db, [entry.id])).get(entry.id, Decimal("0")))
    active = (await _active_items(db, [entry.id])).get(entry.id)
    records = list(
        await db.scalars(
            select(FinanceCostPaymentRecord)
            .where(FinanceCostPaymentRecord.entry_id == entry.id)
            .order_by(FinanceCostPaymentRecord.booked_on, FinanceCostPaymentRecord.id)
        )
    )
    gross = rules.money(row.gross) if row.gross is not None else None
    try:
        mode = rules.mode_for(entry.flags or [], gross or rules.ZERO, row.currency)
        mode_payload: dict[str, Any] = {
            "mode": mode.mode,
            "mode_label": rules.MODE_LABELS[mode.mode],
            "mode_suggested": mode.suggested,
        }
    except rules.PaymentRuleError as exc:
        mode_payload = {"mode": None, "mode_label": None, "mode_problem": str(exc)}
    base.update(
        mode_payload,
        to_pay=_money_text(gross - paid) if gross is not None else None,
        paid_amount=_money_text(paid),
        paid_on=_iso(payment.paid_on) if payment else None,
        paid_source=payment.paid_source if payment else None,
        paid_source_label=payment_state.SOURCE_LABELS.get(
            (payment.paid_source if payment else None) or ""
        ),
        account=choice.account,
        account_source=choice.source,
        account_source_label=ACCOUNT_SOURCE_LABELS.get(choice.source or ""),
        accounts={
            "manual": choice.manual,
            "ksef": list(choice.ksef),
            "counterparty": choice.counterparty,
        },
        can_remember=entry.counterparty_id is not None,
        batch={
            "id": active[1].id,
            "execution_date": _iso(active[1].execution_date),
            "mode": active[0].mode,
            "amount": _money_text(active[0].amount),
        }
        if active
        else None,
        records=[
            {
                "id": record.id,
                "kind": record.kind,
                "match_status": record.match_status,
                "amount": _money_text(record.amount),
                "currency": record.currency,
                "booked_on": _iso(record.booked_on),
                "title": record.title,
                "reason": record.reason,
            }
            for record in records
        ],
    )
    return base


async def set_account(
    db: AsyncSession,
    entry_id: int,
    *,
    account: Optional[str],
    remember: bool,
    actor_id: int,
    payroll: bool,
) -> None:
    row = await _one(db, entry_id, payroll=payroll)
    if row.payroll:
        raise PaymentError(PAYROLL_DETAIL)
    if (await _active_items(db, [entry_id])).get(entry_id):
        raise PaymentError(
            "Faktura jest w paczce — anuluj paczkę, żeby zmienić rachunek."
        )
    value: Optional[str] = None
    if account and account.strip():
        try:
            value = rules.normalize_account(account)
        except rules.PaymentRuleError as exc:
            raise PaymentError(str(exc), 422) from exc
    payment = await db.get(FinanceCostPayment, entry_id, with_for_update=True)
    if payment is None:
        payment = FinanceCostPayment(entry_id=entry_id, state="unpaid")
        db.add(payment)
    payment.account = value
    payment.updated_by = actor_id
    party_id = row.entry.counterparty_id
    if value and remember and party_id:
        statement = insert(FinanceCounterpartyAccount).values(
            counterparty_id=party_id, account=value, updated_by=actor_id
        )
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[FinanceCounterpartyAccount.counterparty_id],
                set_={
                    "account": value,
                    "updated_by": actor_id,
                    "updated_at": func.now(),
                },
            )
        )
    await db.flush()


async def mark_paid(
    db: AsyncSession,
    entry_id: int,
    *,
    amount: Optional[Decimal],
    paid_on: date,
    reason: str,
    actor_id: int,
    now: datetime,
    payroll: bool,
) -> None:
    """Ręczne „Opłacono” (karta, przelew poza paczką, kompensata) — z powodem."""

    note = " ".join((reason or "").split())
    if len(note) < 3:
        raise PaymentError(
            "Podaj powód (co najmniej 3 znaki), np. „karta firmowa”.", 422
        )
    row = await _one(db, entry_id, payroll=payroll)
    if row.payroll:
        raise PaymentError(PAYROLL_DETAIL)
    if row.gross is None or row.gross <= 0:
        raise PaymentError(rules.BLOCK_LABELS["no_amount"], 422)
    await db.execute(
        select(FinanceCostEntry.id)
        .where(FinanceCostEntry.id == entry_id)
        .with_for_update()
    )
    remaining = rules.money(
        Decimal(row.gross)
        - (await _paid_sums(db, [entry_id])).get(entry_id, Decimal("0"))
    )
    if remaining <= rules.ZERO:
        raise PaymentError("Faktura jest już zapłacona.")
    value = rules.money(amount) if amount is not None else remaining
    if value <= rules.ZERO:
        raise PaymentError("Kwota musi być większa od zera.", 422)
    if value > remaining:
        raise PaymentError("Kwota większa niż pozostało do zapłaty.", 422)
    db.add(
        FinanceCostPaymentRecord(
            kind="manual",
            entry_id=entry_id,
            match_status="matched",
            amount=value,
            currency=row.currency,
            booked_on=paid_on,
            reason=note[:REASON_MAX],
            created_by=actor_id,
            resolved_by=actor_id,
            resolved_at=now,
        )
    )
    await db.flush()
    await _close_items(db, [entry_id])
    await refresh(db, [entry_id], actor_id=actor_id)


async def _close_items(db: AsyncSession, entry_ids: list[int]) -> None:
    """Zapłata wpisu w paczce kończy jego pozycję (paczka „wykonana”)."""

    for item in await db.scalars(
        select(FinancePaymentBatchItem).where(
            FinancePaymentBatchItem.entry_id.in_(entry_ids),
            FinancePaymentBatchItem.status == "active",
        )
    ):
        item.status = "done"
    await db.flush()


# ── Wyciąg ───────────────────────────────────────────────────────────────────


@dataclass
class DebitResult:
    format: str
    statement: str
    operations: int = 0
    debits: int = 0
    matched: int = 0
    partial: int = 0
    unmatched: int = 0
    duplicates: int = 0
    known: int = 0
    team: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


async def _candidates(db: AsyncSession) -> list[rules.CostCandidate]:
    """Faktury, które obciążenie może opłacić (bez faktur osób zespołu)."""

    rows = await _rows(
        db,
        FinanceCostEntry.source_type != "payroll_invoice",
        FinanceCostEntry.stage != "rejected",
        payroll=False,
    )
    ids = [row.entry.id for row in rows]
    paid = await _paid_sums(db, ids)
    items = await _active_items(db, ids)
    accounts = await _accounts(db, rows)
    result = []
    for row in rows:
        if row.gross is None or row.gross <= 0:
            continue
        active = items.get(row.entry.id)
        choice = accounts[row.entry.id]
        known = {
            a
            for a in (choice.account, choice.manual, choice.counterparty, *choice.ksef)
            if a
        }
        if active:
            known.add(active[0].account)
        result.append(
            rules.CostCandidate(
                entry_id=row.entry.id,
                currency=row.currency,
                gross=rules.money(row.gross),
                paid=rules.money(paid.get(row.entry.id, Decimal("0"))),
                invoice_number=row.invoice_number,
                ksef_number=(row.ksef_number or "").upper() or None,
                accounts=frozenset(known),
                batch_amount=Decimal(active[0].amount) if active else None,
                batch_account=active[0].account if active else None,
            )
        )
    return result


async def _seen_elsewhere(db: AsyncSession, line: StatementLine, sha: str) -> bool:
    if not line.bank_ref:
        return False
    found = await db.scalar(
        select(func.count())
        .select_from(FinanceCostPaymentRecord)
        .where(
            FinanceCostPaymentRecord.kind == "statement_line",
            FinanceCostPaymentRecord.statement_sha256 != sha,
            FinanceCostPaymentRecord.statement_line_ref.endswith(
                f":{line.bank_ref[:48]}", autoescape=True
            ),
            FinanceCostPaymentRecord.amount == rules.money(line.amount),
            FinanceCostPaymentRecord.booked_on == line.booked_on,
        )
    )
    return bool(found)


async def import_debits(db: AsyncSession, raw: bytes, *, actor_id: int) -> DebitResult:
    """Obciążenia z wyciągu → zapłaty faktur kosztowych (bez commita)."""

    parsed = statements.parse_file(raw)
    sha = hashlib.sha256(raw).hexdigest()
    # Ta sama blokada co import Płac i Faktur do klientów (ten sam plik naraz).
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"hr-statement:{sha}"},
    )
    result = DebitResult(format=parsed.format, statement=sha[:12])
    result.operations = len(parsed.lines)
    known = set(
        await db.scalars(
            select(FinanceCostPaymentRecord.statement_line_ref).where(
                FinanceCostPaymentRecord.kind == "statement_line",
                FinanceCostPaymentRecord.statement_sha256 == sha,
            )
        )
    )
    payroll_refs = set(
        await db.scalars(
            select(PayrollPayment.statement_line_ref).where(
                PayrollPayment.kind == "statement_line",
                PayrollPayment.statement_sha256 == sha,
            )
        )
    )
    team_accounts, _unreadable = await statements.account_owners(db)
    team = await statements.load_candidates(db)
    candidates = {c.entry_id: c for c in await _candidates(db)}
    for line in parsed.lines:
        if line.direction != "debit":
            result.skipped += 1
            continue
        result.debits += 1
        if line.line_ref in known:
            result.known += 1
            continue
        # Obciążenie, które dotyczy osoby z zespołu, zostaje ścieżce Płac.
        if (
            line.line_ref in payroll_refs
            or statements.decide(line, team, team_accounts).related
        ):
            result.team += 1
            continue
        decision = rules.decide_debit(line, list(candidates.values()))
        if not decision.related:
            result.skipped += 1
            continue
        record = FinanceCostPaymentRecord(
            kind="statement_line",
            amount=rules.money(line.amount),
            currency=line.currency,
            booked_on=line.booked_on,
            title=(line.title or "")[:TITLE_MAX] or None,
            counterparty_name=(line.counterparty_name or "")[:NAME_MAX] or None,
            counterparty_last4=(line.counterparty_account or "")[-4:] or None,
            statement_sha256=sha,
            statement_format=parsed.format,
            statement_line_ref=line.line_ref,
            created_by=actor_id,
        )
        if await _seen_elsewhere(db, line, sha):
            record.match_status = "ignored"
            record.reason = DUPLICATE_REASON
            db.add(record)
            result.duplicates += 1
            continue
        if decision.entry_id is None:
            record.match_status = "unmatched"
            record.reason = rules.DEBIT_REASON_LABELS.get(decision.reason)
            record.candidates = list(decision.candidates)
            db.add(record)
            result.unmatched += 1
            continue
        record.match_status = "matched"
        record.entry_id = decision.entry_id
        record.amount = decision.amount or rules.money(line.amount)
        if decision.reason.endswith("_mpp"):
            record.reason = "Podzielona płatność: VAT z rachunku VAT."
        elif decision.partial:
            record.reason = "Zapłata częściowa."
        db.add(record)
        await db.flush()
        await _close_items(db, [decision.entry_id])
        await refresh(db, [decision.entry_id], actor_id=actor_id)
        found = candidates[decision.entry_id]
        candidates[decision.entry_id] = replace(
            found,
            paid=rules.money(found.paid + record.amount),
            batch_amount=None,
            batch_account=None,
        )
        if decision.partial:
            result.partial += 1
        else:
            result.matched += 1
    await db.flush()
    logger.info("[finance-payments] wyciąg %s: %s", sha[:12], result.as_dict())
    return result


async def statement_overview(db: AsyncSession) -> dict[str, Any]:
    records = list(
        await db.scalars(
            select(FinanceCostPaymentRecord)
            .where(
                FinanceCostPaymentRecord.kind == "statement_line",
                FinanceCostPaymentRecord.match_status == "unmatched",
            )
            .order_by(
                FinanceCostPaymentRecord.booked_on.desc(), FinanceCostPaymentRecord.id
            )
        )
    )
    hint_ids = {entry_id for record in records for entry_id in record.candidates or []}
    hints = {
        row.entry.id: row
        for row in await _rows(
            db,
            FinanceCostEntry.id.in_(hint_ids or {0}),
            FinanceCostEntry.source_type != "payroll_invoice",
            payroll=False,
        )
    }
    recent = await db.execute(
        select(
            FinanceCostPaymentRecord.statement_sha256,
            FinanceCostPaymentRecord.statement_format,
            func.min(FinanceCostPaymentRecord.created_at),
            func.count(),
            func.count().filter(FinanceCostPaymentRecord.match_status == "matched"),
            func.count().filter(FinanceCostPaymentRecord.match_status == "unmatched"),
        )
        .where(FinanceCostPaymentRecord.kind == "statement_line")
        .group_by(
            FinanceCostPaymentRecord.statement_sha256,
            FinanceCostPaymentRecord.statement_format,
        )
        .order_by(func.min(FinanceCostPaymentRecord.created_at).desc())
        .limit(5)
    )
    return {
        "unmatched": [
            {
                "id": record.id,
                "booked_on": _iso(record.booked_on),
                "amount": _money_text(record.amount),
                "currency": record.currency,
                "title": record.title or "",
                "counterparty_name": record.counterparty_name,
                "counterparty_last4": record.counterparty_last4,
                "reason": record.reason,
                "hints": [
                    {
                        "entry_id": entry_id,
                        "invoice_number": hints[entry_id].invoice_number,
                        "seller_name": hints[entry_id].seller_name,
                        "gross_amount": _money_text(hints[entry_id].gross),
                        "currency": hints[entry_id].currency,
                    }
                    for entry_id in record.candidates or []
                    if entry_id in hints
                ],
            }
            for record in records
        ],
        "recent": [
            {
                "statement": str(sha)[:12],
                "format": fmt,
                "imported_at": _iso(imported),
                "lines": int(total),
                "matched": int(matched),
                "unmatched": int(unmatched),
            }
            for sha, fmt, imported, total, matched, unmatched in recent.all()
        ],
    }


async def _unmatched(db: AsyncSession, record_id: int) -> FinanceCostPaymentRecord:
    record = await db.scalar(
        select(FinanceCostPaymentRecord)
        .where(
            FinanceCostPaymentRecord.id == record_id,
            FinanceCostPaymentRecord.kind == "statement_line",
        )
        .with_for_update()
    )
    if record is None:
        raise PaymentError("Nie ma takiej operacji z wyciągu.", 404)
    if record.match_status != "unmatched":
        raise PaymentError("Ta operacja jest już rozstrzygnięta.")
    return record


async def assign_record(
    db: AsyncSession,
    record_id: int,
    entry_id: int,
    *,
    actor_id: int,
    now: datetime,
    payroll: bool,
) -> None:
    record = await _unmatched(db, record_id)
    row = await _one(db, entry_id, payroll=payroll)
    if row.payroll:
        raise PaymentError(PAYROLL_DETAIL)
    if row.currency != record.currency:
        raise PaymentError("Waluta przelewu jest inna niż waluta faktury.", 422)
    if row.gross is None or row.gross <= 0:
        raise PaymentError(rules.BLOCK_LABELS["no_amount"], 422)
    remaining = rules.money(
        Decimal(row.gross)
        - (await _paid_sums(db, [entry_id])).get(entry_id, Decimal("0"))
    )
    if remaining <= rules.ZERO:
        raise PaymentError(
            "Faktura jest już zapłacona — sprawdź, czy to nie podwójna zapłata."
        )
    if Decimal(record.amount) > remaining:
        raise PaymentError("Kwota przelewu większa niż pozostało do zapłaty.", 422)
    record.entry_id = entry_id
    record.match_status = "matched"
    record.resolved_by = actor_id
    record.resolved_at = now
    await db.flush()
    await _close_items(db, [entry_id])
    await refresh(db, [entry_id], actor_id=actor_id)


async def ignore_record(
    db: AsyncSession, record_id: int, *, reason: str, actor_id: int, now: datetime
) -> None:
    note = " ".join((reason or "").split())
    if len(note) < 3:
        raise PaymentError("Podaj powód pominięcia (co najmniej 3 znaki).", 422)
    record = await _unmatched(db, record_id)
    record.match_status = "ignored"
    record.reason = note[:REASON_MAX]
    record.resolved_by = actor_id
    record.resolved_at = now
    await db.flush()


__all__ = [
    "PaymentError",
    "PlanItem",
    "assign_record",
    "batch_detail",
    "batch_file",
    "cancel_batch",
    "create_batch",
    "entry_card",
    "ignore_record",
    "import_debits",
    "item_payload",
    "list_batches",
    "load_settings",
    "mark_paid",
    "plan",
    "plan_summary",
    "refresh",
    "render_csv",
    "save_settings",
    "set_account",
    "statement_overview",
]
