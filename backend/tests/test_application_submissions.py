"""Tests for the P0-CAND-01 containment: public /apply/{token} submissions.

Covers:
- Duplicate-email apply parks a pending ApplicationSubmission and leaves the
  matched Candidate byte-for-byte unchanged (name/lastname/cv/owner), with a
  generic response (no created/updated enumeration leak).
- New-email apply still creates a candidate (branch A preserved).
- The recruiter review API: list pending, and resolve link / merge / create /
  reject — each performs the right mutation (or none) and writes an audit
  Activity.
- Authorization: the review API is gated to recruiter+ (viewer 403, anon 401).
"""

from __future__ import annotations

import io
import uuid
from typing import Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.application_submission import (
    ApplicationSubmission,
    ApplicationSubmissionStatus,
)
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole


async def _seed_user(role: UserRole, label: str = "sub") -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"appsub-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Sub"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"AppSub {role.value} {label}",
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _seed_job() -> int:
    from app.models.client import Client

    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"SubClient-{unique}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Backend {unique}",
            location="Kraków",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
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


async def _make_link(client: AsyncClient, headers: dict, job_id: int) -> str:
    resp = await client.post(
        "/api/invite-links",
        json={"job_id": job_id, "expires_in_days": 30},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["token"]


async def _seed_candidate(
    email: str, created_by: int, *, name: str = "Old", cv: str = "orig.pdf"
) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=name,
            lastname="Existing",
            email=email,
            phone="+48 500 500 500",
            created_by=created_by,
            cv_filename=cv,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


@pytest_asyncio.fixture
async def sub_client() -> AsyncClient:
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def _stub_external_services(monkeypatch):
    """Keep branch-A apply from hitting Voyage/Qdrant/LLM in CI."""

    async def _noop_embed(candidate_id, db):
        return True

    async def _noop_task(candidate_id: int) -> None:
        return None

    monkeypatch.setattr(
        "app.services.embedding_service.embed_candidate", _noop_embed
    )
    monkeypatch.setattr(
        "app.api.public_share._invite_post_apply_task", _noop_task
    )


async def _apply(
    client: AsyncClient,
    token: str,
    *,
    email: str,
    first: str = "New",
    last: str = "Applicant",
    phone: Optional[str] = None,
    cv_name: str = "cv.pdf",
) -> None:
    data = {"first_name": first, "last_name": last, "email": email}
    if phone:
        data["phone"] = phone
    resp = await client.post(
        f"/api/public/apply/{token}",
        data=data,
        files={"cv": (cv_name, io.BytesIO(b"%PDF-1.4 body"), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    # Generic response — never leaks whether the e-mail already existed.
    assert resp.json()["status"] == "received"


# ── (a) duplicate email — no mutation, pending submission ────────────────────


@pytest.mark.asyncio
async def test_duplicate_email_apply_parks_submission(sub_client: AsyncClient):
    uid_owner, _, _ = await _seed_user(UserRole.recruiter, "owner")
    uid_link, email_link, pass_link = await _seed_user(UserRole.recruiter, "linker")
    job_id = await _seed_job()
    dup_email = f"dup-{uuid.uuid4().hex[:6]}@example.com"
    cand_id = await _seed_candidate(dup_email, uid_owner, name="Canonical")

    headers = await _login(sub_client, email_link, pass_link)
    token = await _make_link(sub_client, headers, job_id)

    await _apply(
        sub_client, token, email=dup_email, first="Impostor", phone="+48 1 2 3 4 5 6"
    )

    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        assert cand.name == "Canonical"  # untouched
        assert cand.created_by == uid_owner  # owner untouched
        assert cand.cv_filename == "orig.pdf"  # CV untouched
        assert cand.phone == "+48 500 500 500"  # contact untouched

        sub = await db.scalar(
            select(ApplicationSubmission).where(
                ApplicationSubmission.matched_candidate_id == cand_id
            )
        )
        assert sub is not None
        assert sub.status == ApplicationSubmissionStatus.pending_review.value
        assert sub.submitted_first_name == "Impostor"
        assert sub.cv_filename == "cv.pdf"


# ── (b) new email — branch A still creates a candidate ───────────────────────


@pytest.mark.asyncio
async def test_new_email_apply_still_creates_candidate(sub_client: AsyncClient):
    uid, email, password = await _seed_user(UserRole.recruiter, "newmail")
    job_id = await _seed_job()
    headers = await _login(sub_client, email, password)
    token = await _make_link(sub_client, headers, job_id)

    fresh_email = f"fresh-{uuid.uuid4().hex[:6]}@example.com"
    await _apply(sub_client, token, email=fresh_email, first="Genuinely", last="New")

    async with AsyncSessionLocal() as db:
        cand = await db.scalar(
            select(Candidate).where(Candidate.email == fresh_email)
        )
        assert cand is not None
        assert cand.created_by == uid
        assert cand.name == "Genuinely"
        stage = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == cand.id,
                CandidateStage.job_id == job_id,
            )
        )
        assert stage is not None
        # No submission is parked for a genuinely new applicant.
        sub = await db.scalar(
            select(ApplicationSubmission).where(
                ApplicationSubmission.submitted_email == fresh_email
            )
        )
        assert sub is None


# ── Review API helpers ───────────────────────────────────────────────────────


async def _park_submission(
    sub_client: AsyncClient, *, owner_id: int
) -> tuple[int, int, str, str]:
    """Return (submission_id, matched_candidate_id, dup_email, recruiter creds).

    Seeds a matched candidate, then drives a duplicate-email apply.
    """
    uid_link, email_link, pass_link = await _seed_user(UserRole.recruiter, "rev")
    job_id = await _seed_job()
    dup_email = f"rev-{uuid.uuid4().hex[:6]}@example.com"
    cand_id = await _seed_candidate(dup_email, owner_id, name="Matched")
    headers = await _login(sub_client, email_link, pass_link)
    token = await _make_link(sub_client, headers, job_id)
    await _apply(sub_client, token, email=dup_email, first="Sub", phone="+48 700")
    async with AsyncSessionLocal() as db:
        sub = await db.scalar(
            select(ApplicationSubmission).where(
                ApplicationSubmission.matched_candidate_id == cand_id
            )
        )
        assert sub is not None
        return sub.id, cand_id, dup_email, headers["Authorization"]


# ── (c) resolve: list + link / merge / create / reject ───────────────────────


@pytest.mark.asyncio
async def test_list_pending_submissions(sub_client: AsyncClient):
    uid_admin, email_a, pass_a = await _seed_user(UserRole.admin, "list-admin")
    admin_headers = await _login(sub_client, email_a, pass_a)
    sub_id, _, _, _ = await _park_submission(sub_client, owner_id=uid_admin)

    resp = await sub_client.get(
        "/api/application-submissions?status=pending_review", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()]
    assert sub_id in ids


@pytest.mark.asyncio
async def test_resolve_link_attaches_cv_without_mutation(sub_client: AsyncClient):
    uid_admin, email_a, pass_a = await _seed_user(UserRole.admin, "link-admin")
    admin_headers = await _login(sub_client, email_a, pass_a)
    sub_id, cand_id, _, _ = await _park_submission(sub_client, owner_id=uid_admin)

    resp = await sub_client.post(
        f"/api/application-submissions/{sub_id}/resolve",
        json={"action": "link"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "linked"

    async with AsyncSessionLocal() as db:
        # Candidate fields still untouched (link never overwrites).
        cand = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        assert cand.name == "Matched"
        assert cand.cv_filename == "orig.pdf"
        # A (non-primary) document was attached from the submission.
        doc = await db.scalar(
            select(CandidateDocument).where(
                CandidateDocument.candidate_id == cand_id,
                CandidateDocument.external_source == "apply_submission",
            )
        )
        assert doc is not None
        assert doc.is_primary is False
        # Audited.
        act = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == cand_id,
                Activity.action == "application_submission_resolved",
            )
        )
        assert act is not None
        assert (act.details or {}).get("resolve_action") == "link"


@pytest.mark.asyncio
async def test_resolve_merge_fills_only_empty_fields(sub_client: AsyncClient):
    uid_admin, email_a, pass_a = await _seed_user(UserRole.admin, "merge-admin")
    admin_headers = await _login(sub_client, email_a, pass_a)

    # Seed a candidate with NO linkedin so merge can fill it, but WITH a phone
    # so merge must not overwrite it.
    uid_owner, _, _ = await _seed_user(UserRole.recruiter, "merge-owner")
    uid_link, email_link, pass_link = await _seed_user(UserRole.recruiter, "merge-l")
    job_id = await _seed_job()
    dup_email = f"merge-{uuid.uuid4().hex[:6]}@example.com"
    cand_id = await _seed_candidate(dup_email, uid_owner, name="MergeMe")
    link_headers = await _login(sub_client, email_link, pass_link)
    token = await _make_link(sub_client, link_headers, job_id)
    resp0 = await sub_client.post(
        f"/api/public/apply/{token}",
        data={
            "first_name": "Sub",
            "last_name": "Merge",
            "email": dup_email,
            "phone": "+48 000 000 000",
            "linkedin": "https://linkedin.com/in/sub-merge",
        },
        files={"cv": ("m.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert resp0.status_code == 201, resp0.text
    async with AsyncSessionLocal() as db:
        sub = await db.scalar(
            select(ApplicationSubmission).where(
                ApplicationSubmission.matched_candidate_id == cand_id
            )
        )
        sub_id = sub.id

    resp = await sub_client.post(
        f"/api/application-submissions/{sub_id}/resolve",
        json={"action": "merge"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "merged"

    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        assert cand.phone == "+48 500 500 500"  # existing phone NOT overwritten
        assert cand.linkedin == "https://linkedin.com/in/sub-merge"  # empty → filled


@pytest.mark.asyncio
async def test_resolve_create_makes_new_candidate(sub_client: AsyncClient):
    uid_admin, email_a, pass_a = await _seed_user(UserRole.admin, "create-admin")
    admin_headers = await _login(sub_client, email_a, pass_a)
    sub_id, matched_id, dup_email, _ = await _park_submission(
        sub_client, owner_id=uid_admin
    )

    resp = await sub_client.post(
        f"/api/application-submissions/{sub_id}/resolve",
        json={"action": "create"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "created"
    new_id = body["candidate_id"]
    assert new_id is not None and new_id != matched_id

    async with AsyncSessionLocal() as db:
        new_cand = await db.scalar(select(Candidate).where(Candidate.id == new_id))
        assert new_cand is not None
        assert new_cand.name == "Sub"
        assert new_cand.created_by == uid_admin
        act = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == new_id,
                Activity.action == "application_submission_resolved",
            )
        )
        assert act is not None


@pytest.mark.asyncio
async def test_resolve_reject_changes_no_candidate(sub_client: AsyncClient):
    uid_admin, email_a, pass_a = await _seed_user(UserRole.admin, "reject-admin")
    admin_headers = await _login(sub_client, email_a, pass_a)
    sub_id, cand_id, _, _ = await _park_submission(sub_client, owner_id=uid_admin)

    resp = await sub_client.post(
        f"/api/application-submissions/{sub_id}/resolve",
        json={"action": "reject"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"

    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        assert cand.name == "Matched"  # untouched
        act = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "application_submission",
                Activity.entity_id == sub_id,
                Activity.action == "application_submission_resolved",
            )
        )
        assert act is not None


@pytest.mark.asyncio
async def test_resolve_twice_returns_409(sub_client: AsyncClient):
    uid_admin, email_a, pass_a = await _seed_user(UserRole.admin, "twice-admin")
    admin_headers = await _login(sub_client, email_a, pass_a)
    sub_id, _, _, _ = await _park_submission(sub_client, owner_id=uid_admin)

    first = await sub_client.post(
        f"/api/application-submissions/{sub_id}/resolve",
        json={"action": "reject"},
        headers=admin_headers,
    )
    assert first.status_code == 200
    second = await sub_client.post(
        f"/api/application-submissions/{sub_id}/resolve",
        json={"action": "reject"},
        headers=admin_headers,
    )
    assert second.status_code == 409, second.text


# ── Authorization ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_review_api_requires_auth(sub_client: AsyncClient):
    # Anonymous → 401.
    anon = await sub_client.get("/api/application-submissions")
    assert anon.status_code == 401, anon.text

    # Read-only viewer (`user`) → 403.
    _, email_v, pass_v = await _seed_user(UserRole.user, "viewer")
    viewer_headers = await _login(sub_client, email_v, pass_v)
    forbidden = await sub_client.get(
        "/api/application-submissions", headers=viewer_headers
    )
    assert forbidden.status_code == 403, forbidden.text
