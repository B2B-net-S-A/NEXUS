"""Tests for /api/invite-links (recruiter-facing) and /api/public/apply/{token}.

Covers:
- Link creation with published vs draft job (400 on draft).
- RBAC — non-privileged recruiter sees only own links.
- Revoke flow (authorised caller + subsequent 404 on public GET).
- Public GET metadata shape (no sensitive fields leaked).
- Public POST creates new candidate with correct `created_by` + CandidateStage.
- Public POST for a duplicate email updates existing candidate and reassigns ownership.
- Multi-use: second application through the same link increments use_count.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole


async def _seed_user(role: UserRole, label: str = "invite") -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"invlink-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Inv"

    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Invite Test {role.value} {label}",
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        uid = u.id
    return uid, email, password


async def _seed_job(status: JobStatus = JobStatus.published) -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Senior FE {unique}",
            location="Warszawa",
            status=status,
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
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def inv_client() -> AsyncClient:
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_create_invite_link_happy_path(inv_client: AsyncClient):
    uid, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(inv_client, email, password)
    job_id = await _seed_job(JobStatus.published)

    resp = await inv_client.post(
        "/api/invite-links",
        json={"job_id": job_id, "label": "LinkedIn post", "expires_in_days": 7},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token"]
    assert "/apply/" in body["url"]
    assert body["job"]["id"] == job_id
    assert body["status"] == "active"
    assert body["created_by_user"]["id"] == uid


@pytest.mark.asyncio
async def test_create_invite_link_rejects_draft_job(inv_client: AsyncClient):
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(inv_client, email, password)
    job_id = await _seed_job(JobStatus.draft)

    resp = await inv_client.post(
        "/api/invite-links",
        json={"job_id": job_id, "expires_in_days": 30},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_mine_isolates_recruiters(inv_client: AsyncClient):
    # Recruiter A creates a link; recruiter B must not see it.
    _, email_a, pass_a = await _seed_user(UserRole.recruiter, "A")
    headers_a = await _login(inv_client, email_a, pass_a)
    job_id = await _seed_job()
    create = await inv_client.post(
        "/api/invite-links",
        json={"job_id": job_id, "expires_in_days": 30},
        headers=headers_a,
    )
    token_a = create.json()["token"]

    _, email_b, pass_b = await _seed_user(UserRole.recruiter, "B")
    headers_b = await _login(inv_client, email_b, pass_b)
    list_b = await inv_client.get("/api/invite-links", headers=headers_b)
    assert list_b.status_code == 200
    tokens_b = [row["token"] for row in list_b.json()]
    assert token_a not in tokens_b


@pytest.mark.asyncio
async def test_public_get_meta_does_not_leak_secrets(inv_client: AsyncClient):
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(inv_client, email, password)
    job_id = await _seed_job()
    token = (
        await inv_client.post(
            "/api/invite-links",
            json={"job_id": job_id, "label": "PRIVATE_LABEL", "expires_in_days": 30},
            headers=headers,
        )
    ).json()["token"]

    meta = await inv_client.get(f"/api/public/apply/{token}")
    assert meta.status_code == 200, meta.text
    body = meta.json()
    assert "first_name" in body["recruiter"]
    assert body["job"]["title"]
    assert "expires_at" in body
    # Negative: no private label, no email, no token repetition.
    serialized = meta.text
    assert "PRIVATE_LABEL" not in serialized
    assert email not in serialized


@pytest.mark.asyncio
async def test_public_apply_creates_candidate_with_ownership(inv_client: AsyncClient):
    uid, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(inv_client, email, password)
    job_id = await _seed_job()
    token = (
        await inv_client.post(
            "/api/invite-links",
            json={"job_id": job_id, "expires_in_days": 30},
            headers=headers,
        )
    ).json()["token"]

    applicant_email = f"applicant-{uuid.uuid4().hex[:6]}@example.com"
    resp = await inv_client.post(
        f"/api/public/apply/{token}",
        data={
            "first_name": "Jan",
            "last_name": "Kowalski",
            "email": applicant_email,
            "phone": "+48 600 111 222",
        },
        files={"cv": ("cv.pdf", io.BytesIO(b"%PDF-1.4 minimal"), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "created"

    # Verify candidate has created_by = recruiter, and stage exists on correct job.
    async with AsyncSessionLocal() as db:
        cand = await db.scalar(
            select(Candidate).where(Candidate.email == applicant_email)
        )
        assert cand is not None
        assert cand.created_by == uid
        stage = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == cand.id,
                CandidateStage.job_id == job_id,
            )
        )
        assert stage is not None

        link = await db.scalar(
            select(CandidateInviteLink).where(CandidateInviteLink.token == token)
        )
        assert link and link.use_count == 1 and link.last_used_at is not None


@pytest.mark.asyncio
async def test_public_apply_updates_duplicate_email_and_reassigns_ownership(
    inv_client: AsyncClient,
):
    # Seed an existing candidate owned by recruiter X.
    uid_x, email_x, pass_x = await _seed_user(UserRole.recruiter, "owner-x")
    job_id = await _seed_job()
    applicant_email = f"dup-{uuid.uuid4().hex[:6]}@example.com"
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Old",
            lastname="Name",
            email=applicant_email,
            created_by=uid_x,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        original_id = cand.id

    # Recruiter Y creates a link and the candidate re-applies.
    uid_y, email_y, pass_y = await _seed_user(UserRole.recruiter, "new-y")
    headers_y = await _login(inv_client, email_y, pass_y)
    token = (
        await inv_client.post(
            "/api/invite-links",
            json={"job_id": job_id, "expires_in_days": 30},
            headers=headers_y,
        )
    ).json()["token"]

    resp = await inv_client.post(
        f"/api/public/apply/{token}",
        data={
            "first_name": "New",
            "last_name": "Name",
            "email": applicant_email,
        },
        files={"cv": ("cv.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "updated"

    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.id == original_id))
        assert cand is not None
        assert cand.name == "New"
        assert cand.created_by == uid_y  # ownership reassigned


@pytest.mark.asyncio
async def test_public_apply_is_multi_use_until_expiry(inv_client: AsyncClient):
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(inv_client, email, password)
    job_id = await _seed_job()
    token = (
        await inv_client.post(
            "/api/invite-links",
            json={"job_id": job_id, "expires_in_days": 30},
            headers=headers,
        )
    ).json()["token"]

    for i in range(2):
        resp = await inv_client.post(
            f"/api/public/apply/{token}",
            data={
                "first_name": f"Applicant{i}",
                "last_name": "X",
                "email": f"multi-{i}-{uuid.uuid4().hex[:6]}@example.com",
            },
            files={"cv": ("cv.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
        assert resp.status_code == 201, resp.text

    async with AsyncSessionLocal() as db:
        link = await db.scalar(
            select(CandidateInviteLink).where(CandidateInviteLink.token == token)
        )
        assert link and link.use_count == 2


@pytest.mark.asyncio
async def test_revoke_prevents_future_applications(inv_client: AsyncClient):
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(inv_client, email, password)
    job_id = await _seed_job()
    token = (
        await inv_client.post(
            "/api/invite-links",
            json={"job_id": job_id, "expires_in_days": 30},
            headers=headers,
        )
    ).json()["token"]

    rev = await inv_client.post(
        f"/api/invite-links/{token}/revoke", headers=headers
    )
    assert rev.status_code == 204

    meta = await inv_client.get(f"/api/public/apply/{token}")
    assert meta.status_code == 404


@pytest.mark.asyncio
async def test_public_apply_rejects_expired_link(inv_client: AsyncClient):
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(inv_client, email, password)
    job_id = await _seed_job()
    token = (
        await inv_client.post(
            "/api/invite-links",
            json={"job_id": job_id, "expires_in_days": 7},
            headers=headers,
        )
    ).json()["token"]

    async with AsyncSessionLocal() as db:
        link = await db.scalar(
            select(CandidateInviteLink).where(CandidateInviteLink.token == token)
        )
        link.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()

    meta = await inv_client.get(f"/api/public/apply/{token}")
    assert meta.status_code == 404
