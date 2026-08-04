"""Tests for Recruiter Ownership (primary_owner + collaborators + mine filter).

Uses the in-process `rbac_client` fixture pattern (see tests/test_rbac.py) so
the suite runs in CI without a live uvicorn server. Each test seeds its own
users and at least one job to stay order-independent.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.job import Job, JobStatus
from app.models.team_structure import ClientTacAssignment, DeliveryLeadClientAssignment
from app.models.user import User, UserRole


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ownership_client() -> AsyncClient:
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_user(role: UserRole, prefix: str = "own") -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"{prefix}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!OWN"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Own Test {role.value} {unique}",
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _seed_client() -> int:
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        c = Client(name=f"OwnTestClient-{uuid.uuid4().hex[:6]}")
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job(recruiter_id: int | None = None) -> int:
    client_id = await _seed_client()
    async with AsyncSessionLocal() as db:
        j = Job(
            title=f"Ownership-test Job {uuid.uuid4().hex[:6]}",
            status=JobStatus.draft,
            recruiter_id=recruiter_id,
            client_id=client_id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _grant_dl_job_scope(delivery_lead_id: int, job_id: int) -> None:
    """Attach a job to the explicit client–TAC graph visible to one DL."""
    tac_id, _, _ = await _seed_user(UserRole.tac, prefix="own-scope")
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job is not None
        job.tac_id = tac_id
        db.add_all(
            [
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=delivery_lead_id,
                    client_id=job.client_id,
                    is_head=True,
                ),
                ClientTacAssignment(
                    tac_user_id=tac_id,
                    client_id=job.client_id,
                    is_primary=False,
                    is_first_priority_for_tac=False,
                ),
            ]
        )
        await db.commit()


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── Assign owner (Admin + DL only) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_owner_as_dl_succeeds(ownership_client: AsyncClient):
    dl_id, dl_email, dl_pass = await _seed_user(UserRole.delivery_lead)
    rec_id, _, _ = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job()
    await _grant_dl_job_scope(dl_id, job_id)

    headers = await _login(ownership_client, dl_email, dl_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/owner",
        headers=headers,
        json={"user_id": rec_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recruiter_id"] == rec_id
    assert body["primary_owner"]["id"] == rec_id


@pytest.mark.asyncio
async def test_assign_owner_as_admin_succeeds(ownership_client: AsyncClient):
    _, admin_email, admin_pass = await _seed_user(UserRole.admin)
    rec_id, _, _ = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job()

    headers = await _login(ownership_client, admin_email, admin_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/owner",
        headers=headers,
        json={"user_id": rec_id},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_assign_owner_as_tac_forbidden(ownership_client: AsyncClient):
    _, tac_email, tac_pass = await _seed_user(UserRole.tac)
    rec_id, _, _ = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job()

    headers = await _login(ownership_client, tac_email, tac_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/owner",
        headers=headers,
        json={"user_id": rec_id},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_assign_owner_rejects_read_only_user(ownership_client: AsyncClient):
    dl_id, dl_email, dl_pass = await _seed_user(UserRole.delivery_lead)
    viewer_id, _, _ = await _seed_user(UserRole.user)
    job_id = await _seed_job()
    await _grant_dl_job_scope(dl_id, job_id)

    headers = await _login(ownership_client, dl_email, dl_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/owner",
        headers=headers,
        json={"user_id": viewer_id},
    )
    assert resp.status_code == 409, resp.text


# ── Claim (self-assign on unassigned) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_claim_unassigned_as_recruiter_succeeds(ownership_client: AsyncClient):
    rec_id, rec_email, rec_pass = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job()  # no owner

    headers = await _login(ownership_client, rec_email, rec_pass)
    resp = await ownership_client.post(f"/api/jobs/{job_id}/claim", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["primary_owner"]["id"] == rec_id


@pytest.mark.asyncio
async def test_claim_already_owned_returns_409(ownership_client: AsyncClient):
    owner_id, _, _ = await _seed_user(UserRole.recruiter)
    _, challenger_email, challenger_pass = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(recruiter_id=owner_id)

    headers = await _login(ownership_client, challenger_email, challenger_pass)
    resp = await ownership_client.post(f"/api/jobs/{job_id}/claim", headers=headers)
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_claim_as_read_only_user_forbidden(ownership_client: AsyncClient):
    _, viewer_email, viewer_pass = await _seed_user(UserRole.user)
    job_id = await _seed_job()

    headers = await _login(ownership_client, viewer_email, viewer_pass)
    resp = await ownership_client.post(f"/api/jobs/{job_id}/claim", headers=headers)
    assert resp.status_code == 403, resp.text


# ── Mine filter ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mine_filter_includes_primary_owner_jobs(
    ownership_client: AsyncClient,
):
    rec_id, rec_email, rec_pass = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(recruiter_id=rec_id)

    headers = await _login(ownership_client, rec_email, rec_pass)
    resp = await ownership_client.get("/api/jobs?mine=true", headers=headers)
    assert resp.status_code == 200, resp.text
    ids = [j["id"] for j in resp.json()["items"]]
    assert job_id in ids


@pytest.mark.asyncio
async def test_mine_filter_excludes_foreign_jobs(ownership_client: AsyncClient):
    stranger_id, _, _ = await _seed_user(UserRole.recruiter)
    _, viewer_email, viewer_pass = await _seed_user(UserRole.recruiter)
    stranger_job = await _seed_job(recruiter_id=stranger_id)

    headers = await _login(ownership_client, viewer_email, viewer_pass)
    resp = await ownership_client.get("/api/jobs?mine=true", headers=headers)
    assert resp.status_code == 200, resp.text
    ids = [j["id"] for j in resp.json()["items"]]
    assert stranger_job not in ids


@pytest.mark.asyncio
async def test_mine_filter_includes_collaborator_jobs(
    ownership_client: AsyncClient,
):
    owner_id, owner_email, owner_pass = await _seed_user(UserRole.recruiter)
    collab_id, collab_email, collab_pass = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)

    # Owner adds the sourcer as a collaborator (primary owner → allowed)
    owner_headers = await _login(ownership_client, owner_email, owner_pass)
    add = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=owner_headers,
        json={"user_id": collab_id},
    )
    assert add.status_code == 201, add.text

    # Now the sourcer's "mine" should include the job
    collab_headers = await _login(ownership_client, collab_email, collab_pass)
    resp = await ownership_client.get("/api/jobs?mine=true", headers=collab_headers)
    assert resp.status_code == 200
    ids = [j["id"] for j in resp.json()["items"]]
    assert job_id in ids


# ── Collaborator permissions ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_collaborator_add_by_primary_succeeds(ownership_client: AsyncClient):
    owner_id, owner_email, owner_pass = await _seed_user(UserRole.recruiter)
    collab_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)

    headers = await _login(ownership_client, owner_email, owner_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=headers,
        json={"user_id": collab_id},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_collaborator_add_by_foreign_recruiter_forbidden(
    ownership_client: AsyncClient,
):
    owner_id, _, _ = await _seed_user(UserRole.recruiter)
    _, stranger_email, stranger_pass = await _seed_user(UserRole.recruiter)
    collab_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)

    headers = await _login(ownership_client, stranger_email, stranger_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=headers,
        json={"user_id": collab_id},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_collaborator_add_duplicate_is_idempotent(
    ownership_client: AsyncClient,
):
    owner_id, owner_email, owner_pass = await _seed_user(UserRole.recruiter)
    collab_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)
    headers = await _login(ownership_client, owner_email, owner_pass)

    r1 = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=headers,
        json={"user_id": collab_id},
    )
    r2 = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=headers,
        json={"user_id": collab_id},
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    # One row, not two
    async with AsyncSessionLocal() as db:
        from app.models.job_collaborator import JobCollaborator

        rows = (
            (
                await db.execute(
                    select(JobCollaborator).where(
                        JobCollaborator.job_id == job_id,
                        JobCollaborator.user_id == collab_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_collaborator_remove_by_dl_succeeds(ownership_client: AsyncClient):
    dl_id, dl_email, dl_pass = await _seed_user(UserRole.delivery_lead)
    owner_id, _, _ = await _seed_user(UserRole.recruiter)
    collab_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)
    await _grant_dl_job_scope(dl_id, job_id)

    async with AsyncSessionLocal() as db:
        from app.models.job_collaborator import JobCollaborator

        db.add(JobCollaborator(job_id=job_id, user_id=collab_id, added_by=owner_id))
        await db.commit()

    headers = await _login(ownership_client, dl_email, dl_pass)
    resp = await ownership_client.delete(
        f"/api/jobs/{job_id}/collaborators/{collab_id}", headers=headers
    )
    assert resp.status_code == 204, resp.text


# ── /api/users directory ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_users_directory_excludes_read_only_viewers(
    ownership_client: AsyncClient,
):
    _, rec_email, rec_pass = await _seed_user(UserRole.recruiter)
    viewer_id, _, _ = await _seed_user(UserRole.user)

    headers = await _login(ownership_client, rec_email, rec_pass)
    resp = await ownership_client.get("/api/users", headers=headers)
    assert resp.status_code == 200, resp.text
    ids = [u["id"] for u in resp.json()]
    assert viewer_id not in ids


@pytest.mark.asyncio
async def test_users_directory_respects_roles_filter(ownership_client: AsyncClient):
    rec_id, rec_email, rec_pass = await _seed_user(UserRole.recruiter)
    sourcer_id, _, _ = await _seed_user(UserRole.sourcer)

    headers = await _login(ownership_client, rec_email, rec_pass)
    resp = await ownership_client.get("/api/users?roles=recruiter", headers=headers)
    assert resp.status_code == 200
    ids = [u["id"] for u in resp.json()]
    assert rec_id in ids
    assert sourcer_id not in ids


@pytest.mark.asyncio
async def test_users_directory_and_mentions_include_secondary_roles(
    ownership_client: AsyncClient,
):
    _, requester_email, requester_password = await _seed_user(UserRole.recruiter)
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        hybrid = User(
            email=f"hybrid-recruiter-tac-{unique}@example.com",
            password_hash=hash_password(f"T3st_{unique}!HYBRID"),
            name=f"Hybrid TAC {unique}",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value, UserRole.tac.value],
            is_active=True,
        )
        db.add(hybrid)
        await db.commit()
        await db.refresh(hybrid)
        hybrid_id = hybrid.id

    headers = await _login(
        ownership_client,
        requester_email,
        requester_password,
    )
    directory = await ownership_client.get(
        "/api/users?roles=tac",
        headers=headers,
    )
    mentionable = await ownership_client.get(
        "/api/users/mentionable",
        headers=headers,
    )

    assert directory.status_code == 200, directory.text
    assert mentionable.status_code == 200, mentionable.text
    directory_row = next(user for user in directory.json() if user["id"] == hybrid_id)
    assert directory_row["role"] == UserRole.recruiter.value
    assert UserRole.tac.value in directory_row["roles"]
    assert hybrid_id in {user["id"] for user in mentionable.json()}
