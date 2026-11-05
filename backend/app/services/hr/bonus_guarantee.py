"""Gwarancja premii Delivery Leada: dług za premię i potrącenie z kolejnych premii.

Zasada Artura z 05.11.2026: konsultant, który nie przepracuje 12 miesięcy od
startu kontraktu, odbiera DL-owi premię za ten placement. Decyzje z tego dnia:

* 12 miesięcy liczy się od startu kontraktu (``start_date``): kontrakt musi
  trwać co najmniej do dnia przed rocznicą startu (``guarantee_until``),
* gwarancja obejmuje premie DL (``delivery_lead``: rola ``dl`` i ``dl_extra``),
  rekrutera nie,
* zwrot to cała premia, bez proporcji,
* dług zakłada automat, gdy kontrakt się skończył przed terminem (hak końca
  kontraktu i nocny przebieg), albo Płace ręcznie — np. konsultant odszedł,
  a kontrakt w NEXUSIE jeszcze trwa,
* potrącenie idzie samo: raport otwartego miesiąca odejmuje dług od
  przyznanych premii osoby (najwyżej do ich sumy, w tej samej walucie), reszta
  przechodzi na kolejne miesiące. Zamknięcie miesiąca zamraża potrącenie
  w ``hr_bonus_clawback_offsets``, ponowne otwarcie je kasuje.

Cofnięcie zakończenia kontraktu anuluje otwarty dług automatu; dług ręczny
zostaje, bo to decyzja Płac. Dług zdjęty ręcznie automat już nie zakłada.
Potrącenie zamrożone przed anulowaniem zostaje w historii jako „do oddania”
(``refund_due``) — oddaje się je premią, której automat nie zakłada.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.contract import Contract, ContractStatus
from app.models.hr_payroll import (
    HrBonus,
    HrBonusClawback,
    HrBonusClawbackOffset,
    PayrollPeriod,
)
from app.models.user import User
from app.services.hr import audit
from app.services.hr.payroll_errors import (
    PayrollConflict,
    PayrollError,
    PayrollForbidden,
    PayrollNotFound,
)
from app.services.hr.payroll_periods import closed_months
from app.services.hr.placement_bonuses import contract_end
from app.services.hr_bonus_guarantee_schema import NOTE_MAX_LENGTH

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
GUARANTEED_CATEGORY = "delivery_lead"
#: Nocny przebieg patrzy na kontrakty, które ruszyły w tym oknie (rok + zapas).
SYNC_WINDOW_DAYS = 400
REASON_CONTRACT_RESTORED = "contract_restored"
REASON_BONUS_CANCELLED = "bonus_cancelled"
REASON_MANUAL = "manual"
NOTE_MIN_LENGTH = 3


# ── Termin ───────────────────────────────────────────────────────────────────


def guarantee_until(start: date) -> date:
    """Ostatni dzień, do którego kontrakt musi trwać: dzień przed rocznicą startu."""

    try:
        anniversary = start.replace(year=start.year + 1)
    except ValueError:  # 29 lutego → 1 marca kolejnego roku
        anniversary = date(start.year + 1, 3, 1)
    return anniversary - timedelta(days=1)


@dataclass(frozen=True)
class GuaranteeCheck:
    broken: bool
    ended_on: Optional[date] = None


def check_contract(contract: Contract, today: date) -> GuaranteeCheck:
    """Czy kontrakt skończył się przed upływem 12 miesięcy od startu.

    Liczy się koniec, który już nastąpił: kontrakt z datą końca w przyszłości
    („kończy się”) jeszcze trwa, a data może się zmienić (przedłużenie).
    Kontrakt zakończony bez daty przed terminem gwarancji też ją łamie.
    """

    start = contract.start_date
    if start is None:
        return GuaranteeCheck(False)
    until = guarantee_until(start)
    end = contract_end(contract)
    if end is None:
        ended = contract.status == ContractStatus.ended
        return GuaranteeCheck(ended and today <= until)
    if end > today:
        return GuaranteeCheck(False)
    return GuaranteeCheck(end < until, end)


# ── Rozdział potrąceń (czyste funkcje) ───────────────────────────────────────


@dataclass(frozen=True)
class Deduction:
    clawback_id: int
    user_id: int
    currency: str
    amount: Decimal


@dataclass
class _Debt:
    clawback_id: int
    user_id: int
    currency: str
    remaining: Decimal


def allocate(debts: Sequence[_Debt], available: dict[str, Decimal]) -> list[Deduction]:
    """Jeden miesiąc jednej osoby: długi po kolei, każdy w swojej walucie.

    Potrącenie nie przekracza sumy premii miesiąca w tej walucie; ``remaining``
    długów maleje w miejscu, więc kolejne wywołanie dla następnego miesiąca
    widzi tylko resztę.
    """

    left = dict(available)
    out: list[Deduction] = []
    for debt in debts:
        pool = left.get(debt.currency, ZERO)
        take = min(debt.remaining, pool)
        if take <= 0:
            continue
        left[debt.currency] = pool - take
        debt.remaining -= take
        out.append(Deduction(debt.clawback_id, debt.user_id, debt.currency, take))
    return out


async def _open_debts(
    db: AsyncSession, user_ids: Optional[set[int]] = None
) -> list[_Debt]:
    query = (
        select(HrBonusClawback)
        .where(HrBonusClawback.status == "open")
        .order_by(HrBonusClawback.created_at, HrBonusClawback.id)
    )
    if user_ids is not None:
        if not user_ids:
            return []
        query = query.where(HrBonusClawback.recipient_user_id.in_(sorted(user_ids)))
    rows = list(await db.scalars(query))
    if not rows:
        return []
    settled = await settled_amounts(db, [row.id for row in rows])
    debts = [
        _Debt(
            row.id,
            row.recipient_user_id,
            row.currency,
            Decimal(row.amount) - settled.get(row.id, ZERO),
        )
        for row in rows
    ]
    return [debt for debt in debts if debt.remaining > 0]


async def settled_amounts(
    db: AsyncSession, clawback_ids: Sequence[int]
) -> dict[int, Decimal]:
    """Suma potrąceń zamrożonych w zamkniętych miesiącach per dług."""

    if not clawback_ids:
        return {}
    rows = await db.execute(
        select(
            HrBonusClawbackOffset.clawback_id, func.sum(HrBonusClawbackOffset.amount)
        )
        .where(HrBonusClawbackOffset.clawback_id.in_(sorted(set(clawback_ids))))
        .group_by(HrBonusClawbackOffset.clawback_id)
    )
    return {int(cid): Decimal(total) for cid, total in rows.all()}


async def month_deductions(
    db: AsyncSession, year: int, month: int, *, user_ids: Optional[set[int]] = None
) -> dict[int, list[Deduction]]:
    """Potrącenia otwartego miesiąca per osoba.

    Długi idą od najstarszego. Najpierw zjadają premie wcześniejszych otwartych
    miesięcy (te też się jeszcze potrącą), dopiero reszta trafia na ten miesiąc —
    zamknięcie miesiąca wcześniejszego później nie potrąci więcej, niż zostało.
    """

    debts = await _open_debts(db, user_ids)
    if not debts:
        return {}
    recipients = {debt.user_id for debt in debts}
    target = year * 12 + month
    rows = await db.execute(
        select(
            HrBonus.recipient_user_id,
            HrBonus.period_year,
            HrBonus.period_month,
            HrBonus.currency,
            func.sum(HrBonus.amount),
        )
        .where(
            HrBonus.status == "assigned",
            HrBonus.recipient_user_id.in_(sorted(recipients)),
            HrBonus.period_year * 12 + HrBonus.period_month <= target,
        )
        .group_by(
            HrBonus.recipient_user_id,
            HrBonus.period_year,
            HrBonus.period_month,
            HrBonus.currency,
        )
    )
    closed = await closed_months(db)
    available: dict[int, dict[tuple[int, int], dict[str, Decimal]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for user_id, y, m, currency, total in rows.all():
        key = (int(y), int(m))
        if key in closed and key != (year, month):
            continue
        available[int(user_id)][key][str(currency)] = Decimal(total)

    by_user: dict[int, list[_Debt]] = defaultdict(list)
    for debt in debts:
        by_user[debt.user_id].append(debt)
    out: dict[int, list[Deduction]] = {}
    for user_id, user_debts in by_user.items():
        months = available.get(user_id, {})
        for key in sorted(months):
            taken = allocate(user_debts, months[key])
            if key == (year, month) and taken:
                out[user_id] = taken
    return out


def deducted_by_currency(deductions: Sequence[Deduction]) -> dict[str, Decimal]:
    sums: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for item in deductions:
        sums[item.currency] += item.amount
    return dict(sums)


# ── Zamknięcie i ponowne otwarcie miesiąca ───────────────────────────────────


async def lock_open(db: AsyncSession) -> None:
    """Blokada otwartych długów na czas zamknięcia: dwa zamknięcia naraz nie
    potrącą tej samej reszty dwa razy."""

    await db.execute(
        select(HrBonusClawback.id)
        .where(HrBonusClawback.status == "open")
        .order_by(HrBonusClawback.id)
        .with_for_update()
    )


async def freeze_offsets(
    db: AsyncSession, period: PayrollPeriod, deductions: Sequence[Deduction]
) -> int:
    """Zamraża potrącenia miesiąca; dług spłacony do zera → ``settled``."""

    await db.execute(
        delete(HrBonusClawbackOffset).where(
            HrBonusClawbackOffset.period_id == period.id
        )
    )
    if not deductions:
        return 0
    await db.execute(
        insert(HrBonusClawbackOffset),
        [
            {"clawback_id": d.clawback_id, "period_id": period.id, "amount": d.amount}
            for d in deductions
        ],
    )
    await _refresh_statuses(db, [d.clawback_id for d in deductions])
    return len(deductions)


async def release_offsets(db: AsyncSession, period: PayrollPeriod) -> int:
    """Ponowne otwarcie: potrącenia miesiąca wracają do liczenia z danych."""

    ids = list(
        await db.scalars(
            select(HrBonusClawbackOffset.clawback_id).where(
                HrBonusClawbackOffset.period_id == period.id
            )
        )
    )
    if not ids:
        return 0
    await db.execute(
        delete(HrBonusClawbackOffset).where(
            HrBonusClawbackOffset.period_id == period.id
        )
    )
    await _refresh_statuses(db, ids)
    return len(ids)


async def _refresh_statuses(db: AsyncSession, clawback_ids: Sequence[int]) -> None:
    rows = list(
        await db.scalars(
            select(HrBonusClawback)
            .where(
                HrBonusClawback.id.in_(sorted(set(clawback_ids))),
                HrBonusClawback.status != "cancelled",
            )
            .execution_options(populate_existing=True)
        )
    )
    settled = await settled_amounts(db, [row.id for row in rows])
    for row in rows:
        row.status = (
            "settled" if settled.get(row.id, ZERO) >= Decimal(row.amount) else "open"
        )
    await db.flush()


# ── Zakładanie i zdejmowanie długu ───────────────────────────────────────────


def _audit(
    db: AsyncSession, clawback: HrBonusClawback, *, actor_id: Optional[int], action: str
) -> None:
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=clawback.recipient_user_id,
        entity_type="hr_bonus_clawback",
        entity_id=clawback.id,
        action=action,
        sensitivity="payroll",
        details={
            "bonus_id": clawback.bonus_id,
            "contract_id": clawback.contract_id,
            "amount": str(clawback.amount),
            "currency": clawback.currency,
            "origin": clawback.origin,
            "status": clawback.status,
            "ended_on": clawback.ended_on.isoformat() if clawback.ended_on else None,
            "reason": clawback.cancel_reason,
        },
    )


def _new_clawback(
    bonus: HrBonus,
    *,
    origin: str,
    contract: Optional[Contract],
    ended_on: Optional[date],
    note: Optional[str],
    actor_id: Optional[int],
) -> HrBonusClawback:
    start = contract.start_date if contract is not None else None
    return HrBonusClawback(
        bonus_id=bonus.id,
        recipient_user_id=bonus.recipient_user_id,
        contract_id=bonus.contract_id,
        amount=bonus.amount,
        currency=bonus.currency,
        origin=origin,
        status="open",
        contract_start=start,
        ended_on=ended_on,
        guarantee_until=guarantee_until(start) if start else None,
        note=note,
        created_by=actor_id,
    )


def _cancel(
    clawback: HrBonusClawback,
    *,
    reason: str,
    actor_id: Optional[int],
    note: Optional[str] = None,
) -> None:
    clawback.status = "cancelled"
    clawback.cancelled_by = actor_id
    clawback.cancelled_at = local_now()
    clawback.cancel_reason = reason
    clawback.cancel_note = note


async def reconcile_contract(
    db: AsyncSession, contract: Contract, *, today: date
) -> dict[str, int]:
    """Automat: dług za przyznane premie DL kontraktu, który złamał gwarancję."""

    counts = {"created": 0, "cancelled": 0}
    bonuses = list(
        await db.scalars(
            select(HrBonus)
            .where(
                HrBonus.contract_id == contract.id,
                HrBonus.category == GUARANTEED_CATEGORY,
                HrBonus.status == "assigned",
            )
            .order_by(HrBonus.id)
            .with_for_update()
        )
    )
    if not bonuses:
        return counts
    existing: dict[int, list[HrBonusClawback]] = defaultdict(list)
    for row in await db.scalars(
        select(HrBonusClawback)
        .where(HrBonusClawback.bonus_id.in_([b.id for b in bonuses]))
        .order_by(HrBonusClawback.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ):
        existing[row.bonus_id].append(row)

    check = check_contract(contract, today)
    for bonus in bonuses:
        rows = existing.get(bonus.id, [])
        live = next((row for row in rows if row.status != "cancelled"), None)
        if check.broken:
            # Dług zdjęty przez Płace to decyzja — automat go nie wskrzesza.
            if live is not None or any(r.cancel_reason == REASON_MANUAL for r in rows):
                continue
            clawback = _new_clawback(
                bonus,
                origin="automatic",
                contract=contract,
                ended_on=check.ended_on,
                note=None,
                actor_id=None,
            )
            db.add(clawback)
            await db.flush()
            _audit(db, clawback, actor_id=None, action="bonus_clawback_created")
            counts["created"] += 1
        elif live is not None and live.origin == "automatic" and live.status == "open":
            _cancel(live, reason=REASON_CONTRACT_RESTORED, actor_id=None)
            await db.flush()
            _audit(db, live, actor_id=None, action="bonus_clawback_cancelled")
            counts["cancelled"] += 1
    return counts


async def sync_guarantees(db: AsyncSession, *, today: date) -> dict[str, int]:
    """Nocny przebieg: kontrakty z przyznaną premią DL z ostatniego roku
    i kontrakty z otwartym długiem automatu (każdy w osobnym savepoincie)."""

    since = today - timedelta(days=SYNC_WINDOW_DAYS)
    with_bonus = await db.scalars(
        select(HrBonus.contract_id)
        .join(Contract, Contract.id == HrBonus.contract_id)
        .where(
            HrBonus.category == GUARANTEED_CATEGORY,
            HrBonus.status == "assigned",
            Contract.start_date >= since,
        )
        .distinct()
    )
    with_debt = await db.scalars(
        select(HrBonusClawback.contract_id)
        .where(
            HrBonusClawback.origin == "automatic",
            HrBonusClawback.status == "open",
            HrBonusClawback.contract_id.is_not(None),
        )
        .distinct()
    )
    ids = sorted({cid for cid in (*with_bonus, *with_debt) if cid is not None})
    totals = {"contracts": 0, "created": 0, "cancelled": 0, "errors": 0}
    for contract_id in ids:
        totals["contracts"] += 1
        try:
            async with db.begin_nested():
                contract = await db.get(Contract, contract_id)
                if contract is None:
                    continue
                counts = await reconcile_contract(db, contract, today=today)
        except Exception as exc:  # noqa: BLE001 — jeden kontrakt nie zatrzymuje reszty
            logger.error(
                "[payroll] gwarancja premii: błąd kontraktu %s (%s)",
                contract_id,
                type(exc).__name__,
            )
            totals["errors"] += 1
            continue
        totals["created"] += counts["created"]
        totals["cancelled"] += counts["cancelled"]
    return totals


def _clean_note(note: Optional[str]) -> str:
    text = (note or "").strip()
    if len(text) < NOTE_MIN_LENGTH:
        raise PayrollError(
            f"Podaj powód (co najmniej {NOTE_MIN_LENGTH} znaki), np. kiedy konsultant odszedł."
        )
    return text[:NOTE_MAX_LENGTH]


async def register_manual(
    db: AsyncSession,
    *,
    bonus_id: int,
    actor_id: int,
    note: Optional[str],
    today: date,
) -> HrBonusClawback:
    """Płace: zwrot z gwarancji przy premii DL (np. kontrakt w NEXUSIE jeszcze trwa)."""

    text = _clean_note(note)
    bonus = await db.scalar(
        select(HrBonus).where(HrBonus.id == bonus_id).with_for_update()
    )
    if bonus is None:
        raise PayrollNotFound("Nie ma takiej premii.")
    if bonus.recipient_user_id == actor_id:
        raise PayrollForbidden("Zwrotu własnej premii nie zakładasz.")
    if bonus.category != GUARANTEED_CATEGORY:
        raise PayrollConflict("Gwarancja obejmuje premie Delivery Leada.")
    if bonus.status != "assigned":
        raise PayrollConflict("Zwrot dotyczy premii przyznanej.")
    live = await db.scalar(
        select(HrBonusClawback.id).where(
            HrBonusClawback.bonus_id == bonus.id,
            HrBonusClawback.status != "cancelled",
        )
    )
    if live is not None:
        raise PayrollConflict("Ta premia ma już zwrot z gwarancji.")
    contract = await db.get(Contract, bonus.contract_id) if bonus.contract_id else None
    ended_on = contract_end(contract) if contract is not None else None
    if contract is not None and contract.start_date is not None:
        until = guarantee_until(contract.start_date)
        if until < today and (ended_on is None or ended_on >= until):
            raise PayrollConflict(
                "Konsultant przepracował 12 miesięcy — gwarancja tej premii minęła."
            )
    clawback = _new_clawback(
        bonus,
        origin="manual",
        contract=contract,
        ended_on=ended_on if ended_on is not None and ended_on <= today else None,
        note=text,
        actor_id=actor_id,
    )
    db.add(clawback)
    await db.flush()
    _audit(db, clawback, actor_id=actor_id, action="bonus_clawback_created")
    return clawback


async def cancel_manual(
    db: AsyncSession, *, clawback_id: int, actor_id: int, note: Optional[str]
) -> HrBonusClawback:
    """Płace zdejmują dług; automat go potem nie zakłada drugi raz."""

    text = _clean_note(note)
    clawback = await db.scalar(
        select(HrBonusClawback)
        .where(HrBonusClawback.id == clawback_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if clawback is None:
        raise PayrollNotFound("Nie ma takiego zwrotu.")
    if clawback.recipient_user_id == actor_id:
        raise PayrollForbidden("Własnego zwrotu nie zdejmujesz.")
    if clawback.status == "cancelled":
        raise PayrollConflict("Ten zwrot jest już anulowany.")
    _cancel(clawback, reason=REASON_MANUAL, actor_id=actor_id, note=text)
    await db.flush()
    _audit(db, clawback, actor_id=actor_id, action="bonus_clawback_cancelled")
    return clawback


async def on_bonus_cancelled(db: AsyncSession, bonus: HrBonus) -> int:
    """Premia anulowana w otwartym miesiącu nie została wypłacona — nie ma czego zwracać."""

    rows = list(
        await db.scalars(
            select(HrBonusClawback)
            .where(
                HrBonusClawback.bonus_id == bonus.id,
                HrBonusClawback.status == "open",
            )
            .with_for_update()
        )
    )
    for row in rows:
        _cancel(row, reason=REASON_BONUS_CANCELLED, actor_id=None)
        await db.flush()
        _audit(db, row, actor_id=None, action="bonus_clawback_cancelled")
    return len(rows)


# ── Odczyt ───────────────────────────────────────────────────────────────────


async def live_by_bonus(db: AsyncSession, bonus_ids: Sequence[int]) -> set[int]:
    """Premie z żywym (nieanulowanym) długiem — bez przycisku „Zwrot z gwarancji”."""

    if not bonus_ids:
        return set()
    return {
        int(bid)
        for bid in await db.scalars(
            select(HrBonusClawback.bonus_id).where(
                HrBonusClawback.bonus_id.in_(sorted(set(bonus_ids))),
                HrBonusClawback.status != "cancelled",
            )
        )
    }


async def list_clawbacks(
    db: AsyncSession, *, user_id: Optional[int] = None, limit: int = 200
) -> list[dict[str, Any]]:
    """Długi od najnowszego: otwarte, spłacone i anulowane z potrąceniem do oddania.

    Anulowany bez potrącenia nic nie zmienia w wypłatach, więc listy Płac
    go nie pokazują; osoba widzi tylko swoje długi z kwotą.
    """

    query = (
        select(HrBonusClawback, HrBonus)
        .join(HrBonus, HrBonus.id == HrBonusClawback.bonus_id)
        .order_by(HrBonusClawback.created_at.desc(), HrBonusClawback.id.desc())
        .limit(limit)
    )
    if user_id is not None:
        query = query.where(HrBonusClawback.recipient_user_id == user_id)
    rows = (await db.execute(query)).all()
    settled = await settled_amounts(db, [claw.id for claw, _bonus in rows])
    names = (
        {
            int(uid): str(name)
            for uid, name in (
                await db.execute(
                    select(User.id, User.name).where(
                        User.id.in_(
                            sorted({claw.recipient_user_id for claw, _ in rows})
                        )
                    )
                )
            ).all()
        }
        if rows
        else {}
    )
    items: list[dict[str, Any]] = []
    for claw, bonus in rows:
        paid_back = settled.get(claw.id, ZERO)
        if claw.status == "cancelled" and paid_back <= 0:
            continue
        items.append(
            clawback_payload(
                claw, bonus, settled=paid_back, name=names.get(claw.recipient_user_id)
            )
        )
    return items


async def payload_for(db: AsyncSession, claw: HrBonusClawback) -> dict[str, Any]:
    bonus = await db.get(HrBonus, claw.bonus_id)
    assert bonus is not None  # FK z hr_bonuses (premii nie kasuje się na twardo)
    settled = (await settled_amounts(db, [claw.id])).get(claw.id, ZERO)
    name = await db.scalar(select(User.name).where(User.id == claw.recipient_user_id))
    return clawback_payload(claw, bonus, settled=settled, name=name)


def clawback_payload(
    claw: HrBonusClawback,
    bonus: HrBonus,
    *,
    settled: Decimal,
    name: Optional[str],
) -> dict[str, Any]:
    amount = Decimal(claw.amount)
    cancelled = claw.status == "cancelled"
    return {
        "id": claw.id,
        "bonus_id": claw.bonus_id,
        "recipient_user_id": claw.recipient_user_id,
        "recipient_name": name,
        "contract_id": claw.contract_id,
        "description": bonus.description,
        "bonus_period": f"{bonus.period_year}-{bonus.period_month:02d}",
        "amount": str(amount),
        "currency": claw.currency,
        "settled": str(settled),
        "remaining": "0.00" if cancelled else str(max(amount - settled, ZERO)),
        # Potrącone, a dług anulowany (np. cofnięty koniec kontraktu): do oddania premią.
        "refund_due": str(settled) if cancelled and settled > 0 else None,
        "origin": claw.origin,
        "status": claw.status,
        "contract_start": claw.contract_start.isoformat()
        if claw.contract_start
        else None,
        "ended_on": claw.ended_on.isoformat() if claw.ended_on else None,
        "guarantee_until": claw.guarantee_until.isoformat()
        if claw.guarantee_until
        else None,
        "note": claw.note,
        "cancel_reason": claw.cancel_reason,
        "created_at": claw.created_at.isoformat() if claw.created_at else None,
    }


__all__ = [
    "Deduction",
    "GUARANTEED_CATEGORY",
    "GuaranteeCheck",
    "allocate",
    "cancel_manual",
    "check_contract",
    "clawback_payload",
    "deducted_by_currency",
    "freeze_offsets",
    "guarantee_until",
    "list_clawbacks",
    "live_by_bonus",
    "lock_open",
    "month_deductions",
    "on_bonus_cancelled",
    "payload_for",
    "reconcile_contract",
    "register_manual",
    "release_offsets",
    "settled_amounts",
    "sync_guarantees",
]
