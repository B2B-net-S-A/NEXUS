"""Core nowego typu zamówienia Cyfrowego Polsatu (bez parsera Finansów)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today
from app.models.client_order import ClientOrderStatus
from app.services.cyfrowy_polsat_orders import CYFROWY_POLSAT_CLIENT_ID


_TODAY = business_today()


async def _seed_cyfrowy_polsat_contracts(count: int = 2) -> list[int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = await db.get(Client, CYFROWY_POLSAT_CLIENT_ID)
        if client is None:
            client = Client(
                id=CYFROWY_POLSAT_CLIENT_ID,
                name="Cyfrowy Polsat S.A.",
                legal_name="Cyfrowy Polsat S.A.",
            )
            db.add(client)
            await db.flush()

        contract_ids: list[int] = []
        for index in range(count):
            candidate = Candidate(
                name=f"CP{index}",
                lastname=f"Tester-{suffix}",
                email=f"cp-md-{suffix}-{index}@example.com",
            )
            db.add(candidate)
            await db.flush()
            contract = Contract(
                candidate_id=candidate.id,
                client_id=CYFROWY_POLSAT_CLIENT_ID,
                status=ContractStatus.active,
                start_date=_TODAY - timedelta(days=30),
                rate_candidate=Decimal("100.000"),
                rate_client=Decimal("150.000"),
            )
            db.add(contract)
            await db.flush()
            contract_ids.append(contract.id)
        await db.commit()
    return contract_ids


def _shared_line(contract_id: int, *, start_date=None) -> dict:
    return {
        "contract_id": contract_id,
        "rate_cost": 1000,
        "rate_revenue": 1200,
        "start_date": (start_date or (_TODAY - timedelta(days=10))).isoformat(),
    }


async def _create_shared_group(
    app_client: AsyncClient,
    headers: dict,
    contract_id: int,
    *,
    total: int = 40,
) -> dict:
    response = await app_client.post(
        f"/api/clients/{CYFROWY_POLSAT_CLIENT_ID}/order-groups",
        json={
            "order_number": f"CP-{uuid.uuid4().hex[:8]}",
            "start_date": (_TODAY - timedelta(days=10)).isoformat(),
            "is_md_budget_based": True,
            "md_budget_total": total,
            "lines": [_shared_line(contract_id)],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_cyfrowy_polsat_capabilities_do_not_disable_standard_order_policy(
    monkeypatch,
):
    from app.services import cost_orders, multi_consultant_orders
    from app.services.b2b_contract_automation import should_auto_create_order

    monkeypatch.setattr(cost_orders, "cost_order_client_ids", lambda: frozenset({15}))
    monkeypatch.setattr(
        multi_consultant_orders,
        "multi_consultant_client_ids",
        lambda: frozenset({15}),
    )

    assert cost_orders.is_cost_order_client(CYFROWY_POLSAT_CLIENT_ID) is True
    assert (
        multi_consultant_orders.is_multi_consultant_client(CYFROWY_POLSAT_CLIENT_ID)
        is True
    )
    assert should_auto_create_order(CYFROWY_POLSAT_CLIENT_ID) is True
    assert (
        cost_orders.skips_standard_order_group_materialization(CYFROWY_POLSAT_CLIENT_ID)
        is True
    )
    assert (
        cost_orders.hides_standard_drafts_from_order_group_registry(
            CYFROWY_POLSAT_CLIENT_ID
        )
        is True
    )

    # Polkomtel zachowuje wszystkie dotychczasowe wyłączenia.
    assert cost_orders.is_cost_order_client(15) is True
    assert should_auto_create_order(15) is False
    assert cost_orders.skips_standard_order_group_materialization(15) is True
    assert cost_orders.hides_standard_drafts_from_order_group_registry(15) is True


@pytest.mark.asyncio
async def test_cyfrowy_polsat_standard_order_is_not_materialized_as_a_group():
    from app.services.order_group_materializer import (
        materialize_group_for_activated_order,
    )

    order = SimpleNamespace(
        status=ClientOrderStatus.active,
        order_group_id=None,
        client_id=CYFROWY_POLSAT_CLIENT_ID,
    )
    result = await materialize_group_for_activated_order(
        None, order, actor_id=None, candidate_rate=None
    )
    assert result is None
    assert order.order_group_id is None


@pytest.mark.asyncio
async def test_shared_md_continuation_waits_for_the_group_budget():
    from app.models.client_order_group import GROUP_STATUS_ACTIVE
    from app.services.order_group_lifecycle import _predecessor_still_has_md

    predecessor = SimpleNamespace(
        id=41,
        status=GROUP_STATUS_ACTIVE,
        is_cost_based=False,
        is_md_budget_based=True,
        md_budget_remaining=Decimal("2.500000"),
    )
    continuation = SimpleNamespace(predecessor_group_id=predecessor.id)

    # Dla wspólnej puli decyzja pochodzi z grupy; baza nie powinna być pytana
    # o nieistniejące budżety per linia.
    assert (
        await _predecessor_still_has_md(
            None, continuation, {predecessor.id: predecessor}
        )
        is True
    )
    predecessor.md_budget_remaining = Decimal("0")
    assert (
        await _predecessor_still_has_md(
            None, continuation, {predecessor.id: predecessor}
        )
        is False
    )


@pytest.mark.asyncio
async def test_client_api_exposes_all_cyfrowy_polsat_order_capabilities(
    app_client: AsyncClient, app_auth_headers: dict
):
    await _seed_cyfrowy_polsat_contracts(0)

    response = await app_client.get(
        f"/api/clients/{CYFROWY_POLSAT_CLIENT_ID}", headers=app_auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["multi_consultant_orders_enabled"] is True
    assert body["cost_orders_enabled"] is True
    assert body["cyfrowy_polsat_order_types_enabled"] is True


@pytest.mark.asyncio
async def test_cyfrowy_polsat_group_requires_exactly_cost_or_shared_md(
    app_client: AsyncClient, app_auth_headers: dict
):
    await _seed_cyfrowy_polsat_contracts(0)
    url = f"/api/clients/{CYFROWY_POLSAT_CLIENT_ID}/order-groups"
    base = {
        "order_number": f"CP-{uuid.uuid4().hex[:8]}",
        "start_date": _TODAY.isoformat(),
        "lines": [],
    }

    neither = await app_client.post(url, json=base, headers=app_auth_headers)
    assert neither.status_code == 422, neither.text
    assert "dokładnie jeden typ" in neither.text

    both = await app_client.post(
        url,
        json={
            **base,
            "is_cost_based": True,
            "budget_amount": 1000,
            "is_md_budget_based": True,
            "md_budget_total": 10,
        },
        headers=app_auth_headers,
    )
    assert both.status_code == 422, both.text


@pytest.mark.asyncio
async def test_shared_md_settlement_floors_exhausts_blocks_and_reopens(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroup
    from app.services.shared_md_orders import upsert_shared_md_consumption

    first_contract, second_contract = await _seed_cyfrowy_polsat_contracts(2)
    created = await _create_shared_group(
        app_client, app_auth_headers, first_contract, total=10
    )
    assert created["is_cost_based"] is False
    assert created["is_md_budget_based"] is True
    assert created["md_budget_total"] == pytest.approx(10)
    assert created["md_budget_used"] == pytest.approx(0)
    assert created["md_budget_remaining"] == pytest.approx(10)
    assert created["lines"][0]["md_total"] is None

    async with AsyncSessionLocal() as db:
        group = await db.get(ClientOrderGroup, created["id"])
        assert group is not None
        await upsert_shared_md_consumption(
            db,
            group=group,
            period_month="2026-07",
            md_reported=Decimal("13"),
            source="manual",
        )
        await db.commit()

    listing = await app_client.get(
        f"/api/clients/{CYFROWY_POLSAT_CLIENT_ID}/order-groups",
        headers=app_auth_headers,
    )
    body = next(g for g in listing.json()["groups"] if g["id"] == created["id"])
    assert body["md_budget_used"] == pytest.approx(13)
    assert body["md_budget_remaining"] == pytest.approx(0)
    assert body["status"] == "exhausted"
    assert body["can_add_consultant"] is False

    blocked = await app_client.post(
        (f"/api/clients/{CYFROWY_POLSAT_CLIENT_ID}/order-groups/{created['id']}/lines"),
        json=_shared_line(second_contract),
        headers=app_auth_headers,
    )
    assert blocked.status_code == 409, blocked.text

    raised = await app_client.patch(
        (f"/api/clients/{CYFROWY_POLSAT_CLIENT_ID}/order-groups/{created['id']}"),
        json={"md_budget_total": 20},
        headers=app_auth_headers,
    )
    assert raised.status_code == 200, raised.text
    raised_body = raised.json()
    assert raised_body["status"] == "active"
    assert raised_body["md_budget_used"] == pytest.approx(13)
    assert raised_body["md_budget_remaining"] == pytest.approx(7)
    assert raised_body["can_add_consultant"] is True

    added = await app_client.post(
        (f"/api/clients/{CYFROWY_POLSAT_CLIENT_ID}/order-groups/{created['id']}/lines"),
        json=_shared_line(second_contract),
        headers=app_auth_headers,
    )
    assert added.status_code == 201, added.text
    assert added.json()["md_total"] is None

    # Ten sam klucz grupa+miesiąc NADPISUJE zamiast odejmować drugi raz.
    async with AsyncSessionLocal() as db:
        group = await db.get(ClientOrderGroup, created["id"])
        assert group is not None
        await upsert_shared_md_consumption(
            db,
            group=group,
            period_month="2026-07",
            md_reported=Decimal("8"),
            source="manual",
        )
        await db.commit()

    refreshed = await app_client.get(
        f"/api/clients/{CYFROWY_POLSAT_CLIENT_ID}/order-groups",
        headers=app_auth_headers,
    )
    refreshed_group = next(
        g for g in refreshed.json()["groups"] if g["id"] == created["id"]
    )
    assert refreshed_group["md_budget_used"] == pytest.approx(8)
    assert refreshed_group["md_budget_remaining"] == pytest.approx(12)


@pytest.mark.asyncio
async def test_shared_md_extend_line_update_and_swap_keep_budget_on_group(
    app_client: AsyncClient, app_auth_headers: dict
):
    first_contract, second_contract = await _seed_cyfrowy_polsat_contracts(2)
    created = await _create_shared_group(
        app_client, app_auth_headers, first_contract, total=40
    )
    old_line = created["lines"][0]

    updated = await app_client.patch(
        (
            f"/api/clients/{CYFROWY_POLSAT_CLIENT_ID}/order-groups/"
            f"{created['id']}/lines/{old_line['id']}"
        ),
        json={"rate_revenue": 1300},
        headers=app_auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["rate_revenue"] == pytest.approx(1300)
    assert updated.json()["md_total"] is None

    swapped = await app_client.post(
        (
            f"/api/clients/{CYFROWY_POLSAT_CLIENT_ID}/order-groups/"
            f"{created['id']}/lines/{old_line['id']}/swap"
        ),
        json={
            "contract_id": second_contract,
            "rate_cost": 1050,
            "rate_revenue": 1350,
            "swap_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert swapped.status_code == 201, swapped.text
    assert swapped.json()["md_total"] is None

    future_start = _TODAY + timedelta(days=30)
    extended = await app_client.post(
        (
            f"/api/clients/{CYFROWY_POLSAT_CLIENT_ID}/order-groups/"
            f"{created['id']}/extend"
        ),
        json={
            "order_number": f"CP-EXT-{uuid.uuid4().hex[:6]}",
            "start_date": future_start.isoformat(),
            "md_budget_total": 25,
            "lines": [_shared_line(second_contract, start_date=future_start)],
        },
        headers=app_auth_headers,
    )
    assert extended.status_code == 201, extended.text
    extended_body = extended.json()
    assert extended_body["is_md_budget_based"] is True
    assert extended_body["md_budget_total"] == pytest.approx(25)
    assert extended_body["md_budget_remaining"] == pytest.approx(25)
    assert extended_body["lines"][0]["md_total"] is None
