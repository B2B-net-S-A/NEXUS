"""Premia 200%, stała premia dla roli i gwarancja DL — czyste reguły, bez bazy.

Decyzje Artura z 05.11.2026: TCM dostaje stałe 1000 zł; w miesiącach programu
rekruter z celem placementów, 4 weryfikacjami na dzień i precision 75% oraz DL
ze średnią marżą powyżej 50 zł/h dostają premię ×2. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.hr import double_bonus
from app.services.hr.bonus_rules import (
    DEFAULT_RULES,
    BonusRulesError,
    DoubleBonusRule,
    dl_bonus,
    dl_hours_for,
    fixed_amount_for,
    parse_rules,
    rule_amount,
    rules_payload,
)
from app.services.hr.placement_bonuses import placement_targets

RULE = DoubleBonusRule(months=((2026, 11), (2026, 12)))


def test_rules_round_trip_fixed_role_and_double_bonus() -> None:
    rules = parse_rules(
        {
            "fixed_role_amounts": [
                {"role": "talent_community_manager", "amount": "1000"}
            ],
            "double_bonus": {
                "months": ["2026-12", "2026-11"],
                "verifications_per_day": "4",
                "precision_pct": "75",
                "dl_min_margin": "50",
            },
        }
    )
    assert fixed_amount_for("talent_community_manager", rules) == Decimal("1000.00")
    assert fixed_amount_for("recruiter", rules) is None
    assert rules.double_bonus is not None
    assert rules.double_bonus.months == ((2026, 11), (2026, 12))
    assert rules.double_bonus.covers(2026, 11)
    assert not rules.double_bonus.covers(2027, 1)
    assert parse_rules(rules_payload(rules)) == rules


def test_double_bonus_off_by_default() -> None:
    assert DEFAULT_RULES.double_bonus is None
    assert rules_payload(DEFAULT_RULES)["double_bonus"] is None
    assert parse_rules({"double_bonus": None}).double_bonus is None


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"fixed_role_amounts": [{"role": "nobody", "amount": "1"}]}, "nieznana rola"),
        (
            {"fixed_role_amounts": [{"role": "recruiter", "amount": "0"}]},
            "od 0,01",
        ),
        (
            {
                "fixed_role_amounts": [
                    {"role": "recruiter", "amount": "1"},
                    {"role": "recruiter", "amount": "2"},
                ]
            },
            "jedna rola",
        ),
        ({"double_bonus": {"months": []}}, "co najmniej jeden"),
        ({"double_bonus": {"months": ["2026-13"]}}, "RRRR-MM"),
        ({"double_bonus": {"months": ["listopad"]}}, "RRRR-MM"),
        (
            {"double_bonus": {"months": ["2026-11"], "precision_pct": "120"}},
            "precision od 0 do 100",
        ),
    ],
)
def test_invalid_settings_are_refused(raw, message) -> None:
    with pytest.raises(BonusRulesError, match=message):
        parse_rules(raw)


def test_fixed_role_amount_ignores_margin_tiers() -> None:
    targets = placement_targets(
        Decimal("55"), 1, 2, DEFAULT_RULES, fixed_recruiter_amount=Decimal("1000")
    )
    assert targets["recruiter"].amount == Decimal("1000")
    assert targets["dl"].amount == Decimal("924.00")  # DL bez zmian: 10% × 55 × 168
    negative = placement_targets(
        Decimal("-1"), None, 2, DEFAULT_RULES, fixed_recruiter_amount=Decimal("1000")
    )
    assert "recruiter" not in negative


def test_rule_amount_reads_fixed_amount_from_snapshot() -> None:
    snapshot = {"margin_per_hour": "55", "fixed_amount": "1000"}
    assert rule_amount(snapshot, "recruiter") == Decimal("1000.00")


def _user(user_id: int, *, role: str = "recruiter", active: bool = True):
    return SimpleNamespace(
        id=user_id, name=f"Osoba {user_id}", role=role, roles=[role], is_active=active
    )


def _kpi(target: int, per_day: str, precision: str) -> dict:
    return {
        "placements_target": target,
        "verifications_per_workday": float(per_day),
        "precision_pct": float(precision),
    }


def test_recruiter_needs_all_three_conditions() -> None:
    contracts = [{"contract_id": 1}, {"contract_id": 2}]
    ok = double_bonus._recruiter_row(
        _user(1), contracts, _kpi(2, "4.0", "75"), RULE, DEFAULT_RULES
    )
    assert ok["qualified"] is True
    few = double_bonus._recruiter_row(
        _user(1), contracts[:1], _kpi(2, "5", "90"), RULE, DEFAULT_RULES
    )
    assert few["checks"]["placements"] is False and few["qualified"] is False
    slow = double_bonus._recruiter_row(
        _user(1), contracts, _kpi(2, "3.9", "90"), RULE, DEFAULT_RULES
    )
    assert slow["checks"]["verifications"] is False and slow["qualified"] is False
    imprecise = double_bonus._recruiter_row(
        _user(1), contracts, _kpi(2, "5", "74.9"), RULE, DEFAULT_RULES
    )
    assert imprecise["checks"]["precision"] is False
    no_kpi = double_bonus._recruiter_row(_user(1), contracts, None, RULE, DEFAULT_RULES)
    assert no_kpi["qualified"] is False


def test_individual_system_fixed_role_and_inactive_stay_out() -> None:
    rules = parse_rules(
        {
            "individual_recruiters": [
                {
                    "user_id": 7,
                    "base_percent": "25",
                    "step_percent": "5",
                    "expert_percent": "5",
                }
            ],
            "fixed_role_amounts": [
                {"role": "talent_community_manager", "amount": "1000"}
            ],
        }
    )
    contracts = [{"contract_id": 1}] * 3
    kpi = _kpi(1, "6", "95")
    individual = double_bonus._recruiter_row(_user(7), contracts, kpi, RULE, rules)
    tcm = double_bonus._recruiter_row(
        _user(8, role="talent_community_manager"), contracts, kpi, RULE, rules
    )
    gone = double_bonus._recruiter_row(
        _user(9, active=False), contracts, kpi, RULE, rules
    )
    assert (individual["excluded"], individual["qualified"]) == ("individual", False)
    assert (tcm["excluded"], tcm["qualified"]) == ("fixed_role", False)
    assert (gone["excluded"], gone["qualified"]) == ("inactive", False)


def test_dl_average_margin_must_be_above_threshold() -> None:
    def contracts(*margins):
        return [{"contract_id": i, "margin_per_hour": m} for i, m in enumerate(margins)]

    above = double_bonus._dl_row(_user(3), contracts("52.50", "51.25"), RULE)
    assert above["average_margin"] == "51.88" and above["qualified"] is True
    exactly = double_bonus._dl_row(_user(3), contracts("50.00"), RULE)
    assert exactly["qualified"] is False
    below = double_bonus._dl_row(_user(3), contracts("60", "42", "45"), RULE)
    assert below["average_margin"] == "49.00" and below["qualified"] is False
    unknown = double_bonus._dl_row(_user(3), contracts("70", None), RULE)
    assert unknown["missing_margins"] == 1 and unknown["qualified"] is False


@pytest.mark.parametrize(
    ("today", "ended"),
    [
        (date(2026, 11, 30), False),
        (date(2026, 12, 1), True),
        (date(2027, 1, 1), True),
    ],
)
def test_month_result_is_known_after_its_last_day(today, ended) -> None:
    assert double_bonus.month_ended((2026, 11), today) is ended
    assert double_bonus.month_ended((2026, 12), date(2027, 1, 1)) is True


def test_own_rows_hide_per_contract_margin() -> None:
    evaluation = {
        "in_program": True,
        "recruiters": [
            {
                "user_id": 1,
                "kind": "recruiter",
                "contracts": [{"contract_id": 5, "margin_per_hour": "52.40"}],
            },
            {"user_id": 2, "kind": "recruiter", "contracts": []},
        ],
        "dls": [],
    }
    rows = double_bonus.rows_for(
        evaluation, _user(1), parse_rules({"double_bonus": {"months": ["2026-11"]}})
    )
    assert [row["user_id"] for row in rows] == [1]
    assert rows[0]["contracts"] == [{"contract_id": 5}]
    # Ocena w pamięci podręcznej zostaje nietknięta.
    assert evaluation["recruiters"][0]["contracts"][0]["margin_per_hour"] == "52.40"


def test_dl_default_hours_apply_to_every_dl_with_person_exception_first() -> None:
    rules = parse_rules(
        {"dl_default_hours": 160, "dl_hours": [{"user_id": 5, "hours": 120}]}
    )
    assert dl_hours_for(1, rules) == 160
    assert dl_hours_for(5, rules) == 120
    assert dl_bonus(Decimal("46"), rules, dl_user_id=1) == Decimal("736.00")
    # Rekruter w systemie indywidualnym zostaje przy godzinach miesiąca.
    assert rules.monthly_hours == 168
    assert parse_rules(rules_payload(rules)) == rules


def test_dl_default_hours_empty_means_monthly_hours_and_bad_value_is_refused() -> None:
    assert dl_hours_for(1, parse_rules({"dl_default_hours": None})) == 168
    assert dl_hours_for(1, parse_rules({"dl_default_hours": ""})) == 168
    with pytest.raises(BonusRulesError, match="Godziny premii DL"):
        parse_rules({"dl_default_hours": 0})
