"""Plan amortyzacji (K6) bez bazy: liniowa, degresywna z przejściem na liniową,
jednorazowa, ulepszenie w trakcie, likwidacja w trakcie roku, stan z Symfonii,
plan podatkowy ≠ bilansowy. Kwoty fikcyjne, w groszach."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.ledger import depreciation as dep
from app.services.ledger.depreciation import Opening, PlanInput


def _plan(**values) -> PlanInput:
    data = {
        "method": "linear",
        "rate": Decimal("30"),
        "initial": 3_690_000,
        "accepted": date(2026, 7, 14),
    }
    data.update(values)
    return PlanInput(**data)


def _months(rows) -> list[str]:
    return [f"{row.month.year}-{row.month.month:02d}" for row in rows]


def test_linear_starts_month_after_acceptance_and_ends_exactly():
    rows = dep.schedule(_plan())
    # 36 900,00 zł × 30% / 12 = 922,50 zł — 40 równych odpisów, od 08.2026.
    assert rows[0].month == date(2026, 8, 1)
    assert {row.amount for row in rows} == {92_250}
    assert len(rows) == 40
    assert rows[-1].month == date(2029, 11, 1)
    assert rows[-1].accumulated == 3_690_000 and rows[-1].net == 0


@pytest.mark.parametrize(
    ("accepted", "first"),
    [
        (date(2026, 1, 31), date(2026, 2, 1)),
        (date(2026, 12, 1), date(2027, 1, 1)),
        (date(2026, 12, 31), date(2027, 1, 1)),
    ],
)
def test_first_month_is_the_one_after_acceptance(accepted, first):
    assert dep.schedule(_plan(accepted=accepted))[0].month == first


def test_last_installment_is_the_remainder():
    # 1 000,00 zł × 7% / 12 = 5,8333… → 5,83 zł; 171 × 5,83 = 996,93, reszta 3,07.
    rows = dep.schedule(_plan(initial=100_000, rate=Decimal("7")))
    assert len(rows) == 172
    assert {row.amount for row in rows[:-1]} == {583}
    assert rows[-1].amount == 307
    assert sum(row.amount for row in rows) == 100_000


def test_rounding_is_half_up_to_the_grosz():
    # 186 400,00 × 10% / 12 = 1 553,333… → 1 553,33; ostatni odpis = reszta.
    rows = dep.schedule(_plan(initial=18_640_000, rate=Decimal("10")))
    assert rows[0].amount == 155_333
    assert rows[-1].amount == 18_640_000 - 155_333 * (len(rows) - 1)
    assert dep.monthly(5, Decimal("30")) == 0  # 0,125 gr → 0
    assert dep.monthly(6, Decimal("50")) == 0  # 0,25 gr → 0
    assert dep.monthly(30, Decimal("20")) == 1  # 0,5 gr → 1 (połówka w górę)


def test_tiny_value_still_depreciates_by_one_grosz():
    rows = dep.schedule(_plan(initial=3, rate=Decimal("10")))
    assert [row.amount for row in rows] == [1, 1, 1]


def test_improvement_raises_value_from_the_next_month():
    plan = _plan(
        initial=1_200_000,
        rate=Decimal("20"),
        accepted=date(2026, 3, 15),
        improvements=((date(2026, 6, 10), 600_000),),
    )
    rows = dep.schedule(plan)
    # 04–06.2026 po 200 zł od 12 000 zł, od 07.2026 po 300 zł od 18 000 zł.
    assert [row.amount for row in rows[:4]] == [20_000, 20_000, 20_000, 30_000]
    assert rows[3].month == date(2026, 7, 1) and rows[3].value == 1_800_000
    assert sum(row.amount for row in rows) == 1_800_000
    assert len(rows) == 3 + 58
    assert dep.value_at(plan, date(2026, 6, 1)) == 1_800_000  # ewidencja od dnia UL
    assert dep.value_at(plan, date(2026, 5, 1)) == 1_200_000


def test_improvement_of_fully_depreciated_asset_resumes_depreciation():
    plan = _plan(
        initial=120_000,
        rate=Decimal("100"),
        accepted=date(2026, 1, 20),
        improvements=((date(2027, 3, 5), 60_000),),
    )
    rows = dep.schedule(plan)
    assert _months(rows)[:12] == [f"2026-{m:02d}" for m in range(2, 13)] + ["2027-01"]
    assert _months(rows)[12:] == ["2027-04", "2027-05", "2027-06", "2027-07"]
    assert [row.amount for row in rows[12:]] == [15_000] * 4
    assert rows[-1].accumulated == 180_000


def test_liquidation_mid_year_depreciates_through_its_month_only():
    plan = _plan(
        initial=2_400_000,
        rate=Decimal("25"),
        accepted=date(2026, 1, 10),
        disposed=date(2026, 9, 20),
    )
    rows = dep.schedule(plan)
    assert _months(rows) == [f"2026-{m:02d}" for m in range(2, 10)]
    month = date(2026, 9, 1)
    assert dep.accumulated_at(plan, rows, month) == 8 * 50_000
    assert (
        dep.value_at(plan, month) - dep.accumulated_at(plan, rows, month) == 2_000_000
    )


def test_disposal_in_acceptance_month_gives_no_depreciation():
    plan = _plan(accepted=date(2026, 5, 4), disposed=date(2026, 5, 28))
    assert dep.schedule(plan) == []


def test_tax_plan_differs_from_balance_plan():
    balance = dep.schedule(_plan(rate=Decimal("20")))
    tax = dep.schedule(_plan(method="one_off", rate=Decimal("0")))
    assert balance[0].amount == 61_500 and len(balance) == 60
    assert [(row.month, row.amount) for row in tax] == [(date(2026, 8, 1), 3_690_000)]
    faster = dep.schedule(_plan(rate=Decimal("30")))
    assert len(faster) == 40 and faster[0].amount != balance[0].amount


def test_degressive_switches_to_linear_from_the_year_it_pays_less():
    plan = _plan(
        method="degressive",
        rate=Decimal("20"),
        coefficient=Decimal("2.0"),
        initial=10_000_000,
        accepted=date(2025, 12, 10),
    )
    rows = dep.schedule(plan)
    by_year: dict[int, list] = {}
    for row in rows:
        by_year.setdefault(row.month.year, []).append(row)
    # 2026: 40% od 100 000 zł; 2027: 40% od netto 60 000,04 zł.
    assert {row.amount for row in by_year[2026]} == {333_333}
    assert all(row.degressive for row in by_year[2026] + by_year[2027])
    assert {row.amount for row in by_year[2027]} == {200_000}
    # 2028: 40% od 36 000,04 zł = 14 400 < 20 000 liniowo → liniowa (20% od 100 000).
    assert not any(row.degressive for row in by_year[2028])
    assert {row.amount for row in by_year[2028]} == {166_667}
    assert sum(row.amount for row in rows) == 10_000_000
    assert rows[-1].amount <= 166_667


def test_degressive_first_year_uses_initial_value_even_from_august():
    plan = _plan(
        method="degressive",
        rate=Decimal("20"),
        initial=1_200_000,
        accepted=date(2026, 7, 1),
    )
    rows = dep.schedule(plan)
    assert rows[0].month == date(2026, 8, 1)
    assert {row.amount for row in rows[:5]} == {40_000}  # 12 000 × 40% / 12
    january = dep.row_for(rows, date(2027, 1, 1))
    # Podstawa 2027 = 12 000 − 5 × 400 = 10 000 zł → 40% / 12 = 333,33 zł.
    assert january is not None and january.amount == 33_333


def test_degressive_improvement_adds_to_this_year_base():
    plan = _plan(
        method="degressive",
        rate=Decimal("20"),
        initial=1_200_000,
        accepted=date(2025, 12, 1),
        improvements=((date(2026, 3, 15), 600_000),),
    )
    rows = dep.schedule(plan)
    assert [row.amount for row in rows[:4]] == [40_000, 40_000, 40_000, 60_000]


def test_one_off_and_none():
    assert [row.amount for row in dep.schedule(_plan(method="one_off"))] == [3_690_000]
    assert dep.schedule(_plan(method="none")) == []
    assert dep.schedule(_plan(method="linear", rate=Decimal("0"))) == []


def test_opening_from_symfonia_continues_from_next_month():
    plan = _plan(
        initial=14_200_000,
        rate=Decimal("20"),
        accepted=date(2024, 9, 16),
        opening=Opening(month=date(2026, 10, 1), accumulated=5_916_675),
    )
    rows = dep.schedule(plan)
    assert rows[0].month == date(2026, 11, 1)
    assert rows[0].amount == 236_667 and rows[0].accumulated == 5_916_675 + 236_667
    assert rows[-1].accumulated == 14_200_000
    assert dep.accumulated_at(plan, rows, date(2026, 10, 1)) == 5_916_675


def test_opening_degressive_mid_year_uses_year_start_base():
    plan = _plan(
        method="degressive",
        rate=Decimal("20"),
        initial=1_200_000,
        accepted=date(2024, 5, 1),
        opening=Opening(
            month=date(2026, 10, 1), accumulated=700_000, year_start=600_000
        ),
    )
    rows = dep.schedule(plan)
    # Podstawa 2026 = 12 000 − 6 000 = 6 000 zł → 40% / 12 = 200 zł do grudnia.
    assert [row.amount for row in rows[:2]] == [20_000, 20_000]
    # 2027: netto 4 600 × 40% = 1 840 < 2 400 liniowo → liniowa 200 zł.
    assert not rows[2].degressive and rows[2].amount == 20_000


def test_fully_depreciated_opening_has_no_plan():
    plan = _plan(
        initial=2_800_000,
        rate=Decimal("50"),
        accepted=date(2024, 1, 15),
        opening=Opening(month=date(2026, 10, 1), accumulated=2_800_000),
    )
    assert dep.schedule(plan) == []


def test_until_stops_early_and_row_for_finds_the_month():
    rows = dep.schedule(_plan(), until=date(2026, 10, 15))
    assert _months(rows) == ["2026-08", "2026-09", "2026-10"]
    assert dep.row_for(rows, date(2026, 9, 30)).accumulated == 184_500
    assert dep.row_for(rows, date(2026, 7, 1)) is None


def test_add_months_crosses_years():
    assert dep.add_months(date(2026, 11, 1), 2) == date(2027, 1, 1)
    assert dep.add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
