"""Integration tests for GET /api/candidates/check-exists (Phase 7.4 — Outlook Add-in).

In-process httpx.ASGITransport against the postgres service in CI. Seeds a
Candidate row directly via AsyncSessionLocal so the test is hermetic and
does not depend on demo data.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus


async def _seed_candidate(email: str) -> int:
    """Insert a minimal candidate row and return its id."""
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Add-in",
            lastname=f"Lookup-{uuid.uuid4().hex[:6]}",
            email=email,
            status=CandidateStatus.active,
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)
        return candidate.id


async def test_check_exists_requires_auth(app_client: AsyncClient):
    r = await app_client.get(
        "/api/candidates/check-exists",
        params={"email": "x@example.com"},
    )
    # HTTPBearer raises 403 when the Authorization header is absent.
    assert r.status_code in (401, 403)


async def test_check_exists_not_found(app_client: AsyncClient, app_auth_headers: dict):
    """Unknown email → found=false, all other fields None."""
    unique = f"unknown-{uuid.uuid4().hex[:8]}@example.com"
    r = await app_client.get(
        "/api/candidates/check-exists",
        params={"email": unique},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is False
    assert body["candidate_id"] is None
    assert body["candidate_name"] is None
    assert body["profile_url"] is None
    assert body["current_stage"] is None
    assert body["last_activity_at"] is None


async def test_check_exists_found(app_client: AsyncClient, app_auth_headers: dict):
    """Known email → found=true with profile_url + name."""
    email = f"addin-found-{uuid.uuid4().hex[:8]}@example.com"
    cid = await _seed_candidate(email)

    r = await app_client.get(
        "/api/candidates/check-exists",
        params={"email": email},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is True
    assert body["candidate_id"] == cid
    assert body["candidate_name"].startswith("Add-in Lookup-")
    # profile_url is built from PUBLIC_BASE_URL — assert structure, not host.
    assert body["profile_url"].endswith(f"/candidates/{cid}")
    # last_activity_at falls back to candidate.updated_at when Activity is empty.
    assert body["last_activity_at"] is not None


async def test_check_exists_is_case_insensitive(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Outlook may pass FROM headers with mixed case — match must be case-insensitive."""
    email = f"MixedCase-{uuid.uuid4().hex[:8]}@Example.COM".lower()
    cid = await _seed_candidate(email)

    # Query with uppercased domain → should still match.
    r = await app_client.get(
        "/api/candidates/check-exists",
        params={"email": email.upper()},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is True
    assert body["candidate_id"] == cid


async def test_check_exists_rejects_invalid_email(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Pydantic EmailStr query validation → 422 for malformed addresses."""
    r = await app_client.get(
        "/api/candidates/check-exists",
        params={"email": "not-an-email"},
        headers=app_auth_headers,
    )
    assert r.status_code == 422
