"""Regression tests for Module 6 finding P1.3 (presence IDOR + PII leak).

Any authenticated user could subscribe to any ``candidate:{id}`` / ``job:{id}``
presence channel, and the viewer payload carried each colleague's email.
Containment: presence subscribe + the HTTP snapshot are gated to internal
operational roles (viewer excluded), and the payload no longer includes email.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.api.ws import ConnectionManager, ViewerInfo
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole


def test_viewers_payload_has_no_email():
    mgr = ConnectionManager()
    key = "candidate:1"
    mgr._viewers[key] = {5: set()}
    mgr._user_info[5] = ViewerInfo(
        user_id=5, name="Anna Nowak", email="anna@example.com", role="recruiter"
    )

    payload = mgr._build_viewers_payload(key)
    assert len(payload) == 1
    entry = payload[0]
    assert "email" not in entry  # redacted
    assert entry["name"] == "Anna Nowak"  # safe identity kept
    assert entry["role"] == "recruiter"


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"m6pres-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!M6"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"M6 pres {role.value}",
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
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_viewer_cannot_read_presence_snapshot(app_client: AsyncClient):
    v_email, v_pass = await _seed_user(UserRole.user)
    h = await _login(app_client, v_email, v_pass)
    resp = await app_client.get("/api/presence/candidate/1/viewers", headers=h)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_recruiter_can_read_presence_snapshot(app_client: AsyncClient):
    r_email, r_pass = await _seed_user(UserRole.recruiter)
    h = await _login(app_client, r_email, r_pass)
    resp = await app_client.get("/api/presence/candidate/1/viewers", headers=h)
    assert resp.status_code == 200
    assert "viewers" in resp.json()
