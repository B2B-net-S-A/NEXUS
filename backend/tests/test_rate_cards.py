"""Tests for Phase 9 B2 — rate cards."""

from httpx import AsyncClient


async def test_list_rate_cards_empty_ok(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get("/api/rate-cards", headers=app_auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_rate_card_round_trip(app_client: AsyncClient, app_auth_headers: dict):
    clients = (
        (await app_client.get("/api/clients?page_size=1", headers=app_auth_headers))
        .json()
        .get("items", [])
    )
    if not clients:
        return
    payload = {
        "client_id": clients[0]["id"],
        "role": "Senior Java Dev",
        "seniority": "senior",
        "rate_candidate_min": 15000,
        "rate_candidate_max": 18000,
        "rate_client_min": 22000,
        "rate_client_max": 26000,
        "currency": "PLN",
        "rate_unit": "monthly",
    }
    created = await app_client.post(
        "/api/rate-cards", json=payload, headers=app_auth_headers
    )
    assert created.status_code == 201, created.text
    card = created.json()

    # suggest returns midpoints
    s = await app_client.get(
        "/api/rate-cards/suggest",
        params={
            "client_id": clients[0]["id"],
            "role": "Senior Java Dev",
            "seniority": "senior",
        },
        headers=app_auth_headers,
    )
    assert s.status_code == 200
    body = s.json()
    assert body["matched"] is True
    assert body["rate_candidate_suggestion"] == 16500
    assert body["rate_client_suggestion"] == 24000

    # cleanup
    deleted = await app_client.delete(
        f"/api/rate-cards/{card['id']}", headers=app_auth_headers
    )
    assert deleted.status_code == 204


async def test_rate_card_suggest_no_match(
    app_client: AsyncClient, app_auth_headers: dict
):
    clients = (
        (await app_client.get("/api/clients?page_size=1", headers=app_auth_headers))
        .json()
        .get("items", [])
    )
    if not clients:
        return
    s = await app_client.get(
        "/api/rate-cards/suggest",
        params={
            "client_id": clients[0]["id"],
            "role": "Nonexistent role XYZ",
        },
        headers=app_auth_headers,
    )
    assert s.status_code == 200
    assert s.json() == {
        "matched": False,
        "rate_card_id": None,
        "rate_candidate_suggestion": None,
        "rate_client_suggestion": None,
        "currency": None,
        "rate_unit": None,
        "source_role": None,
        "source_seniority": None,
    }
