"""Regression test for Module 6 finding P0.5 (template render PII enumeration).

`POST /api/user-email-templates/{id}/render` exposes candidate email/phone/
location/linkedin to the Jinja context. It used a bare ``CurrentUser``, so a
read-only viewer (``UserRole.user``) could author ``{{ candidate.email }}`` and
enumerate PII across candidate IDs. It now requires ``CandidatePIIAccess`` — the
internal-operational roles already trusted with candidate PII — which excludes
the viewer.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"m6tpl-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!M6"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"M6 tpl {role.value}",
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


@pytest_asyncio.fixture
async def tpl_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_viewer_cannot_render_template(tpl_client: AsyncClient):
    # A recruiter owns a template that dereferences candidate PII.
    r_email, r_pass = await _seed_user(UserRole.recruiter)
    r_headers = await _login(tpl_client, r_email, r_pass)
    created = await tpl_client.post(
        "/api/user-email-templates",
        headers=r_headers,
        json={"name": "leak", "body_html": "{{ candidate.email }}"},
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    # The read-only viewer is refused by the role gate before any render runs.
    v_email, v_pass = await _seed_user(UserRole.user)
    v_headers = await _login(tpl_client, v_email, v_pass)
    resp = await tpl_client.post(
        f"/api/user-email-templates/{template_id}/render",
        headers=v_headers,
        json={"candidate_id": 1},
    )
    assert resp.status_code == 403

    # The gate rejects even a non-existent template id (dependency runs first),
    # so it is not an information oracle.
    resp_missing = await tpl_client.post(
        "/api/user-email-templates/999999/render",
        headers=v_headers,
        json={"candidate_id": 1},
    )
    assert resp_missing.status_code == 403


@pytest.mark.asyncio
async def test_recruiter_can_still_render_own_template(tpl_client: AsyncClient):
    r_email, r_pass = await _seed_user(UserRole.recruiter)
    r_headers = await _login(tpl_client, r_email, r_pass)
    created = await tpl_client.post(
        "/api/user-email-templates",
        headers=r_headers,
        json={"name": "ok", "body_html": "Cześć {{ mystery_var }}"},
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    resp = await tpl_client.post(
        f"/api/user-email-templates/{template_id}/render",
        headers=r_headers,
        json={},  # no candidate → empty namespace, still a valid render
    )
    assert resp.status_code == 200, resp.text
    assert "mystery_var" in resp.json()["unresolved_vars"]
