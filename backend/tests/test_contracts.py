"""Tests for contracts API."""
from httpx import AsyncClient


# Legacy live-server smoke tests (skipped unless RUN_LIVE_TESTS=1)

async def test_list_contracts(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/contracts", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


async def test_contracts_have_margin(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/contracts", headers=auth_headers)
    for c in resp.json()["items"]:
        if c.get("rate_client") and c.get("rate_candidate"):
            assert "margin" in c


async def test_expiring_contracts(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/contracts/expiring", headers=auth_headers)
    assert resp.status_code == 200


async def test_contracts_unauthorized(client: AsyncClient):
    resp = await client.get("/api/contracts")
    assert resp.status_code in (401, 403)


# In-process tests (run always, no rate-limit issues)

async def test_get_contract_detail_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get("/api/contracts/999999", headers=app_auth_headers)
    assert resp.status_code == 404


async def test_contract_activities_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contracts/999999/activities", headers=app_auth_headers
    )
    assert resp.status_code == 404


async def test_contract_rate_history_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contracts/999999/rate-history", headers=app_auth_headers
    )
    assert resp.status_code == 404


async def test_contract_detail_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    """If any contracts exist, GET detail must include denormalized names."""
    list_resp = await app_client.get("/api/contracts", headers=app_auth_headers)
    items = list_resp.json().get("items", [])
    if not items:
        return
    cid = items[0]["id"]
    detail = await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert "candidate_name" in body
    assert "client_name" in body
    assert "job_title" in body


async def test_contract_activities_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    list_resp = await app_client.get("/api/contracts", headers=app_auth_headers)
    items = list_resp.json().get("items", [])
    if not items:
        return
    cid = items[0]["id"]
    resp = await app_client.get(
        f"/api/contracts/{cid}/activities", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_contract_rate_history_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    list_resp = await app_client.get("/api/contracts", headers=app_auth_headers)
    items = list_resp.json().get("items", [])
    if not items:
        return
    cid = items[0]["id"]
    resp = await app_client.get(
        f"/api/contracts/{cid}/rate-history", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_contract_has_rate_unit_default(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Phase 9 A3: response exposes rate_unit + billing_hours_per_month."""
    list_resp = await app_client.get("/api/contracts", headers=app_auth_headers)
    items = list_resp.json().get("items", [])
    if not items:
        return
    for item in items:
        assert "rate_unit" in item
        assert item["rate_unit"] in ("hourly", "daily", "monthly")
        assert "billing_hours_per_month" in item
        assert isinstance(item["billing_hours_per_month"], int)


async def test_contract_documents_list_empty_ok(
    app_client: AsyncClient, app_auth_headers: dict
):
    list_resp = await app_client.get("/api/contracts", headers=app_auth_headers)
    items = list_resp.json().get("items", [])
    if not items:
        return
    cid = items[0]["id"]
    resp = await app_client.get(
        f"/api/contracts/{cid}/documents", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_contract_document_upload_download_delete(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Round-trip: upload → list includes file → download returns bytes → delete."""
    list_resp = await app_client.get("/api/contracts", headers=app_auth_headers)
    items = list_resp.json().get("items", [])
    if not items:
        return
    cid = items[0]["id"]

    payload = b"Test contract content"
    files = {"file": ("test.pdf", payload, "application/pdf")}
    data = {"doc_type": "contract"}
    up = await app_client.post(
        f"/api/contracts/{cid}/documents",
        files=files,
        data=data,
        headers=app_auth_headers,
    )
    assert up.status_code == 201, up.text
    body = up.json()
    assert body["filename"] == "test.pdf"
    assert body["doc_type"] == "contract"
    assert body["size_bytes"] == len(payload)

    # List includes the file
    lst = await app_client.get(
        f"/api/contracts/{cid}/documents", headers=app_auth_headers
    )
    assert lst.status_code == 200
    assert any(d["id"] == body["id"] for d in lst.json())

    # Download returns bytes
    dl = await app_client.get(
        f"/api/contracts/{cid}/documents/{body['id']}/download",
        headers=app_auth_headers,
    )
    assert dl.status_code == 200
    assert dl.content == payload

    # Delete
    dele = await app_client.delete(
        f"/api/contracts/{cid}/documents/{body['id']}",
        headers=app_auth_headers,
    )
    assert dele.status_code == 204


async def test_contract_document_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contracts/999999/documents", headers=app_auth_headers
    )
    assert resp.status_code == 404


async def test_contract_rate_unit_round_trip(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Creating a contract with rate_unit=hourly persists it."""
    # Find an existing candidate and client to reuse
    cands = (
        await app_client.get("/api/candidates?page_size=1", headers=app_auth_headers)
    ).json().get("items", [])
    clients = (
        await app_client.get("/api/clients?page_size=1", headers=app_auth_headers)
    ).json().get("items", [])
    if not cands or not clients:
        return
    payload = {
        "candidate_id": cands[0]["id"],
        "client_id": clients[0]["id"],
        "start_date": "2026-04-17",
        "rate_client": 150,
        "rate_candidate": 100,
        "currency": "PLN",
        "rate_unit": "hourly",
        "billing_hours_per_month": 168,
        "contract_type": "b2b",
        "status": "draft",
    }
    resp = await app_client.post(
        "/api/contracts", json=payload, headers=app_auth_headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rate_unit"] == "hourly"
    assert body["billing_hours_per_month"] == 168
    # Margin auto-computed = 50
    assert body["margin"] == 50
    # Clean up
    await app_client.delete(
        f"/api/contracts/{body['id']}", headers=app_auth_headers
    )
