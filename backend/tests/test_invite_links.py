"""Tests for /api/invite-links (recruiter-facing) and /api/public/apply/{token}.

Covers:
- Link creation with published vs draft job (400 on draft).
- RBAC — non-privileged recruiter sees only own links.
- Revoke flow (authorised caller + subsequent 404 on public GET).
- Public GET metadata shape (no sensitive fields leaked).
- Public POST creates new candidate with correct `created_by` + CandidateStage.
- Public POST for a duplicate email (P0-CAND-01): the existing candidate is NOT
  mutated (no name/CV/contact/owner change); a pending ApplicationSubmission is
  parked instead, and the response never reveals the duplicate.
- Multi-use: second application through the same link increments use_count.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

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
    from app.models.client import Client

    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"InvClient-{unique}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Senior FE {unique}",
            location="Warszawa",
            status=status,
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


def _invite_match(token: str):
    """Match the row behind a raw invite token the way production reads it.

    Since migration 0183 the raw secret is only the `token` PK on the legacy
    path. When `M365_TOKEN_ENCRYPTION_KEY` is configured — which production has
    — minting takes the v2 branch: the PK becomes a non-secret ``v2$…`` revoke
    key and the secret survives only as `token_sha256` (lookup) plus `token_ct`
    (Fernet, so the list can rebuild the URL).

    A bare ``token == <raw secret>`` therefore matches nothing on the path prod
    actually runs, and the assertions built on it degrade into assertions about
    ``None`` rather than failing. Mirrors `_load_valid_link` in
    app/api/public_share.py so the tests follow the product, not the reverse.
    """
    digest = hashlib.sha256(token.encode()).hexdigest()
    return (CandidateInviteLink.token_sha256 == digest) | (
        (CandidateInviteLink.token == token)
        & (CandidateInviteLink.token_sha256.is_(None))
    )


async def _load_link(token: str) -> CandidateInviteLink:
    """Load the invite link for a raw token, failing loudly if it is missing."""
    async with AsyncSessionLocal() as db:
        link = await db.scalar(select(CandidateInviteLink).where(_invite_match(token)))
    assert link is not None, (
        "no invite link matched the issued token — the assertions below would "
        "have silently tested nothing"
    )
    return link


async def _expire_link(token: str) -> None:
    """Backdate the link behind a raw token so it reads as expired.

    The rowcount guard is the point: an UPDATE that matches zero rows fails
    silently, leaving the link live and turning the 404 assertion downstream
    into an assertion about a link that was never expired.
    """
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            update(CandidateInviteLink)
            .where(_invite_match(token))
            .values(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
        )
        await db.commit()
    assert res.rowcount == 1, (
        f"expiry precondition matched {res.rowcount} rows — the test would have "
        "asserted against a link that was never expired"
    )


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


@pytest.fixture(autouse=True)
def _stub_external_services(monkeypatch):
    """Prevent invite-link tests from calling Voyage/Qdrant.

    `submit_public_apply` does an inline `embed_candidate` call. In CI Voyage
    isn't configured, so we replace it with an inert no-op. The background
    pipeline (`_invite_post_apply_task`) is NOT stubbed here — individual
    tests decide whether to capture/stub it, so we don't accidentally hide
    the behaviour a test is trying to verify.
    """

    async def _noop_embed(candidate_id, db):
        return True

    monkeypatch.setattr("app.services.embedding_service.embed_candidate", _noop_embed)


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
    # Response is generic — no created/updated discriminator (enumeration oracle).
    assert resp.json()["status"] == "received"

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

    link = await _load_link(token)
    assert link.use_count == 1
    assert link.last_used_at is not None


@pytest.mark.asyncio
async def test_public_apply_duplicate_email_parks_submission_without_mutation(
    inv_client: AsyncClient,
):
    """P0-CAND-01: a duplicate-email apply must NOT touch the canonical candidate.

    The whole point of the containment: a public, reusable invite link plus a
    known e-mail can no longer overwrite a candidate's name/CV/contact/owner.
    Instead a pending ApplicationSubmission is parked for recruiter review, and
    the response is generic (does not reveal the e-mail already existed).
    """
    from app.models.application_submission import (
        ApplicationSubmission,
        ApplicationSubmissionStatus,
    )

    # Seed an existing candidate owned by recruiter X, with its own CV + phone.
    uid_x, email_x, pass_x = await _seed_user(UserRole.recruiter, "owner-x")
    job_id = await _seed_job()
    applicant_email = f"dup-{uuid.uuid4().hex[:6]}@example.com"
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Old",
            lastname="Name",
            email=applicant_email,
            phone="+48 111 000 000",
            created_by=uid_x,
            cv_filename="original_cv.pdf",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        original_id = cand.id

    # Recruiter Y creates a link and the (duplicate) candidate "re-applies".
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
            "first_name": "Attacker",
            "last_name": "Overwrite",
            "email": applicant_email,
            "phone": "+48 999 888 777",
        },
        files={"cv": ("evil.pdf", io.BytesIO(b"%PDF-1.4 evil"), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    # Generic — no created/updated leak.
    assert resp.json()["status"] == "received"

    async with AsyncSessionLocal() as db:
        # Candidate is byte-for-byte unchanged: name, owner, CV, contact.
        cand = await db.scalar(select(Candidate).where(Candidate.id == original_id))
        assert cand is not None
        assert cand.name == "Old"
        assert cand.lastname == "Name"
        assert cand.created_by == uid_x  # ownership NOT reassigned
        assert cand.cv_filename == "original_cv.pdf"  # CV NOT replaced
        assert cand.phone == "+48 111 000 000"  # contact NOT overwritten

        # A pending submission was parked, pointing at the matched candidate.
        submission = await db.scalar(
            select(ApplicationSubmission).where(
                ApplicationSubmission.matched_candidate_id == original_id
            )
        )
        assert submission is not None
        assert submission.status == ApplicationSubmissionStatus.pending_review.value
        assert submission.submitted_first_name == "Attacker"
        assert submission.submitted_email == applicant_email
        assert submission.job_id == job_id
        # The raw token is never stored — only its digest.
        assert submission.invite_link_token_sha256
        assert submission.invite_link_token_sha256 != token

        # No candidate stage was created for the matched candidate either.
        stage = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == original_id,
                CandidateStage.job_id == job_id,
            )
        )
        assert stage is None


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

    link = await _load_link(token)
    assert link.use_count == 2


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

    rev = await inv_client.post(f"/api/invite-links/{token}/revoke", headers=headers)
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

    # Positive control: the link must serve before backdating. Without it a 404
    # could equally mean "expiry works" or "the link never resolved at all",
    # and only expiry is under test here.
    live = await inv_client.get(f"/api/public/apply/{token}")
    assert live.status_code == 200, live.text

    await _expire_link(token)

    meta = await inv_client.get(f"/api/public/apply/{token}")
    assert meta.status_code == 404


# ─────────────────────────────────────────────────────────────────────────
# Invite-source badge (#2a), ownership-transfer audit (#4), post-apply
# pipeline (#5) — tests added alongside feature work.
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_public_apply_schedules_enrichment(inv_client: AsyncClient, monkeypatch):
    """Successful apply schedules the post-apply pipeline for the new candidate."""
    scheduled: list[int] = []

    async def _capture(candidate_id: int) -> None:
        scheduled.append(candidate_id)

    monkeypatch.setattr("app.api.public_share._invite_post_apply_task", _capture)

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

    resp = await inv_client.post(
        f"/api/public/apply/{token}",
        data={
            "first_name": "Ewa",
            "last_name": "Nowak",
            "email": f"ewa-{uuid.uuid4().hex[:6]}@example.com",
        },
        files={"cv": ("cv.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    # BackgroundTasks execute after the response is sent but inside the
    # ASGITransport lifecycle, so the captured list is ready by the time
    # we inspect it here.
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_get_candidate_returns_invite_source(inv_client: AsyncClient):
    """GET /candidates/{id} surfaces label + recruiter name after invite apply."""
    _, recruiter_email, recruiter_password = await _seed_user(UserRole.recruiter, "src")
    headers = await _login(inv_client, recruiter_email, recruiter_password)
    job_id = await _seed_job()

    # Separate admin account to read the private candidate endpoint.
    _, admin_email, admin_pass = await _seed_user(UserRole.admin, "src-admin")
    admin_headers = await _login(inv_client, admin_email, admin_pass)

    token = (
        await inv_client.post(
            "/api/invite-links",
            json={
                "job_id": job_id,
                "label": "LI kwiecień",
                "expires_in_days": 30,
            },
            headers=headers,
        )
    ).json()["token"]

    applicant_email = f"src-{uuid.uuid4().hex[:6]}@example.com"
    apply_resp = await inv_client.post(
        f"/api/public/apply/{token}",
        data={
            "first_name": "Anna",
            "last_name": "Linkowa",
            "email": applicant_email,
        },
        files={"cv": ("cv.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert apply_resp.status_code == 201

    async with AsyncSessionLocal() as db:
        cand = await db.scalar(
            select(Candidate).where(Candidate.email == applicant_email)
        )
        assert cand is not None
        cand_id = cand.id

    detail = await inv_client.get(f"/api/candidates/{cand_id}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body.get("invite_source") is not None
    assert body["invite_source"]["label"] == "LI kwiecień"
    assert body["invite_source"]["created_by_name"]  # recruiter name filled
    assert body["invite_source"]["previous_created_by_name"] is None


@pytest.mark.asyncio
async def test_invite_source_label_resolves_on_encrypted_v2_path(
    inv_client: AsyncClient, monkeypatch
):
    """The invite-source label must survive the v2 (encrypted) mint path.

    Pinned to v2 regardless of `M365_TOKEN_ENCRYPTION_KEY` so the branch stays
    covered even when the suite runs without a key — production runs *with* one,
    and on that branch the `token` PK is a non-secret ``v2$…`` revoke key. The
    label lookup used to prefix-match the raw secret against that PK and matched
    nothing, so `label` came back None and the campaign suffix on the candidate
    profile badge (`· <label>`) silently disappeared. Every other test here
    reads the same on both branches, so nothing else pins this one.
    """
    from cryptography.fernet import Fernet

    from app.core.encryption import TokenCipher

    cipher = TokenCipher(Fernet.generate_key().decode())
    monkeypatch.setattr("app.core.encryption.get_token_cipher", lambda: cipher)

    _, recruiter_email, recruiter_password = await _seed_user(
        UserRole.recruiter, "v2src"
    )
    headers = await _login(inv_client, recruiter_email, recruiter_password)
    job_id = await _seed_job()
    _, admin_email, admin_pass = await _seed_user(UserRole.admin, "v2src-admin")
    admin_headers = await _login(inv_client, admin_email, admin_pass)

    token = (
        await inv_client.post(
            "/api/invite-links",
            json={
                "job_id": job_id,
                "label": "v2 kampania",
                "expires_in_days": 30,
            },
            headers=headers,
        )
    ).json()["token"]

    # Guard the guard: prove the mint really took the v2 branch, so a green run
    # cannot mean "silently fell back to legacy and asserted nothing new".
    link = await _load_link(token)
    assert link.token.startswith("v2$"), f"expected a v2 mint, got PK {link.token!r}"
    assert link.token_sha256 is not None
    assert link.token != token  # the raw secret is not the PK

    applicant_email = f"v2src-{uuid.uuid4().hex[:6]}@example.com"
    apply_resp = await inv_client.post(
        f"/api/public/apply/{token}",
        data={
            "first_name": "Ewa",
            "last_name": "Szyfrowana",
            "email": applicant_email,
        },
        files={"cv": ("cv.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert apply_resp.status_code == 201, apply_resp.text

    async with AsyncSessionLocal() as db:
        cand = await db.scalar(
            select(Candidate).where(Candidate.email == applicant_email)
        )
        assert cand is not None
        cand_id = cand.id

    detail = await inv_client.get(f"/api/candidates/{cand_id}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["invite_source"]["label"] == "v2 kampania"


@pytest.mark.asyncio
async def test_reapply_audits_submission_not_candidate(
    inv_client: AsyncClient,
):
    """P0-CAND-01: a duplicate-email reapply audits the SUBMISSION, not the candidate.

    The old contract reassigned ownership and wrote an ``applied_via_invite``
    Activity onto the existing candidate. The new contract leaves the candidate
    (and its audit trail) untouched and records a ``submission_received``
    Activity against the parked submission instead.
    """
    from app.models.activity import Activity
    from app.models.application_submission import ApplicationSubmission

    uid_x, _, _ = await _seed_user(UserRole.recruiter, "prev-x")
    uid_y, email_y, pass_y = await _seed_user(UserRole.recruiter, "prev-y")
    job_id = await _seed_job()
    applicant_email = f"reapply-{uuid.uuid4().hex[:6]}@example.com"

    # Seed existing candidate owned by X.
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
        cand_id = cand.id

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
            "first_name": "Old",
            "last_name": "Name",
            "email": applicant_email,
        },
        files={"cv": ("cv.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text

    async with AsyncSessionLocal() as db:
        # No applied_via_invite Activity written onto the existing candidate.
        cand_act = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == cand_id,
                Activity.action == "applied_via_invite",
            )
        )
        assert cand_act is None
        # Ownership stayed with X.
        cand = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        assert cand is not None and cand.created_by == uid_x

        # The submission carries the audit instead.
        submission = await db.scalar(
            select(ApplicationSubmission).where(
                ApplicationSubmission.matched_candidate_id == cand_id
            )
        )
        assert submission is not None
        sub_act = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "application_submission",
                Activity.entity_id == submission.id,
                Activity.action == "submission_received",
            )
        )
        assert sub_act is not None
        assert sub_act.user_id == uid_y


@pytest.mark.asyncio
async def test_post_apply_task_auto_assigns_competence_category(
    monkeypatch,
):
    """When the classifier scores ≥ 0.30, the background task fills competence_category.

    Seeds a real CompetenceCategory row so the FK (`competence_category_id`)
    is satisfied — production classifier always returns real CC ids, and we
    mimic that in the fake.
    """
    from dataclasses import dataclass

    from app.api.public_share import _invite_post_apply_task
    from app.models.competence_category import CompetenceCategory

    # Stub the authenticated-flow enrichment helper so it doesn't touch
    # Voyage/LLM in CI. The task just needs the candidate to exist.
    async def _noop_cv_enrich(candidate_id: int) -> None:
        return None

    monkeypatch.setattr("app.api.candidates._enrich_candidate_cv_task", _noop_cv_enrich)

    # Seed a CompetenceCategory the fake classifier can point at.
    cc_slug = f"backend-dev-{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        cc = CompetenceCategory(
            slug=cc_slug,
            name_pl="Backend",
            name_en="Backend",
            description="Test CC",
            keywords=[],
            is_active=True,
            display_order=999,
        )
        db.add(cc)
        await db.commit()
        await db.refresh(cc)
        cc_id = cc.id

    @dataclass
    class _FakeScore:
        cc_id: int
        slug: str
        score: float

    async def _fake_classify(candidate, db):
        return [_FakeScore(cc_id=cc_id, slug=cc_slug, score=0.45)]

    monkeypatch.setattr(
        "app.services.cc_classifier.classify_candidate_to_cc", _fake_classify
    )

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Auto",
            lastname="CC",
            email=f"autocc-{uuid.uuid4().hex[:6]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        cand_id = cand.id

    await _invite_post_apply_task(cand_id)

    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        assert cand is not None
        assert cand.competence_category == cc_slug
        assert cand.competence_category_id == cc_id
