"""Limit z umowy ramowej: kategoria z COA, cennik i dopłaty technologiczne.

Wartości fikcyjne — prawdziwy cennik klienta trafia do bazy importem, nie do repo.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.framework_limits import (
    AdderView,
    CardView,
    addon_choices,
    category_label,
    framework_limit,
    match_card,
    parse_category_label,
    percent_text,
)


def card(id, role, seniority, rate, valid_from=None, valid_to=None):
    return CardView(
        id=id,
        role=role,
        seniority=seniority,
        rate_client_max=rate,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def adder(tech, pct, *pairs, valid_from=None, valid_to=None):
    return AdderView(
        id=hash(tech) % 1000,
        technology=tech,
        percent=Decimal(pct),
        eligible=tuple({"role": r, "seniority": s} for r, s in pairs),
        valid_from=valid_from,
        valid_to=valid_to,
    )


CARDS = [
    card(1, "IT Developer", "Senior", 100),
    card(2, "IT Developer", "Expert", 110),
    card(3, "IT Developer", None, 90),
    card(4, "IT Architect", None, 100),
    card(5, "IT Automation Tester", None, 70),
    card(6, "IT Automation Tester", "Senior", 85),
]
ADDERS = [
    adder("Kafka", "20", ("IT Developer", "Senior"), ("IT Developer", "Expert"), ("IT Developer", None), ("IT Automation Tester", "Senior")),
    adder("PEGA", "10", ("IT Developer", "Senior"), ("IT Developer", "Expert"), ("IT Developer", None), ("IT Automation Tester", "Senior")),
]


@pytest.mark.parametrize(
    "label, expected",
    [
        ("IT Developer - Senior", ("IT Developer", "Senior")),
        ("IT Developer – Expert", ("IT Developer", "Expert")),
        ("IT  Operations -  Junior", ("IT Operations", "Junior")),
        ("IT Developer", ("IT Developer", None)),
        ("IT Operations - Senior Poland -", ("IT Operations", "Senior")),
        ("I&O - Oracle DBA", ("I&O - Oracle DBA", None)),
        ("   ", None),
        (None, None),
    ],
)
def test_parse_category_label(label, expected):
    assert parse_category_label(label) == expected


def test_category_label_round_trip():
    assert category_label("IT Developer", "Senior") == "IT Developer - Senior"
    assert category_label("IT Developer", None) == "IT Developer"


def test_match_card_is_case_and_space_insensitive():
    assert match_card(CARDS, "it developer - senior", on=date(2026, 11, 15)).id == 1
    assert match_card(CARDS, "IT Developer", on=date(2026, 11, 15)).id == 3


def test_match_card_respects_validity_and_returns_none_for_unknown():
    cards = [
        card(1, "IT Developer", "Senior", 100, valid_to=date(2026, 2, 28)),
        card(9, "IT Developer", "Senior", 105, valid_from=date(2026, 3, 1)),
    ]
    assert match_card(cards, "IT Developer - Senior", on=date(2026, 1, 10)).id == 1
    assert match_card(cards, "IT Developer - Senior", on=date(2026, 11, 15)).id == 9
    assert match_card(cards, "Business Analyst", on=date(2026, 11, 15)) is None


def test_addon_choices_only_for_eligible_category():
    on = date(2026, 11, 15)
    assert [a.technology for a in addon_choices(ADDERS, CARDS[0], on=on)] == ["Kafka", "PEGA"]
    # Architekt i tester na poziomie Regular nie mają addonów w umowie.
    assert addon_choices(ADDERS, CARDS[3], on=on) == []
    assert addon_choices(ADDERS, CARDS[4], on=on) == []


def test_addon_choices_skip_expired_adders():
    old = adder("Hadoop", "20", ("IT Developer", "Senior"), valid_to=date(2026, 2, 28))
    assert addon_choices([old], CARDS[0], on=date(2026, 11, 15)) == []


def test_framework_limit_without_and_with_addon():
    assert framework_limit(CARDS[0], None) == Decimal("100.00")
    assert framework_limit(CARDS[0], Decimal("20")) == Decimal("120.00")
    assert framework_limit(card(7, "X", None, 178), Decimal("10")) == Decimal("195.80")
    assert framework_limit(card(7, "X", None, 161), Decimal("20")) == Decimal("193.20")


def test_framework_limit_needs_a_max_rate():
    assert framework_limit(card(8, "X", None, None), Decimal("10")) is None


def test_views_build_from_orm_like_objects():
    orm = SimpleNamespace(id=1, role="IT Developer", seniority="Senior", rate_client_max=100, valid_from=None, valid_to=None)
    assert CardView.of(orm).id == 1
    orm_adder = SimpleNamespace(id=2, technology="Kafka", percent=Decimal("20"), eligible=[{"role": "IT Developer", "seniority": "Senior"}], valid_from=None, valid_to=None)
    assert AdderView.of(orm_adder).eligible == ({"role": "IT Developer", "seniority": "Senior"},)


def test_percent_text_never_uses_scientific_notation():
    assert percent_text(Decimal("20.00")) == "20"
    assert percent_text(Decimal("10")) == "10"
    assert percent_text(Decimal("12.50")) == "12.5"
