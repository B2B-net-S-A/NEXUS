"""Smoke tests for candidate engagement + location patches."""

from httpx import AsyncClient


async def _any_candidate(app_client: AsyncClient, headers: dict):
    res = await app_client.get("/api/candidates?page_size=1", headers=headers)
    items = res.json().get("items", [])
    return items[0] if items else None


async def test_engagement_patch_roundtrip(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate = await _any_candidate(app_client, app_auth_headers)
    if not candidate:
        return
    cid = candidate["id"]
    original = {
        k: candidate.get(k)
        for k in (
            "is_ambassador",
            "wants_to_verify_candidates",
            "open_to_side_projects",
            "open_to_sales_support",
            "open_to_expert_consult",
            "engagement_notes",
        )
    }

    patched = await app_client.patch(
        f"/api/candidates/{cid}/engagement",
        json={
            "is_ambassador": True,
            "open_to_side_projects": True,
            "engagement_notes": "pytest engagement",
        },
        headers=app_auth_headers,
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["is_ambassador"] is True
    assert body["open_to_side_projects"] is True
    assert body["engagement_notes"] == "pytest engagement"

    # Revert to original state.
    await app_client.patch(
        f"/api/candidates/{cid}/engagement",
        json={
            k: (v if v is not None else False)
            if isinstance(v, bool) or v is None
            else v
            for k, v in original.items()
        },
        headers=app_auth_headers,
    )


async def test_engagement_patch_sets_open_to_timestamp(
    app_client: AsyncClient, app_auth_headers: dict
):
    """PATCH /engagement that toggles open_to_* must set *_updated_at to NOW.

    Sprawdza że nudge UI ma czego się trzymać — bez tego cała Faza 2 (TTL)
    nie ma sensu.
    """
    candidate = await _any_candidate(app_client, app_auth_headers)
    if not candidate:
        return
    cid = candidate["id"]

    res = await app_client.patch(
        f"/api/candidates/{cid}/engagement",
        json={"open_to_side_projects": True},
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["open_to_side_projects"] is True
    ts1 = body.get("open_to_side_projects_updated_at")
    assert ts1, "open_to_side_projects_updated_at not set after touch"

    # Drugi PATCH z tą samą wartością — timestamp ma się odświeżyć (rekruter
    # „potwierdza" świeżość deklaracji).
    import asyncio

    await asyncio.sleep(0.05)
    res2 = await app_client.patch(
        f"/api/candidates/{cid}/engagement",
        json={"open_to_side_projects": True},
        headers=app_auth_headers,
    )
    ts2 = res2.json().get("open_to_side_projects_updated_at")
    assert ts2 and ts2 > ts1, "timestamp not refreshed on confirm-touch"

    # Cleanup
    await app_client.patch(
        f"/api/candidates/{cid}/engagement",
        json={"open_to_side_projects": False},
        headers=app_auth_headers,
    )


async def test_location_patch_uppercases_country(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate = await _any_candidate(app_client, app_auth_headers)
    if not candidate:
        return
    cid = candidate["id"]

    patched = await app_client.patch(
        f"/api/candidates/{cid}/location",
        json={
            "city": "Warszawa",
            "country": "pl",
            "hub_city": "Warszawa",
            "region": "mazowieckie",
        },
        headers=app_auth_headers,
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["city"] == "Warszawa"
    assert body["country"] == "PL"
    assert body["hub_city"] == "Warszawa"

    empty = await app_client.patch(
        f"/api/candidates/{cid}/location",
        json={},
        headers=app_auth_headers,
    )
    assert empty.status_code == 422
