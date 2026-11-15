"""Przegląd „Stawki ramowe”: status, dźwignie z umowy i kwartały (F2). Wartości fikcyjne."""

from datetime import date
from decimal import Decimal

from app.services.framework_category import ClientTerms
from app.services.framework_limits import AdderView, CardView
from app.services.framework_overview import Overview, OverviewRow, classify, levers, quarter_ends

ON = date(2031, 4, 1)
DEV = [("IT Developer", None), ("IT Developer", "Senior"), ("IT Developer", "Expert")]
TERMS = ClientTerms(
    cards=(
        CardView(1, "IT Developer", None, 90),
        CardView(2, "IT Developer", "Senior", 100),
        CardView(3, "IT Developer", "Expert", 110),
        CardView(4, "IT Automation Tester", None, 70),
        CardView(5, "IT Automation Tester", "Senior", 85),
        CardView(6, "IT Architect", None, 100),
    ),
    adders=(
        AdderView(10, "PEGA", Decimal("10"), tuple({"role": r, "seniority": s} for r, s in DEV)),
        AdderView(11, "Kafka", Decimal("20"), tuple({"role": r, "seniority": s} for r, s in DEV) + ({"role": "IT Automation Tester", "seniority": "Senior"},)),
    ),
)


def test_classify():
    assert classify(Decimal("100"), Decimal("100"), Decimal("100")) == "in"
    assert classify(Decimal("110"), Decimal("120"), Decimal("100")) == "in_addon"
    assert classify(Decimal("121"), Decimal("120"), Decimal("100")) == "over"
    assert classify(None, Decimal("120"), None) == "no_limit"
    assert classify(Decimal("100"), None, None) == "no_limit"


def test_small_gap_prefers_the_cheaper_addon():
    (lever, *rest) = levers(TERMS, TERMS.cards[1], Decimal("108"), ON)
    assert (lever.kind, lever.label, lever.limit) == ("addon", "Dopłata +10% (PEGA)", Decimal("110.00"))
    # Awans Senior → Expert (110) też mieści 108.
    assert [l.kind for l in rest] == ["level"]


def test_tester_without_addon_rights_gets_level_up():
    # Tester na poziomie Regular nie ma dopłat; Senior (85) mieści 80.
    assert [(l.kind, l.label) for l in levers(TERMS, TERMS.cards[3], Decimal("80"), ON)] == [
        ("level", "Awans na IT Automation Tester - Senior"),
    ]


def test_level_plus_addon_when_level_alone_is_not_enough():
    out = levers(TERMS, TERMS.cards[3], Decimal("100"), ON)
    assert [(l.kind, l.limit) for l in out] == [("level_addon", Decimal("102.00"))]


def test_no_lever_beyond_contract():
    assert levers(TERMS, TERMS.cards[5], Decimal("150"), ON) == []
    assert levers(TERMS, None, Decimal("150"), ON) == []


def test_quarter_ends_are_closed_quarters():
    assert quarter_ends(date(2026, 11, 15)) == [date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)]
    assert quarter_ends(date(2026, 1, 2), count=1) == [date(2025, 12, 31)]


def test_overview_counts_and_categories():
    def row(status, category, gap=None):
        return OverviewRow(1, "Osoba", category, None, None, None, None, None, None, status, gap, None)

    ov = Overview(ON, [row("in", "IT Developer - Senior"), row("over", "IT Developer", Decimal("7")), row("in_addon", "IT Developer - Expert"), row("no_limit", None)])
    assert ov.counts == {"in": 1, "in_addon": 1, "over": 1, "no_limit": 1}
    assert ov.over_gap == Decimal("7")
    assert ov.by_category() == [("IT Developer", {"in": 1, "in_addon": 1, "over": 1})]
