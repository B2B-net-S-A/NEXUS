"""Authorisation matrix for three previously-bare read surfaces.

Adversarial audit (2026-07-21) found three ``GET`` endpoints resolving on bare
``CurrentUser`` — "authenticated means authorised" — that returned internal
recruiting intel to the read-only viewer role ``user`` (QC / client persona):

- **jobs champion-profile** (``GET /api/jobs/{job_id}/champion-profile``) — the
  Delivery Lead's internal champion *sourcing* profile. The same field is
  already blanked for the viewer by ``redact_job_for_viewer`` on the jobs
  list/detail; this dedicated endpoint bypassed that. Gated to
  ``OperationalUser`` (every operational role, viewer excluded) — matching the
  redaction boundary and preserving the recruiter notification-open flow.
- **champion briefing audio** (``.../champion-profile/briefing/audio-url``) —
  presigned URL to the internal Delivery-Lead briefing recording. Same class,
  same gate.
- **candidate conflicts** (``GET /api/candidates/{candidate_id}/conflicts``) —
  candidate↔client conflict linkage (``client_id`` + free-text ``reason``),
  candidate+client PII. Its finance-read sibling ``list_rate_history`` uses
  ``CandidateFinanceAccess`` (#839); mirrored here so the read matches the
  write siblings' ``ManagerOrAdmin`` sensitivity.

Pattern follows ``test_candidate_module_access.py``: status-code asymmetry —
denied roles must get exactly 403; allowed roles must get *not* 403 (404/422
from a missing fixture job/candidate is fine — only the guard is under test).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole

ROLES = [
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
    UserRole.user,
]

# OperationalUser — every internal role, read-only viewer `user` excluded.
OPERATIONAL_ROLES = {
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
}

# CandidateFinanceAccess — admin + delivery_lead + tac (mirror of list_rate_history).
FINANCE_ROLES = {UserRole.admin, UserRole.delivery_lead, UserRole.tac}


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"authz-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Az"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Authz {role.value}",
                role=role,
                roles=[role.value],
                is_active=True,
            )
        )
        await db.commit()
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def authz_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture(scope="module")
async def headers_by_role(authz_client: AsyncClient) -> dict[UserRole, dict[str, str]]:
    out: dict[UserRole, dict[str, str]] = {}
    for role in ROLES:
        email, password = await _seed_user(role)
        out[role] = await _login(authz_client, email, password)
    return out


# ── Champion-profile reads — OperationalUser (viewer 403) ────────────────────

CHAMPION_ENDPOINTS = [
    ("GET", "/api/jobs/999999/champion-profile"),
    ("GET", "/api/jobs/999999/champion-profile/briefing/audio-url"),
]


@pytest.mark.parametrize("method,path", CHAMPION_ENDPOINTS)
async def test_champion_profile_role_matrix(
    authz_client: AsyncClient,
    headers_by_role: dict[UserRole, dict[str, str]],
    method: str,
    path: str,
):
    for role in ROLES:
        resp = await authz_client.request(method, path, headers=headers_by_role[role])
        if role in OPERATIONAL_ROLES:
            assert resp.status_code != 403, (
                f"[{role.value}] {method} {path} unexpectedly forbidden"
            )
        else:
            assert resp.status_code == 403, (
                f"[{role.value}] {method} {path} expected 403, got {resp.status_code}"
            )


# ── Candidate conflicts read — CandidateFinanceAccess (below-finance 403) ────


async def test_list_conflicts_requires_finance_capability(
    authz_client: AsyncClient, headers_by_role: dict[UserRole, dict[str, str]]
):
    """Conflict linkage (client_id + reason) mirrors the finance read sibling —
    recruiter / sourcer / head_of_recruitment / viewer all 403."""
    path = "/api/candidates/999999/conflicts"
    for role in ROLES:
        resp = await authz_client.get(path, headers=headers_by_role[role])
        if role in FINANCE_ROLES:
            assert resp.status_code != 403, (
                f"[{role.value}] {path} unexpectedly forbidden"
            )
        else:
            assert resp.status_code == 403, (
                f"[{role.value}] {path} expected 403, got {resp.status_code}"
            )
