"""Tests for GET /api/reports/invite-links — channel aggregation + RBAC."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.user import User, UserRole


async def _seed_user(role: UserRole, label: str = "rep") -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"rep-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Rep"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Rep {label} {role.value}",
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _seed_published_job() -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Role {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def rep_client() -> AsyncClient:
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_link(
    creator_id: int,
    job_id: int,
    label: str | None,
    use_count: int = 0,
) -> str:
    """Create a ready-to-query invite-link row directly — bypasses the API."""
    token = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        link = CandidateInviteLink(
            token=token,
            created_by=creator_id,
            job_id=job_id,
            label=label,
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            use_count=use_count,
        )
        db.add(link)
        await db.commit()
    return token


@pytest.mark.asyncio
async def test_invite_links_report_aggregates_by_label(rep_client: AsyncClient):
    creator_id, _, _ = await _seed_user(UserRole.recruiter, "creator")
    job_id = await _seed_published_job()

    # Use a unique label prefix so assertions aren't polluted by links from
    # other tests in the same DB run.
    prefix = uuid.uuid4().hex[:6]
    linkedin_label = f"LinkedIn-{prefix}"
    facebook_label = f"Facebook-{prefix}"

    await _seed_link(creator_id, job_id, linkedin_label, use_count=3)
    await _seed_link(creator_id, job_id, linkedin_label, use_count=1)
    await _seed_link(creator_id, job_id, facebook_label, use_count=2)

    _, admin_email, admin_pass = await _seed_user(UserRole.admin, "rep-admin")
    admin_headers = await _login(rep_client, admin_email, admin_pass)

    resp = await rep_client.get(
        "/api/reports/invite-links?period=all", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    by_channel = {row["channel"]: row for row in data["channels"]}
    # Own labels are grouped and aggregated correctly.
    assert by_channel[linkedin_label]["links_count"] == 2
    assert by_channel[linkedin_label]["applications"] == 4
    assert by_channel[facebook_label]["links_count"] == 1
    assert by_channel[facebook_label]["applications"] == 2
    # `Bez etykiety` bucket always present whenever any unlabelled link
    # exists in the DB (fixtures or earlier tests may have seeded some).
    # We just assert the keys exist, not the counts.
    assert linkedin_label in by_channel
    assert facebook_label in by_channel


@pytest.mark.asyncio
async def test_invite_links_report_rbac_rejects_recruiter(
    rep_client: AsyncClient,
):
    _, email, password = await _seed_user(UserRole.recruiter, "rbac")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get("/api/reports/invite-links", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_invite_links_report_allows_head_of_recruitment(
    rep_client: AsyncClient,
):
    _, email, password = await _seed_user(UserRole.head_of_recruitment, "hr")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get(
        "/api/reports/invite-links?period=all", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "channels" in body and "totals" in body
