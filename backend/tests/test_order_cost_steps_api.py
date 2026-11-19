"""Koszt zamówienia od dnia zmiany stawki Partnera (0740): synchronizacja, widok, lista Finansów.

Zgłoszenie 18.11.2026: zamówienie 01.07–15.12 z jedną stawką kosztu, choć
aneks zmienił stawkę Partnera od 01.09 i od 01.11; zakończone zamówienia
zostały ze stawką sprzed aneksu. Baza wspólna i nieczyszczona: asercje
wyłącznie na własnych wierszach. Kwoty zmyślone.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_cost_step import ClientOrderCostStep
from app.models.contract import Contract, RateUnit
from app.models.contract_candidate_rate import ContractCandidateRate
from app.services.contract_order_sync import sync_orders_cost_from_contract
from app.services.order_revenue_steps import priced_one
from tests.test_b2b_generated_contract_status import _seed_linked_contract

pytestmark = pytest.mark.asyncio

TODAY = business_today()


def m(shift: int, day: int = 1) -> date:
    """Dzień ``day`` miesiąca przesuniętego o ``shift`` od bieżącego."""

    index = TODAY.year * 12 + TODAY.month - 1 + shift
    return date(index // 12, index % 12 + 1, day)


def month_end(shift: int) -> date:
    return date.fromordinal(m(shift + 1).toordinal() - 1)


async def _seed(
    steps: list[tuple[date, str]],
    *,
    start: date,
    end: date,
    order_rate: str,
    status: ClientOrderStatus,
) -> tuple[int, int, int]:
    contract_id, client_id = await _seed_linked_contract("Klient Kosztowy")
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.rate_unit = RateUnit.hourly
        contract.billing_hours_per_month = 168
        contract.rate_candidate = Decimal(steps[-1][1])
        contract.rate_candidate_currency = "PLN"
        for day, rate in steps:
            db.add(
                ContractCandidateRate(
                    contract_id=contract_id, effective_from=day, rate=Decimal(rate)
                )
            )
        order = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title=f"KOSZT-{contract_id}",
            status=status,
            order_type="periodic",
            start_date=start,
            end_date=end,
            rate_client=Decimal("158"),
            rate_candidate=Decimal(order_rate),
            rate_unit=RateUnit.hourly,
            billing_hours_per_month=168,
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
        )
        db.add(order)
        await db.commit()
        return contract_id, client_id, order.id


async def _sync(contract_id: int) -> list[int]:
    async with AsyncSessionLocal() as db:
        contract = await db.scalar(
            select(Contract)
            .where(Contract.id == contract_id)
            .options(selectinload(Contract.candidate_rate_schedule))
        )
        orders = list(
            await db.scalars(
                select(ClientOrder).where(ClientOrder.contract_id == contract_id)
            )
        )
        changed = await sync_orders_cost_from_contract(
            db, contract, orders, today=TODAY
        )
        await db.commit()
        return changed


async def _parts(order_id: int) -> list[tuple[str, float, str]]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(ClientOrderCostStep)
            .where(ClientOrderCostStep.order_id == order_id)
            .order_by(ClientOrderCostStep.effective_from)
        )
        return [
            (r.effective_from.isoformat(), float(r.rate_candidate), r.source)
            for r in rows
        ]


# Jak Nordea 18.11: 120, od dwóch miesięcy 130, od tego miesiąca 140.
NORDEA_STEPS = [(m(-12), "120"), (m(-2), "130"), (m(0), "140")]
LIVE = dict(
    start=m(-4), end=m(1, 15), order_rate="140", status=ClientOrderStatus.active
)
# Jak PFRON 18.11: zakończone zamówienie za poprzedni miesiąc ze stawką sprzed aneksu.
PFRON_STEPS = [(m(-4), "150"), (m(-2), "120")]
PFRON = dict(
    start=m(-1), end=month_end(-1), order_rate="150", status=ClientOrderStatus.completed
)


async def test_live_order_spanning_changes_gets_parts_and_keeps_todays_rate():
    contract_id, _, order_id = await _seed(NORDEA_STEPS, **LIVE)
    assert order_id in await _sync(contract_id)
    assert await _parts(order_id) == [
        (m(-4).isoformat(), 120.0, "contract"),
        (m(-2).isoformat(), 130.0, "contract"),
        (m(0).isoformat(), 140.0, "contract"),
    ]
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, order_id)
        assert float(order.rate_candidate) == 140.0
        # Miesięczne pieniądze czytają koszt z części.
        assert float((await priced_one(db, order, m(-3))).rate_candidate) == 120.0
        assert float((await priced_one(db, order, m(-1))).rate_candidate) == 130.0
        assert float((await priced_one(db, order, m(1))).rate_candidate) == 140.0
    # Drugi przebieg niczego nie zmienia.
    assert order_id not in await _sync(contract_id)


async def test_parts_disappear_when_the_schedule_has_one_rate_in_the_period():
    contract_id, _, order_id = await _seed(NORDEA_STEPS, **LIVE)
    await _sync(contract_id)
    async with AsyncSessionLocal() as db:
        for row in await db.scalars(
            select(ContractCandidateRate).where(
                ContractCandidateRate.contract_id == contract_id,
                ContractCandidateRate.effective_from > m(-12),
            )
        ):
            await db.delete(row)
        await db.commit()
    await _sync(contract_id)
    assert await _parts(order_id) == []


async def test_order_view_shows_cost_parts(app_client, app_auth_headers):
    contract_id, client_id, order_id = await _seed(NORDEA_STEPS, **LIVE)
    await _sync(contract_id)
    resp = await app_client.get(
        f"/api/clients/{client_id}/orders", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    orders = [
        o
        for item in resp.json()["contractors"]
        for o in item["orders"]
        if o["id"] == order_id
    ]
    parts = orders[0]["cost_parts"]
    assert [float(p["rate"]) for p in parts] == [120.0, 130.0, 140.0]
    assert parts[0]["to"] == month_end(-3).isoformat()


async def test_completed_order_with_old_cost_is_listed_and_apply_fixes_it(
    app_client, app_auth_headers
):
    contract_id, _, order_id = await _seed(PFRON_STEPS, **PFRON)
    # Synchronizacja nie rusza zakończonego zamówienia.
    assert order_id not in await _sync(contract_id)

    listed = await app_client.get(
        "/api/finance/order-cost-corrections", headers=app_auth_headers
    )
    assert listed.status_code == 200, listed.text
    [row] = [r for r in listed.json()["rows"] if r["order_id"] == order_id]
    assert [x["month"] for x in row["months"]] == [m(-1).strftime("%Y-%m")]
    assert float(row["estimate"]) == -30 * 168

    resp = await app_client.post(
        f"/api/finance/order-cost-corrections/{order_id}/apply",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        assert float((await db.get(ClientOrder, order_id)).rate_candidate) == 120.0
    assert await _parts(order_id) == []
    again = await app_client.post(
        f"/api/finance/order-cost-corrections/{order_id}/apply",
        headers=app_auth_headers,
    )
    assert again.status_code == 409


async def test_completed_order_spanning_a_change_gets_finance_parts(
    app_client, app_auth_headers
):
    contract_id, _, order_id = await _seed(
        NORDEA_STEPS,
        start=m(-3),
        end=month_end(-2),
        order_rate="120",
        status=ClientOrderStatus.completed,
    )
    resp = await app_client.post(
        f"/api/finance/order-cost-corrections/{order_id}/apply",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert await _parts(order_id) == [
        (m(-3).isoformat(), 120.0, "finance"),
        (m(-2).isoformat(), 130.0, "finance"),
    ]


async def test_dismiss_hides_until_the_schedule_changes(app_client, app_auth_headers):
    contract_id, _, order_id = await _seed(PFRON_STEPS, **PFRON)
    resp = await app_client.post(
        f"/api/finance/order-cost-corrections/{order_id}/dismiss",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    async def listed_ids() -> set[int]:
        r = await app_client.get(
            "/api/finance/order-cost-corrections", headers=app_auth_headers
        )
        return {row["order_id"] for row in r.json()["rows"]}

    assert order_id not in await listed_ids()
    async with AsyncSessionLocal() as db:
        db.add(
            ContractCandidateRate(
                contract_id=contract_id,
                effective_from=m(-1),
                rate=Decimal("110"),
            )
        )
        await db.commit()
    assert order_id in await listed_ids()


async def test_live_order_is_not_on_the_finance_list(app_client, app_auth_headers):
    contract_id, _, order_id = await _seed(NORDEA_STEPS, **LIVE)
    resp = await app_client.post(
        f"/api/finance/order-cost-corrections/{order_id}/apply",
        headers=app_auth_headers,
    )
    assert resp.status_code == 404


async def test_manual_cost_edit_drops_finance_parts(app_client, app_auth_headers):
    """Części w starej jednostce nie mogą przykryć ręcznej zmiany kosztu."""
    contract_id, client_id, order_id = await _seed(
        NORDEA_STEPS,
        start=m(-3),
        end=month_end(-2),
        order_rate="120",
        status=ClientOrderStatus.completed,
    )
    resp = await app_client.post(
        f"/api/finance/order-cost-corrections/{order_id}/apply",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert len(await _parts(order_id)) == 2
    patched = await app_client.patch(
        f"/api/clients/{client_id}/orders/{order_id}",
        json={"rate_candidate": "150"},
        headers=app_auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert await _parts(order_id) == []
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, order_id)
        assert float((await priced_one(db, order, m(-2))).rate_candidate) == 150.0
