"""Focused regression tests for the current client-order projection."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.api import contracts


@pytest.mark.asyncio
async def test_current_order_projection_filters_period_status_and_overlap(monkeypatch):
    today = date(2026, 8, 26)
    monkeypatch.setattr(contracts, "business_today", lambda: today)

    result = SimpleNamespace(
        all=lambda: [
            (11, date(2026, 9, 30)),
            (12, None),
        ]
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    projected = await contracts._latest_order_end_dates(db, [11, 12, 13])

    assert projected == {11: date(2026, 9, 30), 12: None}
    statement = db.execute.await_args.args[0]
    sql = " ".join(
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        .lower()
        .split()
    )

    assert "client_orders.status = 'active'" in sql
    assert "client_orders.start_date <= '2026-08-26'" in sql
    assert "client_orders.end_date is null" in sql
    assert "client_orders.end_date >= '2026-08-26'" in sql
    # A contract with two overlapping current active orders is omitted from
    # the grouped result instead of getting an arbitrary MAX(end_date).
    assert "having count(client_orders.id) = 1" in sql


@pytest.mark.asyncio
async def test_current_order_projection_skips_query_for_empty_scope():
    db = SimpleNamespace(execute=AsyncMock())

    assert await contracts._latest_order_end_dates(db, []) == {}
    db.execute.assert_not_awaited()
