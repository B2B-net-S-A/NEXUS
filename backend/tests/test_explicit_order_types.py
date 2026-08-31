"""Jawny typ nowych zamówień bez zmiany semantyki rekordów historycznych."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today
from app.models.order_type import OrderType


_TODAY = business_today()


async def _seed_client_with_contracts(count: int = 2) -> tuple[int, list[int]]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"ExplicitOrderType-{suffix}")
        db.add(client)
        await db.flush()

        contract_ids: list[int] = []
        for index in range(count):
            candidate = Candidate(
                name=f"Typ{index}",
                lastname=f"Zamowienia-{suffix}",
                email=f"order-type-{suffix}-{index}@example.com",
            )
            db.add(candidate)
            await db.flush()
            contract = Contract(
                candidate_id=candidate.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=_TODAY - timedelta(days=30),
                rate_candidate=Decimal("100.000"),
                rate_client=Decimal("150.000"),
            )
            db.add(contract)
            await db.flush()
            contract_ids.append(contract.id)
        await db.commit()
        return client.id, contract_ids


def _shared_line(contract_id: int) -> dict:
    return {
        "contract_id": contract_id,
        "rate_cost": 1000,
        "rate_revenue": 1200,
        "start_date": (_TODAY - timedelta(days=5)).isoformat(),
    }


def _md_line(contract_id: int, md: int = 80) -> dict:
    return {
        **_shared_line(contract_id),
        "input_mode": "md",
        "input_value": md,
    }


def test_explicit_group_schema_derives_one_unambiguous_type():
    from pydantic import ValidationError

    from app.schemas.client_order_group import OrderGroupCreate

    cost = OrderGroupCreate(
        order_number="COST-1",
        start_date=_TODAY,
        order_type=OrderType.cost,
        budget_amount=Decimal("1000"),
    )
    assert cost.is_cost_based is True
    assert cost.is_md_budget_based is False

    md = OrderGroupCreate(
        order_number="MD-1",
        start_date=_TODAY,
        order_type=OrderType.md,
    )
    assert md.is_cost_based is False
    assert md.is_md_budget_based is False

    shared_md = OrderGroupCreate(
        order_number="MD-SHARED-1",
        start_date=_TODAY,
        order_type=OrderType.md,
        is_md_budget_based=True,
        md_budget_total=Decimal("20"),
    )
    assert shared_md.is_md_budget_based is True

    with pytest.raises(ValidationError, match="sprzeczny z flagą"):
        OrderGroupCreate(
            order_number="MIXED-1",
            start_date=_TODAY,
            order_type=OrderType.cost,
            is_md_budget_based=True,
            budget_amount=Decimal("1000"),
        )


def test_legacy_group_type_is_only_interpreted_not_written():
    from app.services.order_types import effective_group_order_type

    legacy_cost = SimpleNamespace(order_type=None, is_cost_based=True)
    legacy_md = SimpleNamespace(order_type=None, is_cost_based=False)

    assert effective_group_order_type(legacy_cost) == OrderType.cost
    assert effective_group_order_type(legacy_md) == OrderType.md
    assert legacy_cost.order_type is None
    assert legacy_md.order_type is None


@pytest.mark.asyncio
async def test_generic_client_can_mix_new_types_and_get_history_suggestion(
    app_client: AsyncClient,
    app_auth_headers: dict,
):
    client_id, contracts = await _seed_client_with_contracts(2)
    url = f"/api/clients/{client_id}/order-groups"

    empty = await app_client.get(url, headers=app_auth_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["suggested_order_type"] == "periodic"

    cost = await app_client.post(
        url,
        json={
            "order_number": "COST-NOWY",
            "start_date": (_TODAY - timedelta(days=5)).isoformat(),
            "order_type": "cost",
            "budget_amount": 50000,
            "lines": [_shared_line(contracts[0])],
        },
        headers=app_auth_headers,
    )
    assert cost.status_code == 201, cost.text
    assert cost.json()["order_type"] == "cost"
    assert cost.json()["is_cost_based"] is True
    cost_line_id = cost.json()["lines"][0]["id"]

    after_cost = await app_client.get(url, headers=app_auth_headers)
    assert after_cost.json()["suggested_order_type"] == "cost"

    md = await app_client.post(
        url,
        json={
            "order_number": "MD-NOWY",
            "start_date": (_TODAY - timedelta(days=4)).isoformat(),
            "order_type": "md",
            "lines": [_md_line(contracts[1])],
        },
        headers=app_auth_headers,
    )
    assert md.status_code == 201, md.text
    assert md.json()["order_type"] == "md"
    assert md.json()["is_md_budget_based"] is False
    assert md.json()["md_budget_total"] is None
    assert md.json()["lines"][0]["md_total"] == 80
    md_line_id = md.json()["lines"][0]["id"]

    after_md = await app_client.get(url, headers=app_auth_headers)
    assert after_md.json()["suggested_order_type"] == "md"

    periodic = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data={
            "contract_id": str(contracts[0]),
            "title": "(bez numeru)",
            "order_status": "draft",
            "order_type": "periodic",
        },
        headers=app_auth_headers,
    )
    assert periodic.status_code == 201, periodic.text
    assert periodic.json()["order_type"] == "periodic"
    periodic_id = periodic.json()["id"]

    after_periodic = await app_client.get(url, headers=app_auth_headers)
    assert after_periodic.json()["suggested_order_type"] == "periodic"
    assert {group["order_type"] for group in after_periodic.json()["groups"]} == {
        "cost",
        "md",
    }

    periodic_registry = await app_client.get(
        f"/api/clients/{client_id}/orders", headers=app_auth_headers
    )
    assert periodic_registry.status_code == 200, periodic_registry.text
    periodic_registry_ids = {
        order["id"]
        for contractor in periodic_registry.json()["contractors"]
        for order in contractor["orders"]
    }
    assert periodic_id in periodic_registry_ids
    assert cost_line_id not in periodic_registry_ids
    assert md_line_id not in periodic_registry_ids


@pytest.mark.asyncio
async def test_generic_client_legacy_group_request_stays_rejected(
    app_client: AsyncClient,
    app_auth_headers: dict,
):
    client_id, _ = await _seed_client_with_contracts(0)
    response = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": "BEZ-TYPU",
            "start_date": _TODAY.isoformat(),
            "lines": [],
        },
        headers=app_auth_headers,
    )
    assert response.status_code == 422, response.text

    explicit_shared = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": "MD-SHARED-GENERIC",
            "start_date": _TODAY.isoformat(),
            "order_type": "md",
            "is_md_budget_based": True,
            "md_budget_total": 20,
            "lines": [],
        },
        headers=app_auth_headers,
    )
    assert explicit_shared.status_code == 422, explicit_shared.text
    assert "Cyfrowego Polsatu i Lotte Wedel" in explicit_shared.text


@pytest.mark.asyncio
async def test_empty_explicit_md_has_no_group_bar_and_first_line_gets_own_budget(
    app_client: AsyncClient,
    app_auth_headers: dict,
):
    client_id, contracts = await _seed_client_with_contracts(1)
    url = f"/api/clients/{client_id}/order-groups"

    created = await app_client.post(
        url,
        json={
            "order_number": "MD-BEZ-OBSADY",
            "start_date": (_TODAY - timedelta(days=2)).isoformat(),
            "order_type": "md",
            "lines": [],
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    group = created.json()
    assert group["lines"] == []
    assert group["is_md_budget_based"] is False
    assert group["md_budget_total"] is None
    assert group["md_budget_used"] is None
    assert group["md_budget_remaining"] is None

    missing_line_budget = await app_client.post(
        f"{url}/{group['id']}/lines",
        json=_shared_line(contracts[0]),
        headers=app_auth_headers,
    )
    assert missing_line_budget.status_code == 422, missing_line_budget.text
    assert "Podaj budżet konsultanta" in missing_line_budget.text

    added = await app_client.post(
        f"{url}/{group['id']}/lines",
        json=_md_line(contracts[0], md=60),
        headers=app_auth_headers,
    )
    assert added.status_code == 201, added.text
    assert added.json()["md_total"] == 60
    assert added.json()["md_remaining"] == 60


def test_shared_md_pool_predicate_ignores_generic_flag_even_with_lines(monkeypatch):
    from app.services import lotte_wedel_orders
    from app.services.shared_md_orders import uses_shared_md_pool

    monkeypatch.setattr(lotte_wedel_orders, "LOTTE_WEDEL_CLIENT_ID", 155)

    generic = SimpleNamespace(client_id=999, is_md_budget_based=True, lines=[object()])
    cyfrowy_polsat = SimpleNamespace(client_id=38339, is_md_budget_based=True)
    lotte_wedel = SimpleNamespace(client_id=155, is_md_budget_based=True)

    assert uses_shared_md_pool(generic) is False
    assert uses_shared_md_pool(cyfrowy_polsat) is True
    assert uses_shared_md_pool(lotte_wedel) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("is_cost_based", "expected_type"),
    [(True, "cost"), (False, "md")],
)
async def test_legacy_group_drives_suggestion_without_being_backfilled(
    app_client: AsyncClient,
    app_auth_headers: dict,
    is_cost_based: bool,
    expected_type: str,
):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroup

    client_id, _ = await _seed_client_with_contracts(0)
    async with AsyncSessionLocal() as db:
        legacy = ClientOrderGroup(
            client_id=client_id,
            order_number=f"LEGACY-{expected_type.upper()}",
            start_date=_TODAY - timedelta(days=10),
            status="active",
            order_type=None,
            is_cost_based=is_cost_based,
            budget_amount=Decimal("1000") if is_cost_based else None,
            budget_remaining=Decimal("1000") if is_cost_based else None,
        )
        db.add(legacy)
        await db.flush()
        group_id = legacy.id
        await db.commit()

    response = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["suggested_order_type"] == expected_type
    # Sieroca historyczna grupa klienta bez starej capability pozostaje ukryta.
    assert response.json()["groups"] == []

    async with AsyncSessionLocal() as db:
        stored_type = await db.scalar(
            select(ClientOrderGroup.order_type).where(ClientOrderGroup.id == group_id)
        )
    assert stored_type is None


@pytest.mark.asyncio
async def test_reading_legacy_order_does_not_backfill_its_type(
    app_client: AsyncClient,
    app_auth_headers: dict,
):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    client_id, contracts = await _seed_client_with_contracts(1)
    async with AsyncSessionLocal() as db:
        legacy = ClientOrder(
            client_id=client_id,
            contract_id=contracts[0],
            title="HISTORYCZNE",
            status=ClientOrderStatus.draft,
            order_type=None,
        )
        db.add(legacy)
        await db.flush()
        legacy_id = legacy.id
        await db.commit()

    response = await app_client.get(
        f"/api/clients/{client_id}/orders", headers=app_auth_headers
    )
    assert response.status_code == 200, response.text
    wire_order = next(
        order
        for contractor in response.json()["contractors"]
        for order in contractor["orders"]
        if order["id"] == legacy_id
    )
    assert wire_order["order_type"] is None

    attempted_reclassification = await app_client.patch(
        f"/api/clients/{client_id}/orders/{legacy_id}",
        json={"order_type": "cost"},
        headers=app_auth_headers,
    )
    assert attempted_reclassification.status_code == 409

    async with AsyncSessionLocal() as db:
        stored_type = await db.scalar(
            select(ClientOrder.order_type).where(ClientOrder.id == legacy_id)
        )
    assert stored_type is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("order_type", "budget_field", "budget_value"),
    [
        ("cost", "total_value", 50000),
        ("md", "md_quantity", 75),
    ],
)
async def test_completing_typed_draft_materializes_budget_at_the_correct_scope(
    app_client: AsyncClient,
    app_auth_headers: dict,
    order_type: str,
    budget_field: str,
    budget_value: int,
):
    client_id, contracts = await _seed_client_with_contracts(1)
    created = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data={
            "contract_id": str(contracts[0]),
            "title": "(bez numeru)",
            "order_status": "draft",
            "order_type": order_type,
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    completed = await app_client.patch(
        f"/api/clients/{client_id}/orders/{order_id}",
        json={
            "title": f"DRAFT-{order_type.upper()}",
            "order_type": order_type,
            "start_date": (_TODAY - timedelta(days=1)).isoformat(),
            "rate_candidate": 100,
            "rate_client": 150,
            budget_field: budget_value,
        },
        headers=app_auth_headers,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "active"
    assert completed.json()["order_type"] == order_type

    groups = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    assert groups.status_code == 200, groups.text
    assert groups.json()["total_groups"] == 1
    group = groups.json()["groups"][0]
    assert group["order_type"] == order_type
    assert [line["id"] for line in group["lines"]] == [order_id]
    if order_type == "cost":
        assert group["budget_amount"] == budget_value
        assert group["is_cost_based"] is True
    else:
        assert group["is_md_budget_based"] is False
        assert group["md_budget_total"] is None
        assert group["lines"][0]["md_total"] == budget_value


@pytest.mark.asyncio
async def test_new_cost_marker_bypasses_legacy_matcher_gate_only_for_new_group(
    app_client: AsyncClient,
    app_auth_headers: dict,
    monkeypatch,
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroup
    from app.services import cost_orders
    from app.services.client_order_lines import active_cost_lines

    client_id, contracts = await _seed_client_with_contracts(2)
    monkeypatch.setattr(cost_orders, "cost_order_client_ids", lambda: frozenset())

    explicit = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": "EXPLICIT-COST",
            "start_date": (_TODAY - timedelta(days=2)).isoformat(),
            "order_type": "cost",
            "budget_amount": 10000,
            "lines": [_shared_line(contracts[0])],
        },
        headers=app_auth_headers,
    )
    assert explicit.status_code == 201, explicit.text
    explicit_line_id = explicit.json()["lines"][0]["id"]

    async with AsyncSessionLocal() as db:
        legacy_group = ClientOrderGroup(
            client_id=client_id,
            order_number="LEGACY-COST",
            start_date=_TODAY - timedelta(days=2),
            order_type=None,
            status="active",
            is_cost_based=True,
            budget_amount=Decimal("10000"),
            budget_remaining=Decimal("10000"),
        )
        db.add(legacy_group)
        await db.flush()
        legacy_line = ClientOrder(
            client_id=client_id,
            contract_id=contracts[1],
            order_group_id=legacy_group.id,
            order_type=None,
            title="LEGACY-COST — konsultant",
            status=ClientOrderStatus.active,
            start_date=_TODAY - timedelta(days=2),
            rate_client=Decimal("1200"),
        )
        db.add(legacy_line)
        await db.flush()
        legacy_line_id = legacy_line.id
        await db.commit()

    async with AsyncSessionLocal() as db:
        matches = await active_cost_lines(db, _TODAY.strftime("%Y-%m"))
    matched_ids = {match.order.id for match in matches}
    assert explicit_line_id in matched_ids
    assert legacy_line_id not in matched_ids
