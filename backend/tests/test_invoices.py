"""Tests for Phase 9 C1 — invoice ledger."""

from datetime import date, timedelta

from httpx import AsyncClient


async def test_list_invoices_ok(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get("/api/invoices", headers=app_auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_invoice_round_trip_and_mark_paid(
    app_client: AsyncClient, app_auth_headers: dict
):
    contracts = (
        (await app_client.get("/api/contracts?page_size=1", headers=app_auth_headers))
        .json()
        .get("items", [])
    )
    if not contracts:
        return
    cid = contracts[0]["id"]
    payload = {
        "contract_id": cid,
        "direction": "to_client",
        "invoice_number": "TEST/2026/01",
        "issue_date": date.today().isoformat(),
        "due_date": (date.today() + timedelta(days=14)).isoformat(),
        "amount": 10000,
        "currency": "PLN",
    }
    created = await app_client.post(
        "/api/invoices", json=payload, headers=app_auth_headers
    )
    assert created.status_code == 201, created.text
    inv = created.json()
    assert inv["status"] == "issued"

    paid = await app_client.patch(
        f"/api/invoices/{inv['id']}",
        json={"status": "paid", "paid_date": date.today().isoformat()},
        headers=app_auth_headers,
    )
    assert paid.status_code == 200
    assert paid.json()["status"] == "paid"

    # Cleanup
    deleted = await app_client.delete(
        f"/api/invoices/{inv['id']}", headers=app_auth_headers
    )
    assert deleted.status_code == 204


async def test_dso_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get("/api/invoices/dso", headers=app_auth_headers)
    assert resp.status_code == 200
    for row in resp.json():
        assert {
            "client_id",
            "client_name",
            "invoices",
            "total_amount",
            "paid_amount",
            "outstanding",
            "avg_dso_days",
        } <= set(row.keys())


async def test_invoices_csv_export(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get("/api/invoices/export.csv", headers=app_auth_headers)
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/csv")
    # Header row should include Numer + Status
    first_line = resp.text.splitlines()[0]
    assert "Numer" in first_line
    assert "Status" in first_line


async def test_invoice_contract_not_found(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.post(
        "/api/invoices",
        json={
            "contract_id": 999999,
            "direction": "to_client",
            "invoice_number": "X",
            "issue_date": date.today().isoformat(),
            "amount": 1,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 404
