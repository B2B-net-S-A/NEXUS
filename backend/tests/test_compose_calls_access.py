"""Regression tests for Module 6 findings P0.9 / P0.11.

P0.9: the M365 compose/reply/bulk endpoints took a bare ``CurrentUser``, so a
read-only viewer could send real mail (compose) or manage mailbox rows.
P0.11: candidate calls (transcripts + recording URLs) were readable and
creatable by any logged-in user.

All of these now require ``CandidatePIIAccess`` (internal operational roles),
so the viewer role is refused with 403 before anything happens; operational
roles pass the gate.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.user import User, UserRole


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"m6cc-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!M6"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"M6 cc {role.value}",
                role=role,
                roles=[role.value],
                is_active=True,
            )
        )
        await db.commit()
    return email, password


async def _seed_candidate() -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        c = Candidate(name=f"Cand{unique}", lastname="CC", email=f"{unique}@x.com")
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def cc_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app
    from httpx import ASGITransport

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_viewer_cannot_send_or_read_calls(cc_client: AsyncClient):
    cand_id = await _seed_candidate()
    v_email, v_pass = await _seed_user(UserRole.user)
    h = await _login(cc_client, v_email, v_pass)

    compose = await cc_client.post(
        f"/api/candidates/{cand_id}/emails/compose",
        headers=h,
        json={"to": ["x@example.com"], "subject": "hi", "body_html": "<p>hi</p>"},
    )
    assert compose.status_code == 403

    reply = await cc_client.post(
        f"/api/candidates/{cand_id}/emails/reply",
        headers=h,
        json={"email_id": 1, "body_html": "<p>re</p>"},
    )
    assert reply.status_code == 403

    calls = await cc_client.get(f"/api/candidates/{cand_id}/calls", headers=h)
    assert calls.status_code == 403

    log = await cc_client.post("/api/calls", headers=h, json={"candidate_id": cand_id})
    assert log.status_code == 403

    bulk = await cc_client.post(
        "/api/microsoft365/emails/bulk",
        headers=h,
        json={"email_ids": [1], "action": "mark_read"},
    )
    assert bulk.status_code == 403


@pytest.mark.asyncio
async def test_recruiter_passes_the_gate(cc_client: AsyncClient):
    cand_id = await _seed_candidate()
    r_email, r_pass = await _seed_user(UserRole.recruiter)
    h = await _login(cc_client, r_email, r_pass)

    # Reading + logging calls works for an operational role.
    calls = await cc_client.get(f"/api/candidates/{cand_id}/calls", headers=h)
    assert calls.status_code == 200

    log = await cc_client.post("/api/calls", headers=h, json={"candidate_id": cand_id})
    assert log.status_code == 201

    # Compose passes the role gate; it then fails only because the recruiter has
    # no active M365 connection in the test env — the point is it is NOT a 403.
    compose = await cc_client.post(
        f"/api/candidates/{cand_id}/emails/compose",
        headers=h,
        json={"to": ["x@example.com"], "subject": "hi", "body_html": "<p>hi</p>"},
    )
    assert compose.status_code != 403
