"""System indywidualny rekrutera i godziny DL: czyste reguły. Dane fikcyjne."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.hr.bonus_flags import margin_flag
from app.services.hr.bonus_rules import (
    DEFAULT_RULES,
    BonusRulesError,
    DlHoursRule,
    IndividualRecruiterRule,
    dl_bonus,
    individual_percent,
    individual_recruiter_bonus,
    parse_rules,
    rules_payload,
)
from app.models.hr_payroll import HrBonus
from app.services.hr.placement_bonuses import placement_targets

RULE = IndividualRecruiterRule(
    user_id=7,
    base_percent=Decimal("25"),
    step_percent=Decimal("5"),
    expert_percent=Decimal("5"),
)


@pytest.mark.parametrize(
    ("starts", "percent"),
    [(1, "25"), (2, "25"), (3, "35"), (4, "40"), (5, "45")],
)
def test_percent_grows_from_third_start(starts: int, percent: str) -> None:
    assert individual_percent(RULE, starts) == Decimal(percent)


@pytest.mark.parametrize(
    ("margin", "starts", "amount"),
    [
        ("40", 2, "1680.00"),
        ("43", 3, "2528.40"),
        ("60", 3, "3528.00"),
        ("35", 4, "2352.00"),
        ("40", 5, "3024.00"),
    ],
)
def test_amounts_match_the_system_examples(margin, starts, amount) -> None:
    assert individual_recruiter_bonus(Decimal(margin), RULE, starts) == Decimal(amount)


def test_negative_margin_gives_no_bonus() -> None:
    assert individual_recruiter_bonus(Decimal("-1"), RULE, 3) is None


def test_targets_use_individual_rule_only_for_that_person() -> None:
    rules = parse_rules(rules_payload(DEFAULT_RULES))
    rules = type(rules)(**{**rules.__dict__, "individual_recruiters": (RULE,)})
    mine = placement_targets(Decimal("43"), None, 7, rules, recruiter_starts=3)
    other = placement_targets(Decimal("43"), None, 8, rules, recruiter_starts=3)
    assert mine["recruiter"].amount == Decimal("2528.40")
    assert other["recruiter"].amount == Decimal("1500")


def test_dl_hours_exception_only_for_listed_person() -> None:
    rules = type(DEFAULT_RULES)(
        **{**DEFAULT_RULES.__dict__, "dl_hours": (DlHoursRule(user_id=5, hours=160),)}
    )
    assert dl_bonus(Decimal("40.50"), rules, dl_user_id=5) == Decimal("648.00")
    assert dl_bonus(Decimal("40.50"), rules, dl_user_id=6) == Decimal("680.40")


def test_settings_round_trip_and_refusals() -> None:
    raw = {
        "dl_hours": [{"user_id": 5, "hours": 160}],
        "individual_recruiters": [
            {
                "user_id": 7,
                "base_percent": "25",
                "step_percent": "5",
                "expert_percent": "5",
            }
        ],
    }
    parsed = parse_rules(raw)
    assert parse_rules(rules_payload(parsed)) == parsed
    with pytest.raises(BonusRulesError):
        parse_rules({"dl_hours": [{"user_id": 5, "hours": 0}]})
    with pytest.raises(BonusRulesError):
        parse_rules({"dl_hours": [{"user_id": 5, "hours": 160}] * 2})
    with pytest.raises(BonusRulesError):
        parse_rules(
            {
                "individual_recruiters": [
                    {
                        "user_id": 7,
                        "base_percent": "101",
                        "step_percent": "5",
                        "expert_percent": "5",
                    }
                ]
            }
        )


def _bonus(margin: str) -> HrBonus:
    return HrBonus(
        recipient_user_id=1,
        amount=Decimal("1"),
        period_year=2026,
        period_month=11,
        eligible_on=date(2026, 11, 1),
        rule_snapshot={"margin_per_hour": margin},
    )


def test_day_rate_margin_is_flagged_but_normal_is_not() -> None:
    assert margin_flag(_bonus("1180.00"))["code"] == "high_margin"
    assert margin_flag(_bonus("100.00")) is None
    assert margin_flag(_bonus("42.50")) is None
