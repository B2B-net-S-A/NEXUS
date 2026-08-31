"""Polkomtel SAP-number matching and safe Finance batch reprocessing."""

from __future__ import annotations

import inspect
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.services.finance_order_matching import finance_order_number_matches
from tests.test_md_import_shared_budget import (
    _client_and_contract_for_existing_candidate,
)
from tests.test_order_lifecycle_and_cost import (
    _TODAY,
    _cost_line,
    _create_group,
    _enable_cost,
    _enable_multi,
    _finance_headers,
    _import_sheet,
    _md_line,
    _seed_client_with_contracts,
    _sheet,
)


def _set_polkomtel(monkeypatch, client_id: int) -> None:
    from app.services import finance_order_matching

    monkeypatch.setattr(finance_order_matching, "POLKOMTEL_CLIENT_ID", client_id)


async def _group(
    app_client: AsyncClient, headers: dict, client_id: int, group_id: int
) -> dict:
    response = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["groups"] if item["id"] == group_id)


def test_sap_normalization_is_full_string_and_polkomtel_only(monkeypatch):
    _set_polkomtel(monkeypatch, 15)

    assert finance_order_number_matches(
        client_id=15,
        order_number="SAP 1234567",
        numeric_hints=["1234567"],
    )
    assert finance_order_number_matches(
        client_id=15,
        order_number="sap:1234567",
        numeric_hints=["1234567"],
    )
    # Exact matching remains available to every client.
    assert finance_order_number_matches(
        client_id=12,
        order_number="1234567",
        numeric_hints=["1234567"],
    )
    # BIK/BNP do not inherit Polkomtel's prefix rule.
    assert not finance_order_number_matches(
        client_id=12,
        order_number="SAP 1234567",
        numeric_hints=["1234567"],
    )
    assert not finance_order_number_matches(
        client_id=18,
        order_number="SAP 1234567",
        numeric_hints=["1234567"],
    )
    # Compound identifiers fail closed instead of collapsing to arbitrary digits.
    assert not finance_order_number_matches(
        client_id=15,
        order_number="SAP 1234567/2026",
        numeric_hints=["1234567", "2026"],
    )


def test_ordinary_import_locks_lines_then_groups_before_monthly_writes():
    from app.api.md_consumption import create_import

    source = inspect.getsource(create_import)
    line_locks = source.index("await _lock_finance_target_orders")
    group_locks = source.index("await _lock_finance_target_groups")
    evidence_check = source.index("_ordinary_locked_target_is_valid", group_locks)
    md_write = source.index("await _apply_to_line", group_locks)
    shared_write = source.index("await _settle_shared_md_and_record", group_locks)
    cost_write = source.index("await upsert_invoice", group_locks)
    assert (
        line_locks < group_locks < evidence_check < md_write < shared_write < cost_write
    )


def test_ordinary_action_time_revalidation_rejects_renamed_polkomtel_order(
    monkeypatch,
):
    from app.api.md_consumption import _ordinary_locked_target_is_valid
    from app.models.client_order import ClientOrderStatus
    from app.models.client_order_group import GROUP_STATUS_ACTIVE
    from app.models.contract import ContractStatus

    _set_polkomtel(monkeypatch, 15)
    candidate = SimpleNamespace(name="Jan", lastname="Kowalski")
    contract = SimpleNamespace(
        client_id=15,
        status=ContractStatus.active,
        candidate=candidate,
    )
    group = SimpleNamespace(
        id=8,
        client_id=15,
        order_number="SAP 1234567",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status=GROUP_STATUS_ACTIVE,
        is_cost_based=True,
    )
    order = SimpleNamespace(
        id=9,
        client_id=15,
        order_group_id=group.id,
        contract=contract,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status=ClientOrderStatus.active,
        md_total=None,
    )
    row = SimpleNamespace(
        consultant_name="Kowalski Jan",
        notes_raw="1234567",
    )

    assert _ordinary_locked_target_is_valid(
        kind="cost",
        order=order,
        group=group,
        rows=[row],
        expected_client_id=15,
        period_month="2026-07",
    )

    # Simulates a concurrent PATCH that held line -> group first.  Once this
    # import wakes and refreshes the group under its locks, the old sheet row
    # must no longer authorize a write to the renamed order.
    group.order_number = "SAP 7654321"
    assert not _ordinary_locked_target_is_valid(
        kind="cost",
        order=order,
        group=group,
        rows=[row],
        expected_client_id=15,
        period_month="2026-07",
    )

    group.order_number = "SAP 1234567"
    candidate.lastname = "Nowak"
    assert not _ordinary_locked_target_is_valid(
        kind="cost",
        order=order,
        group=group,
        rows=[row],
        expected_client_id=15,
        period_month="2026-07",
    )

    candidate.lastname = "Kowalski"
    order.end_date = date(2026, 6, 30)
    assert not _ordinary_locked_target_is_valid(
        kind="cost",
        order=order,
        group=group,
        rows=[row],
        expected_client_id=15,
        period_month="2026-07",
    )

    order.end_date = date(2026, 12, 31)
    group.client_id = 18
    assert not _ordinary_locked_target_is_valid(
        kind="cost",
        order=order,
        group=group,
        rows=[row],
        expected_client_id=15,
        period_month="2026-07",
    )


@pytest.mark.asyncio
async def test_reprocess_locks_all_lines_before_globally_sorted_groups(monkeypatch):
    from app.api import md_consumption as module
    from app.services.client_order_lines import LineMatch

    group_high = SimpleNamespace(id=20)
    group_low = SimpleNamespace(id=4)
    order_high = SimpleNamespace(
        id=30,
        order_group_id=group_high.id,
        order_group=group_high,
        contract=None,
    )
    order_low = SimpleNamespace(
        id=7,
        order_group_id=group_low.id,
        order_group=group_low,
        contract=None,
    )
    calls: list[str] = []

    class _Scalars:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self._rows

    class _Db:
        async def execute(self, statement):
            rendered = str(statement)
            assert "ORDER BY client_orders.id ASC" in rendered
            calls.append("orders")
            return _Scalars([order_low, order_high])

    async def _lock_group(db, group, *, flush_local_changes):
        assert flush_local_changes is False
        calls.append(f"group:{group.id}")
        return group

    monkeypatch.setattr(module, "lock_group_for_settlement", _lock_group)
    monkeypatch.setattr(
        module,
        "_historical_reprocess_match_is_valid",
        lambda plan, *, period_month: True,
    )
    plans = [
        module._PolkomtelReprocessPlan(
            kind=module._REPROCESS_COST,
            match=LineMatch(order_high, group_high, ""),
            rows=[],
            rows_to_update=[],
            expected_value=Decimal("1"),
        ),
        module._PolkomtelReprocessPlan(
            kind=module._REPROCESS_SHARED_MD,
            match=LineMatch(order_low, group_low, ""),
            rows=[],
            rows_to_update=[],
            expected_value=Decimal("1"),
        ),
    ]

    await module._lock_polkomtel_reprocess_targets(
        _Db(),
        plans,
        period_month="2026-07",
    )

    assert calls == ["orders", "group:4", "group:20"]


@pytest.mark.asyncio
async def test_new_cost_import_matches_numeric_hint_to_polkomtel_sap_order_only(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    (
        neighbour_id,
        neighbour_contracts,
        neighbour_names,
    ) = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, polkomtel_id, neighbour_id)
    _enable_cost(monkeypatch, polkomtel_id, neighbour_id)
    _set_polkomtel(monkeypatch, polkomtel_id)

    polkomtel = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_cost_line(contracts[0])],
        order_number="SAP 1234567",
        is_cost_based=True,
        budget_amount=10000,
    )
    neighbour = await _create_group(
        app_client,
        app_auth_headers,
        neighbour_id,
        [_cost_line(neighbour_contracts[0])],
        order_number="SAP 7654321",
        is_cost_based=True,
        budget_amount=10000,
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client,
        finance,
        _sheet(
            [
                (names[0], 0, "1234567", 2500),
                (neighbour_names[0], 0, "7654321", 2500),
            ]
        ),
    )

    assert detail["rows"][0]["cost_status"] == "applied"
    assert detail["rows"][1]["cost_status"] == "unmatched_number"
    polkomtel_body = await _group(
        app_client, app_auth_headers, polkomtel_id, polkomtel["id"]
    )
    neighbour_body = await _group(
        app_client, app_auth_headers, neighbour_id, neighbour["id"]
    )
    assert polkomtel_body["budget_remaining"] == pytest.approx(7500)
    assert neighbour_body["budget_remaining"] == pytest.approx(10000)


@pytest.mark.asyncio
async def test_polkomtel_number_disambiguates_per_consultant_md_without_changing_bik(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    bik_id, bik_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_multi(monkeypatch, polkomtel_id, bik_id)
    _set_polkomtel(monkeypatch, polkomtel_id)

    polkomtel = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_md_line(contracts[0])],
        order_number="SAP 2345678",
    )
    bik = await _create_group(
        app_client,
        app_auth_headers,
        bik_id,
        [_md_line(bik_contract)],
        order_number="9988776",
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 7, "2345678", 0)]),
    )

    assert detail["rows"][0]["status"] == "applied"
    assert detail["rows"][0]["matched_order_id"] == polkomtel["lines"][0]["id"]
    polkomtel_body = await _group(
        app_client, app_auth_headers, polkomtel_id, polkomtel["id"]
    )
    bik_body = await _group(app_client, app_auth_headers, bik_id, bik["id"])
    assert polkomtel_body["lines"][0]["md_remaining"] == pytest.approx(43)
    assert bik_body["lines"][0]["md_remaining"] == pytest.approx(50)


@pytest.mark.asyncio
async def test_new_md_import_does_not_fallback_to_name_for_wrong_polkomtel_number(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, polkomtel_id)
    _set_polkomtel(monkeypatch, polkomtel_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_md_line(contracts[0])],
        order_number="SAP 2445678",
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 7, "9999999", 0)]),
    )

    assert detail["rows"][0]["status"] == "unmatched"
    body = await _group(app_client, app_auth_headers, polkomtel_id, group["id"])
    assert body["lines"][0]["md_remaining"] == pytest.approx(50)


@pytest.mark.asyncio
async def test_existing_cost_batch_has_dry_run_and_idempotent_apply(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, polkomtel_id)
    _enable_cost(monkeypatch, polkomtel_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_cost_line(contracts[0])],
        order_number="SAP 3456789",
        is_cost_based=True,
        budget_amount=10000,
    )
    finance = await _finance_headers(app_client)

    # Reproduce the pre-fix state: this client is not recognized as Polkomtel,
    # so the literal SAP prefix prevents both rows from matching.
    _set_polkomtel(monkeypatch, -999)
    imported = await _import_sheet(
        app_client,
        finance,
        _sheet(
            [
                (names[0], 0, "3456789", 1000),
                (names[0], 0, "3456789", 1500),
            ]
        ),
    )
    assert imported["rows_cost_unmatched"] == 2
    _set_polkomtel(monkeypatch, polkomtel_id)

    endpoint = f"/api/md-consumption/imports/{imported['id']}/reprocess-polkomtel"
    dry = await app_client.post(endpoint, json={"apply": False}, headers=finance)
    assert dry.status_code == 200, dry.text
    assert dry.json()["rows_to_update"] == 2
    assert dry.json()["targets_to_recalculate"] == 1
    assert dry.json()["conflicts"] == []
    target = dry.json()["targets"][0]
    assert target["kind"] == "cost"
    assert target["group_id"] == group["id"]
    assert target["order_id"] == group["lines"][0]["id"]
    assert target["row_ids"] == target["row_ids_to_update"]
    assert target["current_value"] is None
    assert Decimal(str(target["expected_value"])) == Decimal("2500.00")
    assert target["write_required"] is True
    before = await _group(app_client, app_auth_headers, polkomtel_id, group["id"])
    assert before["budget_remaining"] == pytest.approx(10000)

    applied = await app_client.post(endpoint, json={"apply": True}, headers=finance)
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True
    after = await _group(app_client, app_auth_headers, polkomtel_id, group["id"])
    assert after["budget_remaining"] == pytest.approx(7500)

    again = await app_client.post(endpoint, json={"apply": True}, headers=finance)
    assert again.status_code == 200, again.text
    assert again.json()["rows_to_update"] == 0
    assert again.json()["targets_to_recalculate"] == 0

    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import ClientOrderInvoiceConsumption

    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count(ClientOrderInvoiceConsumption.id)).where(
                ClientOrderInvoiceConsumption.order_id == group["lines"][0]["id"]
            )
        )
        amount = await db.scalar(
            select(ClientOrderInvoiceConsumption.invoice_amount).where(
                ClientOrderInvoiceConsumption.order_id == group["lines"][0]["id"]
            )
        )
    assert count == 1
    assert amount == Decimal("2500.00")


@pytest.mark.asyncio
async def test_existing_cost_batch_reprocesses_an_exhausted_historical_group(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, polkomtel_id)
    _enable_cost(monkeypatch, polkomtel_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_cost_line(contracts[0])],
        order_number="SAP 4056789",
        is_cost_based=True,
        budget_amount=2500,
    )
    finance = await _finance_headers(app_client)

    _set_polkomtel(monkeypatch, -999)
    imported = await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 0, "4056789", 2500)]),
    )
    assert imported["rows"][0]["cost_status"] == "unmatched_number"

    # Reproduce the action-time state: the pool was applicable in the batch
    # month but has since moved out of today's active candidate query.
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import (
        GROUP_STATUS_EXHAUSTED,
        ClientOrderGroup,
    )

    async with AsyncSessionLocal() as db:
        stored_group = await db.get(ClientOrderGroup, group["id"])
        assert stored_group is not None
        stored_group.status = GROUP_STATUS_EXHAUSTED
        stored_group.budget_remaining = Decimal("0")
        await db.commit()

    _set_polkomtel(monkeypatch, polkomtel_id)
    endpoint = f"/api/md-consumption/imports/{imported['id']}/reprocess-polkomtel"
    dry = await app_client.post(endpoint, json={"apply": False}, headers=finance)
    assert dry.status_code == 200, dry.text
    assert dry.json()["rows_to_update"] == 1
    assert dry.json()["targets"][0]["kind"] == "cost"
    assert dry.json()["targets"][0]["group_id"] == group["id"]

    applied = await app_client.post(endpoint, json={"apply": True}, headers=finance)
    assert applied.status_code == 200, applied.text
    body = await _group(app_client, app_auth_headers, polkomtel_id, group["id"])
    assert body["status"] == "exhausted"
    assert body["budget_remaining"] == pytest.approx(0)


@pytest.mark.asyncio
async def test_reprocess_does_not_overwrite_consumption_with_unknown_provenance(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, polkomtel_id)
    _enable_cost(monkeypatch, polkomtel_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_cost_line(contracts[0])],
        order_number="SAP 4156789",
        is_cost_based=True,
        budget_amount=10000,
    )
    finance = await _finance_headers(app_client)

    _set_polkomtel(monkeypatch, -999)
    imported = await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 0, "4156789", 2500)]),
    )

    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import ClientOrderInvoiceConsumption

    async with AsyncSessionLocal() as db:
        db.add(
            ClientOrderInvoiceConsumption(
                order_id=group["lines"][0]["id"],
                period_month=imported["period_month"],
                invoice_amount=Decimal("100"),
                settled_amount=Decimal("100"),
                unsettled_amount=Decimal("0"),
                source="import",
                import_id=None,
            )
        )
        await db.commit()

    _set_polkomtel(monkeypatch, polkomtel_id)
    endpoint = f"/api/md-consumption/imports/{imported['id']}/reprocess-polkomtel"
    dry = await app_client.post(endpoint, json={"apply": False}, headers=finance)
    assert dry.status_code == 200, dry.text
    assert "bez możliwej do potwierdzenia" in dry.json()["conflicts"][0]

    blocked = await app_client.post(endpoint, json={"apply": True}, headers=finance)
    assert blocked.status_code == 409, blocked.text
    async with AsyncSessionLocal() as db:
        amount = await db.scalar(
            select(ClientOrderInvoiceConsumption.invoice_amount).where(
                ClientOrderInvoiceConsumption.order_id == group["lines"][0]["id"],
                ClientOrderInvoiceConsumption.period_month == imported["period_month"],
            )
        )
    assert amount == Decimal("100.000")


@pytest.mark.asyncio
async def test_existing_md_batch_is_reprocessed_from_stored_rows(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    bik_id, bik_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_multi(monkeypatch, polkomtel_id, bik_id)
    polkomtel = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [
            _md_line(
                contracts[0],
                input_value=8,
                end_date=_TODAY.isoformat(),
            )
        ],
        order_number="SAP 4567890",
    )
    bik = await _create_group(
        app_client,
        app_auth_headers,
        bik_id,
        [_md_line(bik_contract)],
        order_number="1122334",
    )
    finance = await _finance_headers(app_client)

    _set_polkomtel(monkeypatch, -999)
    imported = await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 8, "4567890", 0)]),
    )
    assert imported["rows"][0]["status"] == "needs_assignment"

    # The July/current-month line may be completed by the time an operator
    # replays the persisted batch.  It must still be selected by its period.
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    async with AsyncSessionLocal() as db:
        stored_line = await db.get(ClientOrder, polkomtel["lines"][0]["id"])
        assert stored_line is not None
        stored_line.status = ClientOrderStatus.completed
        await db.commit()

    _set_polkomtel(monkeypatch, polkomtel_id)

    endpoint = f"/api/md-consumption/imports/{imported['id']}/reprocess-polkomtel"
    dry = await app_client.post(endpoint, json={"apply": False}, headers=finance)
    assert dry.status_code == 200, dry.text
    assert dry.json()["rows_to_update"] == 1
    assert dry.json()["targets"][0]["kind"] == "md_line"
    assert dry.json()["targets"][0]["order_id"] == polkomtel["lines"][0]["id"]

    applied = await app_client.post(endpoint, json={"apply": True}, headers=finance)
    assert applied.status_code == 200, applied.text
    assert applied.json()["rows_to_update"] == 1

    polkomtel_body = await _group(
        app_client, app_auth_headers, polkomtel_id, polkomtel["id"]
    )
    bik_body = await _group(app_client, app_auth_headers, bik_id, bik["id"])
    assert polkomtel_body["lines"][0]["md_remaining"] == pytest.approx(0)
    assert bik_body["lines"][0]["md_remaining"] == pytest.approx(50)

    async with AsyncSessionLocal() as db:
        stored_line = await db.get(ClientOrder, polkomtel["lines"][0]["id"])
        assert stored_line is not None
        assert stored_line.status == ClientOrderStatus.completed


@pytest.mark.asyncio
async def test_reprocess_does_not_treat_a_draft_line_as_historical_evidence(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    bik_id, bik_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_multi(monkeypatch, polkomtel_id, bik_id)
    polkomtel = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_md_line(contracts[0])],
        order_number="SAP 4577890",
    )
    await _create_group(
        app_client,
        app_auth_headers,
        bik_id,
        [_md_line(bik_contract)],
        order_number="3344556",
    )
    finance = await _finance_headers(app_client)

    _set_polkomtel(monkeypatch, -999)
    imported = await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 8, "4577890", 0)]),
    )
    assert imported["rows"][0]["status"] == "needs_assignment"

    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    async with AsyncSessionLocal() as db:
        stored_line = await db.get(ClientOrder, polkomtel["lines"][0]["id"])
        assert stored_line is not None
        stored_line.status = ClientOrderStatus.draft
        await db.commit()

    _set_polkomtel(monkeypatch, polkomtel_id)
    endpoint = f"/api/md-consumption/imports/{imported['id']}/reprocess-polkomtel"
    dry = await app_client.post(endpoint, json={"apply": False}, headers=finance)
    assert dry.status_code == 200, dry.text
    assert dry.json()["rows_to_update"] == 0
    assert dry.json()["targets"] == []


@pytest.mark.asyncio
async def test_reprocess_fails_closed_before_overwriting_a_successor_md_row(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    bik_id, bik_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_multi(monkeypatch, polkomtel_id, bik_id)
    predecessor = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_md_line(contracts[0], input_value=5)],
        order_number="SAP 4667890",
    )
    await _create_group(
        app_client,
        app_auth_headers,
        bik_id,
        [_md_line(bik_contract)],
        order_number="2233445",
    )
    finance = await _finance_headers(app_client)

    _set_polkomtel(monkeypatch, -999)
    imported = await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 8, "4667890", 0)]),
    )
    assert imported["rows"][0]["status"] == "needs_assignment"

    successor_start = _TODAY + timedelta(days=1)
    extended = await app_client.post(
        f"/api/clients/{polkomtel_id}/order-groups/{predecessor['id']}/extend",
        json={
            "order_number": "SAP 4667891",
            "start_date": successor_start.isoformat(),
            "lines": [
                _md_line(
                    contracts[0],
                    input_value=50,
                    start_date=successor_start.isoformat(),
                )
            ],
        },
        headers=app_auth_headers,
    )
    assert extended.status_code == 201, extended.text
    successor = extended.json()

    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import ClientOrderMdConsumption

    async with AsyncSessionLocal() as db:
        db.add(
            ClientOrderMdConsumption(
                order_id=successor["lines"][0]["id"],
                period_month=imported["period_month"],
                md_reported=Decimal("1"),
                source="manual",
                import_id=None,
            )
        )
        await db.commit()

    _set_polkomtel(monkeypatch, polkomtel_id)
    endpoint = f"/api/md-consumption/imports/{imported['id']}/reprocess-polkomtel"
    dry = await app_client.post(endpoint, json={"apply": False}, headers=finance)
    assert dry.status_code == 200, dry.text
    assert "ma kontynuację" in dry.json()["conflicts"][0]

    blocked = await app_client.post(endpoint, json={"apply": True}, headers=finance)
    assert blocked.status_code == 409, blocked.text
    async with AsyncSessionLocal() as db:
        successor_md = await db.scalar(
            select(ClientOrderMdConsumption.md_reported).where(
                ClientOrderMdConsumption.order_id == successor["lines"][0]["id"],
                ClientOrderMdConsumption.period_month == imported["period_month"],
            )
        )
        predecessor_count = await db.scalar(
            select(func.count(ClientOrderMdConsumption.id)).where(
                ClientOrderMdConsumption.order_id == predecessor["lines"][0]["id"],
            )
        )
    assert successor_md == Decimal("1.000000")
    assert predecessor_count == 0


@pytest.mark.asyncio
async def test_reprocess_fails_closed_on_same_person_and_number_at_bik(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    bik_id, bik_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_multi(monkeypatch, polkomtel_id, bik_id)
    polkomtel = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_md_line(contracts[0])],
        order_number="SAP 5678901",
    )
    bik = await _create_group(
        app_client,
        app_auth_headers,
        bik_id,
        [_md_line(bik_contract)],
        order_number="5678901",
    )
    finance = await _finance_headers(app_client)

    _set_polkomtel(monkeypatch, -999)
    imported = await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 8, "5678901", 0)]),
    )
    _set_polkomtel(monkeypatch, polkomtel_id)

    endpoint = f"/api/md-consumption/imports/{imported['id']}/reprocess-polkomtel"
    dry = await app_client.post(endpoint, json={"apply": False}, headers=finance)
    assert dry.status_code == 200, dry.text
    assert dry.json()["rows_to_update"] == 0
    assert "więcej niż jednej linii MD" in dry.json()["conflicts"][0]

    blocked = await app_client.post(endpoint, json={"apply": True}, headers=finance)
    assert blocked.status_code == 409, blocked.text
    polkomtel_body = await _group(
        app_client, app_auth_headers, polkomtel_id, polkomtel["id"]
    )
    bik_body = await _group(app_client, app_auth_headers, bik_id, bik["id"])
    assert polkomtel_body["lines"][0]["md_remaining"] == pytest.approx(50)
    assert bik_body["lines"][0]["md_remaining"] == pytest.approx(50)


@pytest.mark.asyncio
async def test_reprocess_preserves_cost_group_when_one_row_applies_md_and_invoice(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    bik_id, bik_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_multi(monkeypatch, polkomtel_id, bik_id)
    _enable_cost(monkeypatch, polkomtel_id)
    md_group = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_md_line(contracts[0])],
        order_number="SAP 6789012",
    )
    cost_group = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_cost_line(contracts[0])],
        order_number="SAP 6789012",
        is_cost_based=True,
        budget_amount=10000,
    )
    await _create_group(
        app_client,
        app_auth_headers,
        bik_id,
        [_md_line(bik_contract)],
        order_number="7788990",
    )
    finance = await _finance_headers(app_client)

    _set_polkomtel(monkeypatch, -999)
    imported = await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 8, "6789012", 2500)]),
    )
    assert imported["rows"][0]["status"] == "needs_assignment"
    assert imported["rows"][0]["cost_status"] == "unmatched_number"
    _set_polkomtel(monkeypatch, polkomtel_id)

    endpoint = f"/api/md-consumption/imports/{imported['id']}/reprocess-polkomtel"
    applied = await app_client.post(endpoint, json={"apply": True}, headers=finance)
    assert applied.status_code == 200, applied.text

    detail = await app_client.get(
        f"/api/md-consumption/imports/{imported['id']}", headers=finance
    )
    assert detail.status_code == 200, detail.text
    row = detail.json()["rows"][0]
    assert row["status"] == "applied"
    assert row["matched_order_id"] == md_group["lines"][0]["id"]
    assert row["cost_status"] == "applied"

    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import MdConsumptionImportRow

    async with AsyncSessionLocal() as db:
        stored = await db.get(MdConsumptionImportRow, row["id"])
        assert stored is not None
        assert stored.matched_group_id == cost_group["id"]
    md_body = await _group(app_client, app_auth_headers, polkomtel_id, md_group["id"])
    cost_body = await _group(
        app_client, app_auth_headers, polkomtel_id, cost_group["id"]
    )
    assert md_body["lines"][0]["md_remaining"] == pytest.approx(42)
    assert cost_body["budget_remaining"] == pytest.approx(7500)
