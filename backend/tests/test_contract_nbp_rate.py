"""NBP snapshot contract used by the contract financial-rates card."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.models.fx_rate import FxRate
from app.services.fx_service import (
    _seconds_until_next_nbp_window,
    _should_refresh_nbp,
    get_rate_snapshot_to_pln,
)


class _Result:
    def __init__(self, row) -> None:
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Db:
    def __init__(self, row) -> None:
        self._row = row

    async def execute(self, *_args, **_kwargs):
        return _Result(self._row)


class _Rate:
    currency = "EUR"
    rate_to_pln = Decimal("4.301400")
    effective_date = date(2026, 8, 21)
    source = "NBP"


def test_fx_model_declares_unique_cache_index_for_create_all() -> None:
    cache_keys = {
        tuple(column.name for column in index.columns)
        for index in FxRate.__table__.indexes
        if index.unique
    }

    assert ("effective_date", "currency") in cache_keys


@pytest.mark.asyncio
async def test_snapshot_preserves_the_real_published_date_for_fallback() -> None:
    snapshot = await get_rate_snapshot_to_pln(
        _Db(_Rate()),  # type: ignore[arg-type]
        "eur",
        # Sunday: the newest persisted table is correctly still Friday's.
        date(2026, 8, 23),
    )

    assert snapshot is not None
    assert snapshot.currency == "EUR"
    assert snapshot.rate_to_pln == Decimal("4.301400")
    assert snapshot.effective_date == date(2026, 8, 21)
    assert snapshot.source == "NBP"


@pytest.mark.asyncio
async def test_snapshot_absence_never_becomes_a_fake_one_to_one_rate() -> None:
    assert (
        await get_rate_snapshot_to_pln(
            _Db(None),  # type: ignore[arg-type]
            "EUR",
            date(2026, 8, 26),
        )
        is None
    )


def test_refresh_scheduler_targets_today_before_the_publication_window() -> None:
    warsaw = ZoneInfo("Europe/Warsaw")
    now = datetime(2026, 8, 26, 8, 0, tzinfo=warsaw)

    assert _seconds_until_next_nbp_window(now) == 3.75 * 60 * 60


def test_restart_uses_existing_weekend_cache_without_calling_nbp() -> None:
    warsaw = ZoneInfo("Europe/Warsaw")
    saturday = datetime(2026, 8, 29, 9, 0, tzinfo=warsaw)

    assert _should_refresh_nbp(saturday, date(2026, 8, 28)) is False
    assert _should_refresh_nbp(saturday, None) is True


def test_refresh_is_due_after_publication_window_for_stale_business_day() -> None:
    warsaw = ZoneInfo("Europe/Warsaw")
    before_window = datetime(2026, 8, 26, 8, 0, tzinfo=warsaw)
    after_window = datetime(2026, 8, 26, 12, 15, tzinfo=warsaw)
    yesterday = date(2026, 8, 25)

    assert _should_refresh_nbp(before_window, yesterday) is False
    assert _should_refresh_nbp(after_window, yesterday) is True


def test_refresh_scheduler_skips_weekend() -> None:
    warsaw = ZoneInfo("Europe/Warsaw")
    friday_evening = datetime(2026, 8, 28, 17, 0, tzinfo=warsaw)

    seconds = _seconds_until_next_nbp_window(friday_evening)

    assert (
        friday_evening.timestamp() + seconds
        == datetime(2026, 8, 31, 11, 45, tzinfo=warsaw).timestamp()
    )


def test_refresh_scheduler_handles_dst_change_during_weekend() -> None:
    warsaw = ZoneInfo("Europe/Warsaw")
    friday_evening = datetime(2026, 3, 27, 17, 0, tzinfo=warsaw)

    seconds = _seconds_until_next_nbp_window(friday_evening)

    # Poland switches from UTC+1 to UTC+2 on Sunday. The elapsed time is one
    # hour shorter than the local wall-clock difference.
    assert seconds == 65.75 * 60 * 60
    assert (
        friday_evening.timestamp() + seconds
        == datetime(2026, 3, 30, 11, 45, tzinfo=warsaw).timestamp()
    )
