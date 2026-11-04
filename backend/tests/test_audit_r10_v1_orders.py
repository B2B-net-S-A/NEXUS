"""Runda 10 audytu — „Przywróć” zamówienia MD/kosztowego (R10-V1-3).

Testy z bazą zakładają dane przez ``_seed`` z ``test_order_line_takeover``
(zamówienie MD per osoba: Konrad + Kamila).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.scheduling import business_today
from app.models.client_order import ClientOrderStatus


def _group_url(seed: dict, suffix: str = "") -> str:
    return f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}{suffix}"


async def _close_md_group_cut_to_today(seed: dict, previous_end) -> None:
    """Zamówienie MD zamknięte ręcznie dziś; linia była aktywna do ``previous_end``."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.client_order_group import (
        GROUP_STATUS_COMPLETED,
        ClientOrderGroup,
        ClientOrderGroupEvent,
    )
    from app.services.multi_consultant_orders import EVENT_ORDER_CLOSED

    today = business_today()
    async with AsyncSessionLocal() as db:
        group = await db.get(ClientOrderGroup, seed["group_id"])
        group.status = GROUP_STATUS_COMPLETED
        group.closure_date = today
        group.closure_reason = "Test R10"
        line = await db.get(ClientOrder, seed["line_id"])
        line.status = ClientOrderStatus.completed
        line.end_date = today
        db.add(
            ClientOrderGroupEvent(
                group_id=group.id,
                event_type=EVENT_ORDER_CLOSED,
                description="Zakończono zamówienie (test R10)",
                payload={
                    "lines": [
                        {
                            "id": line.id,
                            "previous_status": "active",
                            "previous_end_date": previous_end.isoformat(),
                        }
                    ]
                },
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_reopen_keeps_the_cut_end_date_of_a_line_of_a_void_contract(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Linia unieważnionej umowy nie wraca — data końca też nie (brak
    fałszywego „przedłużenia” w Finanse → Zmiany)."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.order_change_event import OrderChangeEvent
    from tests.test_audit_r8_md_orders import _end_contract
    from tests.test_audit_r9_money import _close_group_as_cost_order
    from tests.test_order_line_takeover import _enable_multi, _seed

    seed = await _seed(source_state="leaving", with_case=False)
    _enable_multi(monkeypatch, seed["client_id"])
    await _close_group_as_cost_order(seed)
    today = business_today()
    async with AsyncSessionLocal() as db:
        # zamknięcie przycięło linię do dnia zakończenia
        line = await db.get(ClientOrder, seed["line_id"])
        line.end_date = today
        await db.commit()
    await _end_contract(seed["konrad_contract_id"], "void", None)

    async def _change_ids() -> set[int]:
        async with AsyncSessionLocal() as db:
            return set(
                (
                    await db.scalars(
                        select(OrderChangeEvent.id).where(
                            OrderChangeEvent.order_id == seed["line_id"]
                        )
                    )
                ).all()
            )

    # przygotowanie danych samo zapisuje zmiany w dzienniku — liczymy nowe
    before = await _change_ids()
    resp = await app_client.post(_group_url(seed, "/reopen"), headers=app_auth_headers)
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, seed["line_id"])
    assert line.status == ClientOrderStatus.completed
    assert line.end_date == today
    assert await _change_ids() == before


@pytest.mark.asyncio
async def test_reopen_sends_an_md_line_of_an_ended_contract_through_offboarding(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Linia MD z pulą na zakończonej umowie dostaje sprawę o puli — tak
    jak w „Przywróć anulowane”."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.client_order_offboarding import (
        OFFBOARDING_STATUS_PENDING,
        ClientOrderOffboardingCase,
    )
    from tests.test_audit_r8_md_orders import _end_contract
    from tests.test_order_line_takeover import _enable_multi, _seed

    seed = await _seed(source_state="leaving", with_case=False)
    _enable_multi(monkeypatch, seed["client_id"])
    today = business_today()
    await _close_md_group_cut_to_today(seed, today + timedelta(days=30))
    yesterday = today - timedelta(days=1)
    await _end_contract(seed["konrad_contract_id"], "ended", yesterday)

    resp = await app_client.post(_group_url(seed, "/reopen"), headers=app_auth_headers)
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, seed["line_id"])
        cases = (
            await db.scalars(
                select(ClientOrderOffboardingCase).where(
                    ClientOrderOffboardingCase.order_id == seed["line_id"]
                )
            )
        ).all()
    assert line.status == ClientOrderStatus.completed
    assert line.end_date == yesterday
    assert [case.status for case in cases] == [OFFBOARDING_STATUS_PENDING]


@pytest.mark.asyncio
async def test_reopen_still_restores_the_end_date_of_a_returning_md_line(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Linia, która wraca na obsadę, odzyskuje datę sprzed zakończenia."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from tests.test_order_line_takeover import _enable_multi, _seed

    seed = await _seed(source_state="leaving", with_case=False)
    _enable_multi(monkeypatch, seed["client_id"])
    previous_end = business_today() + timedelta(days=30)
    await _close_md_group_cut_to_today(seed, previous_end)

    resp = await app_client.post(_group_url(seed, "/reopen"), headers=app_auth_headers)
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, seed["line_id"])
    assert line.status == ClientOrderStatus.active
    assert line.end_date == previous_end
