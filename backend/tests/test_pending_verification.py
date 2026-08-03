"""Tests for the pending verification flow (migracja 0056).

Cover scenariuszy:
- ruch na 'verified' z rate'm w widełkach → status=active, brak notyfikacji
- ruch na 'verified' z rate'm > Job.salary_max → status=pending + notyfikacje
- ruch na 'verified' bez expected_rate_value → 422
- accept/reject-verification przez admina → decyzja + audit
- Delivery Lead / HoR → 403 na liście i decyzjach
- accept-verification przez recruitera → 403
- reject-verification → tworzy nowy CandidateStage z poprzednim stage'em
- list pending-verifications tylko dla admina
- notification helper wysyła tylko do adminów
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.user import User, UserRole


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def pv_client():
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_user(role: UserRole, label: str = "pv") -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"pv-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Pv"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"PV {role.value} {label}",
            role=role,
            is_active=True,
            profile_completed=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _seed_candidate() -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Pv",
            lastname=f"Test{unique}",
            email=f"pv-cand-{unique}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job(
    salary_max: int | None = 20000,
    delivery_lead_id: int | None = None,
) -> int:
    from app.models.client import Client

    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"PVClient-{unique}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"PV Job {unique}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            salary_min=10000,
            salary_max=salary_max,
            delivery_lead_id=delivery_lead_id,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _cleanup(*, candidate_ids: list[int], job_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        if candidate_ids or job_ids:
            await db.execute(
                delete(CandidateStage).where(
                    CandidateStage.candidate_id.in_(candidate_ids or [-1])
                )
            )
        if candidate_ids:
            await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        if job_ids:
            await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.commit()


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_move_to_verified_within_budget_active(pv_client: AsyncClient):
    _, email, pw = await _seed_user(UserRole.recruiter, "within")
    headers = await _login(pv_client, email, pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000)
    try:
        resp = await pv_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "15000",
                "expected_rate_unit": "monthly",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verification_status"] == "active"
        assert body["budget_max_at_move"] == 20000
        assert body["expected_rate_value"] in ("15000.00", "15000")
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_move_to_verified_above_budget_pending(pv_client: AsyncClient):
    _, email, pw = await _seed_user(UserRole.recruiter, "above")
    headers = await _login(pv_client, email, pw)
    # Admin potrzebny, żeby helper notyfikacyjny miał kogo powiadomić.
    await _seed_user(UserRole.admin, "approver-admin")
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000)
    try:
        resp = await pv_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "25000",
                "expected_rate_unit": "monthly",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verification_status"] == "pending"
        assert body["budget_max_at_move"] == 20000

        # Notyfikacja została zapisana dla co najmniej jednego approvera.
        async with AsyncSessionLocal() as db:
            cnt = await db.scalar(
                select(Notification).where(
                    Notification.notification_type
                    == NotificationType.pending_verification,
                    Notification.related_entity_id == body["id"],
                )
            )
            assert cnt is not None
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_move_to_verified_missing_rate_returns_422(pv_client: AsyncClient):
    _, email, pw = await _seed_user(UserRole.recruiter, "missing")
    headers = await _login(pv_client, email, pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job()
    try:
        resp = await pv_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
            },
        )
        assert resp.status_code == 422, resp.text
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_accept_verification_by_admin(pv_client: AsyncClient):
    _, recr_email, recr_pw = await _seed_user(UserRole.recruiter, "ack-r")
    _, admin_email, admin_pw = await _seed_user(UserRole.admin, "ack-admin")
    recr_headers = await _login(pv_client, recr_email, recr_pw)
    admin_headers = await _login(pv_client, admin_email, admin_pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000)
    try:
        move = await pv_client.post(
            "/api/pipeline/move",
            headers=recr_headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "30000",
                "expected_rate_unit": "monthly",
            },
        )
        assert move.status_code == 200, move.text
        stage_id = move.json()["id"]
        assert move.json()["verification_status"] == "pending"

        accept = await pv_client.post(
            f"/api/pipeline/{stage_id}/accept-verification",
            headers=admin_headers,
        )
        assert accept.status_code == 200, accept.text
        body = accept.json()
        assert body["verification_status"] == "active"
        assert body["approved_by"] is not None
        assert body["approved_at"] is not None
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_accept_verification_forbidden_for_recruiter(pv_client: AsyncClient):
    _, recr_email, recr_pw = await _seed_user(UserRole.recruiter, "forb-r")
    recr_headers = await _login(pv_client, recr_email, recr_pw)
    # Drugi recruiter który próbuje akceptować
    _, recr2_email, recr2_pw = await _seed_user(UserRole.recruiter, "forb-r2")
    recr2_headers = await _login(pv_client, recr2_email, recr2_pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000)
    try:
        move = await pv_client.post(
            "/api/pipeline/move",
            headers=recr_headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "30000",
                "expected_rate_unit": "monthly",
            },
        )
        assert move.status_code == 200, move.text
        stage_id = move.json()["id"]

        forbid = await pv_client.post(
            f"/api/pipeline/{stage_id}/accept-verification",
            headers=recr2_headers,
        )
        assert forbid.status_code == 403, forbid.text
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_accept_verification_forbidden_for_delivery_lead(
    pv_client: AsyncClient,
):
    _, recr_email, recr_pw = await _seed_user(UserRole.recruiter, "forb-dl-r")
    _, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead, "forb-dl")
    recr_headers = await _login(pv_client, recr_email, recr_pw)
    dl_headers = await _login(pv_client, dl_email, dl_pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000)
    try:
        move = await pv_client.post(
            "/api/pipeline/move",
            headers=recr_headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "30000",
                "expected_rate_unit": "monthly",
            },
        )
        stage_id = move.json()["id"]
        denied = await pv_client.post(
            f"/api/pipeline/{stage_id}/accept-verification",
            headers=dl_headers,
        )
        assert denied.status_code == 403, denied.text
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_reject_verification_creates_revert_stage(pv_client: AsyncClient):
    _, recr_email, recr_pw = await _seed_user(UserRole.recruiter, "rej-r")
    _, admin_email, admin_pw = await _seed_user(UserRole.admin, "rej-admin")
    recr_headers = await _login(pv_client, recr_email, recr_pw)
    admin_headers = await _login(pv_client, admin_email, admin_pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000)
    try:
        # Najpierw 'screening' (poprzedni stage)
        prev = await pv_client.post(
            "/api/pipeline/move",
            headers=recr_headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "screening",
            },
        )
        assert prev.status_code == 200, prev.text

        # Teraz 'verified' z rate'm > budżet
        ver = await pv_client.post(
            "/api/pipeline/move",
            headers=recr_headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "28000",
                "expected_rate_unit": "monthly",
            },
        )
        assert ver.status_code == 200, ver.text
        ver_id = ver.json()["id"]

        # Reject przez admina
        rej = await pv_client.post(
            f"/api/pipeline/{ver_id}/reject-verification",
            headers=admin_headers,
            json={"note": "Rate za wysoki, max 22000"},
        )
        assert rej.status_code == 200, rej.text
        assert rej.json()["verification_status"] == "rejected"
        assert rej.json()["rejected_by"] is not None

        # Najnowszy CandidateStage powinien mieć stage = 'screening'
        async with AsyncSessionLocal() as db:
            latest = await db.scalar(
                select(CandidateStage)
                .where(
                    CandidateStage.candidate_id == cand_id,
                    CandidateStage.job_id == job_id,
                )
                .order_by(CandidateStage.moved_at.desc())
                .limit(1)
            )
            assert latest is not None
            assert latest.stage == PipelineStage.screening
            assert latest.verification_status == VerificationStatus.active
            assert "Rejected verification" in (latest.notes or "")
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_pending_verifications_list_role_gated(pv_client: AsyncClient):
    _, recr_email, recr_pw = await _seed_user(UserRole.recruiter, "list-r")
    _, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead, "list-dl")
    _, hor_email, hor_pw = await _seed_user(UserRole.head_of_recruitment, "list-hor")
    _, admin_email, admin_pw = await _seed_user(UserRole.admin, "list-admin")
    recr_headers = await _login(pv_client, recr_email, recr_pw)
    dl_headers = await _login(pv_client, dl_email, dl_pw)
    hor_headers = await _login(pv_client, hor_email, hor_pw)
    admin_headers = await _login(pv_client, admin_email, admin_pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000)
    try:
        await pv_client.post(
            "/api/pipeline/move",
            headers=recr_headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "30000",
                "expected_rate_unit": "monthly",
            },
        )

        for denied_headers in (recr_headers, dl_headers, hor_headers):
            forbidden = await pv_client.get(
                "/api/pipeline/pending-verifications", headers=denied_headers
            )
            assert forbidden.status_code == 403

        ok = await pv_client.get(
            "/api/pipeline/pending-verifications",
            headers=admin_headers,
            params={"job_id": job_id},
        )
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert isinstance(body, list)
        assert any(item["candidate_id"] == cand_id for item in body)
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_pending_verifications_mine_does_not_widen_delivery_lead_access(
    pv_client: AsyncClient,
):
    """`?mine=true` nie omija Admin-only nawet dla DL przypisanego do Joba."""
    _, recr_email, recr_pw = await _seed_user(UserRole.recruiter, "mine-r")
    dl_uid_a, dl_a_email, dl_a_pw = await _seed_user(
        UserRole.delivery_lead, "mine-dl-a"
    )
    recr_headers = await _login(pv_client, recr_email, recr_pw)
    dl_a_headers = await _login(pv_client, dl_a_email, dl_a_pw)
    cand_a = await _seed_candidate()
    job_a = await _seed_job(salary_max=20000, delivery_lead_id=dl_uid_a)
    try:
        a = await pv_client.post(
            "/api/pipeline/move",
            headers=recr_headers,
            json={
                "candidate_id": cand_a,
                "job_id": job_a,
                "stage": "verified",
                "expected_rate_value": "30000",
                "expected_rate_unit": "monthly",
            },
        )
        assert a.status_code == 200, a.text
        mine_resp = await pv_client.get(
            "/api/pipeline/pending-verifications",
            headers=dl_a_headers,
            params={"mine": "true"},
        )
        assert mine_resp.status_code == 403, mine_resp.text
    finally:
        await _cleanup(candidate_ids=[cand_a], job_ids=[job_a])


@pytest.mark.asyncio
async def test_pending_verifications_mine_does_not_widen_hor_access(
    pv_client: AsyncClient,
):
    """`?mine=true` nie omija Admin-only dla Head of Recruitment."""
    _, recr_email, recr_pw = await _seed_user(UserRole.recruiter, "mine-empty-r")
    dl_uid, _, _ = await _seed_user(UserRole.delivery_lead, "mine-empty-dl")
    _, hor_email, hor_pw = await _seed_user(
        UserRole.head_of_recruitment, "mine-empty-hor"
    )
    recr_headers = await _login(pv_client, recr_email, recr_pw)
    hor_headers = await _login(pv_client, hor_email, hor_pw)
    cand_id = await _seed_candidate()
    # Job jest przypisany do DL, nie do HoR
    job_id = await _seed_job(salary_max=20000, delivery_lead_id=dl_uid)
    try:
        await pv_client.post(
            "/api/pipeline/move",
            headers=recr_headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "30000",
                "expected_rate_unit": "monthly",
            },
        )

        all_resp = await pv_client.get(
            "/api/pipeline/pending-verifications", headers=hor_headers
        )
        assert all_resp.status_code == 403

        mine_resp = await pv_client.get(
            "/api/pipeline/pending-verifications",
            headers=hor_headers,
            params={"mine": "true"},
        )
        assert mine_resp.status_code == 403, mine_resp.text
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_pending_verification_notification_sent_only_to_admin(
    pv_client: AsyncClient,
):
    # Tylko admin; DL, HoR i recruiter nie mogą dostać PII ani kwot.
    _, recr_email, recr_pw = await _seed_user(UserRole.recruiter, "notif-r")
    admin_uid, _, _ = await _seed_user(UserRole.admin, "notif-admin")
    dl_uid, _, _ = await _seed_user(UserRole.delivery_lead, "notif-dl")
    hor_uid, _, _ = await _seed_user(UserRole.head_of_recruitment, "notif-hor")
    other_uid, _, _ = await _seed_user(UserRole.recruiter, "notif-other")
    recr_headers = await _login(pv_client, recr_email, recr_pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000)
    try:
        resp = await pv_client.post(
            "/api/pipeline/move",
            headers=recr_headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "40000",
                "expected_rate_unit": "monthly",
            },
        )
        assert resp.status_code == 200, resp.text
        stage_id = resp.json()["id"]

        async with AsyncSessionLocal() as db:
            notifs = (
                (
                    await db.execute(
                        select(Notification).where(
                            Notification.notification_type
                            == NotificationType.pending_verification,
                            Notification.related_entity_id == stage_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            recipients = {n.user_id for n in notifs}
            assert admin_uid in recipients
            assert dl_uid not in recipients
            assert hor_uid not in recipients
            assert other_uid not in recipients
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])
