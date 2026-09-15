"""Calendar partition properties, including real midnight and DST boundaries."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from hypothesis import example, given, strategies as st
import time_machine

from app.core.scheduling import (
    business_today,
    local_day_bounds,
    local_month_bounds,
    local_quarter_bounds,
)

WARSAW = ZoneInfo("Europe/Warsaw")
DAYS = st.dates(min_value=date(2000, 1, 1), max_value=date(2040, 12, 31))


@given(day=DAYS)
@example(day=date(2026, 3, 29))
@example(day=date(2026, 10, 25))
@example(day=date(2024, 2, 29))
def test_day_and_month_partitions_preserve_local_date(day):
    noon = datetime.combine(day, time(12), tzinfo=WARSAW)
    bounds = local_day_bounds(noon)
    assert bounds.start_utc <= noon <= bounds.end_utc
    assert bounds.start_utc.astimezone(WARSAW).date() == day
    assert bounds.end_utc.astimezone(WARSAW).date() == day
    following = local_day_bounds(noon + timedelta(days=1))
    assert bounds.end_utc + timedelta(microseconds=1) == following.start_utc
    month = local_month_bounds(day)
    assert month.start_utc <= bounds.start_utc < month.end_utc
    assert month.start_utc.astimezone(WARSAW).day == 1
    assert (
        local_month_bounds(month.end_utc.astimezone(WARSAW).date()).start_utc
        == month.end_utc
    )
    quarter = local_quarter_bounds(day)
    assert quarter.start_utc <= month.start_utc < month.end_utc <= quarter.end_utc


@given(day=DAYS)
def test_business_today_reads_warsaw_midnight_not_utc_calendar(day):
    local_midnight = datetime.combine(day, time(0, 30), tzinfo=WARSAW)
    assert local_midnight.astimezone(timezone.utc).date() == day - timedelta(days=1)
    with time_machine.travel(local_midnight, tick=False):
        assert business_today() == day
