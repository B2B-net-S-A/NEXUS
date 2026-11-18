"""Szkic zamówienia po zatrudnieniu dostaje typ, w którym klient się rozlicza.

Zgłoszenie 18.11.2026 (BNP 4643_2026): przy potwierdzeniu podpisu umowy hook
założył szkic „Okresowe”, bo brał typ OSTATNIO założonego zamówienia klienta.
U klienta rozliczanego w MD (50 z 51 zamówień) powstało aktywne zamówienie
okresowe bez budżetu MD i bez zużycia z importów. Hook bierze teraz typ
najczęstszy (`most_common_order_type`), jak okno „Nowe zamówienie”.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.order_type import OrderType
from app.services import b2b_contract_automation as automation
from app.services import contract_lifecycle


def _db_without_open_orders() -> MagicMock:
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    return db


@pytest.fixture
def hook(monkeypatch):
    monkeypatch.setattr(
        automation, "has_open_group_line", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(automation, "should_auto_create_order", lambda _client_id: True)
    monkeypatch.setattr(contract_lifecycle, "lock_contract_then_orders", AsyncMock())
    monkeypatch.setattr(automation, "_notify_new_contractor_draft", AsyncMock())
    monkeypatch.setattr(automation, "inherited_order_rate_fields", lambda _contract: {})
    # Ostatnio założone zamówienie klienta jest okresowe (jak u BNP 29.09).
    monkeypatch.setattr(
        automation,
        "suggested_order_type",
        AsyncMock(return_value=OrderType.periodic),
        raising=False,
    )
    return monkeypatch


async def _draft(job_client_id: int):
    db = _db_without_open_orders()
    contract = SimpleNamespace(id=677, start_date=date(2026, 10, 5))
    candidate = SimpleNamespace(id=1, name="Jan", lastname="Testowy")
    job = SimpleNamespace(id=9, client_id=job_client_id, title="Architekt")
    order, created, skipped = await automation._ensure_open_order(
        db,
        contract=contract,
        candidate=candidate,
        job=job,
        actor_id=90,
        source="signed_generated_contract",
    )
    assert (created, skipped) == (True, None)
    return order


@pytest.mark.asyncio
async def test_draft_takes_the_clients_usual_type_not_the_latest(hook):
    # Klient rozlicza się w MD — szkic ma być MD mimo ostatniego okresowego.
    hook.setattr(
        automation,
        "most_common_order_type",
        AsyncMock(return_value=OrderType.md),
        raising=False,
    )
    order = await _draft(job_client_id=999_001)

    assert order.order_type == OrderType.md.value
    # Szkic MD czeka na prawdziwy numer, nie dostaje tytułu-imienia.
    assert order.title == "(bez numeru)"


@pytest.mark.asyncio
async def test_periodic_client_still_gets_a_periodic_draft(hook):
    hook.setattr(
        automation,
        "most_common_order_type",
        AsyncMock(return_value=OrderType.periodic),
        raising=False,
    )
    order = await _draft(job_client_id=999_002)

    assert order.order_type == OrderType.periodic.value
    assert order.title == "Jan Testowy — Architekt"
