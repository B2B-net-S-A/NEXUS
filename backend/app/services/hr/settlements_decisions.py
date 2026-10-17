"""Decyzje Płac o rozliczeniach (R7, R10): zatwierdzenie, korekta, uznanie różnicy, „opłacono”.

* **Zatwierdzenie do zapłaty** — tylko rozliczenie zgodne (``ready``), także
  wszystkie zgodne miesiąca jednym ruchem. Nikt nie zatwierdza sobie
  (CHECK w bazie i odmowa tutaj).
* **„Poproś o korektę”** (B2B, rozbieżność) — powiadomienie osobie bez kwot;
  faktura korygująca z KSeF podepnie się sama (``settlements.match_invoice``).
* **„Uznaj różnicę”** — powód i DRUGA osoba z Płac, Finansów albo admin
  (wnioskujący nie potwierdza sam, CHECK ``override_two_people``). Uznanie
  obejmuje problemy widoczne w chwili wniosku: różnicę netto i rachunek spoza
  białej listy. Nowy dokument albo zmiana rachunku je kasuje.
* **Ręczne „opłacono”** (awaryjnie, Finanse) — z powodem, kwotą i dniem.

Własnego rozliczenia nikt nie rusza (403). Rozliczenie spoza zakresu — 404.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_settlement import PayrollSettlement
from app.models.notification import NotificationType
from app.models.user import User
from app.services.hr import audit, settlements
from app.services.hr.notify import notify_each
from app.services.hr.payroll_errors import (
    PayrollConflict,
    PayrollForbidden,
    PayrollNotFound,
)
from app.services.hr.payroll_periods import label, month_start
from app.services.hr.settlements import SettlementError
from app.services.hr.settlements_rules import B2B, override_kind_for, problems_of
from app.services.hr_settlement_schema import REASON_MAX_LENGTH

NOT_FOUND = "Nie ma takiego rozliczenia."
_STATUS_REFUSAL = {
    "awaiting_document": "Rozliczenie czeka na fakturę.",
    "mismatch": (
        "Rozbieżność wymaga korekty faktury albo uznania różnicy przez drugą osobę."
    ),
    "approved": "Rozliczenie jest już zatwierdzone do zapłaty.",
    "paid": "Rozliczenie jest już opłacone.",
    "cancelled": "Rozliczenie jest anulowane — miesiąc otwarto ponownie.",
}


async def _locked(
    db: AsyncSession, actor: User, settlement_id: int
) -> PayrollSettlement:
    settlement = await settlements.lock_settlement(db, settlement_id)
    if settlement is None:
        raise PayrollNotFound(NOT_FOUND)
    if settlement.user_id == actor.id:
        raise PayrollForbidden(
            "Własnego rozliczenia nie zatwierdzasz ani nie zmieniasz."
        )
    return settlement


def _reason(raw: Optional[str], what: str) -> str:
    text = (raw or "").strip()
    if len(text) < 3:
        raise SettlementError(f"Podaj powód {what} (co najmniej 3 znaki).")
    if len(text) > REASON_MAX_LENGTH:
        raise SettlementError(f"Powód: najwyżej {REASON_MAX_LENGTH} znaków.")
    return text


def _audit(
    db: AsyncSession,
    settlement: PayrollSettlement,
    *,
    actor_id: int,
    action: str,
    **details: object,
) -> None:
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=settlement.user_id,
        entity_type="payroll_settlement",
        entity_id=settlement.id,
        action=action,
        sensitivity="payroll",
        details={
            "status": settlement.status,
            "expected": str(settlement.expected_amount),
            "currency": settlement.currency,
            **details,
        },
    )


async def current_problems(
    db: AsyncSession, settlement: PayrollSettlement
) -> tuple[str, ...]:
    billing = await settlements.billing_of(db, settlement.user_id)
    return problems_of(
        employment_type=settlement.employment_type,
        discrepancy=settlement.discrepancy_amount,
        account_source=billing.account_source if billing else None,
    )


async def approve(
    db: AsyncSession, *, actor: User, settlement_id: int
) -> PayrollSettlement:
    settlement = await _locked(db, actor, settlement_id)
    if settlement.status != "ready":
        raise PayrollConflict(
            _STATUS_REFUSAL.get(settlement.status, "Nie do zatwierdzenia.")
        )
    settlement.status = "approved"
    settlement.approved_by = actor.id
    settlement.approved_at = local_now()
    await db.flush()
    _audit(db, settlement, actor_id=actor.id, action="settlement_approved")
    return settlement


async def approve_ready(
    db: AsyncSession, *, actor: User, period: PayrollPeriod
) -> dict[str, int]:
    """Wszystkie zgodne rozliczenia miesiąca jednym ruchem (bez własnego)."""

    rows = list(
        await db.scalars(
            select(PayrollSettlement)
            .where(
                PayrollSettlement.period_id == period.id,
                PayrollSettlement.status == "ready",
            )
            .order_by(PayrollSettlement.id)
            .with_for_update()
        )
    )
    approved = skipped_own = 0
    now = local_now()
    for row in rows:
        if row.user_id == actor.id:
            skipped_own += 1
            continue
        row.status = "approved"
        row.approved_by = actor.id
        row.approved_at = now
        approved += 1
    await db.flush()
    if approved:
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=None,
            entity_type="payroll_period",
            entity_id=period.id,
            action="settlements_approved",
            sensitivity="payroll",
            details={"year": period.year, "month": period.month, "count": approved},
        )
    return {"approved": approved, "skipped_own": skipped_own}


async def request_correction(
    db: AsyncSession, *, actor: User, settlement_id: int
) -> PayrollSettlement:
    settlement = await _locked(db, actor, settlement_id)
    if settlement.employment_type != B2B or settlement.status != "mismatch":
        raise PayrollConflict("O korektę prosi się przy rozbieżności faktury B2B.")
    settlement.correction_requested_by = actor.id
    settlement.correction_requested_at = local_now()
    await db.flush()
    _audit(db, settlement, actor_id=actor.id, action="correction_requested")
    period = await settlements.period_of(db, settlement)
    await notify_each(
        db,
        [settlement.user_id],
        title="Płace proszą o korektę faktury",
        message=(
            f"Faktura za {label(period.year, period.month)} nie zgadza się z raportem "
            "godzin. Porównanie znajdziesz w „Moim czasie” → Rozliczenie; korekta "
            "z KSeF podepnie się sama."
        ),
        ntype=NotificationType.hr_settlement_correction,
        link=settlements.PERSON_LINK,
        related_entity_type="payroll_settlement",
        related_entity_id=settlement.id,
        log_tag="settlements",
    )
    return settlement


async def request_override(
    db: AsyncSession, *, actor: User, settlement_id: int, reason: Optional[str]
) -> PayrollSettlement:
    settlement = await _locked(db, actor, settlement_id)
    note = _reason(reason, "uznania różnicy")
    if settlement.status != "mismatch":
        raise PayrollConflict("Uznać można tylko rozbieżność.")
    if settlement.override_requested_by is not None:
        raise PayrollConflict("Uznanie różnicy już czeka na drugą osobę.")
    problems = await current_problems(db, settlement)
    kind = override_kind_for(problems)
    if kind is None:
        raise PayrollConflict("Tu nie ma różnicy do uznania — przelicz rozliczenie.")
    settlement.override_kind = kind
    settlement.override_reason = note
    settlement.override_requested_by = actor.id
    settlement.override_requested_at = local_now()
    await db.flush()
    _audit(
        db,
        settlement,
        actor_id=actor.id,
        action="override_requested",
        problems=list(problems),
        discrepancy=None
        if settlement.discrepancy_amount is None
        else str(settlement.discrepancy_amount),
        reason=note,
    )
    name = await settlements.person_name(db, settlement.user_id)
    period = await settlements.period_of(db, settlement)
    await settlements.notify_review(
        db,
        settlement,
        title="Uznanie różnicy czeka na drugą osobę",
        message=(
            f"{name} · {label(period.year, period.month)}: Płace proszą o drugą "
            "parę oczu. Szczegóły w Płacach → Rozliczenia."
        ),
        exclude=(actor.id,),
    )
    return settlement


async def confirm_override(
    db: AsyncSession, *, actor: User, settlement_id: int
) -> PayrollSettlement:
    settlement = await _locked(db, actor, settlement_id)
    if settlement.override_requested_by is None or settlement.status != "mismatch":
        raise PayrollConflict("Nie ma uznania różnicy do potwierdzenia.")
    if settlement.override_requested_by == actor.id:
        raise PayrollForbidden("Uznanie różnicy potwierdza druga osoba.")
    settlement.override_confirmed_by = actor.id
    settlement.override_confirmed_at = local_now()
    await db.flush()
    status = await settlements.recompute(db, settlement)
    _audit(
        db,
        settlement,
        actor_id=actor.id,
        action="override_confirmed",
        kind=settlement.override_kind,
        result=status,
    )
    return settlement


async def withdraw_override(
    db: AsyncSession, *, actor: User, settlement_id: int
) -> PayrollSettlement:
    """Cofnięcie niepotwierdzonego uznania (wnioskujący albo druga osoba)."""

    settlement = await _locked(db, actor, settlement_id)
    if settlement.override_requested_by is None or settlement.override_confirmed_by:
        raise PayrollConflict("Nie ma uznania różnicy do cofnięcia.")
    settlements.clear_override(settlement)
    await db.flush()
    _audit(db, settlement, actor_id=actor.id, action="override_withdrawn")
    return settlement


async def manual_paid(
    db: AsyncSession,
    *,
    actor: User,
    settlement_id: int,
    amount: Decimal,
    paid_on: date,
    reason: Optional[str],
    today: date,
) -> PayrollSettlement:
    settlement = await _locked(db, actor, settlement_id)
    note = _reason(reason, "ręcznego „opłacono”")
    if settlement.status in ("paid", "cancelled"):
        raise PayrollConflict(_STATUS_REFUSAL[settlement.status])
    value = Decimal(amount)
    if not value.is_finite() or value <= 0:
        raise SettlementError("Kwota zapłaty musi być większa od zera.")
    period = await settlements.period_of(db, settlement)
    if paid_on > today:
        raise SettlementError("Dzień zapłaty nie może być w przyszłości.")
    if paid_on < month_start(period.year, period.month):
        raise SettlementError("Dzień zapłaty nie może być przed miesiącem rozliczenia.")
    await settlements.mark_paid(
        db,
        settlement,
        source="manual",
        amount=value,
        paid_on=paid_on,
        actor_id=actor.id,
        reason=note,
    )
    return settlement


__all__ = [
    "approve",
    "approve_ready",
    "confirm_override",
    "current_problems",
    "manual_paid",
    "request_correction",
    "request_override",
    "withdraw_override",
]
