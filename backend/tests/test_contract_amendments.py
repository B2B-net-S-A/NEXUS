"""Tests for Phase 9 B3 — amendments workflow."""

from datetime import date, timedelta

from httpx import AsyncClient


async def test_amendments_list_shape(app_client: AsyncClient, app_auth_headers: dict):
    contracts = (
        (await app_client.get("/api/contracts?page_size=1", headers=app_auth_headers))
        .json()
        .get("items", [])
    )
    if not contracts:
        return
    cid = contracts[0]["id"]
    resp = await app_client.get(
        f"/api/contracts/{cid}/amendments", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_extension_amendment_moves_end_date(
    app_client: AsyncClient, app_auth_headers: dict
):
    contracts = (
        (
            await app_client.get(
                "/api/contracts?status=active&page_size=1", headers=app_auth_headers
            )
        )
        .json()
        .get("items", [])
    )
    if not contracts:
        return
    cid = contracts[0]["id"]
    old_end = contracts[0].get("end_date")
    target = (date.today() + timedelta(days=365)).isoformat()

    payload = {
        "amendment_type": "extension",
        "effective_date": date.today().isoformat(),
        "new_end_date": target,
        "reason": "E2E test",
    }
    resp = await app_client.post(
        f"/api/contracts/{cid}/amendments",
        json=payload,
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["amendment_type"] == "extension"
    assert body["new_values"]["end_date"] == target

    # Contract's end_date is updated
    after = (
        await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
    ).json()
    assert after["end_date"] == target

    # Revert so re-running tests doesn't drift real data.
    if old_end is not None:
        revert = await app_client.post(
            f"/api/contracts/{cid}/amendments",
            json={
                "amendment_type": "extension",
                "effective_date": date.today().isoformat(),
                "new_end_date": old_end,
                "reason": "revert E2E",
            },
            headers=app_auth_headers,
        )
        assert revert.status_code == 201


async def test_rate_change_requires_at_least_one_field(
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
    resp = await app_client.post(
        f"/api/contracts/{cid}/amendments",
        json={
            "amendment_type": "rate_change",
            "effective_date": date.today().isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422
