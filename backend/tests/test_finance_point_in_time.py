"""M7-P0.4 — finance is point-in-time, not "today under a historical label".

The finance endpoints took a ``period`` (and labelled the envelope with it) but
called ``finance_summary(db)`` / ``finance_clients(db)`` / ``client_finance(db,
id)`` with NO period — so they always returned the CURRENT active book. Ask for
January 2025, get today's numbers stamped "January 2025".

Fix: ``finance_as_of(period)`` derives the as-of date (last day of the period,
capped at today) and every finance function threads it into ``_active_contracts``
/ ``_sum_finance`` / ``_bench_and_utilization`` via ``on=``.

``finance_as_of`` is pure (unit-tested with constructed Periods). The
point-in-time query is tested against a real Postgres (CI runs migrations
first), scoped to a throwaway client so sibling rows in the shared CI DB can't
perturb the assertion.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.analytics.metrics import _active_contracts, client_finance, finance_as_of
from app.analytics.periods import Period, PeriodKind, resolve_period
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit

_TZ = ZoneInfo("Europe/Warsaw")


def test_finance_as_of_current_period_is_today() -> None:
    """A live month/quarter/year period resolves its as-of to today."""
    today = datetime.now(_TZ).date()
    for kind in (PeriodKind.month, PeriodKind.quarter, PeriodKind.year):
        period = resolve_period(kind)
        assert finance_as_of(period) == today, kind


def test_finance_as_of_historical_range_is_period_end() -> None:
    """A past custom range → the last day IN the range (end is half-open)."""
    period = Period(
        kind=PeriodKind.custom,
        start=datetime(2025, 1, 1, tzinfo=_TZ),
        end=datetime(2025, 2, 1, tzinfo=_TZ),  # half-open → January
    )
    assert finance_as_of(period) == date(2025, 1, 31)


def test_finance_as_of_never_in_the_future() -> None:
    """A range extending past today is capped at today."""
    today = datetime.now(_TZ).date()
    period = Period(
        kind=PeriodKind.custom,
        start=datetime(today.year, today.month, today.day, tzinfo=_TZ),
        end=datetime(today.year, today.month, today.day, tzinfo=_TZ)
        + timedelta(days=30),
    )
    assert finance_as_of(period) == today


async def _seed_past_contract():
    """A client whose only contract was active Jan–Jun 2025, then ended."""
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"FinPIT {u}")
        cand = Candidate(name="Fin", lastname=f"PIT-{u}")
        db.add_all([client, cand])
        await db.flush()
        # monthly_rate_client/monthly_margin are computed properties — seed the
        # stored fields. rate_unit=monthly → monthly_rate_client == rate_client.
        db.add(
            Contract(
                client_id=client.id,
                candidate_id=cand.id,
                status=ContractStatus.active,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 6, 30),
                rate_client=Decimal("10000"),
                rate_candidate=Decimal("8000"),
                rate_unit=RateUnit.monthly,
                currency="PLN",
            )
        )
        await db.commit()
        return client.id


async def test_active_contracts_is_point_in_time() -> None:
    cid = await _seed_past_contract()
    async with AsyncSessionLocal() as db:
        during = await _active_contracts(db, client_id=cid, on=date(2025, 3, 15))
        after = await _active_contracts(db, client_id=cid, on=date(2030, 1, 1))
        before = await _active_contracts(db, client_id=cid, on=date(2024, 1, 1))
    assert len(during) == 1, "contract must be active mid-term"
    assert len(after) == 0, (
        "contract ended 2025-06-30 — not active in 2030 (was 'today')"
    )
    assert len(before) == 0, "contract not started in 2024"


async def test_client_finance_point_in_time_mrr() -> None:
    cid = await _seed_past_contract()
    async with AsyncSessionLocal() as db:
        during, _, _ = await client_finance(db, cid, as_of=date(2025, 3, 15))
        after, _, _ = await client_finance(db, cid, as_of=date(2030, 1, 1))
    assert during["active_contracts"] == 1 and Decimal(during["mrr"]) == Decimal(
        "10000"
    )
    assert after["active_contracts"] == 0 and Decimal(after["mrr"]) == Decimal("0")
