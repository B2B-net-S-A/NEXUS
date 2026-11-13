"""Jedna kolejka faktur kosztowych w Finansach (E1) nad trzema źródłami.

Źródła zostają, jakie są: faktury osób zespołu (``payroll_invoices``, Płace),
faktury kontraktorów klientów (``client_contractor_invoices``, rozliczenia
klientów) i dokumenty wydatków (``approval_documents``, zgody). Kolejka
dokłada do każdej faktury wpis księgowy (``finance_cost_entries``): etap,
flagi, kategorię, kontrahenta z kartoteki, notatkę i historię. Dane faktury
(numer, sprzedawca, kwoty) czytamy ze źródła przy każdym odczycie, a „Kogo
dotyczy” pokazuje to, co źródło już ustaliło (osoba i rozliczenie miesiąca,
kontrakt, zgoda) — kolejka niczego nie dopasowuje od nowa.

Etapy jak w eBI24: poczekalnia KSeF (``received``: Przyjmij / Odrzuć) →
„Do opisu” (``new``) → „Zweryfikowane” → „Gotowe do księgowania” →
„Zaksięgowane” (``booked``, ustawia je eksport do Symfonii w E2). Cofnięcie
idzie o jeden krok. Nikt nie zmienia etapu własnej faktury (faktura osoby
zespołu z jego kontem).

E2 (``posting.py``): „Zweryfikuj” wylicza dekret, „Gotowa do księgowania”
wymaga kompletnego dekretu, a faktury w paczce eksportu nie cofa się, dopóki
paczki nie anulują.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import (
    Date,
    String,
    and_,
    cast,
    func,
    literal,
    null,
    or_,
    select,
    text,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_month_bounds
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_settlement import ClientContractorInvoice
from app.models.contract import Contract
from app.models.finance_ledger import (
    FinanceCostEntry,
    FinanceCostEntryEvent,
    FinanceCounterparty,
)
from app.models.hr_approval import ApprovalDocument, ApprovalRequest
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_settlement import PayrollInvoice, PayrollSettlement
from app.models.user import User
from app.services.client_identity import client_display_name_expression
from app.services.finance_ledger_schema import (
    CATEGORIES,
    FLAGS,
    LINK_COUNTERPARTIES,
    REASON_MAX,
    STAGES,
    entry_inserts,
)

STAGE_LABELS = {
    "received": "Z KSeF do przyjęcia",
    "new": "Do opisu",
    "verified": "Zweryfikowane",
    "ready": "Gotowe do księgowania",
    "booked": "Zaksięgowane",
    "rejected": "Odrzucone",
}
FLAG_LABELS = {
    "mpp": "MPP",
    "no_mpp": "NIE MPP",
    "hold_payment": "Wstrzymać płatność",
    "tax_office_account": "Zapłata na konto US",
    "duplicate": "Duplikat",
}
CATEGORY_LABELS = {
    "contractor": "Kontraktorzy",
    "team": "Zespół",
    "office": "Biuro",
    "benefit": "Benefity",
    "proforma": "Proforma",
    "other": "Inne",
}
SOURCE_LABELS = {
    "payroll_invoice": "Faktura osoby zespołu (Płace)",
    "contractor_invoice": "Faktura kontraktora klienta (Rozliczenia)",
    "approval_document": "Dokument wydatku (Zgody)",
}
ACTION_LABELS = {
    "accept": "Przyjęta",
    "reject": "Odrzucona",
    "verify": "Zweryfikowana",
    "ready": "Gotowa do księgowania",
    "back": "Cofnięta o krok",
    "flags": "Flagi",
    "category": "Kategoria",
    "note": "Notatka",
    "due_date": "Termin płatności",
    "decree": "Dekret",
    "export": "W paczce eksportu",
    "unexport": "Paczka anulowana",
    "book": "Zaksięgowana",
}
STAGE_ACTIONS = ("accept", "reject", "verify", "ready", "back")
FLAG_ACTIONS = ("flag_add", "flag_remove")
ACTIONS = (*STAGE_ACTIONS, *FLAG_ACTIONS)
BULK_MAX = 500
_EXCLUSIVE = {"mpp": "no_mpp", "no_mpp": "mpp"}

#: (skąd, dokąd) dla akcji, które idą naprzód.
_FORWARD = {
    "accept": (("received",), "new"),
    "reject": (("received", "new"), "rejected"),
    "verify": (("new",), "verified"),
    "ready": (("verified",), "ready"),
}

OWN_INVOICE_DETAIL = "To Twoja faktura — jej status zmienia ktoś inny z Finansów."
BOOKED_DETAIL = "Zaksięgowanej faktury tu nie zmieniasz."
IN_BATCH_DETAIL = (
    "Faktura jest w paczce eksportu do Symfonii — anuluj paczkę w „Księgowanie”, "
    "żeby ją cofnąć."
)


class LedgerError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# ── Reguły (bez bazy) ────────────────────────────────────────────────────────


def next_stage(action: str, stage: str, *, from_ksef: bool) -> str:
    """Etap po akcji albo ``LedgerError`` z powodem po polsku."""

    if stage == "booked":
        raise LedgerError(BOOKED_DETAIL)
    if action == "back":
        if stage == "rejected":
            return "received" if from_ksef else "new"
        if stage == "new":
            if not from_ksef:
                raise LedgerError(
                    "Dokument spoza KSeF nie był w poczekalni — nie ma dokąd cofnąć."
                )
            return "received"
        if stage == "verified":
            return "new"
        if stage == "ready":
            return "verified"
        raise LedgerError("Z poczekalni nie ma kroku wstecz.")
    if action not in _FORWARD:
        raise LedgerError("Nieznana akcja.", status=422)
    allowed, target = _FORWARD[action]
    if stage not in allowed:
        names = " albo ".join(f"„{STAGE_LABELS[name]}”" for name in allowed)
        raise LedgerError(
            f"Faktura jest w etapie „{STAGE_LABELS[stage]}”; ta akcja działa "
            f"tylko w {names}."
        )
    return target


def with_flag(flags: Iterable[str], flag: str, *, on: bool) -> list[str]:
    """Flagi po dodaniu albo zdjęciu jednej; MPP i NIE MPP wykluczają się."""

    if flag not in FLAGS:
        raise LedgerError("Nieznana flaga.", status=422)
    current = [item for item in flags if item in FLAGS]
    if on:
        current = [item for item in current if item != _EXCLUSIVE.get(flag)]
        if flag not in current:
            current.append(flag)
    else:
        current = [item for item in current if item != flag]
    return sorted(current, key=FLAGS.index)


def clean_flags(flags: Iterable[str]) -> list[str]:
    wanted = list(flags)
    if "mpp" in wanted and "no_mpp" in wanted:
        raise LedgerError("MPP i NIE MPP naraz się wykluczają.", status=422)
    result: list[str] = []
    for flag in wanted:
        result = with_flag(result, flag, on=True)
    return result


def clean_reason(reason: Optional[str]) -> str:
    text_ = " ".join((reason or "").split())
    if len(text_) < 3:
        raise LedgerError("Podaj powód odrzucenia (co najmniej 3 znaki).", status=422)
    return text_[:REASON_MAX]


# ── Zakładanie wpisów ────────────────────────────────────────────────────────


async def enqueue_ksef(db: AsyncSession, ksef_number: str) -> None:
    """Wpis dla faktury z KSeF właśnie zapisanej w którymś źródle (hook)."""

    for statement in entry_inserts(by_ksef_number=True):
        await db.execute(text(statement), {"ksef_number": ksef_number})


async def catch_up(db: AsyncSession) -> None:
    """Wpisy dla wszystkich faktur źródeł bez wpisu (też PDF-ów wgranych ręcznie)."""

    for statement in entry_inserts():
        await db.execute(text(statement))
    await db.execute(text(LINK_COUNTERPARTIES))


# ── Odczyt ───────────────────────────────────────────────────────────────────


def _sources():
    payroll = (
        select(
            literal("payroll_invoice", String).label("source_type"),
            PayrollInvoice.id.label("source_id"),
            PayrollInvoice.invoice_number.label("invoice_number"),
            PayrollInvoice.ksef_number.label("ksef_number"),
            User.name.label("seller_name"),
            PayrollInvoice.issue_date.label("issue_date"),
            PayrollInvoice.currency.label("currency"),
            PayrollInvoice.net_amount.label("net_amount"),
            PayrollInvoice.vat_amount.label("vat_amount"),
            PayrollInvoice.gross_amount.label("gross_amount"),
            PayrollSettlement.due_on.label("source_due"),
            PayrollInvoice.user_id.label("person_user_id"),
        )
        .select_from(PayrollInvoice)
        .outerjoin(User, User.id == PayrollInvoice.user_id)
        .outerjoin(
            PayrollSettlement, PayrollSettlement.id == PayrollInvoice.settlement_id
        )
    )
    contractor = select(
        literal("contractor_invoice", String).label("source_type"),
        ClientContractorInvoice.id.label("source_id"),
        ClientContractorInvoice.invoice_number.label("invoice_number"),
        ClientContractorInvoice.ksef_number.label("ksef_number"),
        ClientContractorInvoice.seller_name.label("seller_name"),
        ClientContractorInvoice.issue_date.label("issue_date"),
        ClientContractorInvoice.currency.label("currency"),
        ClientContractorInvoice.net_amount.label("net_amount"),
        ClientContractorInvoice.vat_amount.label("vat_amount"),
        ClientContractorInvoice.gross_amount.label("gross_amount"),
        cast(null(), Date).label("source_due"),
        cast(null(), PayrollInvoice.user_id.type).label("person_user_id"),
    )
    document = select(
        literal("approval_document", String).label("source_type"),
        ApprovalDocument.id.label("source_id"),
        ApprovalDocument.invoice_number.label("invoice_number"),
        ApprovalDocument.ksef_number.label("ksef_number"),
        ApprovalDocument.seller_name.label("seller_name"),
        ApprovalDocument.issue_date.label("issue_date"),
        ApprovalDocument.currency.label("currency"),
        ApprovalDocument.net_amount.label("net_amount"),
        ApprovalDocument.vat_amount.label("vat_amount"),
        ApprovalDocument.gross_amount.label("gross_amount"),
        cast(null(), Date).label("source_due"),
        cast(null(), PayrollInvoice.user_id.type).label("person_user_id"),
    )
    return union_all(payroll, contractor, document).subquery("cost_sources")


@dataclass(frozen=True)
class Filters:
    month: Optional[date] = None
    category: Optional[str] = None
    flag: Optional[str] = None
    q: Optional[str] = None


def _joined(src):
    entry = FinanceCostEntry
    return (
        and_(
            src.c.source_type == entry.source_type, src.c.source_id == entry.source_id
        ),
        FinanceCounterparty.id == entry.counterparty_id,
    )


def _payroll_scope(payroll: bool) -> list[Any]:
    """Faktury osób zespołu (nazwisko i kwota wynagrodzenia) widzą tylko Płace
    i admin (D2, ``ludzie/urlopy-czas-place-wejscie-odejscie.md``) — reszta
    „Modułu Finanse” nie widzi ich w kolejce, licznikach ani na karcie."""

    return [] if payroll else [FinanceCostEntry.source_type != "payroll_invoice"]


def _conditions(src, filters: Filters) -> list[Any]:
    entry = FinanceCostEntry
    conditions: list[Any] = []
    if filters.month is not None:
        bounds = local_month_bounds(filters.month)
        conditions += [
            entry.received_at >= bounds.start_utc,
            entry.received_at < bounds.end_utc,
        ]
    if filters.category:
        conditions.append(entry.category == filters.category)
    if filters.flag == "none":
        conditions.append(func.cardinality(entry.flags) == 0)
    elif filters.flag:
        conditions.append(entry.flags.contains([filters.flag]))
    needle = " ".join((filters.q or "").split())
    if needle:
        pattern = f"%{needle}%"
        conditions.append(
            or_(
                src.c.invoice_number.ilike(pattern),
                src.c.seller_name.ilike(pattern),
                src.c.ksef_number.ilike(pattern),
                FinanceCounterparty.name.ilike(pattern),
                entry.seller_nip.ilike(pattern),
            )
        )
    return conditions


def _money(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else f"{Decimal(value):.2f}"


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


_PAYROLL_STATUS = {
    "matched": "dopasowana do rozliczenia",
    "unmatched": "czeka na przypisanie w Płacach",
    "ignored": "pominięta w Płacach",
}
_NIP_STATE = {
    "known": "NIP z kontraktu",
    "confirmed": "NIP potwierdzony przez Finanse",
    "suggested": "podpowiedź NIP-u do sprawdzenia",
    "rejected": "NIP odrzucony — bez osoby",
}
_DOC_STATUS = {
    "pinned": "przypięta do zgody",
    "settled": "rozliczona ze zgodą",
    "unmatched": "bez zgody",
    "fixed_cost": "stały koszt",
    "dismissed": "zamknięta w Finansach",
}


async def concerning(
    db: AsyncSession, keys: Iterable[tuple[str, int]]
) -> dict[tuple[str, int], dict[str, Any]]:
    """„Kogo dotyczy” — to, co źródło już wie; bez nowych dopasowań."""

    by_type: dict[str, list[int]] = {}
    for source_type, source_id in keys:
        by_type.setdefault(source_type, []).append(source_id)
    result: dict[tuple[str, int], dict[str, Any]] = {}
    if ids := by_type.get("payroll_invoice"):
        rows = await db.execute(
            select(
                PayrollInvoice.id,
                PayrollInvoice.user_id,
                User.name,
                PayrollInvoice.match_status,
                PayrollPeriod.year,
                PayrollPeriod.month,
            )
            .outerjoin(User, User.id == PayrollInvoice.user_id)
            .outerjoin(
                PayrollSettlement, PayrollSettlement.id == PayrollInvoice.settlement_id
            )
            .outerjoin(PayrollPeriod, PayrollPeriod.id == PayrollSettlement.period_id)
            .where(PayrollInvoice.id.in_(ids))
        )
        for invoice_id, user_id, name, status, year, month in rows.all():
            period = f"{int(month):02d}.{int(year)}" if year and month else None
            result[("payroll_invoice", int(invoice_id))] = {
                "kind": "team",
                "person": name,
                "person_user_id": user_id,
                "label": f"Rozliczenie {period}"
                if period
                else "Bez rozliczenia miesiąca",
                "status": status,
                "status_label": _PAYROLL_STATUS.get(status, status),
            }
    if ids := by_type.get("contractor_invoice"):
        rows = await db.execute(
            select(
                ClientContractorInvoice.id,
                ClientContractorInvoice.contract_id,
                ClientContractorInvoice.period_month,
                ClientContractorInvoice.nip_state,
                Candidate.name,
                Candidate.lastname,
                client_display_name_expression(),
            )
            .outerjoin(Contract, Contract.id == ClientContractorInvoice.contract_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(ClientContractorInvoice.id.in_(ids))
        )
        for invoice_id, contract_id, period, state, first, last, client in rows.all():
            person = " ".join(part for part in (first, last) if part) or None
            parts = ["Kontrakt" if contract_id else "Bez kontraktu"]
            if client:
                parts.append(client)
            if period:
                parts.append(f"{period[5:7]}.{period[:4]}")
            result[("contractor_invoice", int(invoice_id))] = {
                "kind": "contractor",
                "person": person,
                "contract_id": contract_id,
                "label": " · ".join(parts),
                "status": state,
                "status_label": _NIP_STATE.get(state, state),
            }
    if ids := by_type.get("approval_document"):
        rows = await db.execute(
            select(
                ApprovalDocument.id,
                ApprovalDocument.status,
                ApprovalDocument.approval_request_id,
                ApprovalRequest.title,
            )
            .outerjoin(
                ApprovalRequest,
                ApprovalRequest.id == ApprovalDocument.approval_request_id,
            )
            .where(ApprovalDocument.id.in_(ids))
        )
        for document_id, status, request_id, title in rows.all():
            label = (
                f"Zgoda na wydatek #{request_id}" + (f" · {title}" if title else "")
                if request_id
                else "Bez zgody na wydatek"
            )
            result[("approval_document", int(document_id))] = {
                "kind": "expense",
                "person": None,
                "request_id": request_id,
                "label": label,
                "status": status,
                "status_label": _DOC_STATUS.get(status, status),
            }
    return result


def _row_payload(row: Any, about: Optional[dict[str, Any]]) -> dict[str, Any]:
    entry: FinanceCostEntry = row.FinanceCostEntry
    due = entry.due_date or row.source_due
    return {
        "id": entry.id,
        "source_type": entry.source_type,
        "source_id": entry.source_id,
        "from_ksef": entry.from_ksef,
        "stage": entry.stage,
        "stage_label": STAGE_LABELS[entry.stage],
        "flags": list(entry.flags or []),
        "category": entry.category,
        "category_label": CATEGORY_LABELS[entry.category],
        "received_at": _iso(entry.received_at),
        "seller_name": row.seller_name or row.counterparty_name,
        "seller_nip": entry.seller_nip,
        "invoice_number": row.invoice_number,
        "ksef_number": row.ksef_number,
        "issue_date": _iso(row.issue_date),
        "currency": row.currency,
        "net_amount": _money(row.net_amount),
        "gross_amount": _money(row.gross_amount),
        "due_date": _iso(due),
        "due_date_set": entry.due_date is not None,
        "counterparty_id": entry.counterparty_id,
        "counterparty_name": row.counterparty_name,
        "cost_account": row.cost_account,
        "concerning": about,
        "reject_reason": entry.reject_reason,
        "note": entry.note,
    }


def _select(src):
    on_source, on_counterparty = _joined(src)
    return (
        select(
            FinanceCostEntry,
            src.c.invoice_number,
            src.c.ksef_number,
            src.c.seller_name,
            src.c.issue_date,
            src.c.currency,
            src.c.net_amount,
            src.c.vat_amount,
            src.c.gross_amount,
            src.c.source_due,
            src.c.person_user_id,
            FinanceCounterparty.name.label("counterparty_name"),
            FinanceCounterparty.cost_account.label("cost_account"),
            FinanceCounterparty.symfonia_partner_id.label("symfonia_partner_id"),
        )
        .join(src, on_source)
        .outerjoin(FinanceCounterparty, on_counterparty)
    )


async def list_view(
    db: AsyncSession,
    *,
    stage: str,
    filters: Filters,
    limit: int,
    offset: int,
    viewer_id: int,
    payroll: bool,
) -> dict[str, Any]:
    src = _sources()
    conditions = [*_conditions(src, filters), *_payroll_scope(payroll)]
    on_source, on_counterparty = _joined(src)
    counted = await db.execute(
        select(FinanceCostEntry.stage, func.count())
        .select_from(FinanceCostEntry)
        .join(src, on_source)
        .outerjoin(FinanceCounterparty, on_counterparty)
        .where(*conditions)
        .group_by(FinanceCostEntry.stage)
    )
    counts = {name: 0 for name in STAGES}
    for name, count in counted.all():
        counts[name] = int(count)
    rows = (
        await db.execute(
            _select(src)
            .where(FinanceCostEntry.stage == stage, *conditions)
            .order_by(FinanceCostEntry.received_at.desc(), FinanceCostEntry.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    about = await concerning(
        db,
        [
            (row.FinanceCostEntry.source_type, row.FinanceCostEntry.source_id)
            for row in rows
        ],
    )
    items = []
    for row in rows:
        entry = row.FinanceCostEntry
        payload = _row_payload(row, about.get((entry.source_type, entry.source_id)))
        payload["own"] = (
            row.person_user_id is not None and row.person_user_id == viewer_id
        )
        items.append(payload)
    return {
        "stage": stage,
        "items": items,
        "total": counts.get(stage, 0),
        "counts": counts,
        "limit": limit,
        "offset": offset,
    }


async def card(
    db: AsyncSession, entry_id: int, *, viewer_id: int, payroll: bool
) -> dict[str, Any]:
    src = _sources()
    row = (
        await db.execute(
            _select(src).where(
                FinanceCostEntry.id == entry_id, *_payroll_scope(payroll)
            )
        )
    ).first()
    if row is None:
        raise LedgerError("Nie ma takiej faktury w kolejce.", status=404)
    entry: FinanceCostEntry = row.FinanceCostEntry
    about = (await concerning(db, [(entry.source_type, entry.source_id)])).get(
        (entry.source_type, entry.source_id)
    )
    payload = _row_payload(row, about)
    payload["own"] = row.person_user_id is not None and row.person_user_id == viewer_id
    payload.update(
        vat_amount=_money(row.vat_amount),
        source_label=SOURCE_LABELS[entry.source_type],
        symfonia_partner_id=row.symfonia_partner_id,
        stage_changed_at=_iso(entry.stage_changed_at),
    )
    from app.services.finance_ledger import posting  # noqa: PLC0415

    payload["decree"] = await posting.section(db, entry, own=payload["own"])
    events = (
        await db.execute(
            select(FinanceCostEntryEvent, User.name)
            .outerjoin(User, User.id == FinanceCostEntryEvent.actor_id)
            .where(FinanceCostEntryEvent.entry_id == entry.id)
            .order_by(FinanceCostEntryEvent.id)
        )
    ).all()
    payload["history"] = [
        {
            "at": _iso(event.created_at),
            "action": event.action,
            "action_label": ACTION_LABELS[event.action],
            "from_stage": event.from_stage,
            "to_stage": event.to_stage,
            "to_stage_label": STAGE_LABELS.get(event.to_stage or ""),
            "detail": event.detail or {},
            "actor": actor,
        }
        for event, actor in events
    ]
    return payload


# ── Zmiany ───────────────────────────────────────────────────────────────────


def _event(
    db: AsyncSession,
    entry: FinanceCostEntry,
    action: str,
    *,
    actor_id: int,
    now: datetime,
    from_stage: Optional[str] = None,
    to_stage: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    db.add(
        FinanceCostEntryEvent(
            entry_id=entry.id,
            action=action,
            from_stage=from_stage,
            to_stage=to_stage,
            detail=detail or {},
            actor_id=actor_id,
            created_at=now,
        )
    )


async def _own_entry_ids(
    db: AsyncSession, entries: list[FinanceCostEntry], actor_id: int
) -> set[int]:
    payroll = {e.source_id: e.id for e in entries if e.source_type == "payroll_invoice"}
    if not payroll:
        return set()
    owned = await db.scalars(
        select(PayrollInvoice.id).where(
            PayrollInvoice.id.in_(payroll), PayrollInvoice.user_id == actor_id
        )
    )
    return {payroll[invoice_id] for invoice_id in owned}


def _apply_stage(
    db: AsyncSession,
    entry: FinanceCostEntry,
    action: str,
    *,
    reason: Optional[str],
    actor_id: int,
    now: datetime,
) -> None:
    target = next_stage(action, entry.stage, from_ksef=entry.from_ksef)
    detail: dict[str, Any] = {}
    if action == "reject":
        entry.reject_reason = clean_reason(reason)
        detail["reason"] = entry.reject_reason
    elif entry.stage == "rejected":
        detail["reason"] = entry.reject_reason
        entry.reject_reason = None
    _event(
        db,
        entry,
        action,
        actor_id=actor_id,
        now=now,
        from_stage=entry.stage,
        to_stage=target,
        detail=detail,
    )
    entry.stage = target
    entry.stage_changed_by = actor_id
    entry.stage_changed_at = now


def _apply_flag(
    db: AsyncSession,
    entry: FinanceCostEntry,
    flag: Optional[str],
    *,
    on: bool,
    actor_id: int,
    now: datetime,
) -> bool:
    if entry.stage == "booked":
        raise LedgerError(BOOKED_DETAIL)
    if not flag:
        raise LedgerError("Wybierz flagę.", status=422)
    before = list(entry.flags or [])
    after = with_flag(before, flag, on=on)
    if after == before:
        return False
    entry.flags = after
    _event(
        db,
        entry,
        "flags",
        actor_id=actor_id,
        now=now,
        detail={"from": before, "to": after},
    )
    return True


async def act(
    db: AsyncSession,
    ids: list[int],
    action: str,
    *,
    actor_id: int,
    now: datetime,
    payroll: bool,
    reason: Optional[str] = None,
    flag: Optional[str] = None,
) -> dict[str, Any]:
    """Akcja na zaznaczonych; odmowa jednej faktury nie zatrzymuje reszty.

    Wszystkie odmówione = ``LedgerError`` z powodem pierwszej (trasa: 4xx),
    część = wynik z listą ``refused``.
    """

    if action not in ACTIONS:
        raise LedgerError("Nieznana akcja.", status=422)
    if action == "reject":
        reason = clean_reason(reason)
    unique = list(dict.fromkeys(ids))[:BULK_MAX]
    entries = list(
        await db.scalars(
            select(FinanceCostEntry)
            .where(FinanceCostEntry.id.in_(unique), *_payroll_scope(payroll))
            .order_by(FinanceCostEntry.id)
            .with_for_update()
        )
    )
    found = {entry.id for entry in entries}
    refused: list[dict[str, Any]] = [
        {"id": entry_id, "detail": "Nie ma takiej faktury w kolejce.", "status": 404}
        for entry_id in unique
        if entry_id not in found
    ]
    own = await _own_entry_ids(db, entries, actor_id)
    from app.services.finance_ledger import posting  # noqa: PLC0415

    ctx = (
        await posting.load_context(db, entries)
        if action in ("verify", "ready")
        else None
    )
    changed = 0
    for entry in entries:
        if entry.id in own:
            refused.append(
                {"id": entry.id, "detail": OWN_INVOICE_DETAIL, "status": 403}
            )
            continue
        try:
            if action in STAGE_ACTIONS:
                if action == "back" and entry.batch_id is not None:
                    raise LedgerError(IN_BATCH_DETAIL)
                if action == "ready" and entry.stage == "verified":
                    posting.ensure_ready(entry, ctx, now=now)
                _apply_stage(
                    db, entry, action, reason=reason, actor_id=actor_id, now=now
                )
                if action == "verify":
                    posting.refresh(entry, ctx, now=now)
                changed += 1
            elif _apply_flag(
                db, entry, flag, on=action == "flag_add", actor_id=actor_id, now=now
            ):
                changed += 1
        except LedgerError as exc:
            refused.append(
                {"id": entry.id, "detail": exc.message, "status": exc.status}
            )
    if refused and not changed and len(refused) == len(unique):
        first = sorted(refused, key=lambda item: item["id"])[0]
        raise LedgerError(first["detail"], status=first["status"])
    await db.flush()
    refused.sort(key=lambda item: item["id"])
    return {"changed": changed, "refused": refused}


async def update(
    db: AsyncSession,
    entry_id: int,
    changes: dict[str, Any],
    *,
    actor_id: int,
    now: datetime,
    payroll: bool,
) -> None:
    """Kategoria, flagi, termin płatności i notatka jednej faktury."""

    entry = await db.scalar(
        select(FinanceCostEntry)
        .where(FinanceCostEntry.id == entry_id, *_payroll_scope(payroll))
        .with_for_update()
    )
    if entry is None:
        raise LedgerError("Nie ma takiej faktury w kolejce.", status=404)
    if entry.id in await _own_entry_ids(db, [entry], actor_id):
        raise LedgerError(OWN_INVOICE_DETAIL, status=403)
    locked = {"category", "flags", "due_date"} & set(changes)
    if entry.stage == "booked" and locked:
        raise LedgerError(BOOKED_DETAIL)
    if "category" in changes:
        category = changes["category"]
        if category not in CATEGORIES:
            raise LedgerError("Nieznana kategoria.", status=422)
        if category != entry.category:
            _event(
                db,
                entry,
                "category",
                actor_id=actor_id,
                now=now,
                detail={"from": entry.category, "to": category},
            )
            entry.category = category
            if entry.stage in ("new", "verified") and entry.decree:
                from app.services.finance_ledger import posting  # noqa: PLC0415

                posting.refresh(entry, await posting.load_context(db, [entry]), now=now)
    if "flags" in changes:
        flags = clean_flags(changes["flags"] or [])
        if flags != list(entry.flags or []):
            _event(
                db,
                entry,
                "flags",
                actor_id=actor_id,
                now=now,
                detail={"from": list(entry.flags or []), "to": flags},
            )
            entry.flags = flags
    if "due_date" in changes and changes["due_date"] != entry.due_date:
        _event(
            db,
            entry,
            "due_date",
            actor_id=actor_id,
            now=now,
            detail={"from": _iso(entry.due_date), "to": _iso(changes["due_date"])},
        )
        entry.due_date = changes["due_date"]
    if "note" in changes:
        note = (changes["note"] or "").strip() or None
        if note != entry.note:
            _event(db, entry, "note", actor_id=actor_id, now=now)
            entry.note = note
    await db.flush()
