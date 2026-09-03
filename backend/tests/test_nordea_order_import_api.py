"""End-to-end transaction semantics for the admin Nordea CSV import."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload


def _csv(name: str, rows: list[tuple[str, date, date, str, str]]) -> bytes:
    header = (
        "Numer zamówienia;Kontraktor;Line manager;Start date;End date;"
        "Stawka  przychodowa;Stawka z umowy ramowej"
    )
    body = [header]
    for number, start, end, revenue, framework in rows:
        body.append(
            ";".join(
                [
                    number,
                    name,
                    "Manager",
                    start.strftime("%d.%m.%Y"),
                    end.strftime("%d.%m.%Y"),
                    revenue,
                    framework,
                ]
            )
        )
    return "\n".join(body).encode("utf-8")


def test_live_order_horizon_prefers_open_ended_order():
    from app.services.nordea_order_import import _live_order_horizon

    today = date(2026, 8, 31)
    horizon = _live_order_horizon(
        [
            SimpleNamespace(
                order_group_id=None,
                status="active",
                start_date=today - timedelta(days=20),
                end_date=today + timedelta(days=30),
            ),
            SimpleNamespace(
                order_group_id=None,
                status="active",
                start_date=today - timedelta(days=10),
                end_date=None,
            ),
        ],
        today=today,
    )

    assert horizon == (today - timedelta(days=20), None)


async def _seed_nordea() -> tuple[int, int, int, str]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:8]
    full_name = f"Jan Importowski {suffix}"
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Nordea Bank ABP {suffix}")
        candidate = Candidate(
            name="Jan",
            lastname=f"Importowski {suffix}",
            email=f"nordea-import-{suffix}@example.com",
        )
        db.add_all([client, candidate])
        await db.commit()
        await db.refresh(client)
        await db.refresh(candidate)
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=date.today() - timedelta(days=365),
            rate_candidate=Decimal("123.456"),
            rate_client=Decimal("150.000"),
            framework_rate=Decimal("110.00"),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title="OLD-NUMBER",
            status=ClientOrderStatus.active,
            start_date=date.today() - timedelta(days=100),
            end_date=date.today() + timedelta(days=100),
            rate_client=Decimal("149.000"),
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return client.id, contract.id, order.id, full_name


async def _seed_ended_nordea() -> tuple[int, int, str, date]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:8]
    previous_end = date.today() - timedelta(days=30)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Nordea Bank ABP {suffix}")
        candidate = Candidate(
            name="Grzegorz",
            lastname=f"Importowy {suffix}",
            email=f"nordea-ended-{suffix}@example.com",
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.ended,
            start_date=date.today() - timedelta(days=365),
            end_date=previous_end,
            client_order_end_date=previous_end,
            rate_candidate=Decimal("123.456"),
            rate_client=Decimal("150.000"),
            framework_rate=Decimal("110.00"),
        )
        db.add(contract)
        await db.commit()
        return (
            client.id,
            contract.id,
            f"{candidate.name} {candidate.lastname}",
            previous_end,
        )


async def test_dry_run_then_apply_is_atomic_and_idempotent(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.contract import Contract

    client_id, contract_id, original_order_id, name = await _seed_nordea()
    current_start = date.today() - timedelta(days=180)
    current_end = date.today() + timedelta(days=2)
    future_start = date.today() + timedelta(days=3)
    future_end = date.today() + timedelta(days=180)
    content = _csv(
        name,
        [
            ("279411", current_start, current_end, "185", "178"),
            ("285838", future_start, future_end, "195,8", "190,4"),
        ],
    )
    url = f"/api/admin/clients/{client_id}/nordea-orders/import"

    preview = await app_client.post(
        url,
        params={"dry_run": "true"},
        headers=app_auth_headers,
        files={"file": ("Nordea.csv", content, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["orders_updated"] == 1
    assert preview.json()["orders_created"] == 1
    assert preview.json()["cost_rates_changed"] == 0

    # Dry-run must leave both order data and the contract cost rate untouched.
    async with AsyncSessionLocal() as db:
        unchanged = await db.get(ClientOrder, original_order_id)
        contract = await db.get(Contract, contract_id)
        assert unchanged.title == "OLD-NUMBER"
        assert unchanged.rate_client == Decimal("149.000")
        assert contract.rate_candidate == Decimal("123.456")

    applied = await app_client.post(
        url,
        params={"dry_run": "false"},
        headers=app_auth_headers,
        files={"file": ("Nordea.csv", content, "text/csv")},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True

    async with AsyncSessionLocal() as db:
        contract = await db.scalar(
            select(Contract)
            .options(
                selectinload(Contract.client_orders),
                selectinload(Contract.framework_rate_schedule),
            )
            .where(Contract.id == contract_id)
        )
        assert contract is not None
        orders = {order.title: order for order in contract.client_orders}
        assert set(orders) == {"279411", "285838"}
        assert orders["279411"].id == original_order_id
        assert orders["279411"].rate_client == Decimal("185.000")
        assert orders["285838"].start_date == future_start
        assert contract.rate_candidate == Decimal("123.456")
        assert contract.framework_rate == Decimal("178.00")
        assert {
            (step.effective_from, step.rate)
            for step in contract.framework_rate_schedule
        } == {(current_start, Decimal("178.00")), (future_start, Decimal("190.40"))}

    repeated = await app_client.post(
        url,
        params={"dry_run": "false"},
        headers=app_auth_headers,
        files={"file": ("Nordea.csv", content, "text/csv")},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["orders_created"] == 0
    assert repeated.json()["orders_updated"] == 0
    assert repeated.json()["orders_unchanged"] == 2
    assert repeated.json()["framework_created"] == 0
    assert repeated.json()["framework_unchanged"] == 2


async def test_apply_is_blocked_when_a_file_person_is_unmatched(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id, _, _, _ = await _seed_nordea()
    content = _csv(
        "Nie Istnieje",
        [
            (
                "999999",
                date.today(),
                date.today() + timedelta(days=30),
                "150",
                "120",
            )
        ],
    )
    response = await app_client.post(
        f"/api/admin/clients/{client_id}/nordea-orders/import",
        params={"dry_run": "false"},
        headers=app_auth_headers,
        files={"file": ("Nordea.csv", content, "text/csv")},
    )
    assert response.status_code == 409, response.text
    assert "nie został zapisany" in response.text


async def test_nordea_apply_revives_an_ended_contract_but_preview_rolls_back(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.client_order import ClientOrder
    from app.models.contract import Contract, ContractStatus

    client_id, contract_id, name, previous_end = await _seed_ended_nordea()
    new_end = date.today() + timedelta(days=120)
    content = _csv(
        name,
        [
            (
                "285493",
                date.today() - timedelta(days=2),
                new_end,
                "185",
                "178",
            )
        ],
    )
    url = f"/api/admin/clients/{client_id}/nordea-orders/import"

    preview = await app_client.post(
        url,
        params={"dry_run": "true"},
        headers=app_auth_headers,
        files={"file": ("Nordea.csv", content, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["contracts_revived"] == 1

    async with AsyncSessionLocal() as db:
        unchanged = await db.get(Contract, contract_id)
        assert unchanged is not None
        assert unchanged.status == ContractStatus.ended
        assert unchanged.end_date == previous_end
        assert (
            await db.scalar(
                select(ClientOrder.id).where(ClientOrder.contract_id == contract_id)
            )
            is None
        )

    applied = await app_client.post(
        url,
        params={"dry_run": "false"},
        headers=app_auth_headers,
        files={"file": ("Nordea.csv", content, "text/csv")},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["contracts_revived"] == 1

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None
        assert contract.status == ContractStatus.active
        # Reguła 09.2026: umowa wraca jako bezterminowa, a data z zamówienia
        # ląduje w „Końcu zamówienia u klienta" (tu śledzonym w seedzie).
        assert contract.end_date is None
        assert contract.client_order_end_date == new_end
        audit = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == contract_id,
                Activity.action == "contract_reopened",
            )
        )
        assert audit is not None
        assert audit.details["from_status"] == "ended"
        assert audit.details["to_status"] == "active"


async def test_nordea_revives_once_with_the_widest_overlapping_order_horizon(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    client_id, contract_id, name, _ = await _seed_ended_nordea()
    shorter_end = date.today() + timedelta(days=30)
    farther_end = date.today() + timedelta(days=180)
    content = _csv(
        name,
        [
            (
                "285493-SHORT",
                date.today() - timedelta(days=20),
                shorter_end,
                "185",
                "178",
            ),
            (
                "285493-LONG",
                date.today() - timedelta(days=10),
                farther_end,
                "190",
                "180",
            ),
        ],
    )

    applied = await app_client.post(
        f"/api/admin/clients/{client_id}/nordea-orders/import",
        params={"dry_run": "false"},
        headers=app_auth_headers,
        files={"file": ("Nordea.csv", content, "text/csv")},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["contracts_revived"] == 1
    assert len(applied.json()["overlap_warnings"]) == 1

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None
        assert contract.status == ContractStatus.active
        assert contract.end_date is None
        # Najszerszy horyzont z nachodzących zamówień — na właściwym polu.
        assert contract.client_order_end_date == farther_end


async def test_nordea_future_order_does_not_revive_contract_early(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    client_id, contract_id, name, previous_end = await _seed_ended_nordea()
    content = _csv(
        name,
        [
            (
                "285623",
                date.today() + timedelta(days=10),
                date.today() + timedelta(days=120),
                "185",
                "178",
            )
        ],
    )

    applied = await app_client.post(
        f"/api/admin/clients/{client_id}/nordea-orders/import",
        params={"dry_run": "false"},
        headers=app_auth_headers,
        files={"file": ("Nordea.csv", content, "text/csv")},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["contracts_revived"] == 0

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None
        assert contract.status == ContractStatus.ended
        assert contract.end_date == previous_end


async def test_admin_can_read_the_cross_client_repair_audit(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    response = await app_client.get(
        "/api/admin/audits/live-order-contract-repair",
        headers=app_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["key"] == "0250_live_order_contract_repair"
    assert body["value"]["revision"] == "0250_live_order_contract_repair"
    assert "audited_stale_contracts" in body["value"]
    assert "analogous_contracts_not_mutated" in body["value"]
    assert "by_client" in body["value"]
