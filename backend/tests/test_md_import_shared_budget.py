"""Import wspólnej puli MD Cyfrowego Polsatu i bezpieczne kolizje numerów."""

from __future__ import annotations

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

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

pytestmark = pytest.mark.asyncio


def _enable_cyfrowy_polsat(monkeypatch, client_id: int) -> None:
    from app.services import cyfrowy_polsat_orders

    monkeypatch.setattr(cyfrowy_polsat_orders, "CYFROWY_POLSAT_CLIENT_ID", client_id)


async def _create_shared_md_group(
    app_client: AsyncClient,
    headers: dict,
    client_id: int,
    contract_id: int,
    *,
    order_number: str,
    budget: Decimal | int = 50,
) -> dict:
    return await _create_group(
        app_client,
        headers,
        client_id,
        [_cost_line(contract_id)],
        order_number=order_number,
        is_md_budget_based=True,
        md_budget_total=budget,
    )


async def _client_and_contract_for_existing_candidate(
    source_contract_id: int,
) -> tuple[int, int]:
    """Drugi klient tej samej osoby — potrzebny do testu zakazu fallbacku."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        source = await db.get(Contract, source_contract_id)
        assert source is not None
        client = Client(name=f"ImportCollision-{source_contract_id}-{id(source)}")
        db.add(client)
        await db.flush()
        contract = Contract(
            candidate_id=source.candidate_id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=30),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        db.add(contract)
        await db.commit()
        return client.id, contract.id


async def _group_from_list(
    app_client: AsyncClient, headers: dict, client_id: int, group_id: int
) -> dict:
    response = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert response.status_code == 200, response.text
    return next(group for group in response.json()["groups"] if group["id"] == group_id)


async def _shared_consumption_count(*group_ids: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroupMdConsumption

    async with AsyncSessionLocal() as db:
        value = await db.scalar(
            select(func.count(ClientOrderGroupMdConsumption.id)).where(
                ClientOrderGroupMdConsumption.group_id.in_(group_ids)
            )
        )
        return int(value or 0)


def _sheet_without_recognized_md(name: str, notes: str) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Imię i nazwisko", "Godziny", "Uwagi", "Faktura"])
    sheet.append([name, 80, notes, 1000])
    payload = io.BytesIO()
    workbook.save(payload)
    return payload.getvalue()


async def test_shared_md_requires_an_explicitly_recognized_md_column(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_cyfrowy_polsat(monkeypatch, client_id)
    group = await _create_shared_md_group(
        app_client,
        app_auth_headers,
        client_id,
        contracts[0],
        order_number="4500810000",
    )
    finance = await _finance_headers(app_client)

    response = await app_client.post(
        "/api/md-consumption/imports",
        files={
            "file": (
                "raport.xlsx",
                _sheet_without_recognized_md(names[0], "SAP 4500810000"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"period_month": _TODAY.strftime("%Y-%m")},
        headers=finance,
    )

    assert response.status_code == 422, response.text
    assert await _shared_consumption_count(group["id"]) == 0


async def test_shared_md_matches_notes_and_consultant_without_false_cost_error(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_cyfrowy_polsat(monkeypatch, client_id)
    group = await _create_shared_md_group(
        app_client,
        app_auth_headers,
        client_id,
        contracts[0],
        order_number="4500810001",
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client,
        finance,
        # Faktura jest dodatnia celowo: typ shared-MD ma zakończyć routing,
        # a nie dostać równolegle `cost_status=unmatched_number`.
        _sheet([(names[0], 12, "SAP 4500810001", 1234)]),
    )

    assert detail["rows_applied"] == 1
    row = detail["rows"][0]
    assert row["status"] == "applied"
    assert row["matched_order_id"] == group["lines"][0]["id"]
    assert row["matched"]["order_number"] == "4500810001"
    assert row["cost_status"] is None

    body = await _group_from_list(app_client, app_auth_headers, client_id, group["id"])
    assert body["md_budget_used"] == pytest.approx(12.0)
    assert body["md_budget_remaining"] == pytest.approx(38.0)

    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import MdConsumptionImportRow

    async with AsyncSessionLocal() as db:
        stored = await db.get(MdConsumptionImportRow, row["id"])
        assert stored is not None
        assert stored.matched_group_id == group["id"]


async def test_shared_md_duplicate_rows_sum_and_reimport_overwrites_month(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_cyfrowy_polsat(monkeypatch, client_id)
    group = await _create_shared_md_group(
        app_client,
        app_auth_headers,
        client_id,
        contracts[0],
        order_number="4500810002",
    )
    finance = await _finance_headers(app_client)
    payload = _sheet(
        [
            (names[0], 5, "SAP 4500810002", 0),
            (names[0], 7, "SAP 4500810002", 0),
        ]
    )

    first = await _import_sheet(app_client, finance, payload)
    second = await _import_sheet(app_client, finance, payload)
    assert first["rows_applied"] == second["rows_applied"] == 2

    body = await _group_from_list(app_client, app_auth_headers, client_id, group["id"])
    assert body["md_budget_used"] == pytest.approx(12.0)
    assert body["md_budget_remaining"] == pytest.approx(38.0)
    assert await _shared_consumption_count(group["id"]) == 1


async def test_shared_md_clamps_at_zero_warns_and_exhausts_group(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, names = await _seed_client_with_contracts(2)
    _enable_cyfrowy_polsat(monkeypatch, client_id)
    group = await _create_shared_md_group(
        app_client,
        app_auth_headers,
        client_id,
        contracts[0],
        order_number="4500810003",
        budget=10,
    )
    finance = await _finance_headers(app_client)

    await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 15, "SAP 4500810003", 0)]),
    )

    body = await _group_from_list(app_client, app_auth_headers, client_id, group["id"])
    assert body["md_budget_used"] == pytest.approx(15.0)
    assert body["md_budget_remaining"] == pytest.approx(0.0)
    assert body["status"] == "exhausted"
    assert body["can_add_consultant"] is False

    events_response = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group['id']}/events",
        headers=app_auth_headers,
    )
    assert events_response.status_code == 200, events_response.text
    events = events_response.json()["events"]
    imported = next(event for event in events if event["event_type"] == "import_md")
    assert imported["payload"]["md_over_budget"] == "5.000000"
    assert "przekracza dostępny budżet" in imported["description"]
    assert any(event["event_type"] == "wyczerpanie" for event in events)

    blocked = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines",
        json=_cost_line(contracts[1]),
        headers=app_auth_headers,
    )
    assert blocked.status_code == 409, blocked.text


async def test_shared_md_bad_or_ambiguous_number_never_writes_or_falls_back(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    shared_client, contracts, names = await _seed_client_with_contracts(1)
    legacy_client, legacy_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_cyfrowy_polsat(monkeypatch, shared_client)
    _enable_multi(monkeypatch, legacy_client)

    shared_a = await _create_shared_md_group(
        app_client,
        app_auth_headers,
        shared_client,
        contracts[0],
        order_number="4500810004",
    )
    shared_b = await _create_shared_md_group(
        app_client,
        app_auth_headers,
        shared_client,
        contracts[0],
        order_number="4500810004",
    )
    legacy = await _create_group(
        app_client,
        app_auth_headers,
        legacy_client,
        [_md_line(legacy_contract, input_value=50)],
        order_number="4500810999",
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client,
        finance,
        _sheet(
            [
                (names[0], 5, "SAP 9999999999", 0),
                # Dwie aktywne grupy z tym samym numerem i konsultantem.
                (names[0], 7, "SAP 4500810004", 0),
            ]
        ),
    )

    assert [row["status"] for row in detail["rows"]] == ["unmatched", "unmatched"]
    assert all(row["matched_order_id"] is None for row in detail["rows"])
    assert await _shared_consumption_count(shared_a["id"], shared_b["id"]) == 0

    legacy_body = await _group_from_list(
        app_client, app_auth_headers, legacy_client, legacy["id"]
    )
    assert legacy_body["lines"][0]["md_remaining"] == pytest.approx(50.0)


async def test_cost_duplicate_number_across_clients_uses_consultant_too(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    (
        polkomtel_id,
        polkomtel_contracts,
        polkomtel_names,
    ) = await _seed_client_with_contracts(1)
    cyfrowy_id, cyfrowy_contracts, _ = await _seed_client_with_contracts(1)
    _enable_cyfrowy_polsat(monkeypatch, cyfrowy_id)
    _enable_multi(monkeypatch, polkomtel_id)
    _enable_cost(monkeypatch, polkomtel_id)

    polkomtel = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_cost_line(polkomtel_contracts[0])],
        order_number="4500810005",
        is_cost_based=True,
        budget_amount=10000,
    )
    cyfrowy = await _create_group(
        app_client,
        app_auth_headers,
        cyfrowy_id,
        [_cost_line(cyfrowy_contracts[0])],
        order_number="4500810005",
        is_cost_based=True,
        budget_amount=10000,
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client,
        finance,
        _sheet([(polkomtel_names[0], 0, "SAP 4500810005", 2500)]),
    )
    assert detail["rows"][0]["cost_status"] == "applied"

    polkomtel_body = await _group_from_list(
        app_client, app_auth_headers, polkomtel_id, polkomtel["id"]
    )
    cyfrowy_body = await _group_from_list(
        app_client, app_auth_headers, cyfrowy_id, cyfrowy["id"]
    )
    assert polkomtel_body["budget_remaining"] == pytest.approx(7500.0)
    assert cyfrowy_body["budget_remaining"] == pytest.approx(10000.0)


async def test_cost_duplicate_number_and_consultant_is_ambiguous_no_guess(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    polkomtel_id, contracts, names = await _seed_client_with_contracts(1)
    cyfrowy_id, cyfrowy_contract = await _client_and_contract_for_existing_candidate(
        contracts[0]
    )
    _enable_cyfrowy_polsat(monkeypatch, cyfrowy_id)
    _enable_multi(monkeypatch, polkomtel_id)
    _enable_cost(monkeypatch, polkomtel_id)

    first = await _create_group(
        app_client,
        app_auth_headers,
        polkomtel_id,
        [_cost_line(contracts[0])],
        order_number="4500810006",
        is_cost_based=True,
        budget_amount=10000,
    )
    second = await _create_group(
        app_client,
        app_auth_headers,
        cyfrowy_id,
        [_cost_line(cyfrowy_contract)],
        order_number="4500810006",
        is_cost_based=True,
        budget_amount=10000,
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 0, "SAP 4500810006", 2500)]),
    )
    assert detail["rows"][0]["cost_status"] == "unmatched_consultant"

    first_body = await _group_from_list(
        app_client, app_auth_headers, polkomtel_id, first["id"]
    )
    second_body = await _group_from_list(
        app_client, app_auth_headers, cyfrowy_id, second["id"]
    )
    assert first_body["budget_remaining"] == pytest.approx(10000.0)
    assert second_body["budget_remaining"] == pytest.approx(10000.0)
