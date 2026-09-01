"""Tests for the candidate-pin (short-list) API — Phase 4 manual search.

In-process tests via the `app_client` fixture (httpx.ASGITransport, no
live server). Each test seeds a fresh candidate, exercises the toggle /
listing endpoints, and cleans up the resulting pin records.

We exercise four scenarios:
1. Toggle ON → row exists, pinned=True
2. Toggle ON twice → second call returns pinned=False (toggle OFF)
3. GET /pins returns my pinned candidates with embedded brief
4. POST against a non-existent candidate returns 404
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_pin import CandidatePin


@pytest_asyncio.fixture
async def seeded_candidate() -> AsyncIterator[int]:
    """Seed a Candidate row and return its id. Cleans up after the test."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        c = Candidate(
            name=f"Pin",
            lastname=f"Test-{unique}",
            email=f"pin-test-{unique}@example.com",
            status=CandidateStatus.active,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        cid = c.id

    yield cid

    async with AsyncSessionLocal() as db:
        # CandidatePin rows cascade via FK ondelete=CASCADE when we delete
        # the candidate. Belt-and-suspenders: also explicit-delete any pins
        # we may have created so a partial test failure doesn't leave rows.
        await db.execute(delete(CandidatePin).where(CandidatePin.candidate_id == cid))
        await db.execute(delete(Candidate).where(Candidate.id == cid))
        await db.commit()


@pytest.mark.asyncio
async def test_toggle_on_creates_pin(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    seeded_candidate: int,
) -> None:
    """First POST against a fresh candidate creates a pin."""
    resp = await app_client.post(
        f"/api/candidates/{seeded_candidate}/pin",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pinned"] is True
    assert body["pin"] is not None
    assert body["pin"]["candidate_id"] == seeded_candidate
    assert body["pin"]["candidate"]["id"] == seeded_candidate


@pytest.mark.asyncio
async def test_toggle_off_removes_pin(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    seeded_candidate: int,
) -> None:
    """Second POST removes the previously-created pin (toggle OFF)."""
    # Toggle ON
    on_resp = await app_client.post(
        f"/api/candidates/{seeded_candidate}/pin",
        headers=app_auth_headers,
    )
    assert on_resp.status_code == 200
    assert on_resp.json()["pinned"] is True

    # Toggle OFF
    off_resp = await app_client.post(
        f"/api/candidates/{seeded_candidate}/pin",
        headers=app_auth_headers,
    )
    assert off_resp.status_code == 200
    body = off_resp.json()
    assert body["pinned"] is False
    assert body["pin"] is None


@pytest.mark.asyncio
async def test_get_pin_state_reflects_current(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    seeded_candidate: int,
) -> None:
    """GET /{id}/pin probes the current pin state without mutating."""
    # Before pin: state = unpinned
    probe1 = await app_client.get(
        f"/api/candidates/{seeded_candidate}/pin",
        headers=app_auth_headers,
    )
    assert probe1.status_code == 200
    assert probe1.json()["pinned"] is False

    # After POST: state = pinned
    await app_client.post(
        f"/api/candidates/{seeded_candidate}/pin",
        headers=app_auth_headers,
    )
    probe2 = await app_client.get(
        f"/api/candidates/{seeded_candidate}/pin",
        headers=app_auth_headers,
    )
    assert probe2.status_code == 200
    body = probe2.json()
    assert body["pinned"] is True
    assert body["pin"]["candidate"]["id"] == seeded_candidate


@pytest.mark.asyncio
async def test_list_pins_includes_brief(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    seeded_candidate: int,
) -> None:
    """GET /pins returns my pinned candidates with eager-loaded brief."""
    # Pin one candidate first
    await app_client.post(
        f"/api/candidates/{seeded_candidate}/pin",
        headers=app_auth_headers,
    )

    list_resp = await app_client.get(
        "/api/candidates/pins",
        headers=app_auth_headers,
    )
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json()
    assert isinstance(items, list)
    matching = [p for p in items if p["candidate_id"] == seeded_candidate]
    assert len(matching) == 1
    item = matching[0]
    assert item["candidate"]["id"] == seeded_candidate
    # Brief fields are populated (lastname was set in seeded_candidate)
    assert item["candidate"]["lastname"] is not None


@pytest.mark.asyncio
async def test_post_unknown_candidate_returns_404(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    """Pinning a non-existent candidate returns 404 (clean), not 500."""
    resp = await app_client.post(
        "/api/candidates/999999999/pin",
        headers=app_auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_is_idempotent(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    seeded_candidate: int,
) -> None:
    """Explicit DELETE returns 204 even when no pin exists."""
    # Delete with no existing pin
    resp1 = await app_client.delete(
        f"/api/candidates/{seeded_candidate}/pin",
        headers=app_auth_headers,
    )
    assert resp1.status_code == 204

    # Create a pin, then delete it
    await app_client.post(
        f"/api/candidates/{seeded_candidate}/pin",
        headers=app_auth_headers,
    )
    resp2 = await app_client.delete(
        f"/api/candidates/{seeded_candidate}/pin",
        headers=app_auth_headers,
    )
    assert resp2.status_code == 204

    # Confirm pin is gone
    probe = await app_client.get(
        f"/api/candidates/{seeded_candidate}/pin",
        headers=app_auth_headers,
    )
    assert probe.json()["pinned"] is False
