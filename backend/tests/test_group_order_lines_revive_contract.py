"""Every group-order path that creates an active line keeps Contract coherent."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from tests.test_multi_consultant_orders import (
    _TODAY,
    _create_group,
    _enable_for,
    _line_payload,
    _seed_client_with_contracts,
)


async def _mark_ended(contract_id: int) -> date:
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    previous_end = _TODAY - timedelta(days=20)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None
        contract.status = ContractStatus.ended
        contract.end_date = previous_end
        contract.client_order_end_date = previous_end
        await db.commit()
    return previous_end


async def _assert_revived_with_order_end(
    contract_id: int, order_end: date | None
) -> None:
    """Wskrzeszony kontrakt: aktywny i BEZTERMINOWY, data z zamówienia osobno.

    Reguła zakładki „Zakończeni" (09.2026): zamówienie nigdy nie ustawia daty
    końca UMOWY — inaczej po upływie jego okresu nocny cron kończy umowę
    i osoba wraca do „Zakończonych" tylko dlatego, że skończył się okres
    zamówienia. Data z zamówienia ma swoje miejsce w „Końcu zamówienia
    u klienta" (``client_order_end_date``), tu śledzonym przez ``_mark_ended``.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None
        assert contract.status == ContractStatus.active
        assert contract.end_date is None
        assert contract.client_order_end_date == order_end


async def test_create_group_with_live_line_revives_ended_contract(
    app_client, app_auth_headers, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    await _mark_ended(contracts[0])
    new_end = _TODAY + timedelta(days=60)

    created = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": "GROUP-REVIVE-CREATE",
            "start_date": (_TODAY - timedelta(days=10)).isoformat(),
            "end_date": new_end.isoformat(),
            "lines": [_line_payload(contracts[0], end_date=new_end.isoformat())],
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    await _assert_revived_with_order_end(contracts[0], new_end)


async def test_add_live_line_revives_its_ended_contract(
    app_client, app_auth_headers, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    await _mark_ended(contracts[1])
    new_end = _TODAY + timedelta(days=75)

    added = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines",
        json=_line_payload(contracts[1], end_date=new_end.isoformat()),
        headers=app_auth_headers,
    )
    assert added.status_code == 201, added.text
    await _assert_revived_with_order_end(contracts[1], new_end)


async def test_swap_to_live_successor_revives_ended_contract(
    app_client, app_auth_headers, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)
    new_end = _TODAY + timedelta(days=90)
    group = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": "GROUP-REVIVE-SWAP",
            "start_date": (_TODAY - timedelta(days=10)).isoformat(),
            "end_date": new_end.isoformat(),
            "lines": [_line_payload(contracts[0], end_date=new_end.isoformat())],
        },
        headers=app_auth_headers,
    )
    assert group.status_code == 201, group.text
    await _mark_ended(contracts[1])

    swapped = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group.json()['id']}"
        f"/lines/{group.json()['lines'][0]['id']}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 800,
            "rate_revenue": 950,
            "swap_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert swapped.status_code == 201, swapped.text
    await _assert_revived_with_order_end(contracts[1], new_end)


async def test_scheduled_group_revives_contract_only_when_line_materializes(
    app_client, app_auth_headers, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus
    from app.services.order_group_lifecycle import materialize_scheduled_order_groups

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    previous_end = await _mark_ended(contracts[0])
    future_start = _TODAY + timedelta(days=14)

    created = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": "GROUP-REVIVE-SCHEDULED",
            "start_date": future_start.isoformat(),
            "lines": [_line_payload(contracts[0], start_date=future_start.isoformat())],
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "scheduled"
    assert created.json()["lines"][0]["status"] == "draft"

    async with AsyncSessionLocal() as db:
        before = await db.get(Contract, contracts[0])
        assert before is not None
        assert before.status == ContractStatus.ended
        assert before.end_date == previous_end

        changed = await materialize_scheduled_order_groups(
            db, client_id=client_id, today=future_start
        )
        assert changed == 1
        await db.commit()

    await _assert_revived_with_order_end(contracts[0], None)
    async with AsyncSessionLocal() as db:
        line_status = await db.scalar(
            select(ClientOrder.status).where(
                ClientOrder.order_group_id == created.json()["id"]
            )
        )
        assert line_status == ClientOrderStatus.active
