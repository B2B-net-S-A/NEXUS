"""CI PostgreSQL acceptance: atomic import, stale preview, access and API gate."""

import uuid
from copy import deepcopy

import pytest

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job, JobStatus
from tests.test_champion_intake_v4 import filled


@pytest.fixture(autouse=True)
def _enable_champion_gate(monkeypatch):
    # Gate defaults OFF in production (advisory); this suite asserts the
    # blocking API contract, so turn it on.
    monkeypatch.setenv("CHAMPION_INTAKE_GATE_ENABLED", "true")


async def seed():
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Synthetic Champion v4 {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        cp = filled()
        cp.pop("intake")
        j = Job(
            title="Synthetic Java role",
            status=JobStatus.draft,
            client_id=client.id,
            champion_profile=cp,
            rate_budget_hourly=110,
            location="Kraków",
        )
        db.add(j)
        await db.commit()
        return j.id


async def test_apply_is_atomic_and_stale_preview_cannot_overwrite(
    app_client, app_auth_headers, monkeypatch
):
    async def no_refresh(*args, **kwargs):
        pass

    monkeypatch.setattr(
        "app.services.job_matching_refresh.refresh_job_matching", no_refresh
    )
    jid = await seed()
    route = f"/api/jobs/{jid}/champion-profile"
    before = (await app_client.get(route, headers=app_auth_headers)).json()
    cp = filled()
    cp["basics"]["rate_value"] = 170
    cp["basics"]["rate_raw"] = None
    cp["intake"]["applied_by"] = 999999
    result = await app_client.post(
        route + "/apply-import",
        headers=app_auth_headers,
        json={
            "profile": cp,
            "expected_fingerprint": before["fingerprint"],
            "sync_fields": ["rate_value"],
        },
    )
    assert result.status_code == 200, result.text
    applied = result.json()
    assert applied["champion_profile"]["intake"]["applied_by"] != 999999
    assert applied["job_values"]["rate_value"] == 170
    assert applied["job_values"]["candidate_location_pref"] == "Kraków"
    assert any(i["code"] == "column_conflict" for i in applied["validation"]["issues"])
    cp["project"]["about"] = "Stale writer must never persist this"
    conflict = await app_client.post(
        route + "/apply-import",
        headers=app_auth_headers,
        json={
            "profile": cp,
            "expected_fingerprint": before["fingerprint"],
            "sync_fields": [],
        },
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["fingerprint"] == applied["fingerprint"]
    after = (await app_client.get(route, headers=app_auth_headers)).json()
    assert after["champion_profile"] == applied["champion_profile"]
    assert (await app_client.post(route + "/apply-import", json={})).status_code == 401


async def test_draft_save_and_direct_search_api_cannot_bypass(
    app_client, app_auth_headers, monkeypatch
):
    async def no_refresh(*args, **kwargs):
        pass

    monkeypatch.setattr(
        "app.services.job_matching_refresh.refresh_job_matching", no_refresh
    )
    jid = await seed()
    route = f"/api/jobs/{jid}/champion-profile"
    before = (await app_client.get(route, headers=app_auth_headers)).json()
    cp = deepcopy(before["champion_profile"])
    noop = await app_client.put(route, json=cp, headers=app_auth_headers)
    assert noop.status_code == 200, noop.text
    assert noop.json()["champion_profile"]["intake"] is None
    cp["screening_questions"] = []
    cp["basics"]["rate_value"] = "120–150 EUR/h"
    saved = await app_client.put(route, json=cp, headers=app_auth_headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["validation"]["status"] == "draft"
    assert saved.json()["champion_profile"]["basics"]["rate_value"] is None
    search = await app_client.post(
        "/api/candidate-search/runs", json={"job_id": jid}, headers=app_auth_headers
    )
    assert search.status_code == 422, search.text
    assert "search" in search.json()["detail"]["validation"]["blocked_operations"]
