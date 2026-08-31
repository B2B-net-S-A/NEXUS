"""Jawne warianty zamówień Lotte Wedel bez zmiany innych klientów."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.services.lotte_wedel_orders import LOTTE_WEDEL_CLIENT_ID
from tests.test_order_lifecycle_and_cost import (
    _TODAY,
    _cost_line,
    _create_group,
    _finance_headers,
    _import_sheet,
    _seed_client_with_contracts,
    _sheet,
)


def _enable_lotte_wedel(monkeypatch: pytest.MonkeyPatch, client_id: int) -> None:
    from app.services import lotte_wedel_orders

    monkeypatch.setattr(lotte_wedel_orders, "LOTTE_WEDEL_CLIENT_ID", client_id)


async def _group_from_list(
    app_client: AsyncClient, headers: dict, client_id: int, group_id: int
) -> dict:
    response = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert response.status_code == 200, response.text
    return next(group for group in response.json()["groups"] if group["id"] == group_id)


def test_lotte_wedel_is_an_explicit_hardcoded_client(monkeypatch: pytest.MonkeyPatch):
    from app.services import cost_orders, lotte_wedel_orders, multi_consultant_orders
    from app.services.cyfrowy_polsat_orders import CYFROWY_POLSAT_CLIENT_ID
    from app.services.lotte_wedel_orders import is_lotte_wedel_order_types_client

    monkeypatch.setattr(
        lotte_wedel_orders, "LOTTE_WEDEL_CLIENT_ID", LOTTE_WEDEL_CLIENT_ID
    )
    monkeypatch.setattr(cost_orders, "cost_order_client_ids", frozenset)
    monkeypatch.setattr(
        multi_consultant_orders, "multi_consultant_client_ids", frozenset
    )

    assert LOTTE_WEDEL_CLIENT_ID == 155
    assert is_lotte_wedel_order_types_client(LOTTE_WEDEL_CLIENT_ID) is True
    assert is_lotte_wedel_order_types_client(5244) is False
    assert is_lotte_wedel_order_types_client(5249) is False
    assert cost_orders.is_cost_order_client(LOTTE_WEDEL_CLIENT_ID) is True
    assert (
        multi_consultant_orders.is_multi_consultant_client(LOTTE_WEDEL_CLIENT_ID)
        is True
    )

    # Lotte, tak samo jak CP, zachowuje standardowy wariant w legacy rejestrze.
    assert cost_orders.skips_standard_order_automation(LOTTE_WEDEL_CLIENT_ID) is False
    assert (
        cost_orders.skips_standard_order_group_materialization(LOTTE_WEDEL_CLIENT_ID)
        is True
    )
    assert (
        cost_orders.hides_standard_drafts_from_order_group_registry(
            LOTTE_WEDEL_CLIENT_ID
        )
        is True
    )

    # Regresja: dotychczasowy hardcode CP pozostaje aktywny, a inne ID nie
    # dostają nowych capability przy pustych listach środowiskowych.
    assert cost_orders.is_cost_order_client(CYFROWY_POLSAT_CLIENT_ID) is True
    assert cost_orders.is_cost_order_client(156) is False
    assert multi_consultant_orders.is_multi_consultant_client(156) is False


@pytest.mark.asyncio
async def test_shared_md_settlement_locks_before_reading_consumption(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.models.client_order_group import ClientOrderGroup
    from app.services import shared_md_orders

    _enable_lotte_wedel(monkeypatch, LOTTE_WEDEL_CLIENT_ID)

    group = ClientOrderGroup(
        id=99155,
        client_id=LOTTE_WEDEL_CLIENT_ID,
        order_number="4500810155",
        start_date=_TODAY,
        status="active",
        is_cost_based=False,
        is_md_budget_based=True,
        md_budget_total=Decimal("10"),
        md_budget_remaining=Decimal("10"),
    )
    calls: list[str] = []

    async def fake_lock(_db, candidate, *, flush_local_changes):
        assert flush_local_changes is True
        calls.append("lock")
        return candidate

    async def fake_used_total(_db, group_id):
        assert group_id == group.id
        assert calls == ["lock"]
        calls.append("sum")
        return Decimal("3")

    monkeypatch.setattr(shared_md_orders, "lock_group_for_settlement", fake_lock)
    monkeypatch.setattr(shared_md_orders, "shared_md_used_total", fake_used_total)

    remaining = await shared_md_orders.settle_shared_md_group(object(), group)

    assert calls == ["lock", "sum"]
    assert remaining == Decimal("7.000000")
    assert group.md_budget_remaining == Decimal("7.000000")


@pytest.mark.asyncio
async def test_shared_md_upsert_locks_group_before_month_row(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.models.client_order_group import (
        ClientOrderGroup,
        ClientOrderGroupMdConsumption,
    )
    from app.services import shared_md_orders

    _enable_lotte_wedel(monkeypatch, LOTTE_WEDEL_CLIENT_ID)

    group = ClientOrderGroup(
        id=99156,
        client_id=LOTTE_WEDEL_CLIENT_ID,
        order_number="4500810156",
        start_date=_TODAY,
        status="active",
        is_cost_based=False,
        is_md_budget_based=True,
        md_budget_total=Decimal("10"),
        md_budget_remaining=Decimal("10"),
    )
    calls: list[str] = []

    async def fake_lock(_db, candidate, *, flush_local_changes):
        assert flush_local_changes is False
        calls.append("group_lock")
        return candidate

    async def fake_settle(_db, candidate):
        assert candidate is group
        calls.append("settle")
        return Decimal("6")

    class FakeDb:
        async def scalar(self, _statement):
            assert calls == ["group_lock"]
            calls.append("month_write")
            return 77155

        async def get(self, _model, row_id):
            assert row_id == 77155
            calls.append("month_read")
            return ClientOrderGroupMdConsumption(
                id=row_id,
                group_id=group.id,
                period_month="2026-08",
                md_reported=Decimal("4"),
                source="import",
            )

    monkeypatch.setattr(shared_md_orders, "lock_group_for_settlement", fake_lock)
    monkeypatch.setattr(shared_md_orders, "settle_shared_md_group", fake_settle)

    row, remaining = await shared_md_orders.upsert_shared_md_consumption(
        FakeDb(),
        group=group,
        period_month="2026-08",
        md_reported=Decimal("4"),
    )

    assert row.id == 77155
    assert remaining == Decimal("6")
    assert calls == ["group_lock", "month_write", "month_read", "settle"]


@pytest.mark.asyncio
async def test_shared_md_upsert_waits_for_budget_edit_and_uses_fresh_total(
    app_client: AsyncClient,
    app_auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    """Real PostgreSQL lock: stale import must wait and refresh the MD budget."""

    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroup
    from app.services.cost_orders import lock_group_for_settlement
    from app.services.shared_md_orders import (
        settle_shared_md_group,
        upsert_shared_md_consumption,
    )

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_lotte_wedel(monkeypatch, client_id)
    created = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        order_number="4500810199",
        is_md_budget_based=True,
        md_budget_total=10,
    )
    group_id = created["id"]

    stale_loaded = asyncio.Event()
    edit_holds_group = asyncio.Event()
    start_import = asyncio.Event()
    release_edit = asyncio.Event()
    import_pid = asyncio.get_running_loop().create_future()

    async def edit_budget_in_first_transaction() -> Decimal:
        async with AsyncSessionLocal() as db:
            group = await db.get(ClientOrderGroup, group_id)
            assert group is not None
            group = await lock_group_for_settlement(
                db, group, flush_local_changes=False
            )
            group.md_budget_total = Decimal("20")
            await db.flush([group])
            edit_holds_group.set()
            await release_edit.wait()
            remaining = await settle_shared_md_group(db, group)
            await db.commit()
            return remaining

    async def import_from_stale_second_transaction() -> Decimal:
        async with AsyncSessionLocal() as db:
            stale_group = await db.get(ClientOrderGroup, group_id)
            assert stale_group is not None
            pid = await db.scalar(text("SELECT pg_backend_pid()"))
            import_pid.set_result(int(pid))
            stale_loaded.set()
            await start_import.wait()
            _, remaining = await upsert_shared_md_consumption(
                db,
                group=stale_group,
                period_month="2026-08",
                md_reported=Decimal("12"),
            )
            await db.commit()
            return remaining

    import_task = asyncio.create_task(import_from_stale_second_transaction())
    edit_task = None
    try:
        await asyncio.wait_for(stale_loaded.wait(), timeout=5)
        edit_task = asyncio.create_task(edit_budget_in_first_transaction())
        await asyncio.wait_for(edit_holds_group.wait(), timeout=5)
        start_import.set()
        pid = await asyncio.wait_for(import_pid, timeout=5)

        blocked = False
        deadline = asyncio.get_running_loop().time() + 5
        async with AsyncSessionLocal() as observer:
            while asyncio.get_running_loop().time() < deadline:
                blocker_count = await observer.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid))"),
                    {"pid": pid},
                )
                if int(blocker_count or 0) > 0:
                    blocked = True
                    break
                if import_task.done():
                    break
                await asyncio.sleep(0.02)
        assert blocked, "shared-MD import did not wait on the budget edit lock"

        release_edit.set()
        assert await asyncio.wait_for(edit_task, timeout=5) == Decimal("20.000000")
        assert await asyncio.wait_for(import_task, timeout=5) == Decimal("8.000000")
    finally:
        release_edit.set()
        start_import.set()
        tasks = [import_task]
        if edit_task is not None:
            tasks.append(edit_task)
        await asyncio.gather(*tasks, return_exceptions=True)

    refreshed = await _group_from_list(
        app_client, app_auth_headers, client_id, group_id
    )
    assert refreshed["md_budget_total"] == pytest.approx(20)
    assert refreshed["md_budget_used"] == pytest.approx(12)
    assert refreshed["md_budget_remaining"] == pytest.approx(8)
    assert refreshed["status"] == "active"


@pytest.mark.asyncio
async def test_lotte_profile_and_group_api_require_one_special_type(
    app_client: AsyncClient,
    app_auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_lotte_wedel(monkeypatch, client_id)

    profile = await app_client.get(
        f"/api/clients/{client_id}", headers=app_auth_headers
    )
    assert profile.status_code == 200, profile.text
    body = profile.json()
    assert body["multi_consultant_orders_enabled"] is True
    assert body["cost_orders_enabled"] is True
    assert body["lotte_wedel_order_types_enabled"] is True
    assert body["cyfrowy_polsat_order_types_enabled"] is False

    url = f"/api/clients/{client_id}/order-groups"
    base = {
        "order_number": "4500810155",
        "start_date": _TODAY.isoformat(),
        "lines": [_cost_line(contracts[0])],
    }
    neither = await app_client.post(url, json=base, headers=app_auth_headers)
    assert neither.status_code == 422, neither.text
    assert "Lotte Wedel" in neither.text

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
    assert "jednocześnie kosztowe i na MD" in both.text


@pytest.mark.asyncio
async def test_lotte_finance_import_matches_uwagi_for_cost_and_md_and_exhausts(
    app_client: AsyncClient,
    app_auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    client_id, contracts, names = await _seed_client_with_contracts(3)
    _enable_lotte_wedel(monkeypatch, client_id)

    cost = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        order_number="4500810155",
        is_cost_based=True,
        budget_amount=1000,
    )
    shared_md = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[1])],
        order_number="4500810156",
        is_md_budget_based=True,
        md_budget_total=10,
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client,
        finance,
        _sheet(
            [
                (names[0], 0, "SAP 4500810155", 1200),
                (names[1], 12, "SAP 4500810156", 0),
            ]
        ),
    )

    assert detail["rows_applied"] == 1
    assert detail["rows_unmatched"] == 1
    assert detail["rows_cost_applied"] == 1

    cost_row, md_row = detail["rows"]
    assert cost_row["cost_status"] == "applied"
    assert cost_row["order_number_hint"] == "4500810155"
    assert md_row["status"] == "applied"
    assert md_row["matched"]["order_number"] == "4500810156"

    cost_body = await _group_from_list(
        app_client, app_auth_headers, client_id, cost["id"]
    )
    assert cost_body["budget_used"] == pytest.approx(1000)
    assert cost_body["budget_remaining"] == pytest.approx(0)
    assert cost_body["status"] == "exhausted"
    assert cost_body["can_add_consultant"] is False
    assert cost_body["lines"][0]["invoiced_total"] == pytest.approx(1200)
    assert cost_body["lines"][0]["unsettled_total"] == pytest.approx(200)

    md_body = await _group_from_list(
        app_client, app_auth_headers, client_id, shared_md["id"]
    )
    assert md_body["md_budget_used"] == pytest.approx(12)
    assert md_body["md_budget_remaining"] == pytest.approx(0)
    assert md_body["status"] == "exhausted"
    assert md_body["can_add_consultant"] is False

    events = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{shared_md['id']}/events",
        headers=app_auth_headers,
    )
    assert events.status_code == 200, events.text
    md_import = next(
        event for event in events.json()["events"] if event["event_type"] == "import_md"
    )
    assert md_import["payload"]["md_over_budget"] == "2.000000"
    assert "przekracza dostępny budżet" in md_import["description"]

    for group in (cost, shared_md):
        blocked = await app_client.post(
            f"/api/clients/{client_id}/order-groups/{group['id']}/lines",
            json=_cost_line(contracts[2]),
            headers=app_auth_headers,
        )
        assert blocked.status_code == 409, blocked.text

    raised = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{shared_md['id']}",
        json={"md_budget_total": 20},
        headers=app_auth_headers,
    )
    assert raised.status_code == 200, raised.text
    raised_body = raised.json()
    assert raised_body["status"] == "active"
    assert raised_body["md_budget_used"] == pytest.approx(12)
    assert raised_body["md_budget_remaining"] == pytest.approx(8)
    assert raised_body["can_add_consultant"] is True


@pytest.mark.asyncio
async def test_non_lotte_client_still_cannot_create_shared_md(
    app_client: AsyncClient,
    app_auth_headers: dict,
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    response = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": "4500810999",
            "start_date": _TODAY.isoformat(),
            "is_md_budget_based": True,
            "md_budget_total": 10,
            "lines": [_cost_line(contracts[0])],
        },
        headers=app_auth_headers,
    )
    assert response.status_code == 422, response.text
