"""Anulowanie zamówienia MD/kosztowego z przywróceniem (0359, PR2).

Pokrywa:

- anulowanie: grupa ``cancelled`` pamięta stan sprzed anulowania, linie
  ``cancelled``, zdarzenie ``order_cancelled`` niesie statusy linii;
- przywrócenie: grupa i linie wracają do stanu sprzed anulowania;
- 409 przy rozliczeniach (MD, faktury) — nic się nie zmienia;
- 409 przy podwójnym anulowaniu i przywróceniu nieanulowanego;
- anulowane zamówienie nie przyjmuje edycji ani zakończenia, „Przywróć”
  z archiwum (reopen) je odrzuca;
- role bez cyklu życia zamówienia → 403.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.scheduling import business_today
from app.core.database import AsyncSessionLocal
from app.models.client_order import ClientOrder
from app.models.client_order_group import ClientOrderGroup, ClientOrderGroupEvent
from app.models.md_consumption import (
    CONSUMPTION_SOURCE_IMPORT,
    ClientOrderMdConsumption,
)
from tests.test_order_lifecycle_and_cost import (
    _cost_line,
    _create_group,
    _enable_cost,
    _enable_multi,
    _headers_for,
    _md_line,
    _seed_client_with_contracts,
    _seed_user,
)

pytestmark = pytest.mark.asyncio


def _url(client_id: int, group_id: int, action: str) -> str:
    return f"/api/clients/{client_id}/order-groups/{group_id}/{action}"


async def _group_state(group_id: int) -> tuple[ClientOrderGroup, list[ClientOrder]]:
    async with AsyncSessionLocal() as db:
        group = await db.get(ClientOrderGroup, group_id)
        lines = list(
            (
                await db.scalars(
                    select(ClientOrder)
                    .where(ClientOrder.order_group_id == group_id)
                    .order_by(ClientOrder.id)
                )
            ).all()
        )
        return group, lines


@pytest.mark.parametrize("cost_based", [False, True], ids=["md", "kosztowe"])
async def test_cancel_then_restore_round_trips_group_and_lines(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, cost_based: bool
):
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    if cost_based:
        _enable_cost(monkeypatch, client_id)
        group = await _create_group(
            app_client,
            app_auth_headers,
            client_id,
            [_cost_line(contracts[0]), _cost_line(contracts[1])],
            is_cost_based=True,
            budget_amount=50000,
        )
    else:
        group = await _create_group(
            app_client,
            app_auth_headers,
            client_id,
            [_md_line(contracts[0]), _md_line(contracts[1])],
        )
    before, before_lines = await _group_state(group["id"])
    assert before.status == "active"
    line_statuses = [line.status.value for line in before_lines]

    resp = await app_client.post(
        _url(client_id, group["id"], "cancel"),
        json={"reason": "Klient wycofał zamówienie"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["status_label"] == "Anulowane"
    assert body["status_before_cancel"] == "active"
    assert body["cancellation_reason"] == "Klient wycofał zamówienie"

    cancelled, cancelled_lines = await _group_state(group["id"])
    assert cancelled.status == "cancelled"
    assert cancelled.status_before_cancel == "active"
    assert {line.status.value for line in cancelled_lines} == {"cancelled"}
    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(ClientOrderGroupEvent).where(
                ClientOrderGroupEvent.group_id == group["id"],
                ClientOrderGroupEvent.event_type == "order_cancelled",
            )
        )
        assert event is not None
        assert [e["previous_status"] for e in event.payload["lines"]] == line_statuses

    restored = await app_client.post(
        _url(client_id, group["id"], "restore"), headers=app_auth_headers
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "active"
    assert restored.json()["status_before_cancel"] is None

    after, after_lines = await _group_state(group["id"])
    assert after.status == "active"
    assert after.status_before_cancel is None and after.cancelled_at is None
    assert [line.status.value for line in after_lines] == line_statuses


async def test_cancel_with_settlements_is_409_and_changes_nothing(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    line_id = group["lines"][0]["id"]
    async with AsyncSessionLocal() as db:
        db.add(
            ClientOrderMdConsumption(
                order_id=line_id,
                period_month=business_today().strftime("%Y-%m"),
                md_reported=Decimal("5"),
                source=CONSUMPTION_SOURCE_IMPORT,
            )
        )
        await db.commit()

    resp = await app_client.post(
        _url(client_id, group["id"], "cancel"), json={}, headers=app_auth_headers
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "order_group_has_settlements"
    assert any("MD" in b for b in detail["blockers"])

    group_row, lines = await _group_state(group["id"])
    assert group_row.status == "active"
    assert group_row.status_before_cancel is None
    assert lines[0].status.value == "active"


async def test_double_cancel_and_restore_of_live_order_are_409(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )

    not_cancelled = await app_client.post(
        _url(client_id, group["id"], "restore"), headers=app_auth_headers
    )
    assert not_cancelled.status_code == 409

    first = await app_client.post(
        _url(client_id, group["id"], "cancel"), json={}, headers=app_auth_headers
    )
    assert first.status_code == 200
    second = await app_client.post(
        _url(client_id, group["id"], "cancel"), json={}, headers=app_auth_headers
    )
    assert second.status_code == 409


async def test_cancelled_order_is_read_only_until_restored(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    assert (
        await app_client.post(
            _url(client_id, group["id"], "cancel"), json={}, headers=app_auth_headers
        )
    ).status_code == 200

    patch = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}",
        json={"notes": "po anulowaniu"},
        headers=app_auth_headers,
    )
    assert patch.status_code == 409
    close = await app_client.post(
        _url(client_id, group["id"], "close"),
        json={"closure_date": business_today().isoformat()},
        headers=app_auth_headers,
    )
    assert close.status_code == 409
    reopen = await app_client.post(
        _url(client_id, group["id"], "reopen"), headers=app_auth_headers
    )
    assert reopen.status_code == 409
    assert "Przywróć anulowane" in reopen.json()["detail"]

    group_row, _ = await _group_state(group["id"])
    assert group_row.status == "cancelled"
    assert group_row.notes != "po anulowaniu"


@pytest.mark.parametrize("role", ["head_of_recruitment", "recruiter"])
async def test_cancel_and_restore_forbidden_for_excluded_roles(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, role: str
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    _, email, password = await _seed_user(role, client_id)
    headers = await _headers_for(app_client, email, password)

    for action in ("cancel", "restore"):
        resp = await app_client.post(
            _url(client_id, group["id"], action), json={}, headers=headers
        )
        assert resp.status_code == 403, f"{role} {action} -> {resp.status_code}"


async def _event_count(group_id: int, event_type: str) -> int:
    async with AsyncSessionLocal() as db:
        return len(
            (
                await db.scalars(
                    select(ClientOrderGroupEvent.id).where(
                        ClientOrderGroupEvent.group_id == group_id,
                        ClientOrderGroupEvent.event_type == event_type,
                    )
                )
            ).all()
        )


async def test_parallel_close_and_reopen_happen_once(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Audyt 25.09.2026: status sprawdzany dopiero pod blokadą nagłówka.

    Dwa równoległe „Zakończ” przechodziły oba (status czytany przed
    blokadami) — drugie zapisywało drugie „Zakończono zamówienie” z pustą
    listą linii, a „Przywróć” odtwarzało wtedy stan z tego pustego wpisu.
    """
    import asyncio

    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0]), _md_line(contracts[1])],
    )
    closure = business_today().isoformat()

    first, second = await asyncio.gather(
        app_client.post(
            _url(client_id, group["id"], "close"),
            json={"closure_date": closure},
            headers=app_auth_headers,
        ),
        app_client.post(
            _url(client_id, group["id"], "close"),
            json={"closure_date": closure},
            headers=app_auth_headers,
        ),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409], (
        first.text,
        second.text,
    )
    assert await _event_count(group["id"], "zakonczenie") == 1

    again = await app_client.post(
        _url(client_id, group["id"], "close"),
        json={"closure_date": closure},
        headers=app_auth_headers,
    )
    assert again.status_code == 409
    assert await _event_count(group["id"], "zakonczenie") == 1

    first, second = await asyncio.gather(
        app_client.post(
            _url(client_id, group["id"], "reopen"), headers=app_auth_headers
        ),
        app_client.post(
            _url(client_id, group["id"], "reopen"), headers=app_auth_headers
        ),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409], (
        first.text,
        second.text,
    )
    assert await _event_count(group["id"], "przywrocenie") == 1
    after, _ = await _group_state(group["id"])
    assert after.status == "active"
    assert after.closure_date is None
