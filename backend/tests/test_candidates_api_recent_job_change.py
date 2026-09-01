"""Integration tests for the new LinkedIn-backed candidates API surface.

Uses the in-process `app_client` fixture so we hit FastAPI via ASGI
transport without a real uvicorn. Covers:

- `GET /api/candidates?recently_changed_jobs={1,2,3}` filter window
- `GET /api/candidates/{id}` returns linkedin_* fields + snapshots
- `POST /api/candidates/{id}/sync-linkedin` — 503 without PROXYCURL_API_KEY,
  400 without a LinkedIn URL on the candidate.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.linkedin_snapshot import (
    CandidateLinkedinSnapshot,
    LinkedinChangeKind,
    LinkedinSyncStatus,
)


async def _seed_candidate(
    *,
    name: str,
    changed_at: datetime | None = None,
    linkedin: str | None = None,
) -> int:
    """Insert a test candidate and return its id."""
    async with AsyncSessionLocal() as db:
        lastname = uuid.uuid4().hex[:8]
        cand = Candidate(
            name=name,
            lastname=lastname,
            email=f"{name.lower()}-{lastname}@example.com",
            status=CandidateStatus.active,
            linkedin=linkedin,
            linkedin_employment_changed_at=changed_at,
            linkedin_sync_status=(
                LinkedinSyncStatus.ok if changed_at else LinkedinSyncStatus.disabled
            ),
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _cleanup_candidate(cid: int) -> None:
    async with AsyncSessionLocal() as db:
        cand = await db.get(Candidate, cid)
        if cand is not None:
            await db.delete(cand)
            await db.commit()


@pytest.mark.asyncio
async def test_recently_changed_jobs_filter_respects_window(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Only candidates whose change was within N months show up."""
    now = datetime.now(timezone.utc)
    recent_id = await _seed_candidate(
        name="FilterRecent",
        changed_at=now - timedelta(days=10),
        linkedin="https://linkedin.com/in/filter-recent",
    )
    old_id = await _seed_candidate(
        name="FilterOld",
        changed_at=now - timedelta(days=120),
        linkedin="https://linkedin.com/in/filter-old",
    )
    never_id = await _seed_candidate(name="FilterNever")

    try:
        # 1-month window: only the recent one.
        resp = await app_client.get(
            "/api/candidates?recently_changed_jobs=1&page_size=100",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()["items"]}
        assert recent_id in ids
        assert old_id not in ids
        assert never_id not in ids

        # 3-month window still excludes the 120-day-old change.
        resp3 = await app_client.get(
            "/api/candidates?recently_changed_jobs=3&page_size=100",
            headers=app_auth_headers,
        )
        assert resp3.status_code == 200
        ids3 = {item["id"] for item in resp3.json()["items"]}
        assert recent_id in ids3
        assert old_id not in ids3

        # Without the filter, the DB has at least the three candidates we
        # seeded (and usually many more). Just sanity-check that the endpoint
        # responds; we avoid scanning all pages to keep the test deterministic.
        resp_all = await app_client.get(
            "/api/candidates?page_size=100", headers=app_auth_headers
        )
        assert resp_all.status_code == 200
        assert resp_all.json()["total"] >= 3
    finally:
        for cid in (recent_id, old_id, never_id):
            await _cleanup_candidate(cid)


@pytest.mark.asyncio
async def test_detail_exposes_linkedin_fields_and_snapshots(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    cid = await _seed_candidate(
        name="DetailCheck",
        changed_at=datetime.now(timezone.utc) - timedelta(days=3),
        linkedin="https://linkedin.com/in/detail-check",
    )

    try:
        # Seed a snapshot so the history appears in the detail payload.
        async with AsyncSessionLocal() as db:
            db.add(
                CandidateLinkedinSnapshot(
                    candidate_id=cid,
                    fetched_at=datetime.now(timezone.utc),
                    profile_json={},
                    current_company="Beta Corp",
                    current_title="Staff Engineer",
                    changed_from_previous=True,
                    change_kind=LinkedinChangeKind.new_company,
                )
            )
            await db.commit()

        resp = await app_client.get(f"/api/candidates/{cid}", headers=app_auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["linkedin_sync_status"] == "ok"
        assert data["linkedin"] == "https://linkedin.com/in/detail-check"
        assert data["linkedin_employment_changed_at"] is not None
        assert isinstance(data["linkedin_snapshots"], list)
        assert len(data["linkedin_snapshots"]) >= 1
        latest = data["linkedin_snapshots"][0]
        assert latest["current_company"] == "Beta Corp"
        assert latest["change_kind"] == "new_company"
    finally:
        await _cleanup_candidate(cid)


@pytest.mark.asyncio
async def test_list_response_does_not_expose_snapshots(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Keep list payloads small — snapshots are a detail-view concern."""
    cid = await _seed_candidate(
        name="ListSnapshotGuard",
        linkedin="https://linkedin.com/in/list-guard",
    )
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                CandidateLinkedinSnapshot(
                    candidate_id=cid,
                    fetched_at=datetime.now(timezone.utc),
                    profile_json={},
                    current_company="Acme",
                    current_title="Engineer",
                    change_kind=LinkedinChangeKind.first_snapshot,
                )
            )
            await db.commit()

        resp = await app_client.get(
            "/api/candidates?page_size=100", headers=app_auth_headers
        )
        assert resp.status_code == 200
        candidates = resp.json()["items"]
        for item in candidates:
            assert item.get("linkedin_snapshots") is None
    finally:
        await _cleanup_candidate(cid)


@pytest.mark.asyncio
async def test_sync_endpoint_returns_503_without_api_key(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
) -> None:
    """When Proxycurl is not configured the endpoint refuses cleanly."""
    monkeypatch.setenv("PROXYCURL_API_KEY", "")
    # Force settings reload by patching the in-memory value (avoid restart).
    from app.core.config import settings

    monkeypatch.setattr(settings, "PROXYCURL_API_KEY", "")
    monkeypatch.setattr(settings, "PROXYCURL_ENABLED", True)

    cid = await _seed_candidate(
        name="SyncGuard",
        linkedin="https://linkedin.com/in/sync-guard",
    )
    try:
        resp = await app_client.post(
            f"/api/candidates/{cid}/sync-linkedin", headers=app_auth_headers
        )
        assert resp.status_code == 503
        assert "LinkedIn sync" in resp.json()["detail"]
    finally:
        await _cleanup_candidate(cid)


@pytest.mark.asyncio
async def test_sync_endpoint_returns_400_without_linkedin_url(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
) -> None:
    """Even when Proxycurl is configured, the candidate must have a URL."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "PROXYCURL_API_KEY", "fake-test-key")
    monkeypatch.setattr(settings, "PROXYCURL_ENABLED", True)

    cid = await _seed_candidate(name="NoUrl")  # linkedin intentionally None
    try:
        resp = await app_client.post(
            f"/api/candidates/{cid}/sync-linkedin", headers=app_auth_headers
        )
        assert resp.status_code == 400
        assert "LinkedIn" in resp.json()["detail"]
    finally:
        await _cleanup_candidate(cid)
