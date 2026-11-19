"""Części kosztu zamówienia przy zmianie stawki Partnera w jego okresie — bez bazy.

Zgłoszenie 18.11.2026: zamówienie 01.07–15.12 z jedną stawką kosztu, a aneks
zmienił stawkę Partnera od 01.09 i od 01.11. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.models.contract import RateUnit
from app.services import order_cost_steps as ocs
from app.services import order_cost_steps_schema as schema


class _Contract(SimpleNamespace):
    def effective_candidate_rate(self, on: date):
        current = None
        for step in sorted(
            self.candidate_rate_schedule, key=lambda s: s.effective_from
        ):
            if step.effective_from <= on:
                current = step.rate
        if current is None and self.candidate_rate_schedule:
            current = min(
                self.candidate_rate_schedule, key=lambda s: s.effective_from
            ).rate
        return current if current is not None else self.rate_candidate


def _contract(*steps: tuple[date, str], unit=RateUnit.hourly):
    return _Contract(
        rate_unit=unit,
        billing_hours_per_month=168,
        rate_candidate=None,
        resolved_rate_candidate_currency="PLN",
        candidate_rate_schedule=[
            SimpleNamespace(effective_from=d, rate=Decimal(r)) for d, r in steps
        ],
    )


def _order(start=date(2026, 7, 1), end=date(2026, 12, 15), rate="140", **over):
    base = dict(
        id=11,
        start_date=start,
        end_date=end,
        rate_unit=RateUnit.hourly,
        rate_candidate=Decimal(rate) if rate is not None else None,
        billing_hours_per_month=168,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _step(day: date, rate: str):
    return SimpleNamespace(effective_from=day, rate_candidate=Decimal(rate))


NORDEA = _contract(
    (date(2022, 10, 3), "120"), (date(2026, 9, 1), "130"), (date(2026, 11, 1), "140")
)


def test_order_spanning_two_changes_gets_three_parts():
    parts = ocs.contract_parts(NORDEA, _order())
    assert parts == [
        (date(2026, 7, 1), Decimal("120.000")),
        (date(2026, 9, 1), Decimal("130.000")),
        (date(2026, 11, 1), Decimal("140.000")),
    ]
    assert ocs.steps_for(parts) == parts


def test_order_without_change_in_its_period_has_no_rows():
    parts = ocs.contract_parts(NORDEA, _order(start=date(2026, 11, 1)))
    assert parts == [(date(2026, 11, 1), Decimal("140.000"))]
    assert ocs.steps_for(parts) == []


def test_change_after_order_end_is_ignored_and_change_on_end_day_counts():
    order = _order(start=date(2026, 7, 1), end=date(2026, 8, 31))
    assert ocs.steps_for(ocs.contract_parts(NORDEA, order)) == []
    order = _order(start=date(2026, 7, 1), end=date(2026, 9, 1))
    assert len(ocs.contract_parts(NORDEA, order)) == 2


def test_step_with_the_same_rate_does_not_split():
    contract = _contract((date(2026, 1, 1), "120"), (date(2026, 9, 1), "120"))
    assert ocs.steps_for(ocs.contract_parts(contract, _order())) == []


def test_daily_order_converts_hourly_contract_rate():
    parts = ocs.contract_parts(NORDEA, _order(rate_unit=RateUnit.daily))
    assert [r for _, r in parts] == [
        Decimal("960.000"),
        Decimal("1040.000"),
        Decimal("1120.000"),
    ]


def test_order_without_start_or_unit_gives_nothing():
    assert ocs.contract_parts(NORDEA, _order(start=None)) == []
    assert ocs.contract_parts(NORDEA, _order(rate_unit=None)) == []
    assert (
        ocs.contract_parts(NORDEA, _order(start=date(2026, 9, 1), end=date(2026, 8, 1)))
        == []
    )


def test_rate_on_uses_parts_and_falls_back_to_the_column():
    order = _order()
    own = [_step(date(2026, 7, 1), "120"), _step(date(2026, 9, 1), "130")]
    assert ocs.rate_on(order, own, date(2026, 8, 1)) == Decimal("120")
    assert ocs.rate_on(order, own, date(2026, 10, 1)) == Decimal("130")
    assert ocs.rate_on(order, [], date(2026, 10, 1)) == Decimal("140")


def test_completed_order_with_old_cost_lists_every_month_after_the_change():
    # Zamówienie za październik ze stawką sprzed aneksu od 01.09 (PFRON, 18.11).
    contract = _contract((date(2026, 7, 1), "150"), (date(2026, 9, 1), "120"))
    order = _order(start=date(2026, 10, 1), end=date(2026, 10, 31), rate="150")
    found = ocs.correction_for(order, contract, [])
    assert found is not None
    assert [m["month"] for m in found.months] == ["2026-10"]
    assert found.months[0]["diff"] == Decimal("-30.000")
    assert found.estimate == Decimal("-30.000") * 168


def test_completed_order_spanning_a_change_lists_only_months_that_differ():
    order = _order(rate="140")
    found = ocs.correction_for(order, NORDEA, [])
    assert [m["month"] for m in found.months] == [
        "2026-07",
        "2026-08",
        "2026-09",
        "2026-10",
    ]
    assert found.in_contract[-1] == (date(2026, 11, 1), Decimal("140.000"))


def test_order_matching_its_parts_is_not_a_correction():
    order = _order(rate="140")
    own = [
        _step(date(2026, 7, 1), "120"),
        _step(date(2026, 9, 1), "130"),
        _step(date(2026, 11, 1), "140"),
    ]
    assert ocs.correction_for(order, NORDEA, own) is None


def test_mid_month_start_prices_its_first_month_from_the_start_day():
    contract = _contract((date(2026, 1, 1), "100"), (date(2026, 10, 10), "110"))
    order = _order(start=date(2026, 10, 5), end=date(2026, 11, 30), rate="100")
    found = ocs.correction_for(order, contract, [])
    # 05.10 jeszcze 100 (zgodne), listopad już 110.
    assert [m["month"] for m in found.months] == ["2026-11"]


def test_signature_changes_with_the_schedule():
    a = ocs.signature([(date(2026, 7, 1), Decimal("120"))])
    b = ocs.signature([(date(2026, 7, 1), Decimal("120.000"))])
    c = ocs.signature([(date(2026, 7, 1), Decimal("125"))])
    assert a == b and a != c


def test_parts_label_closes_each_part_the_day_before_the_next():
    rows = ocs.parts_label(
        [(date(2026, 7, 1), Decimal("120")), (date(2026, 9, 1), Decimal("130"))],
        date(2026, 12, 15),
    )
    assert rows[0]["to"] == date(2026, 8, 31)
    assert rows[1]["to"] == date(2026, 12, 15)


def test_schema_checks_match_the_model():
    from app.models.client_order_cost_step import ClientOrderCostStep

    checks = {
        c.name: str(c.sqltext)
        for c in ClientOrderCostStep.__table__.constraints
        if c.name and c.name.startswith("ck_")
    }
    ddl = " ".join(schema.TABLE_DDL)
    for name in checks:
        assert name in ddl
    assert "source IN ('contract', 'finance')" in ddl
