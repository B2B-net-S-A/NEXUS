"""Pipeline v4 (decyzje Artura 23.09.2026): blokada 12 h, stawka przy „CV
wysłane" i „kto zakończył proces".

* osoba dodana ręcznie jest przez 12 h na wyłączność dodającego — inny
  rekruter dostaje 423, DL/HoR/admin przechodzą, „Biorę" po upływie działa
  dla każdego, przejęcie cudzej aktywnej blokady — tylko DL/HoR/admin;
* poza Nordeą „CV wysłane" wysyła Delivery Lead i wpisuje stawkę do klienta;
* odrzucenie zapisuje, kto zakończył proces.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.job_collaborator import JobCollaborator
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import pipeline_move_rules as rules

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_user(role: UserRole) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"v4-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!V4"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"V4 {role.value} {unique}",
            role=role,
            is_active=True,
            profile_completed=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_job(
    owner_id: int, collaborator_ids: tuple[int, ...] = ()
) -> tuple[int, int]:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"V4Client-{unique}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"V4 Job {unique}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
            recruiter_id=owner_id,
        )
        db.add(job)
        await db.flush()
        for uid in collaborator_ids:
            db.add(JobCollaborator(job_id=job.id, user_id=uid, added_by=owner_id))
        await db.commit()
        return job.id, cli.id


async def _seed_candidate() -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="V4", lastname=f"Osoba{unique}", email=f"v4-{unique}@example.com"
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def _cleanup(candidate_ids: list[int], job_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateStage).where(CandidateStage.candidate_id.in_(candidate_ids))
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.commit()


async def _process(candidate_id: int, job_id: int) -> RecruitmentProcess:
    async with AsyncSessionLocal() as db:
        proc = await db.scalar(
            select(RecruitmentProcess)
            .where(
                RecruitmentProcess.candidate_id == candidate_id,
                RecruitmentProcess.job_id == job_id,
            )
            .order_by(RecruitmentProcess.attempt_no.desc())
            .limit(1)
        )
    assert proc is not None
    return proc


async def _add(client, headers, job_id: int, candidate_id: int, source: str):
    resp = await client.post(
        f"/api/jobs/{job_id}/proposals/bulk",
        headers=headers,
        json={
            "candidate_ids": [candidate_id],
            "initial_stage_legacy": "new",
            "source": source,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] == [candidate_id], resp.text


async def test_manual_add_claims_for_12h_and_blocks_other_recruiter(api_client):
    owner_id, owner_email, owner_pw = await _seed_user(UserRole.recruiter)
    other_id, other_email, other_pw = await _seed_user(UserRole.recruiter)
    job_id, _ = await _seed_job(owner_id, collaborator_ids=(other_id,))
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner_email, owner_pw)
    other_h = await _login(api_client, other_email, other_pw)
    try:
        await _add(api_client, owner_h, job_id, cand_id, "manual_search")
        proc = await _process(cand_id, job_id)
        assert proc.entry_source == "added_manual"
        assert proc.claimed_by_user_id == owner_id
        assert proc.claimed_until is not None
        remaining = proc.claimed_until - datetime.now(timezone.utc)
        assert timedelta(hours=11, minutes=58) < remaining <= timedelta(hours=12)

        blocked = await api_client.post(
            "/api/pipeline/move",
            headers=other_h,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "verified"},
        )
        assert blocked.status_code == 423, blocked.text
        assert blocked.json()["detail"]["code"] == "CANDIDATE_CLAIMED"

        take = await api_client.post(
            "/api/pipeline/claim",
            headers=other_h,
            json={"candidate_id": cand_id, "job_id": job_id},
        )
        assert take.status_code == 423, take.text

        # Karta mówi, kto trzyma osobę i że patrzący nie może jej wziąć.
        board = await api_client.get(f"/api/pipeline/kanban/{job_id}", headers=other_h)
        assert board.status_code == 200, board.text
        cards = [
            item
            for col in board.json()["columns"]
            for item in col["items"]
            if item["candidate_id"] == cand_id
        ]
        assert len(cards) == 1
        assert cards[0]["claim_user_id"] == owner_id
        assert cards[0]["can_take"] is False
        assert cards[0]["entry_source"] == "added_manual"

        # Właściciel blokady rusza osobę dalej — blokada znika.
        moved = await api_client.post(
            "/api/pipeline/move",
            headers=owner_h,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "verified"},
        )
        assert moved.status_code == 200, moved.text
        proc = await _process(cand_id, job_id)
        assert proc.claimed_by_user_id is None and proc.claimed_until is None
    finally:
        await _cleanup([cand_id], job_id)


async def test_expired_claim_can_be_taken_by_anyone_in_team(api_client):
    owner_id, owner_email, owner_pw = await _seed_user(UserRole.recruiter)
    other_id, other_email, other_pw = await _seed_user(UserRole.recruiter)
    job_id, _ = await _seed_job(owner_id, collaborator_ids=(other_id,))
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner_email, owner_pw)
    other_h = await _login(api_client, other_email, other_pw)
    try:
        await _add(api_client, owner_h, job_id, cand_id, "manual_search")
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(RecruitmentProcess)
                .where(
                    RecruitmentProcess.candidate_id == cand_id,
                    RecruitmentProcess.job_id == job_id,
                )
                .values(claimed_until=datetime.now(timezone.utc) - timedelta(minutes=1))
            )
            await db.commit()

        take = await api_client.post(
            "/api/pipeline/claim",
            headers=other_h,
            json={"candidate_id": cand_id, "job_id": job_id},
        )
        assert take.status_code == 200, take.text
        assert take.json()["claim_user_id"] == other_id
        # Wygasła blokada nie jest „przejęciem" — bez dzwonka dla poprzedniego.
        assert take.json()["taken_over_from"] is None
        proc = await _process(cand_id, job_id)
        assert proc.claimed_by_user_id == other_id
    finally:
        await _cleanup([cand_id], job_id)


async def test_delivery_lead_takes_over_active_claim_and_previous_holder_is_notified(
    api_client,
):
    owner_id, owner_email, owner_pw = await _seed_user(UserRole.recruiter)
    dl_id, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead)
    job_id, _ = await _seed_job(owner_id, collaborator_ids=(dl_id,))
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner_email, owner_pw)
    dl_h = await _login(api_client, dl_email, dl_pw)
    try:
        await _add(api_client, owner_h, job_id, cand_id, "manual_search")
        take = await api_client.post(
            "/api/pipeline/claim",
            headers=dl_h,
            json={"candidate_id": cand_id, "job_id": job_id},
        )
        assert take.status_code == 200, take.text
        assert take.json()["taken_over_from"] == owner_id
        async with AsyncSessionLocal() as db:
            notif = await db.scalar(
                select(Notification).where(
                    Notification.user_id == owner_id,
                    Notification.notification_type
                    == NotificationType.candidate_claim_taken,
                )
            )
        assert notif is not None
    finally:
        await _cleanup([cand_id], job_id)


async def test_proposal_add_is_a_proposal_source_and_auto_match_is_not_claimed(
    api_client,
):
    owner_id, owner_email, owner_pw = await _seed_user(UserRole.recruiter)
    job_id, _ = await _seed_job(owner_id)
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner_email, owner_pw)
    try:
        await _add(api_client, owner_h, job_id, cand_id, "proposal_inbox")
        proc = await _process(cand_id, job_id)
        assert proc.entry_source == "proposal"
        # „Biorę" na propozycji to też decyzja człowieka — blokada 12 h.
        assert proc.claimed_by_user_id == owner_id
    finally:
        await _cleanup([cand_id], job_id)


async def test_cv_sent_requires_delivery_lead_and_client_rate(api_client):
    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    dl_id, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead)
    job_id, _ = await _seed_job(rec_id, collaborator_ids=(dl_id,))
    cand_id = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    dl_h = await _login(api_client, dl_email, dl_pw)
    try:
        await _add(api_client, rec_h, job_id, cand_id, "manual_search")
        ok = await api_client.post(
            "/api/pipeline/move",
            headers=rec_h,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "verified"},
        )
        assert ok.status_code == 200, ok.text

        by_recruiter = await api_client.post(
            "/api/pipeline/move",
            headers=rec_h,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "cv_sent",
                "client_rate_value": "170",
            },
        )
        assert by_recruiter.status_code == 403, by_recruiter.text

        without_rate = await api_client.post(
            "/api/pipeline/move",
            headers=dl_h,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "cv_sent"},
        )
        assert without_rate.status_code == 422, without_rate.text

        sent = await api_client.post(
            "/api/pipeline/move",
            headers=dl_h,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "cv_sent",
                "client_rate_value": "170",
                "client_rate_unit": "hourly",
            },
        )
        assert sent.status_code == 200, sent.text
        body = sent.json()
        assert Decimal(str(body["client_rate_value"])) == Decimal("170")
        assert body["client_rate_unit"] == "hourly"
        assert body["client_rate_currency"] == "PLN"
    finally:
        await _cleanup([cand_id], job_id)


async def test_cv_sent_at_nordea_keeps_the_cpro_path(api_client, monkeypatch):
    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    job_id, client_id = await _seed_job(rec_id)
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(client_id))
    cand_id = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    try:
        await _add(api_client, rec_h, job_id, cand_id, "manual_search")
        sent = await api_client.post(
            "/api/pipeline/move",
            headers=rec_h,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "cv_sent"},
        )
        assert sent.status_code == 200, sent.text
    finally:
        await _cleanup([cand_id], job_id)


async def test_rejection_records_who_ended_the_process(api_client):
    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    job_id, _ = await _seed_job(rec_id)
    cand_a = await _seed_candidate()
    cand_b = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    try:
        for cid in (cand_a, cand_b):
            await _add(api_client, rec_h, job_id, cid, "manual_search")
        by_client = await api_client.post(
            "/api/pipeline/move",
            headers=rec_h,
            json={
                "candidate_id": cand_a,
                "job_id": job_id,
                "stage": "rejected",
                "rejection_reason": "Klient wybrał innego kandydata",
                "ended_by": "client",
            },
        )
        assert by_client.status_code == 200, by_client.text
        assert by_client.json()["ended_by"] == "client"

        as_dl = await api_client.post(
            "/api/pipeline/move",
            headers=rec_h,
            json={
                "candidate_id": cand_b,
                "job_id": job_id,
                "stage": "rejected",
                "rejection_reason": "Stawka",
                "ended_by": "delivery_lead",
            },
        )
        assert as_dl.status_code == 403, as_dl.text

        default = await api_client.post(
            "/api/pipeline/move",
            headers=rec_h,
            json={
                "candidate_id": cand_b,
                "job_id": job_id,
                "stage": "rejected",
                "rejection_reason": "Stawka",
            },
        )
        assert default.status_code == 200, default.text
        assert default.json()["ended_by"] == "recruiter"
    finally:
        await _cleanup([cand_a, cand_b], job_id)


def _user(*roles: UserRole) -> SimpleNamespace:
    return SimpleNamespace(has_any_role=lambda *wanted: any(r in roles for r in wanted))


def test_withdrawal_is_always_the_candidate() -> None:
    recruiter = _user(UserRole.recruiter)
    assert rules.resolve_ended_by(None, withdrawn=True, user=recruiter) == "candidate"
    with pytest.raises(HTTPException) as err:
        rules.resolve_ended_by("client", withdrawn=True, user=recruiter)
    assert err.value.status_code == 422


def test_cv_sent_rule_ignores_other_stages_and_nordea(monkeypatch) -> None:
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "77")
    assert rules.requires_dl_client_rate(PipelineStage.cv_sent, 15) is True
    assert rules.requires_dl_client_rate(PipelineStage.cv_sent, 77) is False
    assert rules.requires_dl_client_rate(PipelineStage.verified, 15) is False
