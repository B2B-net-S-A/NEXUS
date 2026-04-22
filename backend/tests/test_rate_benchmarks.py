"""Smoke tests for the rate benchmarks admin endpoints."""

from datetime import date

from httpx import AsyncClient


async def test_benchmark_create_list_delete(
    app_client: AsyncClient, app_auth_headers: dict
):
    payload = {
        "role": "Pytest Java Dev",
        "seniority": "senior",
        "currency": "PLN",
        "rate_unit": "hourly",
        "market_min": 150,
        "market_median": 180,
        "market_max": 220,
        "source": "Pytest Guide 2026",
        "source_date": date.today().isoformat(),
        "location": "Warsaw",
    }
    created = await app_client.post(
        "/api/rate-benchmarks", json=payload, headers=app_auth_headers
    )
    assert created.status_code == 201, created.text
    row_id = created.json()["id"]

    listing = await app_client.get(
        "/api/rate-benchmarks?role=Pytest", headers=app_auth_headers
    )
    assert listing.status_code == 200
    assert any(r["id"] == row_id for r in listing.json())

    patched = await app_client.patch(
        f"/api/rate-benchmarks/{row_id}",
        json={"market_median": 190},
        headers=app_auth_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["market_median"] == 190

    deleted = await app_client.delete(
        f"/api/rate-benchmarks/{row_id}", headers=app_auth_headers
    )
    assert deleted.status_code == 204


async def test_benchmark_csv_import(app_client: AsyncClient, app_auth_headers: dict):
    csv_body = (
        "role,seniority,currency,rate_unit,market_min,market_median,market_max,"
        "source,source_date,location\n"
        "Pytest PM,mid,PLN,monthly,16000,19000,23000,Pytest CSV,2026-01-01,Warsaw\n"
        "Pytest PM,senior,PLN,monthly,22000,26000,30000,Pytest CSV,2026-01-01,\n"
        "Broken Row,,PLN,hourly,,,not-a-number,Pytest CSV,,\n"
    )
    files = {"file": ("benchmarks.csv", csv_body, "text/csv")}
    resp = await app_client.post(
        "/api/rate-benchmarks/import", files=files, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] >= 2
    assert body["skipped"] >= 1

    # Clean up inserted rows.
    listing = await app_client.get(
        "/api/rate-benchmarks?role=Pytest PM", headers=app_auth_headers
    )
    for row in listing.json():
        await app_client.delete(
            f"/api/rate-benchmarks/{row['id']}", headers=app_auth_headers
        )
