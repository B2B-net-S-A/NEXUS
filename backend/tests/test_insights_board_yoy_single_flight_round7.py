"""Runda 7 (R7-N10-6): tabele rok-do-roku liczy jeden wykonawca, a wyceny
kontraktów idą w wątku (CPU, nie baza)."""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.api import insights_board as board_api
from app.core import cache as cache_module
from app.core.rate_limit import limiter
from app.models.user import UserRole
from app.services import insights_board_yoy


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/insights/board/yoy",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1),
        }
    )


@pytest.mark.asyncio
async def test_parallel_requests_compute_the_grid_once(monkeypatch) -> None:
    cache_module._cache.clear()
    limiter.enabled = False
    calls = 0

    async def _compute(_db, years, today):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"years": years, "metrics": []}

    monkeypatch.setattr(board_api, "compute_board_yoy", _compute)
    admin = SimpleNamespace(has_any_role=lambda *roles: UserRole.admin in roles)

    try:
        first, second = await asyncio.gather(
            board_api.insights_board_yoy(_request(), admin, None, None, 3),
            board_api.insights_board_yoy(_request(), admin, None, None, 3),
        )
    finally:
        limiter.enabled = True
        cache_module._cache.clear()

    assert calls == 1
    assert first == second


def test_money_snapshots_are_folded_off_the_event_loop_thread() -> None:
    import inspect

    source = inspect.getsource(insights_board_yoy.compute_board_yoy)
    assert "asyncio.to_thread(" in source
    assert "_fold_valued_slots" in source
    # Pętla po miesiącach czyta gotowe zdjęcia — sama nie wycenia kontraktów.
    assert "fold_money(" not in source


def test_fold_helper_values_every_slot(monkeypatch) -> None:
    monkeypatch.setattr(
        insights_board_yoy, "fold_money", lambda contracts, asof, rates: asof
    )
    slots = [
        SimpleNamespace(asof=date(2026, 1, 31)),
        SimpleNamespace(asof=date(2026, 2, 28)),
    ]

    folds = insights_board_yoy._fold_valued_slots([], slots, {})

    assert folds == {slot.asof: slot.asof for slot in slots}
