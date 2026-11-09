"""Samo przyznawanie premii (decyzja Artura 09.11.2026).

Po włączeniu (``hr_bonus_rules.auto_assign_from``) nocny przebieg przyznaje
propozycje z placementów i z Ligi od tego miesiąca premii, gdy minął ich termin.
Nikt ich nie zatwierdza; ręcznie zmienia tylko admin, z powodem.

Propozycja osoby z nieaktywnym kontem przepada (``recipient_left``). Premia 200%
przyznaje się bez czekania na termin, bo należy się w miesiącu podpisu.

Premia zostaje propozycją, gdy miesiąc jest zamknięty, gdy ma znacznik, którego
automat nie rozstrzygnie (``HOLD_FLAGS``, wtedy admin zmienia zasadę albo dane),
albo gdy kontrakt podpisano w miesiącu programu 200% bez zapisanego wyniku,
bo dopiero wynik mówi, jaka jest kwota.

Pozycje poza regułami (``rule_items``) przyznaje ten sam przebieg, raz na pozycję.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.hr_payroll import HrBonus
from app.models.user import User
from app.services.hr import double_bonus
from app.services.hr.bonus_flags import bonus_flags
from app.services.hr.bonus_rules import BonusRules, RuleItem, load_rules
from app.services.hr.payroll_bonuses import auto_assign
from app.services.hr.payroll_periods import closed_months, lock_period_shared
from app.services.hr.placement_bonuses import RECIPIENT_LEFT

AUTO_SOURCES = ("contract_placement", "league")
HOLD_FLAGS = frozenset({"high_margin", "no_order", "owner", "second_bonus", "twin"})
RULE_ITEM_KEY = "rule_item"


def _due(bonus: HrBonus, today: date) -> bool:
    if bonus.eligible_on is None or bonus.eligible_on <= today:
        return True
    return bool((bonus.rule_snapshot or {}).get("double_bonus"))


def _first_month(rules: BonusRules) -> Optional[int]:
    if rules.auto_assign_from is None:
        return None
    return rules.auto_assign_from[0] * 12 + rules.auto_assign_from[1]


def _in_scope(bonus: HrBonus, rules: BonusRules) -> bool:
    first = _first_month(rules)
    return (
        first is not None
        and bonus.source in AUTO_SOURCES
        and bonus.period_year * 12 + bonus.period_month >= first
    )


def is_scheduled(bonus: HrBonus, *, rules: BonusRules, today: date) -> bool:
    """Propozycja, którą automat przyzna sam w dniu terminu."""

    return _in_scope(bonus, rules) and not _due(bonus, today)


def needs_person(
    bonus: HrBonus,
    *,
    rules: BonusRules,
    today: date,
    codes: set[str],
    closed: set[tuple[int, int]],
) -> bool:
    """Propozycja w ikonie „Premie do decyzji” (decyzja Artura 09.11.2026).

    Przy włączonym automacie zostaje w niej tylko to, czego automat sam nie
    przyzna: premia po terminie ze znacznikiem wstrzymującym albo w zamkniętym
    miesiącu. Premię przed terminem i czekającą na wynik 200% automat przyzna
    sam, a spoza jego zakresu (ręczne, sprzed „od miesiąca”) rozstrzyga człowiek.
    """

    if not _in_scope(bonus, rules):
        return True
    if not _due(bonus, today):
        return False
    return (bonus.period_year, bonus.period_month) in closed or bool(codes & HOLD_FLAGS)


async def _awaiting_double_result(
    db: AsyncSession, rules: BonusRules, contract_ids: list[int]
) -> set[int]:
    """Kontrakty podpisane w miesiącu programu 200%, który nie ma jeszcze wyniku."""

    rule = rules.double_bonus
    if rule is None or not contract_ids:
        return set()
    stored = await double_bonus.stored_results(db)
    open_months = {
        month for month in rule.months if double_bonus.month_key(month) not in stored
    }
    signed = await double_bonus.signed_dates(db, contract_ids)
    return {
        contract_id
        for contract_id, (day, _source) in signed.items()
        if (day.year, day.month) in open_months
    }


async def assign_due(
    db: AsyncSession, *, today: date, rules: Optional[BonusRules] = None
) -> dict[str, int]:
    rules = rules or await load_rules(db)
    counts = {"assigned": 0, "held": 0, "left": 0}
    first = _first_month(rules)
    if first is None:
        return counts
    bonuses = list(
        await db.scalars(
            select(HrBonus)
            .where(
                HrBonus.status == "proposed",
                HrBonus.source.in_(AUTO_SOURCES),
                HrBonus.period_year * 12 + HrBonus.period_month >= first,
            )
            .order_by(HrBonus.id)
            .with_for_update()
        )
    )
    bonuses = [bonus for bonus in bonuses if _due(bonus, today)]
    if not bonuses:
        return counts
    closed = await closed_months(db)
    flags = await bonus_flags(db, bonuses, today=today)
    waiting = await _awaiting_double_result(
        db, rules, sorted({b.contract_id for b in bonuses if b.contract_id})
    )
    now = local_now()
    for bonus in bonuses:
        codes = {flag["code"] for flag in flags.get(bonus.id, ())}
        if "inactive" in codes:
            bonus.status = "cancelled"
            bonus.cancelled_by = None
            bonus.cancelled_at = now
            bonus.cancel_reason = RECIPIENT_LEFT
            counts["left"] += 1
            continue
        held = (
            (bonus.period_year, bonus.period_month) in closed
            or bonus.contract_id in waiting
            or bool(codes & HOLD_FLAGS)
        )
        if held:
            counts["held"] += 1
            continue
        await auto_assign(db, bonus, now=now)
        counts["assigned"] += 1
    return counts


async def _create_item(db: AsyncSession, item: RuleItem, now: Any) -> HrBonus:
    bonus = HrBonus(
        recipient_user_id=item.user_id,
        proposed_by=None,
        amount=item.amount,
        currency="PLN",
        category="custom",
        period_year=item.month[0],
        period_month=item.month[1],
        status="proposed",
        source="manual",
        rule_snapshot={RULE_ITEM_KEY: item.key, "rule": RULE_ITEM_KEY},
        description=item.reason,
    )
    db.add(bonus)
    await db.flush()
    await auto_assign(db, bonus, now=now)
    return bonus


async def assign_rule_items(
    db: AsyncSession, *, rules: Optional[BonusRules] = None
) -> dict[str, int]:
    rules = rules or await load_rules(db)
    counts = {"items_assigned": 0}
    if rules.auto_assign_from is None or not rules.rule_items:
        return counts
    done = set(
        await db.scalars(
            select(func.distinct(HrBonus.rule_snapshot[RULE_ITEM_KEY].astext)).where(
                HrBonus.source == "manual",
                HrBonus.rule_snapshot[RULE_ITEM_KEY].astext.is_not(None),
            )
        )
    )
    closed = await closed_months(db)
    active = set(
        await db.scalars(
            select(User.id).where(
                User.id.in_(sorted({i.user_id for i in rules.rule_items})),
                User.is_active.is_(True),
            )
        )
    )
    now = local_now()
    for item in rules.rule_items:
        if item.key in done or item.month in closed or item.user_id not in active:
            continue
        await lock_period_shared(db, *item.month)
        await _create_item(db, item, now)
        done.add(item.key)
        counts["items_assigned"] += 1
    return counts


__all__ = [
    "HOLD_FLAGS",
    "assign_due",
    "assign_rule_items",
    "is_scheduled",
    "needs_person",
]
