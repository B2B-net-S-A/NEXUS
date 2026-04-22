"""Smoke tests for Kontrakty expansion — equipment, terminate, benchmark, notes timeline."""

from datetime import date, timedelta

from httpx import AsyncClient


async def _any_contract(app_client: AsyncClient, headers: dict):
    res = await app_client.get(
        "/api/contracts?page_size=1&status=active", headers=headers
    )
    items = res.json().get("items", [])
    return items[0] if items else None


# ── Equipment ───────────────────────────────────────────────────────────────


async def test_equipment_crud_roundtrip(
    app_client: AsyncClient, app_auth_headers: dict
):
    contract = await _any_contract(app_client, app_auth_headers)
    if not contract:
        return
    cid = contract["id"]

    list_resp = await app_client.get(
        f"/api/contracts/{cid}/equipment", headers=app_auth_headers
    )
    assert list_resp.status_code == 200
    before = len(list_resp.json())

    created = await app_client.post(
        f"/api/contracts/{cid}/equipment",
        json={
            "item_type": "laptop",
            "owner": "ours",
            "brand_model": "ThinkPad X1 Carbon",
            "serial_number": "PYTEST-X1-001",
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["item_type"] == "laptop"
    assert body["owner"] == "ours"
    assert body["return_status"] == "pending"
    eq_id = body["id"]

    patched = await app_client.patch(
        f"/api/contracts/{cid}/equipment/{eq_id}",
        json={"returned_date": date.today().isoformat()},
        headers=app_auth_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["return_status"] == "returned"

    deleted = await app_client.delete(
        f"/api/contracts/{cid}/equipment/{eq_id}", headers=app_auth_headers
    )
    assert deleted.status_code == 204

    after = await app_client.get(
        f"/api/contracts/{cid}/equipment", headers=app_auth_headers
    )
    assert len(after.json()) == before


# ── Terminate ───────────────────────────────────────────────────────────────


async def test_terminate_sets_reason_and_amendment(
    app_client: AsyncClient, app_auth_headers: dict
):
    contract = await _any_contract(app_client, app_auth_headers)
    if not contract:
        return
    cid = contract["id"]
    original = await app_client.get(
        f"/api/contracts/{cid}", headers=app_auth_headers
    )
    original_data = original.json()
    original_status = original_data["status"]
    original_end = original_data["end_date"]

    effective = (date.today() + timedelta(days=5)).isoformat()
    if original_end:
        effective = min(effective, original_end)

    terminated = await app_client.post(
        f"/api/contracts/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "termination_lessons": "pytest smoke",
            "terminated_at": effective,
        },
        headers=app_auth_headers,
    )
    assert terminated.status_code == 200, terminated.text
    assert terminated.json()["status"] == "ended"
    assert terminated.json()["termination_reason"] == "project_ended"
    assert terminated.json()["termination_lessons"] == "pytest smoke"

    # Revert — flip back via PATCH so subsequent runs stay idempotent.
    if original_status != "ended":
        revert = await app_client.patch(
            f"/api/contracts/{cid}",
            json={"status": original_status, "end_date": original_end},
            headers=app_auth_headers,
        )
        assert revert.status_code == 200


# ── Benchmark ───────────────────────────────────────────────────────────────


async def test_benchmark_endpoint_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    contract = await _any_contract(app_client, app_auth_headers)
    if not contract:
        return
    cid = contract["id"]

    bench = await app_client.get(
        f"/api/contracts/{cid}/benchmark", headers=app_auth_headers
    )
    assert bench.status_code == 200, bench.text
    payload = bench.json()
    # The fields exist even if internal_sample_size is 0 or role is None.
    for key in (
        "contract_rate_monthly",
        "internal_avg_monthly",
        "internal_median_monthly",
        "internal_sample_size",
        "market_min",
        "market_median",
        "market_max",
        "market_source",
        "role_used",
        "currency",
    ):
        assert key in payload


# ── Notes+Calls timeline ────────────────────────────────────────────────────


async def test_contract_notes_timeline_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    contract = await _any_contract(app_client, app_auth_headers)
    if not contract:
        return
    cid = contract["id"]
    res = await app_client.get(
        f"/api/contracts/{cid}/notes", headers=app_auth_headers
    )
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    for item in res.json():
        assert item["kind"] in ("note", "call")
        assert "at" in item
