"""KPI tygodniowe Sprzedaży — definicje z Atlasa bez bazy (``services/sales/kpi.py``).

Deduplikacja spotkań, światła, tygodnie i miesiące w kalendarzu firmy
(przełom miesiąca, zmiana czasu), body leasing poza krzywą WON MRR.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.core.scheduling import local_day_start_utc
from app.services.sales.kpi import (
    _bucket,
    dedup_count,
    is_body_leasing,
    light,
    net_mrr,
    recent_weeks,
    week_start,
)


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def test_meetings_within_15_minutes_of_the_previous_count_once() -> None:
    # Łańcuch 10:00 → 10:10 → 10:24: każdy krok ≤ 15 min, jedno spotkanie
    # (jak w Atlasie: odstęp od poprzedniego, nie od początku grupy).
    chain = [_at("2026-10-27T10:00"), _at("2026-10-27T10:24"), _at("2026-10-27T10:10")]
    assert dedup_count(chain) == 1
    assert dedup_count([_at("2026-10-27T10:00"), _at("2026-10-27T10:15")]) == 1
    assert dedup_count([_at("2026-10-27T10:00"), _at("2026-10-27T10:16")]) == 2
    assert dedup_count([]) == 0


def test_traffic_light_green_at_target_yellow_from_half_red_below() -> None:
    assert light(4, 4) == "green"
    assert light(5, 4) == "green"
    assert light(2, 4) == "yellow"
    assert light(2, 3) == "yellow"  # 2 × 2 ≥ 3
    assert light(1, 3) == "red"
    assert light(0, 1) == "red"
    # Bez celu nie ma światła (Atlas pokazywał wtedy zielone).
    assert light(0, 0) is None
    assert light(3, 0) is None


def test_weeks_start_on_monday_and_cross_the_month_boundary() -> None:
    # Niedziela 01.11 należy do tygodnia od poniedziałku 26.10.
    assert week_start(date(2026, 11, 1)) == date(2026, 10, 26)
    assert recent_weeks(date(2026, 11, 1), 3) == [
        date(2026, 10, 12),
        date(2026, 10, 19),
        date(2026, 10, 26),
    ]
    assert recent_weeks(date(2026, 11, 2), 2) == [date(2026, 10, 26), date(2026, 11, 2)]
    assert recent_weeks(date(2027, 1, 1), 1) == [date(2026, 12, 28)]


def test_week_bounds_are_warsaw_midnight_not_utc() -> None:
    # 26.10.2026 to dzień po zmianie czasu — północ w Warszawie to 23:00 UTC.
    assert local_day_start_utc(date(2026, 10, 26)) == _at("2026-10-25T23:00")
    assert local_day_start_utc(date(2026, 10, 19)) == _at("2026-10-18T22:00")


def test_events_are_bucketed_by_the_company_calendar() -> None:
    mondays = {date(2026, 10, 19), date(2026, 10, 26)}
    rows = [
        # Niedziela 25.10 23:30 UTC = poniedziałek 26.10 00:30 w Warszawie.
        (1, _at("2026-10-25T23:30")),
        # Niedziela 25.10 22:30 UTC = 23:30 w Warszawie — jeszcze stary tydzień.
        (1, _at("2026-10-25T22:30")),
        # Sobota 31.10 23:30 UTC = niedziela 01.11 w Warszawie — ten sam tydzień.
        (1, _at("2026-10-31T23:30")),
        # Poza oknem i bez opiekuna — pomijane.
        (1, _at("2026-11-01T23:30")),
        (None, _at("2026-10-27T10:00")),
    ]
    buckets = _bucket(rows, mondays)
    assert len(buckets[(1, date(2026, 10, 26))]) == 2
    assert len(buckets[(1, date(2026, 10, 19))]) == 1
    assert set(buckets) == {(1, date(2026, 10, 19)), (1, date(2026, 10, 26))}


def test_body_leasing_is_out_of_the_won_mrr_curve() -> None:
    assert is_body_leasing("bodyleasing", [])
    assert is_body_leasing(None, ["Body leasing"])
    assert not is_body_leasing("subscription", ["Body"])
    assert not is_body_leasing(None, None)


def test_net_mrr_is_mrr_times_margin() -> None:
    assert net_mrr(Decimal("1000"), Decimal("20")) == Decimal("200")
    assert net_mrr(Decimal("1000"), None) == Decimal("0")
    assert net_mrr(None, Decimal("20")) == Decimal("0")


def test_recent_weeks_count_is_respected() -> None:
    weeks = recent_weeks(date(2026, 10, 28), 8)
    assert len(weeks) == 8
    assert weeks[-1] == date(2026, 10, 26)
    assert all(b - a == timedelta(weeks=1) for a, b in zip(weeks, weeks[1:]))
