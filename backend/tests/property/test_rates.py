"""Generated regressions for document rates and the order/contract unit boundary."""

from decimal import Decimal

from hypothesis import given, strategies as st

from app.models.contract import RateUnit
from app.services.champion_intake import document_rate, pln_hourly_bounds
from app.services.order_rate_snapshots import CONTRACT_RATE_SCALE, convert_order_rate


@given(
    low=st.integers(1, 1000),
    spread=st.integers(1, 999),
    separator=st.sampled_from(["-", "–", "—", "/", " do "]),
    suffix=st.sampled_from([" zł/h", " PLN / h", " zł netto/h", " zł/h (netto, B2B)"]),
)
def test_document_budget_keeps_upper_bound(low, spread, separator, suffix):
    high = low + spread
    text = f"{low}{separator}{high}{suffix}"
    assert pln_hourly_bounds(text) == (low, high)
    assert document_rate(text) == (high, True)


@given(
    amount=st.integers(1, 1999),
    suffix=st.sampled_from(
        [" EUR/h", " USD/h", " zł/MD", " zł/miesiąc", " zł brutto/h"]
    ),
)
def test_foreign_unit_or_gross_amount_cannot_become_pln_hourly_budget(amount, suffix):
    assert document_rate(f"{amount}{suffix}") is None


@given(md_mills=st.integers(1, 10_000_000))
def test_md_to_contract_hourly_and_back_preserves_every_mill(md_mills):
    md = Decimal(md_mills) / 1000
    hourly = convert_order_rate(
        md, RateUnit.daily, RateUnit.hourly, scale=CONTRACT_RATE_SCALE
    )
    assert hourly * 8 == md
    assert convert_order_rate(hourly, RateUnit.hourly, RateUnit.daily) == md


@given(cents=st.integers(1, 200_000), hours=st.integers(80, 240))
def test_monthly_conversion_uses_agreed_hours_not_a_fixed_md_bridge(cents, hours):
    hourly = Decimal(cents) / 100
    monthly = convert_order_rate(hourly, RateUnit.hourly, RateUnit.monthly, hours)
    assert monthly == hourly * hours
    assert (
        convert_order_rate(monthly, RateUnit.monthly, RateUnit.hourly, hours) == hourly
    )
