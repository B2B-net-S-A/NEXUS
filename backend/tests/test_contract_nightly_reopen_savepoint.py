"""Runda 9 (R9-V1-1): odmowa wznowienia kontraktu nie wywraca nocnego skanu.

Runda 8 dołożyła 422 w `reopen_contract` dla kontraktu klienta usuniętego albo
scalonego. Nocne przebiegi (`reconcile_contracts_to_live_orders`,
`materialize_scheduled_order_groups`) wołały go bez savepointu, więc jedna
odmowa wycofywała cały skan wygasania.
"""

from __future__ import annotations

import contextlib
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import contract_lifecycle as cl

pytestmark = pytest.mark.asyncio


class _Db:
    def __init__(self) -> None:
        self.savepoints = 0

    @contextlib.asynccontextmanager
    async def _nested(self):
        self.savepoints += 1
        yield

    def begin_nested(self):
        return self._nested()


async def test_refused_reopen_is_skipped_not_raised(monkeypatch) -> None:
    async def refuse(*_a, **_kw):
        raise HTTPException(status_code=422, detail={"code": "client_merged"})

    monkeypatch.setattr(cl, "sync_contract_to_live_order", refuse)
    db = _Db()
    assert (
        await cl.sync_contract_to_live_order_nightly(
            db,
            SimpleNamespace(id=7),
            order_start=date(2026, 9, 1),
            order_end=None,
            today=date(2026, 9, 27),
        )
        is False
    )
    assert db.savepoints == 1


async def test_successful_reopen_passes_through(monkeypatch) -> None:
    async def ok(*_a, **kw):
        assert kw["actor_id"] is None
        return True

    monkeypatch.setattr(cl, "sync_contract_to_live_order", ok)
    assert await cl.sync_contract_to_live_order_nightly(
        _Db(),
        SimpleNamespace(id=7),
        order_start=None,
        order_end=None,
        today=date(2026, 9, 27),
    )


def test_nightly_callers_use_the_savepoint_wrapper() -> None:
    import inspect

    from app.services import order_group_lifecycle as ogl

    for fn in (
        cl.reconcile_contracts_to_live_orders,
        ogl.materialize_scheduled_order_groups,
    ):
        src = inspect.getsource(fn)
        assert "sync_contract_to_live_order_nightly(" in src
        assert "await sync_contract_to_live_order(" not in src
