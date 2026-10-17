"""Paczka przelewów do banku (R9) — OPCJA, domyślnie wyłączona.

Domyślnie przelewy robią Finanse jak dziś (eBI24 albo bank) z listy „Dla
Finansów”. Po włączeniu w Ustawieniach → Płace (rachunek i nazwa nadawcy)
Płace mogą pobrać plik Elixir-O albo CSV z zatwierdzonymi fakturami B2B:

* tylko B2B z fakturą (kwota = brutto faktur); zlecenie i UoP wypłaca
  Symfonia (kwotę na rękę liczy program płacowy),
* tylko PLN (Elixir to przelew krajowy),
* rachunek sprawdzony w wykazie VAT w dniu paczki (``white_list.check``,
  identyfikator zapytania zostaje w śladzie R-B). „NIE” albo brak odpowiedzi
  wykazu blokuje pozycję do decyzji Finansów — chyba że rachunek spoza listy
  uznały dwie osoby (``override_kind='white_list'``, R10),
* rozliczenie w paczce, która czeka, nie trafia do kolejnej.

Paczka to wiersze ``payroll_payments`` (``kind='transfer_batch'``, wspólny
``batch_key``). Plik powstaje przy pobraniu z bieżącego rachunku osoby
— jeśli rachunek zmienił się po utworzeniu paczki (inne 4 ostatnie cyfry),
pobranie odmawia. „Bank wykonał” oznacza opłacone (``mark_paid`` ze źródłem
``transfer_batch``); „Anuluj paczkę” zwalnia rozliczenia.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import TokenCipherNotConfigured
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollPayment,
    PayrollSettlement,
)
from app.models.user import User
from app.services.hr import audit, billing_details, white_list
from app.services.hr import settlements as settlement_service
from app.services.hr.bank import elixir
from app.services.hr.bank.finance import PayableRow, describe
from app.services.hr.bank.settings import PaymentSettings, load_settings
from app.services.hr.bank.titles import InvoiceRef, title_lines
from app.services.hr.payroll_errors import (
    PayrollConflict,
    PayrollError,
    PayrollNotFound,
)
from app.services.hr.payroll_report import money
from app.services.hr_settlement_schema import TITLE_MAX_LENGTH

MAX_AHEAD_DAYS = 30
CANCEL_REASON = "Paczka anulowana."

EXCLUDED_LABELS: dict[str, str] = {
    "not_b2b": "Wynagrodzenie zlecenia i UoP wypłaca Symfonia (kwota na rękę z programu).",
    "no_invoice": "Brak faktury przy rozliczeniu.",
    "currency": "Paczka Elixir obejmuje tylko przelewy w złotych.",
    "no_account": "Brak rachunku w danych do rozliczeń.",
    "account_unreadable": "Nie udało się odczytać rachunku — sprawdź klucz szyfrowania.",
    "no_nip": "Brak NIP-u — nie da się sprawdzić rachunku w wykazie VAT.",
    "not_listed": "Rachunku nie ma na białej liście VAT — decyzja Finansów.",
    "unchecked": "Wykaz VAT nie odpowiedział — rachunek niesprawdzony, decyzja Finansów.",
    "in_batch": "Już w paczce, która czeka na wysłanie (nieaktualną paczkę anuluj).",
    "not_payable": "Rozliczenie nie jest zatwierdzone do zapłaty.",
    "override_stale": "Rachunek zmienił się po uznaniu spoza białej listy — potrzebne "
    "ponowne uznanie przez dwie osoby.",
}


@dataclass(frozen=True)
class BatchItem:
    row: PayableRow
    included: bool
    reason: Optional[str] = None
    white_list_request_id: Optional[str] = None


def ensure_enabled(settings: PaymentSettings) -> None:
    if not settings.transfer_batch.enabled:
        raise PayrollConflict(
            "Paczka przelewów jest wyłączona — przelewy robią Finanse z listy "
            "„Dla Finansów”. Włączysz ją w Ustawieniach → Płace.",
            code="transfer_batch_disabled",
        )


async def _billing(
    db: AsyncSession, user_ids: set[int]
) -> dict[int, EmployeeBillingDetails]:
    if not user_ids:
        return {}
    return {
        details.user_id: details
        for details in await db.scalars(
            select(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id.in_(user_ids)
            )
        )
    }


async def _waiting(db: AsyncSession) -> set[tuple[int, int, int]]:
    """Osoba × miesiąc z paczką, która czeka (także po anulowaniu rozliczenia).

    Ponowne zamknięcie miesiąca zakłada NOWE rozliczenie (inne ``id``) — stara
    paczka mogła już pójść do banku, więc to samo zobowiązanie nie wchodzi do
    drugiej, dopóki pierwszej ktoś nie anuluje.
    """

    rows = await db.execute(
        select(PayrollSettlement.user_id, PayrollPeriod.year, PayrollPeriod.month)
        .join(PayrollPayment, PayrollPayment.settlement_id == PayrollSettlement.id)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollSettlement.period_id)
        .where(
            PayrollPayment.kind == "transfer_batch",
            PayrollPayment.match_status == "matched",
            PayrollSettlement.status != "paid",
        )
    )
    return {(int(uid), int(year), int(month)) for uid, year, month in rows.all()}


def _override_fresh(
    settlement: PayrollSettlement, details: Optional[EmployeeBillingDetails]
) -> bool:
    """Uznanie „spoza białej listy” dotyczy rachunku sprzed uznania.

    Zmiana danych do rozliczeń po potwierdzeniu uznania (np. inny rachunek)
    unieważnia je dla paczki — inaczej jedna osoba mogłaby przekierować
    przelew bez drugiej pary oczu (R10).
    """

    if settlement.override_kind != "white_list" or settlement.override_confirmed_at is None:
        return False
    return details is not None and details.updated_at <= settlement.override_confirmed_at


def _account(details: Optional[EmployeeBillingDetails]) -> tuple[Optional[str], str]:
    try:
        account = billing_details.decrypt_account(details)
    except (TokenCipherNotConfigured, ValueError):
        return None, "account_unreadable"
    return account, "" if account else "no_account"


async def plan(
    db: AsyncSession,
    *,
    settlement_ids: Optional[list[int]],
    today: date,
    actor_id: Optional[int],
) -> list[BatchItem]:
    """Które zatwierdzone rozliczenia wejdą do paczki i dlaczego pozostałe nie."""

    query = select(PayrollSettlement).where(PayrollSettlement.status == "approved")
    if settlement_ids:
        query = query.where(PayrollSettlement.id.in_(settlement_ids))
    settlements = list(
        await db.scalars(query.order_by(PayrollSettlement.due_on, PayrollSettlement.id))
    )
    if settlement_ids:
        missing = set(settlement_ids) - {s.id for s in settlements}
        if missing:
            raise PayrollConflict(
                "Część wybranych rozliczeń nie jest już zatwierdzona do zapłaty — "
                "odśwież listę.",
                code="not_payable",
                data={"settlement_ids": sorted(missing)},
            )
    rows = await describe(db, settlements)
    by_id = {settlement.id: settlement for settlement in settlements}
    billing = await _billing(db, {row.user_id for row in rows})
    waiting = await _waiting(db)
    items: list[BatchItem] = []
    for row in rows:
        reason = None
        if row.employment_type != "b2b":
            reason = "not_b2b"
        elif row.amount_to_pay is None or row.amount_to_pay <= 0:
            reason = "no_invoice"
        elif row.currency != "PLN":
            reason = "currency"
        elif row.batch_key or (row.user_id, row.year, row.month) in waiting:
            reason = "in_batch"
        if reason:
            items.append(BatchItem(row=row, included=False, reason=reason))
            continue
        details = billing.get(row.user_id)
        account, problem = _account(details)
        if account is None:
            items.append(BatchItem(row=row, included=False, reason=problem))
            continue
        override = row.white_list_override
        honored = override and _override_fresh(by_id[row.settlement_id], details)

        def refused(default: str) -> Optional[str]:
            if honored:
                return None
            return "override_stale" if override else default

        if not row.nip:
            items.append(
                BatchItem(row=row, included=honored, reason=refused("no_nip"))
            )
            continue
        try:
            check = await white_list.check(
                db,
                row.nip,
                account,
                today,
                actor_id=actor_id,
                subject_user_id=row.user_id,
            )
        except white_list.WhiteListError:
            items.append(
                BatchItem(row=row, included=honored, reason=refused("unchecked"))
            )
            continue
        listed = check.listed or honored
        items.append(
            BatchItem(
                row=row,
                included=listed,
                reason=None if check.listed else refused("not_listed"),
                white_list_request_id=check.request_id,
            )
        )
    return items


def item_payload(item: BatchItem) -> dict[str, Any]:
    row = item.row
    return {
        "settlement_id": row.settlement_id,
        "name": row.name,
        "period": f"{row.month:02d}/{row.year}",
        "amount": str(row.amount_to_pay) if row.amount_to_pay is not None else None,
        "currency": row.currency,
        "title": row.title,
        "account_last4": row.account_last4,
        "included": item.included,
        "reason": item.reason,
        "reason_label": EXCLUDED_LABELS.get(item.reason or ""),
        "white_list_checked": item.white_list_request_id is not None,
    }


def _execution_date(raw: Optional[date], today: date) -> date:
    chosen = raw or today
    if chosen < today or chosen > today + timedelta(days=MAX_AHEAD_DAYS):
        raise PayrollError(f"Data wykonania: od dziś do {MAX_AHEAD_DAYS} dni naprzód.")
    return chosen


async def create_batch(
    db: AsyncSession,
    *,
    settlement_ids: Optional[list[int]],
    execution_date: Optional[date],
    actor_id: int,
    today: date,
) -> dict[str, Any]:
    settings = await load_settings(db)
    ensure_enabled(settings)
    when = _execution_date(execution_date, today)
    # Dwie paczki naraz nie mogą wziąć tego samego rozliczenia.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('hr-transfer-batch'))"))
    items = await plan(
        db, settlement_ids=settlement_ids, today=today, actor_id=actor_id
    )
    included = [item for item in items if item.included]
    if not included:
        raise PayrollConflict(
            "Żadne rozliczenie nie może wejść do paczki — sprawdź powody na liście.",
            code="batch_empty",
            data={"items": [item_payload(item) for item in items]},
        )
    key = uuid.uuid4().hex
    for item in included:
        row = item.row
        db.add(
            PayrollPayment(
                kind="transfer_batch",
                settlement_id=row.settlement_id,
                match_status="matched",
                amount=money(row.amount_to_pay or Decimal("0")),
                currency=row.currency,
                booked_on=when,
                title=row.title[:TITLE_MAX_LENGTH],
                counterparty_last4=row.account_last4,
                batch_key=key,
                batch_format=settings.transfer_batch.format,
                created_by=actor_id,
            )
        )
    await db.flush()
    total = money(sum((item.row.amount_to_pay or Decimal("0")) for item in included))
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="transfer_batch",
        entity_id=key,
        action="transfer_batch_created",
        sensitivity="payroll",
        details={
            "format": settings.transfer_batch.format,
            "execution_date": when.isoformat(),
            "count": len(included),
            "total": str(total),
            "excluded": {
                item.reason: sum(1 for other in items if other.reason == item.reason)
                for item in items
                if not item.included and item.reason
            },
            "settlement_ids": [item.row.settlement_id for item in included],
        },
    )
    return {
        "batch_key": key,
        "format": settings.transfer_batch.format,
        "execution_date": when.isoformat(),
        "count": len(included),
        "total": str(total),
        "items": [item_payload(item) for item in items],
    }


async def _rows(db: AsyncSession, key: str) -> list[PayrollPayment]:
    rows = list(
        await db.scalars(
            select(PayrollPayment)
            .where(
                PayrollPayment.kind == "transfer_batch",
                PayrollPayment.batch_key == key,
            )
            .order_by(PayrollPayment.id)
        )
    )
    if not rows:
        raise PayrollNotFound("Nie ma takiej paczki przelewów.")
    return rows


async def _current(
    db: AsyncSession, rows: list[PayrollPayment]
) -> tuple[dict[int, PayrollSettlement], dict[int, PayableRow]]:
    """Rozliczenia paczki i ich bieżące kwoty; nieaktualna paczka = 409.

    Rozliczenie anulowane (ponowne otwarcie miesiąca), z cofniętym
    zatwierdzeniem albo z inną kwotą faktur niż w chwili utworzenia paczki nie
    może ani trafić do pliku, ani zostać „opłacone” paczką.
    """

    settlements = {
        s.id: s
        for s in await db.scalars(
            select(PayrollSettlement).where(
                PayrollSettlement.id.in_({row.settlement_id for row in rows})
            )
        )
    }
    described = {
        row.settlement_id: row for row in await describe(db, list(settlements.values()))
    }
    stale = sorted(
        payment.settlement_id
        for payment in rows
        if payment.settlement_id not in settlements
        or settlements[payment.settlement_id].status not in ("approved", "paid")
        or (
            settlements[payment.settlement_id].status == "approved"
            and described[payment.settlement_id].amount_to_pay
            != Decimal(payment.amount)
        )
    )
    if stale:
        raise PayrollConflict(
            "Paczka jest nieaktualna — rozliczenie zostało anulowane, cofnięte do "
            "decyzji albo zmieniła się kwota faktury. Anuluj paczkę i utwórz nową.",
            code="batch_stale",
            data={"settlement_ids": stale},
        )
    return settlements, described


async def batch_file(db: AsyncSession, key: str) -> tuple[str, bytes, str]:
    settings = await load_settings(db)
    ensure_enabled(settings)
    rows = [row for row in await _rows(db, key) if row.match_status == "matched"]
    if not rows:
        raise PayrollConflict("Ta paczka jest anulowana.")
    settlements, described = await _current(db, rows)
    billing = await _billing(db, {s.user_id for s in settlements.values()})
    transfers: list[elixir.TransferRow] = []
    for payment in rows:
        settlement = settlements[payment.settlement_id]
        details = billing.get(settlement.user_id)
        account, problem = _account(details)
        if account is None or account[-4:] != payment.counterparty_last4:
            raise PayrollConflict(
                "Rachunek osoby zmienił się po utworzeniu paczki albo jest nieczytelny "
                "— anuluj paczkę i utwórz nową.",
                code="batch_account_changed",
                data={"settlement_id": settlement.id},
            )
        row = described[settlement.id]
        refs = [InvoiceRef(i.invoice_number, i.ksef_number) for i in row.invoices]
        transfers.append(
            elixir.TransferRow(
                recipient_name=(details.registry_name if details else None) or row.name,
                recipient_account=account,
                amount=Decimal(payment.amount),
                title_lines=tuple(
                    title_lines(row.employment_type, row.year, row.month, refs)
                ),
                execution_date=payment.booked_on,
            )
        )
    batch = settings.transfer_batch
    stamp = rows[0].booked_on.strftime("%Y-%m-%d")
    if rows[0].batch_format == "csv":
        return (
            f"przelewy-{stamp}-{key[:8]}.csv",
            elixir.render_csv(transfers),
            "text/csv",
        )
    sender = elixir.Sender(name=batch.sender_name, account=batch.sender_account or "")
    return (
        f"przelewy-{stamp}-{key[:8]}.pli",
        elixir.render_elixir(transfers, sender),
        "text/plain; charset=windows-1250",
    )


async def confirm_batch(
    db: AsyncSession, key: str, *, paid_on: date, actor_id: int
) -> dict[str, Any]:
    rows = [row for row in await _rows(db, key) if row.match_status == "matched"]
    if not rows:
        raise PayrollConflict("Ta paczka jest anulowana.")
    settlements, _described = await _current(db, rows)
    paid = 0
    for payment in rows:
        settlement = settlements[payment.settlement_id]
        if await settlement_service.mark_paid(
            db,
            settlement,
            source="transfer_batch",
            amount=Decimal(payment.amount),
            paid_on=paid_on,
            actor_id=actor_id,
        ):
            paid += 1
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="transfer_batch",
        entity_id=key,
        action="transfer_batch_confirmed",
        sensitivity="payroll",
        details={"paid": paid, "count": len(rows), "paid_on": paid_on.isoformat()},
    )
    return {"batch_key": key, "paid": paid, "count": len(rows)}


async def cancel_batch(db: AsyncSession, key: str, *, actor_id: int) -> dict[str, Any]:
    rows = await _rows(db, key)
    statuses = dict(
        (
            await db.execute(
                select(PayrollSettlement.id, PayrollSettlement.status).where(
                    PayrollSettlement.id.in_({row.settlement_id for row in rows})
                )
            )
        ).all()
    )
    released = 0
    for payment in rows:
        if payment.match_status != "matched":
            continue
        if statuses.get(payment.settlement_id) == "paid":
            continue
        payment.match_status = "ignored"
        payment.reason = CANCEL_REASON
        released += 1
    if not released:
        raise PayrollConflict("W tej paczce nie ma nic do anulowania.")
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="transfer_batch",
        entity_id=key,
        action="transfer_batch_cancelled",
        sensitivity="payroll",
        details={"released": released},
    )
    return {"batch_key": key, "released": released}


async def list_batches(db: AsyncSession, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(
            PayrollPayment.batch_key,
            PayrollPayment.batch_format,
            func.min(PayrollPayment.created_at),
            func.min(PayrollPayment.booked_on),
            func.count(),
            func.count().filter(PayrollPayment.match_status == "matched"),
            func.sum(PayrollPayment.amount).filter(
                PayrollPayment.match_status == "matched"
            ),
            func.count().filter(PayrollSettlement.status == "paid"),
            func.min(User.name),
        )
        .join(PayrollSettlement, PayrollSettlement.id == PayrollPayment.settlement_id)
        .outerjoin(User, User.id == PayrollPayment.created_by)
        .where(PayrollPayment.kind == "transfer_batch")
        .group_by(PayrollPayment.batch_key, PayrollPayment.batch_format)
        .order_by(func.min(PayrollPayment.created_at).desc())
        .limit(limit)
    )
    out = []
    for key, fmt, created, execution, total, active, amount, paid, author in rows.all():
        out.append(
            {
                "batch_key": key,
                "format": fmt,
                "created_at": created.isoformat() if created else None,
                "execution_date": execution.isoformat() if execution else None,
                "count": int(total),
                "active": int(active),
                "paid": int(paid),
                "total": str(money(Decimal(amount or 0))),
                "created_by_name": author,
                "status": "cancelled"
                if active == 0
                else ("paid" if paid >= active else "created"),
            }
        )
    return out


__all__ = [
    "BatchItem",
    "EXCLUDED_LABELS",
    "batch_file",
    "cancel_batch",
    "confirm_batch",
    "create_batch",
    "ensure_enabled",
    "item_payload",
    "list_batches",
    "plan",
]
