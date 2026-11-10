"""Ikona „Premie do decyzji” przy włączonym automacie (decyzja Artura 09.11.2026).

Bez bazy: co automat bierze na siebie, a co musi ruszyć admin. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.models.hr_payroll import HrBonus
from app.services.hr.bonus_auto_assign import is_scheduled, needs_person
from app.services.hr.bonus_rules import BonusRules

TODAY = date(2026, 11, 9)
AUTOMATIC = BonusRules(auto_assign_from=(2026, 11))


def _bonus(**changes: object) -> HrBonus:
    fields: dict[str, object] = {
        "source": "contract_placement",
        "period_year": 2026,
        "period_month": 11,
        "eligible_on": TODAY - timedelta(days=1),
        "rule_snapshot": {},
    }
    return HrBonus(**{**fields, **changes})


def _person(bonus: HrBonus, *, codes=(), closed=(), rules=AUTOMATIC) -> bool:
    return needs_person(
        bonus, rules=rules, today=TODAY, codes=set(codes), closed=set(closed)
    )


def test_automat_takes_due_bonus_without_hold_flag() -> None:
    assert not _person(_bonus())
    assert not _person(_bonus(source="league", eligible_on=None))
    # Znacznik, który automat rozstrzyga sam, nie zatrzymuje premii.
    assert not _person(_bonus(), codes={"amount_rule"})
    # Konto nieaktywne: automat zdejmuje premię sam.
    assert not _person(_bonus(), codes={"inactive"})


def test_admin_gets_held_bonus_after_its_deadline() -> None:
    assert _person(_bonus(), codes={"no_order"})
    assert _person(_bonus(), codes={"owner", "amount_rule"})
    assert _person(_bonus(), closed={(2026, 11)})


def test_bonus_before_deadline_waits_for_automat_even_with_a_flag() -> None:
    future = _bonus(eligible_on=TODAY + timedelta(days=8))
    assert not _person(future)
    assert not _person(future, codes={"owner"})
    assert is_scheduled(future, rules=AUTOMATIC, today=TODAY)
    assert not is_scheduled(_bonus(), rules=AUTOMATIC, today=TODAY)


def test_doubled_bonus_is_due_before_its_deadline() -> None:
    doubled = _bonus(
        eligible_on=TODAY + timedelta(days=8), rule_snapshot={"double_bonus": True}
    )
    assert not is_scheduled(doubled, rules=AUTOMATIC, today=TODAY)


def test_bonus_outside_automat_still_needs_a_person() -> None:
    assert _person(_bonus(source="manual"))
    assert _person(_bonus(period_month=10))
    assert _person(_bonus(), rules=BonusRules())
    october_future = _bonus(period_month=10, eligible_on=TODAY + timedelta(days=8))
    assert not is_scheduled(october_future, rules=AUTOMATIC, today=TODAY)
    assert not is_scheduled(
        _bonus(eligible_on=TODAY + timedelta(days=8)), rules=BonusRules(), today=TODAY
    )
