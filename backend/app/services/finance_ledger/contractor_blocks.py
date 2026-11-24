"""Blokady płatności kontraktorów: zajęcia wierzytelności i „Spór / wstrzymane”.

Decyzja Artura z 23.11.2026 — rejestr w NEXUSIE zamiast Excela „Kontraktorzy”
i maili. Reguły kwot bez bazy: ``garnishment_rules.py``; plan i paczka:
``payments.py``. Tabele: ``contractor_payment_blocks_schema.py``.

* **Zajęcie** leży na kontrakcie, ale dotyczy wierzytelności osoby: działa na
  faktury przypięte do tego kontraktu i na każdą inną fakturę kosztową od
  sprzedawcy z NIP-em, który ma przypięte faktury tego kontraktu (ta sama
  firma kontraktora u innego klienta albo dokument wydatku).
* **Wstrzymanie** leży na rozliczeniu kontraktora (kontrakt + miesiąc,
  ``client_settlements`` rodzaju ``actual``) i blokuje faktury tego kontraktu
  za ten miesiąc, aż ktoś je zwolni. Powód i kto zdecydował są widoczne
  w planie paczki.
* **Zmiana zajęcia albo wstrzymanie zdejmuje fakturę z paczki czekającej na
  bank** (``payments.release_entries``): podział płatności liczony przed
  zmianą byłby zły, a wstrzymana faktura nie może pójść do banku. Plik takiej
  paczki jest wtedy nieaktualny.
* Dane zajęć są wrażliwe: trasy tylko z „Modułem Finanse” (to samo uprawnienie
  co kwoty Finansów), każda zmiana idzie do Historii zdarzeń bez kwot
  i sygnatur (``critical_events``), a log aplikacji ma tylko identyfikatory.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_settlement import ClientContractorInvoice, ClientSettlement
from app.models.contract import Contract
from app.models.contractor_payment_blocks import (
    ContractorGarnishment,
    ContractorPaymentHold,
)
from app.models.finance_ledger import FinanceCostEntry
from app.models.finance_payments import FinancePaymentBatch, FinancePaymentBatchItem
from app.models.user import User
from app.services import critical_events
from app.services.client_identity import client_display_name
from app.services.contractor_payment_blocks_schema import (
    AUTHORITY_KINDS,
    INTEREST_MODES,
)
from app.services.finance_ledger import garnishment_rules as grules
from app.services.finance_ledger import payment_rules as prules

logger = logging.getLogger(__name__)

PINNED_NIP_STATES = ("known", "confirmed")
#: Faktura przypięta do kontraktu i miesiąca, także z NIP-em do zatwierdzenia —
#: spór i zajęcie mają ją zablokować, zanim Finanse rozstrzygną NIP. Odrzucona
#: („to nie ta osoba”) nie należy do kontraktu.
LINKED_NIP_STATES = ("known", "suggested", "confirmed")
#: Pola zajęcia, których zmiana nie zmienia podziału płatności ani pliku.
NOTE_ONLY_FIELDS = frozenset({"note"})
GARNISHMENT_FIELDS = (
    "authority_kind",
    "authority_name",
    "case_number",
    "served_on",
    "principal_amount",
    "costs_amount",
    "interest_mode",
    "interest_amount",
    "interest_rate",
    "interest_from",
    "authority_account",
    "note",
)


class BlockError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _money(value: Optional[Decimal]) -> Optional[str]:
    return f"{grules.money(value):.2f}" if value is not None else None


def terms_of(row: ContractorGarnishment) -> grules.Terms:
    return grules.Terms(
        id=row.id,
        case_number=row.case_number,
        authority_name=row.authority_name,
        served_on=row.served_on,
        principal=Decimal(row.principal_amount),
        costs=Decimal(row.costs_amount or 0),
        interest_mode=row.interest_mode,
        interest_amount=Decimal(row.interest_amount)
        if row.interest_amount is not None
        else None,
        interest_rate=Decimal(row.interest_rate)
        if row.interest_rate is not None
        else None,
        interest_from=row.interest_from,
        account=row.authority_account,
        lifted_on=row.lifted_on,
    )


# ── Wiersze planu → zajęcia i wstrzymania ────────────────────────────────────


@dataclass
class RowBlocks:
    """Co wiersze planu wiedzą o zajęciach i wstrzymaniach (jedno zapytanie
    na rodzaj, bez zapytań na fakturę)."""

    #: wpis → kontrakt i miesiąc faktury kontraktora (do przycisków w planie).
    contract_of: dict[int, int] = field(default_factory=dict)
    month_of: dict[int, str] = field(default_factory=dict)
    settlement_of: dict[int, int] = field(default_factory=dict)
    #: wpis → aktywne wstrzymanie (powód, kto, kiedy).
    holds: dict[int, dict[str, Any]] = field(default_factory=dict)
    #: wpis → zajęcia, które mogą go dotyczyć (filtr dnia w planie).
    garnishments: dict[int, list[grules.Terms]] = field(default_factory=dict)
    #: zajęcie → przelewy do organu z paczek (aktywne i wykonane).
    transfers: dict[int, list[grules.Transfer]] = field(default_factory=dict)
    authority_kind: dict[int, str] = field(default_factory=dict)


async def _names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {
        uid: name
        for uid, name in (
            await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
        ).all()
    }


async def transfers_for(
    db: AsyncSession, garnishment_ids: set[int]
) -> dict[int, list[grules.Transfer]]:
    """Przelewy do organów z pozycji paczek, które nie zostały zdjęte."""

    if not garnishment_ids:
        return {}
    rows = await db.execute(
        select(FinancePaymentBatchItem.garnishments, FinancePaymentBatch.execution_date)
        .join(
            FinancePaymentBatch,
            FinancePaymentBatch.id == FinancePaymentBatchItem.batch_id,
        )
        .where(
            FinancePaymentBatchItem.status != "released",
            FinancePaymentBatchItem.garnishments != text("'[]'::jsonb"),
        )
    )
    out: dict[int, list[grules.Transfer]] = defaultdict(list)
    for parts, on in rows.all():
        for part in parts or []:
            gid = int(part.get("garnishment_id") or 0)
            if gid in garnishment_ids:
                out[gid].append(grules.Transfer(on=on, amount=Decimal(part["amount"])))
    return dict(out)


async def for_rows(db: AsyncSession, rows: list[Any]) -> RowBlocks:
    """``rows`` — ``payments.PayRow`` (wpis kolejki z danymi źródła)."""

    result = RowBlocks()
    plain = [row for row in rows if not row.payroll]
    if not plain:
        return result
    invoice_entry = {
        row.entry.source_id: row.entry.id
        for row in plain
        if row.entry.source_type == "contractor_invoice"
    }
    if invoice_entry:
        for invoice_id, contract_id, month in (
            await db.execute(
                select(
                    ClientContractorInvoice.id,
                    ClientContractorInvoice.contract_id,
                    ClientContractorInvoice.period_month,
                ).where(
                    ClientContractorInvoice.id.in_(invoice_entry),
                    ClientContractorInvoice.contract_id.is_not(None),
                    ClientContractorInvoice.nip_state.in_(LINKED_NIP_STATES),
                )
            )
        ).all():
            entry_id = invoice_entry[invoice_id]
            result.contract_of[entry_id] = int(contract_id)
            if month:
                result.month_of[entry_id] = month
    nips = {row.entry.seller_nip for row in plain if row.entry.seller_nip}
    contracts_of_nip: dict[str, set[int]] = defaultdict(set)
    if nips:
        for nip, contract_id in (
            await db.execute(
                select(
                    ClientContractorInvoice.seller_nip,
                    ClientContractorInvoice.contract_id,
                )
                .where(
                    ClientContractorInvoice.seller_nip.in_(nips),
                    ClientContractorInvoice.contract_id.is_not(None),
                    ClientContractorInvoice.nip_state.in_(PINNED_NIP_STATES),
                )
                .distinct()
            )
        ).all():
            contracts_of_nip[nip].add(int(contract_id))
    contracts = set(result.contract_of.values()) | {
        c for found in contracts_of_nip.values() for c in found
    }
    by_contract: dict[int, list[grules.Terms]] = defaultdict(list)
    if contracts:
        for g in await db.scalars(
            select(ContractorGarnishment).where(
                ContractorGarnishment.contract_id.in_(contracts)
            )
        ):
            by_contract[g.contract_id].append(terms_of(g))
            result.authority_kind[g.id] = g.authority_kind
    if by_contract:
        for row in plain:
            mine = set(contracts_of_nip.get(row.entry.seller_nip or "", set()))
            if row.entry.id in result.contract_of:
                mine.add(result.contract_of[row.entry.id])
            found = [t for c in sorted(mine) for t in by_contract.get(c, [])]
            if found:
                result.garnishments[row.entry.id] = found
        result.transfers = await transfers_for(
            db, {t.id for found in by_contract.values() for t in found}
        )
    keys = {
        (result.contract_of[e], result.month_of[e])
        for e in result.month_of
        if e in result.contract_of
    }
    if keys:
        settlements = {
            (s.contract_id, s.period_month): s.id
            for s in await db.scalars(
                select(ClientSettlement).where(
                    ClientSettlement.kind == "actual",
                    ClientSettlement.contract_id.in_({c for c, _m in keys}),
                    ClientSettlement.period_month.in_({m for _c, m in keys}),
                )
            )
        }
        for entry_id, month in result.month_of.items():
            sid = settlements.get((result.contract_of.get(entry_id), month))
            if sid is not None:
                result.settlement_of[entry_id] = sid
        if result.settlement_of:
            holds = list(
                await db.scalars(
                    select(ContractorPaymentHold).where(
                        ContractorPaymentHold.settlement_id.in_(
                            set(result.settlement_of.values())
                        ),
                        ContractorPaymentHold.released_at.is_(None),
                    )
                )
            )
            names = await _names(db, {h.created_by for h in holds if h.created_by})
            by_settlement = {h.settlement_id: hold_payload(h, names) for h in holds}
            for entry_id, sid in result.settlement_of.items():
                if sid in by_settlement:
                    result.holds[entry_id] = by_settlement[sid]
    return result


def hold_payload(hold: ContractorPaymentHold, names: dict[int, str]) -> dict[str, Any]:
    return {
        "id": hold.id,
        "settlement_id": hold.settlement_id,
        "reason": hold.reason,
        "created_by_name": names.get(hold.created_by or 0),
        "created_at": _iso(hold.created_at),
        "released_by_name": names.get(hold.released_by or 0),
        "released_at": _iso(hold.released_at),
        "release_note": hold.release_note,
    }


def hold_label(hold: dict[str, Any]) -> str:
    who = hold.get("created_by_name") or "Finanse"
    day = (hold.get("created_at") or "")[:10]
    when = f" {day[8:10]}.{day[5:7]}.{day[:4]}" if len(day) == 10 else ""
    return (
        f"Spór / wstrzymane: {hold['reason']} (zdecydował(a): {who}{when}). "
        "Płatność czeka na zwolnienie."
    )


# ── Wpisy kolejki, których dotyczy zmiana ───────────────────────────────────


async def entries_for_contract(db: AsyncSession, contract_id: int) -> list[int]:
    """Wpisy (bez faktur osób zespołu), na które działa zajęcie kontraktu."""

    nips = set(
        await db.scalars(
            select(ClientContractorInvoice.seller_nip)
            .where(
                ClientContractorInvoice.contract_id == contract_id,
                ClientContractorInvoice.nip_state.in_(PINNED_NIP_STATES),
            )
            .distinct()
        )
    )
    invoice_ids = list(
        await db.scalars(
            select(ClientContractorInvoice.id).where(
                ClientContractorInvoice.contract_id == contract_id
            )
        )
    )
    conditions = []
    if invoice_ids:
        conditions.append(
            (FinanceCostEntry.source_type == "contractor_invoice")
            & FinanceCostEntry.source_id.in_(invoice_ids)
        )
    if nips:
        conditions.append(FinanceCostEntry.seller_nip.in_(nips))
    if not conditions:
        return []
    return list(
        await db.scalars(
            select(FinanceCostEntry.id).where(
                FinanceCostEntry.source_type != "payroll_invoice", or_(*conditions)
            )
        )
    )


async def entries_for_settlement(
    db: AsyncSession, settlement: ClientSettlement
) -> list[int]:
    invoice_ids = list(
        await db.scalars(
            select(ClientContractorInvoice.id).where(
                ClientContractorInvoice.contract_id == settlement.contract_id,
                ClientContractorInvoice.period_month == settlement.period_month,
                ClientContractorInvoice.nip_state.in_(LINKED_NIP_STATES),
            )
        )
    )
    if not invoice_ids:
        return []
    return list(
        await db.scalars(
            select(FinanceCostEntry.id).where(
                FinanceCostEntry.source_type == "contractor_invoice",
                FinanceCostEntry.source_id.in_(invoice_ids),
            )
        )
    )


# ── Zajęcia: odczyt i zapis ─────────────────────────────────────────────────


async def _contract_labels(
    db: AsyncSession, contract_ids: set[int]
) -> dict[int, dict[str, Any]]:
    if not contract_ids:
        return {}
    rows = await db.execute(
        select(Contract.id, Candidate.name, Candidate.lastname, Client)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(Client, Client.id == Contract.client_id)
        .where(Contract.id.in_(contract_ids))
    )
    out = {}
    for cid, first, last, client in rows.all():
        person = f"{(first or '').strip()} {(last or '').strip()}".strip()
        out[cid] = {
            "contract_id": cid,
            "contractor_name": person or None,
            "client_name": client_display_name(client) if client else None,
        }
    return out


def garnishment_payload(
    row: ContractorGarnishment,
    names: dict[int, str],
    *,
    today: date,
    transfers: list[grules.Transfer],
    contract: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    try:
        balance = grules.balance_on(terms_of(row), today, transfers)
        due: Optional[str] = _money(balance.due)
        problem = None
    except grules.GarnishmentError as exc:
        due, problem = None, str(exc)
    if problem is None and not row.authority_account:
        problem = grules.ERROR_LABELS["no_account"]
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        **(contract or {}),
        "authority_kind": row.authority_kind,
        "authority_label": grules.AUTHORITY_LABELS.get(row.authority_kind),
        "authority_name": row.authority_name,
        "case_number": row.case_number,
        "served_on": _iso(row.served_on),
        "principal_amount": _money(row.principal_amount),
        "costs_amount": _money(row.costs_amount),
        "interest_mode": row.interest_mode,
        "interest_label": grules.INTEREST_LABELS.get(row.interest_mode),
        "interest_amount": _money(row.interest_amount),
        "interest_rate": f"{Decimal(row.interest_rate):.3f}"
        if row.interest_rate is not None
        else None,
        "interest_from": _iso(row.interest_from),
        "authority_account": row.authority_account,
        "note": row.note,
        "lifted_on": _iso(row.lifted_on),
        "lifted_note": row.lifted_note,
        "lifted_by_name": names.get(row.lifted_by or 0),
        "active": row.lifted_on is None or row.lifted_on > today,
        "transferred": _money(sum((t.amount for t in transfers), Decimal("0"))),
        "due_today": due,
        "problem": problem,
        "created_by_name": names.get(row.created_by or 0),
        "created_at": _iso(row.created_at),
        "updated_by_name": names.get(row.updated_by or 0),
        "updated_at": _iso(row.updated_at),
    }


async def list_garnishments(
    db: AsyncSession, *, today: date, contract_id: Optional[int] = None
) -> list[dict[str, Any]]:
    query = select(ContractorGarnishment).order_by(
        ContractorGarnishment.lifted_on.is_not(None),
        ContractorGarnishment.served_on.desc(),
        ContractorGarnishment.id.desc(),
    )
    if contract_id is not None:
        query = query.where(ContractorGarnishment.contract_id == contract_id)
    rows = list(await db.scalars(query))
    names = await _names(
        db,
        {
            uid
            for r in rows
            for uid in (r.created_by, r.updated_by, r.lifted_by)
            if uid is not None
        },
    )
    labels = await _contract_labels(db, {r.contract_id for r in rows})
    transfers = await transfers_for(db, {r.id for r in rows})
    return [
        garnishment_payload(
            r,
            names,
            today=today,
            transfers=transfers.get(r.id, []),
            contract=labels.get(r.contract_id),
        )
        for r in rows
    ]


@dataclass(frozen=True)
class GarnishmentData:
    authority_kind: str
    authority_name: str
    case_number: str
    served_on: date
    principal_amount: Decimal
    costs_amount: Decimal = Decimal("0")
    interest_mode: str = "unknown"
    interest_amount: Optional[Decimal] = None
    interest_rate: Optional[Decimal] = None
    interest_from: Optional[date] = None
    authority_account: Optional[str] = None
    note: Optional[str] = None


def _clean(data: GarnishmentData, today: date) -> dict[str, Any]:
    if data.authority_kind not in AUTHORITY_KINDS:
        raise BlockError("Nieznany rodzaj organu.", 422)
    if data.interest_mode not in INTEREST_MODES:
        raise BlockError("Nieznany sposób liczenia odsetek.", 422)
    if data.served_on > today:
        raise BlockError("Data doręczenia nie może być z przyszłości.", 422)
    name = " ".join(data.authority_name.split())
    case = " ".join(data.case_number.split())
    if not name or not case:
        raise BlockError("Podaj organ i sygnaturę sprawy.", 422)
    account = None
    if data.authority_account and data.authority_account.strip():
        try:
            account = prules.normalize_account(data.authority_account)
        except prules.PaymentRuleError as exc:
            raise BlockError(
                "Rachunek organu ma zły format albo sumę kontrolną.", 422
            ) from exc
        if not prules.is_domestic(account):
            raise BlockError("Rachunek organu to rachunek krajowy (26 cyfr).", 422)
    values: dict[str, Any] = {
        "authority_kind": data.authority_kind,
        "authority_name": name,
        "case_number": case,
        "served_on": data.served_on,
        "principal_amount": grules.money(data.principal_amount),
        "costs_amount": grules.money(data.costs_amount or Decimal("0")),
        "interest_mode": data.interest_mode,
        # Pola odsetek innego sposobu nie zostają (nie liczyłyby się po cichu).
        "interest_amount": grules.money(data.interest_amount)
        if data.interest_mode == "fixed" and data.interest_amount is not None
        else None,
        "interest_rate": data.interest_rate if data.interest_mode == "rate" else None,
        "interest_from": data.interest_from if data.interest_mode == "rate" else None,
        "authority_account": account,
        "note": (data.note or "").strip() or None,
    }
    return values


async def _released(
    db: AsyncSession, entry_ids: list[int], *, actor_id: int, now: datetime
) -> list[dict[str, Any]]:
    from app.services.finance_ledger import payments

    return await payments.release_entries(db, entry_ids, actor_id=actor_id, now=now)


async def _audit(
    db: AsyncSession,
    actor: User,
    event_type: str,
    *,
    contract_id: int,
    label: str,
    details: dict[str, Any],
) -> None:
    client_id = await db.scalar(
        select(Contract.client_id).where(Contract.id == contract_id)
    )
    await critical_events.record_executed(
        db,
        actor=actor,
        event_type=event_type,
        entity_type="contract",
        entity_id=contract_id,
        entity_label=label,
        client_id=client_id,
        details=details,
    )


async def create_garnishment(
    db: AsyncSession,
    contract_id: int,
    data: GarnishmentData,
    *,
    actor: User,
    today: date,
    now: datetime,
) -> dict[str, Any]:
    if await db.get(Contract, contract_id) is None:
        raise BlockError("Nie ma takiego kontraktu.", 404)
    values = _clean(data, today)
    row = ContractorGarnishment(
        contract_id=contract_id,
        created_by=actor.id,
        updated_by=actor.id,
        **values,
    )
    db.add(row)
    await db.flush()
    released = await _released(
        db, await entries_for_contract(db, contract_id), actor_id=actor.id, now=now
    )
    await _audit(
        db,
        actor,
        "contract.garnishment_add",
        contract_id=contract_id,
        label=f"Zajęcie wierzytelności #{row.id} (kontrakt #{contract_id})",
        details={"garnishment_id": row.id, "released_from_batches": len(released)},
    )
    logger.info(
        "[contractor-blocks] zajęcie %s na kontrakcie %s dodane przez %s",
        row.id,
        contract_id,
        actor.id,
    )
    return await _one(db, row, today=today, released=released)


async def _garnishment(
    db: AsyncSession, garnishment_id: int, *, lock: bool = True
) -> ContractorGarnishment:
    query = select(ContractorGarnishment).where(
        ContractorGarnishment.id == garnishment_id
    )
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise BlockError("Nie ma takiego zajęcia.", 404)
    return row


async def _one(
    db: AsyncSession,
    row: ContractorGarnishment,
    *,
    today: date,
    released: list[dict[str, Any]],
) -> dict[str, Any]:
    names = await _names(
        db, {u for u in (row.created_by, row.updated_by, row.lifted_by) if u}
    )
    labels = await _contract_labels(db, {row.contract_id})
    transfers = await transfers_for(db, {row.id})
    return {
        **garnishment_payload(
            row,
            names,
            today=today,
            transfers=transfers.get(row.id, []),
            contract=labels.get(row.contract_id),
        ),
        "released_from_batches": released,
    }


async def update_garnishment(
    db: AsyncSession,
    garnishment_id: int,
    data: GarnishmentData,
    *,
    actor: User,
    today: date,
    now: datetime,
) -> dict[str, Any]:
    row = await _garnishment(db, garnishment_id)
    if row.lifted_on is not None:
        raise BlockError("Zajęcie jest uchylone — jego danych już nie zmieniasz.")
    values = _clean(data, today)
    changed = [key for key, value in values.items() if getattr(row, key) != value]
    if not changed:
        return await _one(db, row, today=today, released=[])
    for key in changed:
        setattr(row, key, values[key])
    row.updated_by = actor.id
    row.updated_at = now
    await db.flush()
    released = (
        []
        if set(changed) <= NOTE_ONLY_FIELDS
        else await _released(
            db,
            await entries_for_contract(db, row.contract_id),
            actor_id=actor.id,
            now=now,
        )
    )
    await _audit(
        db,
        actor,
        "contract.garnishment_update",
        contract_id=row.contract_id,
        label=f"Zajęcie wierzytelności #{row.id} (kontrakt #{row.contract_id})",
        # Same nazwy pól — bez kwot, sygnatur i rachunków (repo i log publiczne).
        details={
            "garnishment_id": row.id,
            "fields": changed,
            "released_from_batches": len(released),
        },
    )
    logger.info("[contractor-blocks] zajęcie %s zmienione przez %s", row.id, actor.id)
    return await _one(db, row, today=today, released=released)


async def lift_garnishment(
    db: AsyncSession,
    garnishment_id: int,
    *,
    lifted_on: date,
    note: Optional[str],
    actor: User,
    today: date,
    now: datetime,
) -> dict[str, Any]:
    row = await _garnishment(db, garnishment_id)
    if row.lifted_on is not None:
        raise BlockError("To zajęcie jest już uchylone.")
    if lifted_on > today:
        raise BlockError("Data uchylenia nie może być z przyszłości.", 422)
    if lifted_on < row.served_on:
        raise BlockError("Uchylenie nie może być przed doręczeniem zajęcia.", 422)
    row.lifted_on = lifted_on
    row.lifted_note = (note or "").strip() or None
    row.lifted_by = actor.id
    row.lifted_at = now
    row.updated_by = actor.id
    row.updated_at = now
    await db.flush()
    released = await _released(
        db, await entries_for_contract(db, row.contract_id), actor_id=actor.id, now=now
    )
    await _audit(
        db,
        actor,
        "contract.garnishment_lift",
        contract_id=row.contract_id,
        label=f"Zajęcie wierzytelności #{row.id} (kontrakt #{row.contract_id})",
        details={"garnishment_id": row.id, "released_from_batches": len(released)},
    )
    logger.info("[contractor-blocks] zajęcie %s uchylone przez %s", row.id, actor.id)
    return await _one(db, row, today=today, released=released)


# ── Spór / wstrzymane ───────────────────────────────────────────────────────


async def _settlement_for(
    db: AsyncSession, *, settlement_id: Optional[int], entry_id: Optional[int]
) -> ClientSettlement:
    if settlement_id is not None:
        settlement = await db.get(ClientSettlement, settlement_id)
        if settlement is None or settlement.kind != "actual":
            raise BlockError("Nie ma takiego rozliczenia kontraktora.", 404)
        return settlement
    entry = await db.get(FinanceCostEntry, entry_id or 0)
    if entry is None or entry.source_type != "contractor_invoice":
        raise BlockError(
            "Spór zapisujemy na rozliczeniu kontraktora — ta faktura nie jest "
            "fakturą kontraktora. Użyj flagi „Wstrzymać płatność” na karcie.",
            409,
        )
    invoice = await db.get(ClientContractorInvoice, entry.source_id)
    if invoice is None or invoice.contract_id is None or not invoice.period_month:
        raise BlockError(
            "Faktura nie jest przypięta do kontraktu i miesiąca rozliczenia — "
            "użyj flagi „Wstrzymać płatność” na karcie faktury."
        )
    settlement = await db.scalar(
        select(ClientSettlement).where(
            ClientSettlement.kind == "actual",
            ClientSettlement.contract_id == invoice.contract_id,
            ClientSettlement.period_month == invoice.period_month,
        )
    )
    if settlement is None:
        raise BlockError(
            "Kontraktor nie ma w NEXUSIE rozliczenia za ten miesiąc — użyj flagi "
            "„Wstrzymać płatność” na karcie faktury."
        )
    return settlement


async def list_holds(
    db: AsyncSession, *, active_only: bool = True
) -> list[dict[str, Any]]:
    query = (
        select(ContractorPaymentHold, ClientSettlement)
        .join(
            ClientSettlement, ClientSettlement.id == ContractorPaymentHold.settlement_id
        )
        .order_by(ContractorPaymentHold.id.desc())
        .limit(200)
    )
    if active_only:
        query = query.where(ContractorPaymentHold.released_at.is_(None))
    rows = (await db.execute(query)).all()
    names = await _names(
        db,
        {
            uid
            for hold, _s in rows
            for uid in (hold.created_by, hold.released_by)
            if uid is not None
        },
    )
    labels = await _contract_labels(db, {s.contract_id for _h, s in rows})
    return [
        {
            **hold_payload(hold, names),
            **labels.get(s.contract_id, {"contract_id": s.contract_id}),
            "period_month": s.period_month,
        }
        for hold, s in rows
    ]


async def set_hold(
    db: AsyncSession,
    *,
    settlement_id: Optional[int],
    entry_id: Optional[int],
    reason: str,
    actor: User,
    now: datetime,
) -> dict[str, Any]:
    text_ = " ".join((reason or "").split())
    if not text_:
        raise BlockError("Podaj powód wstrzymania.", 422)
    settlement = await _settlement_for(
        db, settlement_id=settlement_id, entry_id=entry_id
    )
    # Dwie osoby naraz nie założą dwóch wstrzymań (indeks częściowy i tak odmówi).
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"contractor-hold:{settlement.id}"},
    )
    existing = await db.scalar(
        select(ContractorPaymentHold).where(
            ContractorPaymentHold.settlement_id == settlement.id,
            ContractorPaymentHold.released_at.is_(None),
        )
    )
    if existing is not None:
        raise BlockError("To rozliczenie jest już wstrzymane — najpierw je zwolnij.")
    hold = ContractorPaymentHold(
        settlement_id=settlement.id, reason=text_[:500], created_by=actor.id
    )
    db.add(hold)
    await db.flush()
    released = await _released(
        db, await entries_for_settlement(db, settlement), actor_id=actor.id, now=now
    )
    await _audit(
        db,
        actor,
        "settlement.payment_hold",
        contract_id=settlement.contract_id,
        label=f"Spór / wstrzymane — rozliczenie {settlement.period_month} "
        f"(kontrakt #{settlement.contract_id})",
        details={
            "hold_id": hold.id,
            "settlement_id": settlement.id,
            "released_from_batches": len(released),
        },
    )
    logger.info(
        "[contractor-blocks] wstrzymanie %s rozliczenia %s przez %s",
        hold.id,
        settlement.id,
        actor.id,
    )
    await db.refresh(hold)
    names = await _names(db, {actor.id})
    return {
        **hold_payload(hold, names),
        "period_month": settlement.period_month,
        "contract_id": settlement.contract_id,
        "released_from_batches": released,
    }


async def release_hold(
    db: AsyncSession,
    hold_id: int,
    *,
    note: Optional[str],
    actor: User,
    now: datetime,
) -> dict[str, Any]:
    hold = await db.scalar(
        select(ContractorPaymentHold)
        .where(ContractorPaymentHold.id == hold_id)
        .with_for_update()
    )
    if hold is None:
        raise BlockError("Nie ma takiego wstrzymania.", 404)
    if hold.released_at is not None:
        raise BlockError("To wstrzymanie jest już zwolnione.")
    settlement = await db.get(ClientSettlement, hold.settlement_id)
    hold.released_at = now
    hold.released_by = actor.id
    hold.release_note = (note or "").strip()[:500] or None
    await db.flush()
    await _audit(
        db,
        actor,
        "settlement.payment_release",
        contract_id=settlement.contract_id,
        label=f"Zwolnienie wstrzymania — rozliczenie {settlement.period_month} "
        f"(kontrakt #{settlement.contract_id})",
        details={"hold_id": hold.id, "settlement_id": settlement.id},
    )
    logger.info(
        "[contractor-blocks] wstrzymanie %s zwolnione przez %s", hold.id, actor.id
    )
    names = await _names(db, {u for u in (hold.created_by, hold.released_by) if u})
    return {
        **hold_payload(hold, names),
        "period_month": settlement.period_month,
        "contract_id": settlement.contract_id,
    }


__all__ = [
    "BlockError",
    "GarnishmentData",
    "RowBlocks",
    "create_garnishment",
    "entries_for_contract",
    "entries_for_settlement",
    "for_rows",
    "hold_label",
    "lift_garnishment",
    "list_garnishments",
    "list_holds",
    "release_hold",
    "set_hold",
    "terms_of",
    "transfers_for",
    "update_garnishment",
]
