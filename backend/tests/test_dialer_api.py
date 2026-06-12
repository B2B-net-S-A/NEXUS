"""Integration tests for /api/dialer/token + /api/dialer/calls/initiate.

Covers the kill-switch (503), the dialer-enablement gate (412), the PL-only
allowlist (400), the anti-toll-fraud daily cap (429), and the happy path.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.call import Call
from app.models.candidate import Candidate
from app.models.user import User


@pytest.fixture
def _enable_dialer(monkeypatch):
    monkeypatch.setattr(settings, "OWN_DIALER_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "DIALER_WEBHOOK_SECRET", "s" * 40, raising=False)


async def _make_candidate(phone: str) -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"DialerAPI-{unique}",
            lastname="Test",
            email=f"dialer-api-{unique}@example.com",
            phone=phone,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _cleanup_candidate(candidate_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Call).where(Call.candidate_id == candidate_id))
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.commit()


async def _set_admin_sip(app_client: AsyncClient, username: str | None) -> None:
    email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email))
        user.dialer_sip_username = username
        await db.commit()


# ── /token ────────────────────────────────────────────────────────────────────


async def test_token_503_when_disabled(
    app_client: AsyncClient, app_auth_headers, monkeypatch
):
    monkeypatch.setattr(settings, "OWN_DIALER_ENABLED", False, raising=False)
    resp = await app_client.post("/api/dialer/token", headers=app_auth_headers)
    assert resp.status_code == 503


async def test_token_412_without_sip_username(
    app_client: AsyncClient, app_auth_headers, _enable_dialer
):
    await _set_admin_sip(app_client, None)
    resp = await app_client.post("/api/dialer/token", headers=app_auth_headers)
    assert resp.status_code == 412


async def test_token_success(
    app_client: AsyncClient, app_auth_headers, _enable_dialer, monkeypatch
):
    monkeypatch.setattr(
        settings, "COTURN_URLS", "turn:turn.example:3478", raising=False
    )
    monkeypatch.setattr(settings, "COTURN_STATIC_SECRET", "turn-secret", raising=False)
    monkeypatch.setattr(settings, "JAMBONZ_SIP_REALM", "dialer.example", raising=False)
    await _set_admin_sip(app_client, "recruiter-test-sip")
    try:
        resp = await app_client.post("/api/dialer/token", headers=app_auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["sip_username"] == "recruiter-test-sip"
        assert data["sip_realm"] == "dialer.example"
        assert data["sip_password"]  # non-empty short-lived secret
        assert len(data["ice_servers"]) == 1
        ice = data["ice_servers"][0]
        assert ice["urls"].startswith("turn:")
        assert ice["username"] and ice["credential"]  # ephemeral TURN creds
        assert data["expires_at"] > 0
    finally:
        await _set_admin_sip(app_client, None)


# ── /calls/initiate ─────────────────────────────────────────────────────────


async def test_initiate_503_when_disabled(
    app_client: AsyncClient, app_auth_headers, monkeypatch
):
    monkeypatch.setattr(settings, "OWN_DIALER_ENABLED", False, raising=False)
    resp = await app_client.post(
        "/api/dialer/calls/initiate", json={"candidate_id": 1}, headers=app_auth_headers
    )
    assert resp.status_code == 503


async def test_initiate_rejects_non_pl(
    app_client: AsyncClient, app_auth_headers, _enable_dialer
):
    candidate_id = await _make_candidate("+1 415 555 0100")  # US number
    try:
        resp = await app_client.post(
            "/api/dialer/calls/initiate",
            json={"candidate_id": candidate_id},
            headers=app_auth_headers,
        )
        assert resp.status_code == 400
    finally:
        await _cleanup_candidate(candidate_id)


async def test_initiate_daily_cap(
    app_client: AsyncClient, app_auth_headers, _enable_dialer, monkeypatch
):
    monkeypatch.setattr(settings, "DIALER_MAX_CALLS_PER_USER_PER_DAY", 0, raising=False)
    candidate_id = await _make_candidate("+48 602-345-678")
    try:
        resp = await app_client.post(
            "/api/dialer/calls/initiate",
            json={"candidate_id": candidate_id},
            headers=app_auth_headers,
        )
        assert resp.status_code == 429
    finally:
        await _cleanup_candidate(candidate_id)


async def test_initiate_success_pl(
    app_client: AsyncClient, app_auth_headers, _enable_dialer
):
    candidate_id = await _make_candidate("+48 602-345-678")
    try:
        resp = await app_client.post(
            "/api/dialer/calls/initiate",
            json={"candidate_id": candidate_id},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["candidate_id"] == candidate_id
        assert data["call_id"] > 0
        async with AsyncSessionLocal() as db:
            call = await db.get(Call, data["call_id"])
            assert call.provider_type == "dialer"
            assert call.status.value == "initiated"
    finally:
        await _cleanup_candidate(candidate_id)
