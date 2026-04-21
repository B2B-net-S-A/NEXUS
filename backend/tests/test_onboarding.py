"""Tests for the first-login onboarding endpoint.

Covers the DL/recruiter happy paths plus error cases (wrong role, empty lists,
invalid job ids, idempotency, unauthenticated). Uses the in-process ASGI client
so no live backend is required.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.client import Client
from app.models.job import Job, JobPriority, JobStatus
from app.models.job_collaborator import JobCollaborator
from app.models.user import User, UserRole


# ── Local helpers ────────────────────────────────────────────────────────────


async def _seed_user(role: UserRole, profile_completed: bool = False) -> tuple[User, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"pytest-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!PassX"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Pytest {role.value} {unique}",
            role=role,
            is_active=True,
            profile_completed=profile_completed,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user, password


async def _seed_client_and_jobs(count: int) -> list[int]:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Pytest Client {unique}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        ids: list[int] = []
        for i in range(count):
            job = Job(
                title=f"Pytest Job {unique} #{i}",
                status=JobStatus.published,
                priority=JobPriority.medium,
                needs_sourcing=False,
                client_id=client.id,
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)
            ids.append(job.id)
        return ids


async def _login(app_client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def dl_auth(app_client: AsyncClient) -> AsyncIterator[tuple[User, dict[str, str]]]:
    user, password = await _seed_user(UserRole.delivery_lead)
    headers = await _login(app_client, user.email, password)
    yield user, headers


@pytest_asyncio.fixture
async def recruiter_auth(
    app_client: AsyncClient,
) -> AsyncIterator[tuple[User, dict[str, str]]]:
    user, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, user.email, password)
    yield user, headers


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_me_returns_profile_completed(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Regression: UserResponse now exposes profile_completed + profile_completed_at."""
    resp = await app_client.get("/api/auth/me", headers=app_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "profile_completed" in body
    assert "profile_completed_at" in body
    assert isinstance(body["profile_completed"], bool)


@pytest.mark.asyncio
async def test_onboarding_unauthenticated(app_client: AsyncClient):
    resp = await app_client.post("/api/users/me/onboarding", json={})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_onboarding_wrong_role_rejected(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Admin must not be allowed to run onboarding — their flag is preset."""
    resp = await app_client.post(
        "/api/users/me/onboarding", headers=app_auth_headers, json={}
    )
    assert resp.status_code == 400
    assert "does not require onboarding" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_dl_happy_path(
    app_client: AsyncClient, dl_auth: tuple[User, dict[str, str]]
):
    user, headers = dl_auth
    job_ids = await _seed_client_and_jobs(count=3)
    priority_ids = job_ids[:2]
    sourcing_ids = job_ids[2:]

    resp = await app_client.post(
        "/api/users/me/onboarding",
        headers=headers,
        json={
            "priority_job_ids": priority_ids,
            "needs_sourcing_job_ids": sourcing_ids,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["profile_completed"] is True
    assert body["user"]["profile_completed_at"] is not None

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(Job).where(Job.id.in_(job_ids)))
        ).scalars().all()
        by_id = {j.id: j for j in rows}
        for jid in priority_ids:
            assert by_id[jid].priority == JobPriority.high
        for jid in sourcing_ids:
            assert by_id[jid].needs_sourcing is True

        refreshed = await db.scalar(select(User).where(User.id == user.id))
        assert refreshed.profile_completed is True
        assert refreshed.profile_completed_at is not None


@pytest.mark.asyncio
async def test_recruiter_happy_path(
    app_client: AsyncClient, recruiter_auth: tuple[User, dict[str, str]]
):
    user, headers = recruiter_auth
    job_ids = await _seed_client_and_jobs(count=3)

    resp = await app_client.post(
        "/api/users/me/onboarding",
        headers=headers,
        json={"active_job_ids": job_ids},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["profile_completed"] is True

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(JobCollaborator).where(
                    JobCollaborator.user_id == user.id,
                    JobCollaborator.job_id.in_(job_ids),
                )
            )
        ).scalars().all()
        assert {r.job_id for r in rows} == set(job_ids)


@pytest.mark.asyncio
async def test_onboarding_already_completed_conflict(
    app_client: AsyncClient, dl_auth: tuple[User, dict[str, str]]
):
    _, headers = dl_auth
    first = await app_client.post(
        "/api/users/me/onboarding",
        headers=headers,
        json={"priority_job_ids": [], "needs_sourcing_job_ids": []},
    )
    assert first.status_code == 200

    second = await app_client.post(
        "/api/users/me/onboarding",
        headers=headers,
        json={"priority_job_ids": [], "needs_sourcing_job_ids": []},
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_onboarding_invalid_job_ids(
    app_client: AsyncClient, dl_auth: tuple[User, dict[str, str]]
):
    _, headers = dl_auth
    resp = await app_client.post(
        "/api/users/me/onboarding",
        headers=headers,
        json={"priority_job_ids": [999_999_999], "needs_sourcing_job_ids": []},
    )
    assert resp.status_code == 400
    assert "Unknown job ids" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_onboarding_empty_lists_allowed(
    app_client: AsyncClient, recruiter_auth: tuple[User, dict[str, str]]
):
    user, headers = recruiter_auth
    resp = await app_client.post(
        "/api/users/me/onboarding",
        headers=headers,
        json={"active_job_ids": []},
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["profile_completed"] is True

    async with AsyncSessionLocal() as db:
        count = (
            await db.execute(
                select(JobCollaborator).where(JobCollaborator.user_id == user.id)
            )
        ).scalars().all()
        assert count == []
