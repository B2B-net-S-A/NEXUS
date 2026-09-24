"""BIK: zamówienie kończy wyczerpanie limitów MD WSZYSTKICH osób, nie data.

Zużycie wpisuje istniejący mechanizm (``upsert_consumption`` — ten sam, który
woła import z Finansów), więc testy idą przez niego, a nie przez ręczne
ustawianie statusów.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.scheduling import business_today
from tests.test_explicit_order_types import _md_line, _seed_client_with_contracts


def _month():
    return business_today().strftime("%Y-%m")


def _month_end(day):
    import calendar

    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


async def _bik_group(app_client, headers, monkeypatch, *, bik: bool = True):
    client_id, contracts = await _seed_client_with_contracts(2)
    if bik:
        monkeypatch.setenv("BIK_ORDER_CLIENT_IDS", str(client_id))
    else:
        monkeypatch.delenv("BIK_ORDER_CLIENT_IDS", raising=False)
    response = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        headers=headers,
        json={
            "order_number": f"45000{client_id}",
            "start_date": (business_today() - timedelta(days=5)).isoformat(),
            "order_type": "md",
            "md_budget_mode": "per_person",
            "lines": [_md_line(contracts[0], 35), _md_line(contracts[1], 42)],
        },
    )
    assert response.status_code == 201, response.text
    group = response.json()
    if group["status"] == "draft":
        activated = await app_client.patch(
            f"/api/clients/{client_id}/order-groups/{group['id']}",
            headers=headers,
            json={"status": "active"},
        )
        assert activated.status_code == 200, activated.text
        group = activated.json()
    assert group["status"] == "active"
    return client_id, group


async def _consume(line_id: int, md: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.services.client_order_lines import upsert_consumption

    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, line_id)
        await upsert_consumption(
            db, order=order, period_month=_month(), md_reported=Decimal(md)
        )
        await db.commit()


async def _group_state(group_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.client_order_group import ClientOrderGroup

    async with AsyncSessionLocal() as db:
        group = await db.get(ClientOrderGroup, group_id)
        lines = (
            (
                await db.execute(
                    select(ClientOrder)
                    .where(ClientOrder.order_group_id == group_id)
                    .order_by(ClientOrder.id)
                )
            )
            .scalars()
            .all()
        )
        return group, [line.status.value for line in lines]


@pytest.mark.asyncio
async def test_order_ends_only_when_the_last_person_exhausts_the_limit(
    app_client, app_auth_headers, monkeypatch
):
    from app.services.order_md_exhaustion import MD_EXHAUSTED_CLOSURE_REASON

    _client_id, group = await _bik_group(app_client, app_auth_headers, monkeypatch)
    first, second = (line["id"] for line in group["lines"])

    await _consume(first, "35")
    state, lines = await _group_state(group["id"])
    assert lines == ["completed", "active"]
    # Jedna osoba ma jeszcze MD — zamówienie trwa.
    assert state.status == "active"

    await _consume(second, "42")
    state, lines = await _group_state(group["id"])
    assert lines == ["completed", "completed"]
    assert state.status == "completed"
    assert state.closure_reason == MD_EXHAUSTED_CLOSURE_REASON
    # Koniec miesiąca zejścia, które wyczerpało pulę (ticket 4500030067).
    today = business_today()
    assert state.closure_date == _month_end(today)
    assert state.closed_by_user_id is None
    # Koniec wyznacza limit, nie data — zamówienie zostaje bezterminowe.
    assert state.end_date is None


@pytest.mark.asyncio
async def test_consumption_correction_reopens_an_automatically_ended_order(
    app_client, app_auth_headers, monkeypatch
):
    _client_id, group = await _bik_group(app_client, app_auth_headers, monkeypatch)
    first, second = (line["id"] for line in group["lines"])
    await _consume(first, "35")
    await _consume(second, "42")
    state, _ = await _group_state(group["id"])
    assert state.status == "completed"

    # Finanse poprawiają raport: drugiej osobie zostało 12 MD.
    await _consume(second, "30")
    state, lines = await _group_state(group["id"])
    assert lines == ["completed", "active"]
    assert state.status == "active"
    assert state.closure_date is None and state.closure_reason is None


@pytest.mark.asyncio
async def test_manual_reopen_of_exhausted_order_explains_what_to_do(
    app_client, app_auth_headers, monkeypatch
):
    client_id, group = await _bik_group(app_client, app_auth_headers, monkeypatch)
    for line in group["lines"]:
        await _consume(line["id"], str(line["md_total"]))
    response = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/reopen",
        headers=app_auth_headers,
    )
    assert response.status_code == 409, response.text
    assert "wyczerpali limit MD" in response.json()["detail"]


@pytest.mark.asyncio
async def test_other_clients_orders_also_close_when_the_pool_is_used_up(
    app_client, app_auth_headers, monkeypatch
):
    """Od ticketu 4500030067 reguła dotyczy KAŻDEGO zamówienia MD per osoba,
    nie tylko klientów z polityką BIK."""
    _client_id, group = await _bik_group(
        app_client, app_auth_headers, monkeypatch, bik=False
    )
    for line in group["lines"]:
        await _consume(line["id"], str(line["md_total"]))
    state, lines = await _group_state(group["id"])
    assert lines == ["completed", "completed"]
    assert state.status == "completed"


@pytest.mark.asyncio
async def test_pending_decision_zeroed_by_a_later_import_closes_itself_and_the_order(
    app_client, app_auth_headers, monkeypatch
):
    """Ticket 4500030067: sprawa założona przy 13,75 MD, import sierpnia
    zjadł resztę — sprawa zamyka się sama, zamówienie idzie do zakończonych
    z datą końca miesiąca zejścia."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_offboarding import ClientOrderOffboardingCase

    client_id, group = await _bik_group(app_client, app_auth_headers, monkeypatch)
    first, second = (line["id"] for line in group["lines"])
    await _consume(first, "35")
    async with AsyncSessionLocal() as db:
        departed = await db.get(ClientOrder, second)
        departed.status = ClientOrderStatus.completed
        db.add(
            ClientOrderOffboardingCase(
                contract_id=departed.contract_id,
                order_id=second,
                order_group_id=group["id"],
                client_id=client_id,
                effective_date=business_today(),
                uses_shared_md_pool=False,
                remaining_md_snapshot=Decimal("13.75"),
            )
        )
        await db.commit()
    state, _ = await _group_state(group["id"])
    assert state.status == "active"

    await _consume(second, "42")

    state, _ = await _group_state(group["id"])
    assert state.status == "completed"
    assert state.closure_date == _month_end(business_today())
    async with AsyncSessionLocal() as db:
        case = await db.scalar(
            select(ClientOrderOffboardingCase).where(
                ClientOrderOffboardingCase.order_id == second
            )
        )
        assert case.status == "resolved"
        assert case.resolution == "remove"
        assert case.resolution_payload["reason"] == "pool_used_up"


@pytest.mark.asyncio
async def test_listing_the_tab_catches_up_orders_exhausted_before_the_policy(
    app_client, app_auth_headers, monkeypatch
):
    client_id, group = await _bik_group(
        app_client, app_auth_headers, monkeypatch, bik=False
    )
    for line in group["lines"]:
        await _consume(line["id"], str(line["md_total"]))
    monkeypatch.setenv("BIK_ORDER_CLIENT_IDS", str(client_id))
    response = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    assert response.status_code == 200, response.text
    listed = next(g for g in response.json()["groups"] if g["id"] == group["id"])
    assert listed["status"] == "completed"


@pytest.mark.asyncio
async def test_person_without_a_limit_keeps_the_order_open(
    app_client, app_auth_headers, monkeypatch
):
    """Osoba bez wpisanego limitu MD niczego nie „wyczerpała"."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    _client_id, group = await _bik_group(app_client, app_auth_headers, monkeypatch)
    first, second = (line["id"] for line in group["lines"])
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, second)
        line.md_total = None
        line.md_remaining = None
        line.md_input_mode = None
        line.md_input_value = None
        await db.commit()

    await _consume(first, "35")
    state, lines = await _group_state(group["id"])
    assert lines == ["completed", "active"]
    assert state.status == "active"
