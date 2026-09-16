"""Ręczne zejścia MD linii ze statusem (Faza B, ticket CeZ 09.2026).

``GET/PUT/DELETE /order-groups/{g}/lines/{l}/consumptions[/{RRRR-MM}]``:

* PUT tworzy wpis ``manual`` ze statusem, notatką, autorem i wpisem w historii;
* powtórny PUT za ten sam miesiąc NADPISUJE (klucz idempotencji jak import);
* DELETE przelicza pozostałość od zera;
* zapis wymaga roli cyklu życia zamówienia (jak ``/close``);
* linia bez budżetu per osoba (kosztowa / wspólna pula) → 422.

Nazwiska, numery i liczby są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient

from tests.test_multi_consultant_orders import (
    _TODAY,
    _enable_for,
    _headers_for,
    _line_payload,
    _seed_client_with_contracts,
    _seed_user,
)

pytestmark = pytest.mark.asyncio


async def _create_md_group(
    app_client: AsyncClient, headers: dict, client_id: int, lines: list[dict]
) -> dict:
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"CeZ-{uuid.uuid4().hex[:6]}",
            "start_date": (_TODAY - timedelta(days=10)).isoformat(),
            "order_type": "md",
            "md_budget_mode": "per_person",
            "lines": lines,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _url(client_id: int, group_id: int, line_id: int, month: str | None = None) -> str:
    base = (
        f"/api/clients/{client_id}/order-groups/{group_id}/lines/{line_id}/consumptions"
    )
    return f"{base}/{month}" if month else base


async def test_put_creates_a_manual_row_with_status_author_and_event(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    line = group["lines"][0]

    resp = await app_client.put(
        _url(client_id, group["id"], line["id"], "2026-07"),
        json={"md_reported": 12.5, "status": "accepted", "note": "  protokół OK "},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["md_used"] == 12.5
    assert body["md_remaining"] == 37.5
    assert body["md_base_used"] == 12.5

    listing = await app_client.get(
        _url(client_id, group["id"], line["id"]), headers=app_auth_headers
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["period_month"] == "2026-07"
    assert row["md_reported"] == 12.5
    assert row["status"] == "accepted"
    assert row["note"] == "protokół OK"
    assert row["source"] == "manual"
    assert row["import_id"] is None
    assert row["created_by_name"] == "Pytest Admin"
    assert row["updated_at"]

    events = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group['id']}/events",
        headers=app_auth_headers,
    )
    assert events.status_code == 200, events.text
    entry = next(
        e
        for e in events.json()["events"]
        if "zejście MD za lipiec 2026" in e["description"]
    )
    assert entry["event_type"] == "edycja_reczna"
    assert "Zaakceptowany" in entry["description"]
    assert entry["payload"]["status"] == "accepted"
    assert entry["payload"]["md_reported"] == "12.500000"


async def test_second_put_for_the_same_month_overwrites_not_adds(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    line = group["lines"][0]
    url = _url(client_id, group["id"], line["id"], "2026-07")

    first = await app_client.put(
        url, json={"md_reported": 10, "status": "protocol"}, headers=app_auth_headers
    )
    assert first.status_code == 200, first.text
    second = await app_client.put(
        url, json={"md_reported": 15, "status": "accepted"}, headers=app_auth_headers
    )
    assert second.status_code == 200, second.text
    assert second.json()["md_used"] == 15
    assert second.json()["md_remaining"] == 35

    other = await app_client.put(
        _url(client_id, group["id"], line["id"], "2026-08"),
        json={"md_reported": 5},
        headers=app_auth_headers,
    )
    assert other.status_code == 200, other.text
    # `md_used` linii = suma wpisów (15 + 5), nie ostatni wpis.
    assert other.json()["md_used"] == 20
    assert other.json()["md_remaining"] == 30

    rows = (
        await app_client.get(
            _url(client_id, group["id"], line["id"]), headers=app_auth_headers
        )
    ).json()["rows"]
    assert [(r["period_month"], r["md_reported"], r["status"]) for r in rows] == [
        ("2026-07", 15, "accepted"),
        ("2026-08", 5, None),
    ]


async def test_delete_recomputes_the_remaining_budget(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    line = group["lines"][0]
    url = _url(client_id, group["id"], line["id"], "2026-07")
    await app_client.put(url, json={"md_reported": 20}, headers=app_auth_headers)

    resp = await app_client.delete(url, headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["md_used"] == 0
    assert resp.json()["md_remaining"] == 50

    again = await app_client.delete(url, headers=app_auth_headers)
    assert again.status_code == 404, again.text

    events = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group['id']}/events",
        headers=app_auth_headers,
    )
    assert any(
        "usunięto zejście MD za lipiec 2026" in e["description"]
        for e in events.json()["events"]
    )


async def test_bad_month_is_refused_before_anything_is_written(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    line = group["lines"][0]
    resp = await app_client.put(
        _url(client_id, group["id"], line["id"], "2026-7"),
        json={"md_reported": 1},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "RRRR-MM" in resp.text


async def test_role_without_order_lifecycle_cannot_write(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """TAC widzi zamówienie w zespole klienta, ale zejść nie prowadzi."""
    from app.core.database import AsyncSessionLocal
    from app.models.team_structure import ClientTacAssignment

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    line = group["lines"][0]

    user_id, email, password = await _seed_user("tac")
    async with AsyncSessionLocal() as db:
        db.add(ClientTacAssignment(client_id=client_id, tac_user_id=user_id))
        await db.commit()
    headers = await _headers_for(app_client, email, password)

    resp = await app_client.put(
        _url(client_id, group["id"], line["id"], "2026-07"),
        json={"md_reported": 1},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    resp = await app_client.delete(
        _url(client_id, group["id"], line["id"], "2026-07"), headers=headers
    )
    assert resp.status_code == 403, resp.text


async def test_cost_order_line_has_no_per_person_consumptions(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.services import cost_orders as co

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    monkeypatch.setattr(co, "cost_order_client_ids", lambda: frozenset({client_id}))
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"K-{uuid.uuid4().hex[:6]}",
            "start_date": (_TODAY - timedelta(days=10)).isoformat(),
            "order_type": "cost",
            "is_cost_based": True,
            "budget_amount": 100000,
            "lines": [
                {
                    "contract_id": contracts[0],
                    "rate_cost": 1000,
                    "rate_revenue": 1200,
                    "start_date": (_TODAY - timedelta(days=10)).isoformat(),
                }
            ],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    group = resp.json()
    line = group["lines"][0]

    put = await app_client.put(
        _url(client_id, group["id"], line["id"], "2026-07"),
        json={"md_reported": 1},
        headers=app_auth_headers,
    )
    assert put.status_code == 422, put.text
    assert "wspólnej puli" in put.text
