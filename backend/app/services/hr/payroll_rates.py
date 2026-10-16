"""Historia stawek godzinowych pracowników (``employee_rates``).

Reguły (Compass ``internal-rates.ts`` + naprawy):

* stawka obowiązuje od 1. dnia miesiąca (CHECK w bazie),
* zmiana wstecz najwyżej o 12 miesięcy, licząc od miesiąca „dziś” w kalendarzu
  firmy — Compass liczył „przyszły miesiąc” w UTC (``internal-rates.ts:78-86``),
* nowa stawka domyka poprzednią w tej samej transakcji (``effective_to`` =
  dzień przed nową) i sama kończy się dzień przed kolejną, jeśli taka jest,
* ta sama data „od” = poprawka istniejącego kroku,
* nic nie zmienia się w zamkniętym miesiącu płac (409),
* osoba dostaje dzwonek ``hr_rate_changed`` BEZ kwoty (Compass miał typ
  ``rate_changed``, którego nikt nie wysyłał); kwota zostaje w
  ``hr_audit_events`` z ``sensitivity='payroll'``.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_payroll import EmployeeRate
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.services.hr import audit
from app.services.hr.payroll_errors import PayrollError, PayrollNotFound
from app.services.hr.payroll_periods import add_months, assert_range_open
from app.services.hr_payroll_schema import CURRENCIES
from app.services.notification_triggers import emit

logger = logging.getLogger(__name__)

RATE_BACKDATE_MAX_MONTHS = 12
RATE_AHEAD_MAX_MONTHS = 24
RATE_MAX = Decimal("9999999.99")


def validate_effective_from(effective_from: date, today: date) -> None:
    if effective_from.day != 1:
        raise PayrollError("Stawka obowiązuje od 1. dnia miesiąca.")
    earliest = date(*add_months(today.year, today.month, -RATE_BACKDATE_MAX_MONTHS), 1)
    if effective_from < earliest:
        raise PayrollError(
            "Stawkę można zmienić wstecz najwyżej o "
            f"{RATE_BACKDATE_MAX_MONTHS} miesięcy (od {earliest:%d.%m.%Y})."
        )
    latest = date(*add_months(today.year, today.month, RATE_AHEAD_MAX_MONTHS), 1)
    if effective_from > latest:
        raise PayrollError(f"Stawkę można zaplanować najdalej na {latest:%m.%Y}.")


def validate_rate(hourly_rate: Decimal, currency: str) -> tuple[Decimal, str]:
    if not hourly_rate.is_finite() or hourly_rate < 0 or hourly_rate > RATE_MAX:
        raise PayrollError("Stawka musi być liczbą od 0 do 9 999 999,99.")
    code = (currency or "").strip().upper()
    if code not in CURRENCIES:
        raise PayrollError("Waluta stawki: PLN, EUR albo USD.")
    return hourly_rate.quantize(Decimal("0.01")), code


def rate_payload(rate: EmployeeRate) -> dict[str, Any]:
    return {
        "id": rate.id,
        "user_id": rate.user_id,
        "hourly_rate": str(rate.hourly_rate),
        "currency": rate.currency,
        "effective_from": rate.effective_from.isoformat(),
        "effective_to": rate.effective_to.isoformat() if rate.effective_to else None,
        "reason": rate.reason,
        "set_by": rate.set_by,
    }


def rate_on(rates: list[EmployeeRate], day: date) -> Optional[EmployeeRate]:
    """Stawka obowiązująca w dniu ``day`` (historia posortowana dowolnie)."""

    for rate in rates:
        if rate.effective_from <= day and (
            rate.effective_to is None or rate.effective_to >= day
        ):
            return rate
    return None


async def history(db: AsyncSession, user_id: int) -> list[EmployeeRate]:
    rows = await db.scalars(
        select(EmployeeRate)
        .where(EmployeeRate.user_id == user_id)
        .order_by(EmployeeRate.effective_from.desc())
    )
    return list(rows)


async def rates_on(db: AsyncSession, day: date) -> dict[int, EmployeeRate]:
    """Stawka obowiązująca w dniu ``day`` dla każdej osoby, która ją ma."""

    rows = await db.scalars(
        select(EmployeeRate).where(
            EmployeeRate.effective_from <= day,
            (EmployeeRate.effective_to.is_(None)) | (EmployeeRate.effective_to >= day),
        )
    )
    return {rate.user_id: rate for rate in rows}


async def _locked_history(db: AsyncSession, user_id: int) -> list[EmployeeRate]:
    profile = await db.scalar(
        select(EmployeeProfile.id)
        .where(EmployeeProfile.user_id == user_id)
        .with_for_update()
    )
    if profile is None:
        raise PayrollNotFound("Ta osoba nie ma kartoteki pracownika.")
    rows = await db.scalars(
        select(EmployeeRate)
        .where(EmployeeRate.user_id == user_id)
        .order_by(EmployeeRate.effective_from)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _notify(db: AsyncSession, rate: EmployeeRate) -> None:
    try:
        async with db.begin_nested():
            await emit(
                db,
                user_id=rate.user_id,
                title="Zmiana Twojej stawki",
                message=(
                    f"Nowa stawka obowiązuje od {rate.effective_from:%d.%m.%Y}. "
                    "Szczegóły w „Moim czasie” → Premie."
                ),
                ntype=NotificationType.hr_rate_changed,
                related_entity_type="employee_rate",
                related_entity_id=rate.id,
                link="/my-time",
            )
    except Exception:  # noqa: BLE001 — dzwonek nie cofa zapisu stawki
        logger.exception("[payroll] dzwonek o stawce nie wyszedł rate=%s", rate.id)


async def set_rate(
    db: AsyncSession,
    *,
    user_id: int,
    hourly_rate: Decimal,
    currency: str,
    effective_from: date,
    reason: Optional[str],
    actor_id: int,
    today: date,
) -> EmployeeRate:
    """Nowa stawka od 1. dnia miesiąca (albo poprawka kroku z tą samą datą)."""

    validate_effective_from(effective_from, today)
    amount, code = validate_rate(hourly_rate, currency)
    note = (reason or "").strip() or None
    if note and len(note) > 500:
        raise PayrollError("Powód zmiany: najwyżej 500 znaków.")

    rows = await _locked_history(db, user_id)
    same = next((r for r in rows if r.effective_from == effective_from), None)
    earlier = [r for r in rows if r.effective_from < effective_from]
    later = [r for r in rows if r.effective_from > effective_from]
    new_to = later[0].effective_from - timedelta(days=1) if later else None
    await assert_range_open(db, effective_from, new_to)

    previous: Optional[dict[str, Any]] = None
    if same is not None:
        previous = {"hourly_rate": str(same.hourly_rate), "currency": same.currency}
        same.hourly_rate = amount
        same.currency = code
        same.reason = note
        same.set_by = actor_id
        rate = same
    else:
        if earlier:
            before = earlier[-1]
            previous = {
                "hourly_rate": str(before.hourly_rate),
                "currency": before.currency,
            }
            before.effective_to = effective_from - timedelta(days=1)
            # Indeks „jedna otwarta stawka” sprawdza każdy wiersz od razu.
            await db.flush()
        rate = EmployeeRate(
            user_id=user_id,
            hourly_rate=amount,
            currency=code,
            effective_from=effective_from,
            effective_to=new_to,
            reason=note,
            set_by=actor_id,
        )
        db.add(rate)
    await db.flush()

    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=user_id,
        entity_type="employee_rate",
        entity_id=rate.id,
        action="rate_set" if same is None else "rate_corrected",
        sensitivity="payroll",
        details={
            "effective_from": effective_from.isoformat(),
            "effective_to": new_to.isoformat() if new_to else None,
            "hourly_rate": str(amount),
            "currency": code,
            "previous": previous,
        },
    )
    await _notify(db, rate)
    return rate


async def delete_rate(db: AsyncSession, *, rate_id: int, actor_id: int) -> int:
    """Usuwa pomyłkowy krok; poprzedni krok przejmuje jego okres. Zwraca ``user_id``."""

    user_id = await db.scalar(
        select(EmployeeRate.user_id).where(EmployeeRate.id == rate_id)
    )
    if user_id is None:
        raise PayrollNotFound("Nie ma takiej stawki.")
    rows = await _locked_history(db, user_id)
    rate = next((r for r in rows if r.id == rate_id), None)
    if rate is None:
        raise PayrollNotFound("Nie ma takiej stawki.")
    await assert_range_open(db, rate.effective_from, rate.effective_to)
    before = next(
        (r for r in rows if r.effective_to == rate.effective_from - timedelta(days=1)),
        None,
    )
    snapshot = rate_payload(rate)
    await db.delete(rate)
    await db.flush()
    if before is not None:
        before.effective_to = rate.effective_to
        await db.flush()
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=user_id,
        entity_type="employee_rate",
        entity_id=rate_id,
        action="rate_deleted",
        sensitivity="payroll",
        details={"deleted": snapshot},
    )
    return int(user_id)


__all__ = [
    "RATE_BACKDATE_MAX_MONTHS",
    "delete_rate",
    "history",
    "rate_on",
    "rate_payload",
    "rates_on",
    "set_rate",
    "validate_effective_from",
    "validate_rate",
]
