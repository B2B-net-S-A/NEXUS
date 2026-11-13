"""Finanse → „Księgowanie” (E2, makieta M3): eksport miesiąca do Symfonii FK.

Miesiąc = miesiąc wpływu faktury (``received_at`` w kalendarzu firmy), jak
filtr „Miesiąc wpływu” w kolejce. Lista: wpisy „Gotowe do księgowania” spoza
paczek, per rejestr z sumami Wn/Ma i kontrolą (bilans, konto kontrahenta,
konta w planie).

„Pobierz plik” zakłada paczkę (numer ``RRRR-MM/n``, kto i kiedy, lista wpisów,
plik i jego SHA-256) i zapisuje bajty pliku — ponowne pobranie tej paczki daje
ten sam plik. Wpis w paczce zostaje „Gotowy”, ale nie cofa się go (najpierw
„Anuluj paczkę”). „Oznacz jako zaksięgowane” przestawia wpisy paczki na
``booked``. Faktury z wadą dekretu (też kwoty źródła zmienione po dekrecie)
„Pobierz plik” pomija — zostają „Gotowe”, z powodami na liście, i wchodzą do
następnej paczki; same wadliwe = paczka nie powstaje (409). Kwoty źródła
zmienione po pobraniu blokują „Oznacz jako zaksięgowane” (409).

Faktury osób zespołu (D2) widzą tylko Płace i admin: osoba bez Płac nie widzi
ich na liście, nie wkłada do paczki i nie widzi paczek, które je mają.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date, local_month_bounds
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.finance_posting import FinancePostingBatch
from app.models.user import User
from app.services.finance_ledger import posting
from app.services.finance_ledger.costs import (
    LedgerError,
    _event,
    _payroll_scope,
    _select,
    _sources,
)
from app.services.finance_ledger.export_formats import (
    DEFAULT_FORMAT,
    FORMATS,
    ExportRow,
)
from app.services.finance_posting_schema import REGISTERS

#: Klucz blokady numeracji paczek (``pg_advisory_xact_lock``).
_NUMBER_LOCK = 697_0001
BATCH_STATUS_LABELS = {
    "exported": "Pobrana — czeka na zaksięgowanie",
    "booked": "Zaksięgowana",
    "cancelled": "Anulowana",
}
NO_BATCH = "Nie ma takiej paczki."


@dataclass(frozen=True)
class Item:
    entry: FinanceCostEntry
    row: Any
    issues: list[str]


def _month_conditions(month: date) -> list[Any]:
    bounds = local_month_bounds(month)
    return [
        FinanceCostEntry.received_at >= bounds.start_utc,
        FinanceCostEntry.received_at < bounds.end_utc,
    ]


async def _items(
    db: AsyncSession, month: date, *, payroll: bool, lock: bool = False
) -> list[Item]:
    conditions = [
        FinanceCostEntry.stage == "ready",
        FinanceCostEntry.batch_id.is_(None),
        *_month_conditions(month),
        *_payroll_scope(payroll),
    ]
    if lock:
        # Blokada osobno: ``FOR UPDATE`` nie przejdzie przez ``UNION`` źródeł.
        await db.execute(
            select(FinanceCostEntry.id).where(*conditions).with_for_update()
        )
    src = _sources()
    statement = (
        _select(src)
        .add_columns(FinanceCounterparty.id_value.label("counterparty_nip"))
        .where(*conditions)
        .order_by(FinanceCostEntry.received_at, FinanceCostEntry.id)
    )
    rows = (await db.execute(statement)).all()
    plan = await posting.load_plan(db)
    return [
        Item(
            row.FinanceCostEntry,
            row,
            posting.issues_for(
                row.FinanceCostEntry.decree, plan, row.gross_amount, row.currency
            ),
        )
        for row in rows
    ]


def _register(item: Item) -> str:
    register = (item.entry.decree or {}).get("register")
    return register if register in REGISTERS else "purchase"


def _item_payload(item: Item) -> dict[str, Any]:
    decree = item.entry.decree or {}
    debit, credit = posting.totals(decree.get("positions") or [])
    return {
        "id": item.entry.id,
        "invoice_number": item.row.invoice_number,
        "seller_name": item.row.seller_name or item.row.counterparty_name,
        "seller_nip": item.entry.seller_nip,
        "issue_date": item.row.issue_date.isoformat() if item.row.issue_date else None,
        "doc_type": decree.get("doc_type") or None,
        "description": decree.get("description") or None,
        "manual": bool(decree.get("manual")),
        "exportable": not item.issues,
        "debit_total": posting.money(debit),
        "credit_total": posting.money(credit),
        "issues": item.issues,
    }


async def preview(db: AsyncSession, month: date, *, payroll: bool) -> dict[str, Any]:
    items = await _items(db, month, payroll=payroll)
    registers = []
    for register in REGISTERS:
        chosen = [item for item in items if _register(item) == register]
        if not chosen:
            continue
        debit = credit = 0
        # Sumy rejestru = to, co pójdzie do pliku (faktury z wadą są pomijane).
        for item in chosen:
            if item.issues:
                continue
            d, c = posting.totals((item.entry.decree or {}).get("positions") or [])
            debit += d
            credit += c
        registers.append(
            {
                "register": register,
                "label": posting.REGISTER_LABELS[register],
                "entries": [_item_payload(item) for item in chosen],
                "debit_total": posting.money(debit),
                "credit_total": posting.money(credit),
                "balanced": debit == credit,
            }
        )
    skipped = skipped_payload(items)
    return {
        "month": month.strftime("%Y-%m"),
        "registers": registers,
        "count": len(items),
        "blocked": len(skipped),
        "skipped": skipped,
        "can_export": len(skipped) < len(items),
        "formats": [
            {"key": fmt.key, "label": fmt.label, "extension": fmt.extension}
            for fmt in FORMATS.values()
        ],
        "default_format": DEFAULT_FORMAT,
    }


def skipped_payload(items: list[Item]) -> list[dict[str, Any]]:
    """Faktury z wadą dekretu — „Pobierz plik” je pomija, zostają „Gotowe”."""

    return [
        {
            "id": item.entry.id,
            "invoice_number": item.row.invoice_number,
            "seller_name": item.row.seller_name or item.row.counterparty_name,
            "issues": item.issues,
        }
        for item in items
        if item.issues
    ]


def export_rows(items: list[Item]) -> list[ExportRow]:
    """Wiersz pliku na pozycję dekretu; kolejność: rejestr, data, numer, wpis."""

    ordered = sorted(
        items,
        key=lambda item: (
            REGISTERS.index(_register(item)),
            item.row.issue_date or date.min,
            item.row.invoice_number or "",
            item.entry.id,
        ),
    )
    rows: list[ExportRow] = []
    for item in ordered:
        decree = item.entry.decree or {}
        register = posting.REGISTER_LABELS[_register(item)]
        for position in decree.get("positions") or []:
            amount = Decimal(int(position.get("amount") or 0)) / 100
            debit = position.get("side") == "debit"
            rows.append(
                ExportRow(
                    register=register,
                    doc_type=decree.get("doc_type") or "",
                    invoice_number=item.row.invoice_number,
                    ksef_number=item.row.ksef_number,
                    issue_date=item.row.issue_date,
                    received_date=business_date(item.entry.received_at),
                    counterparty=item.row.counterparty_name or item.row.seller_name,
                    nip=item.row.counterparty_nip or item.entry.seller_nip,
                    symfonia_id=item.row.symfonia_partner_id,
                    account=position.get("account") or "",
                    debit=amount if debit else None,
                    credit=None if debit else amount,
                    description=decree.get("description") or "",
                    vat_rate=position.get("vat_rate"),
                    deduction=posting.DEDUCTION_LABELS.get(
                        position.get("deduction") or ""
                    ),
                )
            )
    return rows


def _scope(payroll: bool) -> list[Any]:
    return [] if payroll else [FinancePostingBatch.has_payroll.is_(False)]


def _batch_payload(batch: FinancePostingBatch, names: dict[int, str]) -> dict[str, Any]:
    fmt = FORMATS.get(batch.file_format)
    return {
        "id": batch.id,
        "number": batch.number,
        "month": batch.month.strftime("%Y-%m"),
        "status": batch.status,
        "status_label": BATCH_STATUS_LABELS[batch.status],
        "file_format": batch.file_format,
        "file_format_label": fmt.label if fmt else batch.file_format,
        "file_name": batch.file_name,
        "file_sha256": batch.file_sha256,
        "entry_ids": list(batch.entry_ids),
        "entry_count": batch.entry_count,
        "debit_total": posting.money(batch.debit_total),
        "credit_total": posting.money(batch.credit_total),
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "created_by": names.get(batch.created_by or 0),
        "booked_at": batch.booked_at.isoformat() if batch.booked_at else None,
        "booked_by": names.get(batch.booked_by or 0),
        "cancelled_at": batch.cancelled_at.isoformat() if batch.cancelled_at else None,
        "cancelled_by": names.get(batch.cancelled_by or 0),
    }


async def _names(
    db: AsyncSession, batches: list[FinancePostingBatch]
) -> dict[int, str]:
    ids = {
        user_id
        for batch in batches
        for user_id in (batch.created_by, batch.booked_by, batch.cancelled_by)
        if user_id
    }
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {row.id: row.name for row in rows.all()}


async def list_batches(
    db: AsyncSession, month: Optional[date], *, payroll: bool
) -> list[dict[str, Any]]:
    statement = select(FinancePostingBatch).where(*_scope(payroll))
    if month is not None:
        statement = statement.where(FinancePostingBatch.month == month)
    batches = list(
        await db.scalars(statement.order_by(FinancePostingBatch.id.desc()).limit(100))
    )
    names = await _names(db, batches)
    return [_batch_payload(batch, names) for batch in batches]


async def batch_payload(db: AsyncSession, batch: FinancePostingBatch) -> dict[str, Any]:
    return _batch_payload(batch, await _names(db, [batch]))


async def create_batch(
    db: AsyncSession,
    month: date,
    file_format: str,
    *,
    actor_id: int,
    now: datetime,
    payroll: bool,
) -> tuple[FinancePostingBatch, list[dict[str, Any]]]:
    """Paczka z faktur bez wady; zwraca też listę pominiętych (z powodami)."""

    fmt = FORMATS.get(file_format)
    if fmt is None:
        raise LedgerError("Nieznany format pliku.", status=422)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _NUMBER_LOCK})
    items = await _items(db, month, payroll=payroll, lock=True)
    if not items:
        raise LedgerError(
            "Za ten miesiąc nie ma faktur „Gotowych do księgowania” spoza paczek."
        )
    skipped = [item for item in items if item.issues]
    items = [item for item in items if not item.issues]
    skipped_list = skipped_payload(skipped)
    if not items:
        first = skipped[0]
        number = first.row.invoice_number or f"#{first.entry.id}"
        raise LedgerError(
            f"Paczka nie powstała: każda z {len(skipped)} gotowych faktur ma wadę "
            f"dekretu. Pierwsza — {number}: {first.issues[0]}"
        )
    rows = export_rows(items)
    content = fmt.render(rows)
    debit = credit = 0
    for item in items:
        d, c = posting.totals((item.entry.decree or {}).get("positions") or [])
        debit += d
        credit += c
    sequence = (
        await db.scalar(
            select(func.count())
            .select_from(FinancePostingBatch)
            .where(FinancePostingBatch.month == month)
        )
        or 0
    ) + 1
    number = f"{month:%Y-%m}/{sequence}"
    batch = FinancePostingBatch(
        number=number,
        month=month,
        status="exported",
        file_format=fmt.key,
        file_name=f"symfonia-{month:%Y-%m}-{sequence}.{fmt.extension}",
        file_content=content,
        file_sha256=hashlib.sha256(content).hexdigest(),
        entry_ids=[item.entry.id for item in items],
        entry_count=len(items),
        debit_total=debit,
        credit_total=credit,
        has_payroll=any(item.entry.source_type == "payroll_invoice" for item in items),
        created_by=actor_id,
        created_at=now,
    )
    db.add(batch)
    await db.flush()
    for item in items:
        item.entry.batch_id = batch.id
        _event(
            db,
            item.entry,
            "export",
            actor_id=actor_id,
            now=now,
            detail={"batch": number},
        )
    await db.flush()
    return batch, skipped_list


async def _batch(
    db: AsyncSession, batch_id: int, *, payroll: bool, lock: bool = False
) -> FinancePostingBatch:
    statement = select(FinancePostingBatch).where(
        FinancePostingBatch.id == batch_id, *_scope(payroll)
    )
    if lock:
        statement = statement.with_for_update()
    batch = await db.scalar(statement)
    if batch is None:
        raise LedgerError(NO_BATCH, status=404)
    return batch


async def batch_file(
    db: AsyncSession, batch_id: int, *, payroll: bool
) -> FinancePostingBatch:
    return await _batch(db, batch_id, payroll=payroll)


async def _batch_entries(
    db: AsyncSession, batch: FinancePostingBatch
) -> list[FinanceCostEntry]:
    return list(
        await db.scalars(
            select(FinanceCostEntry)
            .where(FinanceCostEntry.batch_id == batch.id)
            .order_by(FinanceCostEntry.id)
            .with_for_update()
        )
    )


async def book_batch(
    db: AsyncSession, batch_id: int, *, actor_id: int, now: datetime, payroll: bool
) -> FinancePostingBatch:
    """„Oznacz jako zaksięgowane”: wpisy paczki → ``booked``."""

    batch = await _batch(db, batch_id, payroll=payroll, lock=True)
    if batch.status != "exported":
        raise LedgerError(
            f"Paczka {batch.number} jest już „{BATCH_STATUS_LABELS[batch.status]}”."
        )
    entries = await _batch_entries(db, batch)
    if {entry.id for entry in entries} != set(batch.entry_ids) or any(
        entry.stage != "ready" for entry in entries
    ):
        raise LedgerError(
            f"Wpisy paczki {batch.number} zmieniły się od pobrania — anuluj ją "
            "i pobierz plik od nowa."
        )
    inputs = await posting.load_inputs(db, entries)
    for entry in entries:
        inp = inputs[entry.id]
        if posting.amount_issue(entry.decree, inp.gross, inp.currency):
            number = inp.invoice_number or f"#{entry.id}"
            raise LedgerError(
                f"Kwoty faktury {number} zmieniły się po dekrecie — plik paczki "
                f"{batch.number} jest nieaktualny. Anuluj paczkę, Cofnij i przelicz."
            )
    for entry in entries:
        _event(
            db,
            entry,
            "book",
            actor_id=actor_id,
            now=now,
            from_stage=entry.stage,
            to_stage="booked",
            detail={"batch": batch.number},
        )
        entry.stage = "booked"
        entry.stage_changed_by = actor_id
        entry.stage_changed_at = now
    batch.status = "booked"
    batch.booked_by = actor_id
    batch.booked_at = now
    await db.flush()
    return batch


async def cancel_batch(
    db: AsyncSession, batch_id: int, *, actor_id: int, now: datetime, payroll: bool
) -> FinancePostingBatch:
    """„Anuluj paczkę”: wpisy wracają na listę miesiąca (zostają „Gotowe”)."""

    batch = await _batch(db, batch_id, payroll=payroll, lock=True)
    if batch.status != "exported":
        raise LedgerError(
            f"Paczka {batch.number} jest „{BATCH_STATUS_LABELS[batch.status]}” — "
            "anulować można tylko pobraną."
        )
    for entry in await _batch_entries(db, batch):
        entry.batch_id = None
        _event(
            db,
            entry,
            "unexport",
            actor_id=actor_id,
            now=now,
            detail={"batch": batch.number},
        )
    batch.status = "cancelled"
    batch.cancelled_by = actor_id
    batch.cancelled_at = now
    await db.flush()
    return batch
