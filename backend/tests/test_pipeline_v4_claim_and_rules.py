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


async def test_own_active_claim_cannot_be_extended(api_client):
    """Runda 8 (R8-N8-7): ponowne „Biorę" własnej aktywnej blokady nie
    przesuwa jej o kolejne 12 h — po 12 h osobę może przejąć każdy."""
    owner_id, owner_email, owner_pw = await _seed_user(UserRole.recruiter)
    job_id, _ = await _seed_job(owner_id)
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner_email, owner_pw)
    try:
        await _add(api_client, owner_h, job_id, cand_id, "manual_search")
        before = (await _process(cand_id, job_id)).claimed_until
        again = await api_client.post(
            "/api/pipeline/claim",
            headers=owner_h,
            json={"candidate_id": cand_id, "job_id": job_id},
        )
        assert again.status_code == 409, again.text
        assert (await _process(cand_id, job_id)).claimed_until == before
    finally:
        await _cleanup([cand_id], job_id)


async def test_claim_of_a_deactivated_account_binds_nobody(api_client):
    """Runda 8 (R8-N8-7): blokada konta nieaktywnego nie daje 423."""
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
                update(User).where(User.id == owner_id).values(is_active=False)
            )
            await db.commit()
        board = await api_client.get(f"/api/pipeline/kanban/{job_id}", headers=other_h)
        card = next(
            item
            for col in board.json()["columns"]
            for item in col["items"]
            if item["candidate_id"] == cand_id
        )
        assert card.get("claim_user_id") is None and card["can_take"] is True
        moved = await api_client.post(
            "/api/pipeline/move",
            headers=other_h,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "verified"},
        )
        assert moved.status_code == 200, moved.text
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
    """U Nordei „CV wysłane” = Cpro: bez stawki DL, ale wrzuca osoba od Cpro.
    Runda 8 (R8-N8-3): także przy wyłączonej bramce QC (autouse w conftest)."""
    from app.services import cpro_sender
    from tests.test_board_tasks import restore_cpro_sender

    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    other_id, other_email, other_pw = await _seed_user(UserRole.recruiter)
    job_id, client_id = await _seed_job(rec_id)
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(client_id))
    cand_id = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    other_h = await _login(api_client, other_email, other_pw)
    try:
        async with restore_cpro_sender():
            async with AsyncSessionLocal() as db:
                actor = await db.get(User, rec_id)
                await cpro_sender.set_sender(db, user_id=rec_id, until=None, actor=actor)
                await db.commit()
            await _add(api_client, rec_h, job_id, cand_id, "manual_search")
            move = {"candidate_id": cand_id, "job_id": job_id, "stage": "cv_sent"}
            refused = await api_client.post(
                "/api/pipeline/move", headers=other_h, json=move
            )
            assert refused.status_code == 403, refused.text
            sent = await api_client.post("/api/pipeline/move", headers=rec_h, json=move)
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


async def test_leaving_client_interview_requires_debrief(api_client):
    """Wyjście z „Rozmowy u klienta" do „Umowy" wymaga debriefu z pytaniami
    klienta albo jawnego „klient nie zadawał pytań" — 409 DEBRIEF_REQUIRED."""
    from app.models.calendar_event import CalendarEvent, EventStatus, EventType
    from app.models.interview_feedback import FeedbackSource, InterviewFeedback

    dl_id, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead)
    job_id, client_id = await _seed_job(dl_id)
    cand_id = await _seed_candidate()
    headers = await _login(api_client, dl_email, dl_pw)
    try:
        await _add(api_client, headers, job_id, cand_id, "manual_search")
        to_interview = await api_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "client_interview",
            },
        )
        assert to_interview.status_code == 200, to_interview.text
        start = datetime.now(timezone.utc) - timedelta(hours=3)
        async with AsyncSessionLocal() as db:
            event = CalendarEvent(
                title="Rozmowa u klienta",
                event_type=EventType.client_interview,
                start_time=start,
                end_time=start + timedelta(hours=1),
                status=EventStatus.completed,
                created_by=dl_id,
                operational_owner_id=dl_id,
                candidate_id=cand_id,
                job_id=job_id,
                client_id=client_id,
                attendees=[],
            )
            db.add(event)
            await db.commit()
            event_id = event.id

        blocked = await api_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "acceptance"},
        )
        assert blocked.status_code == 409, blocked.text
        detail = blocked.json()["detail"]
        assert detail["code"] == "DEBRIEF_REQUIRED"
        assert detail["event_id"] == event_id

        # Debrief z „klient nie zadawał pytań" otwiera bramkę.
        async with AsyncSessionLocal() as db:
            db.add(
                InterviewFeedback(
                    calendar_event_id=event_id,
                    candidate_id=cand_id,
                    job_id=job_id,
                    feedback_source=FeedbackSource.candidate_side,
                    overall_impression=5,
                    client_questions=None,
                    no_client_questions=True,
                )
            )
            await db.commit()
        ok = await api_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "acceptance"},
        )
        assert ok.status_code == 200, ok.text
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(InterviewFeedback).where(
                    InterviewFeedback.candidate_id == cand_id
                )
            )
            await db.execute(
                delete(CalendarEvent).where(CalendarEvent.candidate_id == cand_id)
            )
            await db.commit()
        await _cleanup([cand_id], job_id)


async def test_client_rate_in_move_needs_client_rate_write_rights(api_client):
    """Przegląd 23.09: stawka do klienta w ruchu = bramka `PATCH …/client-rate`.
    Rekruter-współpracownik (nie właściciel) nie zapisze jej ruchem."""
    owner_id, _, _ = await _seed_user(UserRole.recruiter)
    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    job_id, _ = await _seed_job(owner_id, collaborator_ids=(rec_id,))
    cand_id = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    try:
        await _add(api_client, rec_h, job_id, cand_id, "manual_search")
        resp = await api_client.post(
            "/api/pipeline/move",
            headers=rec_h,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "client_rate_value": "999",
            },
        )
        assert resp.status_code == 403, resp.text
    finally:
        await _cleanup([cand_id], job_id)


async def test_claim_does_not_bind_outside_new_column(api_client):
    """Import z Traffita przesuwa osobę bez `transition_process` — blokada,
    która przeżyła wyjście z „Nowych", nie może blokować dalszych etapów."""
    owner_id, owner_email, owner_pw = await _seed_user(UserRole.recruiter)
    other_id, other_email, other_pw = await _seed_user(UserRole.recruiter)
    job_id, _ = await _seed_job(owner_id, collaborator_ids=(other_id,))
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner_email, owner_pw)
    other_h = await _login(api_client, other_email, other_pw)
    try:
        await _add(api_client, owner_h, job_id, cand_id, "manual_search")
        # „Import": nowy wiersz etapu bez przejścia przez komendę procesu.
        async with AsyncSessionLocal() as db:
            db.add(
                CandidateStage(
                    candidate_id=cand_id,
                    job_id=job_id,
                    stage=PipelineStage.verified,
                    moved_at=datetime.now(timezone.utc) + timedelta(seconds=1),
                )
            )
            await db.commit()
        proc = await _process(cand_id, job_id)
        assert proc.claimed_by_user_id == owner_id  # blokada wciąż zapisana
        moved = await api_client.post(
            "/api/pipeline/move",
            headers=other_h,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "rejected",
                "rejection_reason": "Stawka",
            },
        )
        assert moved.status_code == 200, moved.text
    finally:
        await _cleanup([cand_id], job_id)


async def test_debrief_gate_covers_bulk_move_and_detour_through_cv_sent(api_client):
    from app.models.calendar_event import CalendarEvent, EventStatus, EventType

    dl_id, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead)
    job_id, client_id = await _seed_job(dl_id)
    cand_id = await _seed_candidate()
    headers = await _login(api_client, dl_email, dl_pw)
    try:
        await _add(api_client, headers, job_id, cand_id, "manual_search")
        for stage in ("client_interview",):
            ok = await api_client.post(
                "/api/pipeline/move",
                headers=headers,
                json={"candidate_id": cand_id, "job_id": job_id, "stage": stage},
            )
            assert ok.status_code == 200, ok.text
        start = datetime.now(timezone.utc) - timedelta(hours=2)
        async with AsyncSessionLocal() as db:
            db.add(
                CalendarEvent(
                    title="Rozmowa u klienta",
                    event_type=EventType.client_interview,
                    start_time=start,
                    end_time=start + timedelta(hours=1),
                    status=EventStatus.completed,
                    created_by=dl_id,
                    operational_owner_id=dl_id,
                    candidate_id=cand_id,
                    job_id=job_id,
                    client_id=client_id,
                    attendees=[],
                )
            )
            await db.commit()
        bulk = await api_client.post(
            "/api/pipeline/bulk-move",
            headers=headers,
            json={"candidate_ids": [cand_id], "job_id": job_id, "stage": "acceptance"},
        )
        assert bulk.status_code == 409, bulk.text
        assert bulk.json()["detail"]["code"] == "DEBRIEF_REQUIRED"

        # Okrężna droga: z Rozmowy z powrotem na „CV wysłane", potem Umowa.
        back = await api_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "cv_sent",
                "client_rate_value": "170",
            },
        )
        assert back.status_code == 200, back.text
        detour = await api_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "acceptance"},
        )
        assert detour.status_code == 409, detour.text
    finally:
        async with AsyncSessionLocal() as db:
            from app.models.calendar_event import CalendarEvent as _Ev

            await db.execute(delete(_Ev).where(_Ev.candidate_id == cand_id))
            await db.commit()
        await _cleanup([cand_id], job_id)


async def test_debrief_gate_is_not_skipped_through_the_closed_column(api_client):
    """Audyt 25.09.2026: „Rozmowa u klienta → Odrzucony → Umowa" omijało
    debrief, bo bramka patrzyła na bieżącą kolumnę („Zamknięci"). Liczy się
    kolumna sprzed zamknięcia."""
    from app.models.calendar_event import CalendarEvent, EventStatus, EventType

    dl_id, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead)
    job_id, client_id = await _seed_job(dl_id)
    cand_id = await _seed_candidate()
    headers = await _login(api_client, dl_email, dl_pw)
    try:
        await _add(api_client, headers, job_id, cand_id, "manual_search")
        ok = await api_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "client_interview",
            },
        )
        assert ok.status_code == 200, ok.text
        start = datetime.now(timezone.utc) - timedelta(hours=2)
        async with AsyncSessionLocal() as db:
            db.add(
                CalendarEvent(
                    title="Rozmowa u klienta",
                    event_type=EventType.client_interview,
                    start_time=start,
                    end_time=start + timedelta(hours=1),
                    status=EventStatus.completed,
                    created_by=dl_id,
                    operational_owner_id=dl_id,
                    candidate_id=cand_id,
                    job_id=job_id,
                    client_id=client_id,
                    attendees=[],
                )
            )
            await db.commit()
        rejected = await api_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "rejected",
                "rejection_reason": "Klient się wycofał",
            },
        )
        assert rejected.status_code == 200, rejected.text
        blocked = await api_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "acceptance"},
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["detail"]["code"] == "DEBRIEF_REQUIRED"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CalendarEvent).where(CalendarEvent.candidate_id == cand_id)
            )
            await db.commit()
        await _cleanup([cand_id], job_id)


# ── Poprawki po teście na produkcji (23.09.2026) ───────────────────────────


def _card(board: dict, candidate_id: int) -> dict:
    for col in board.get("columns", []):
        for item in col.get("items", []):
            if item.get("candidate_id") == candidate_id:
                return item
    raise AssertionError(f"kandydata {candidate_id} nie ma na tablicy")


async def test_screening_and_rates_follow_the_card_and_client_rate_is_dl_only(
    api_client,
):
    """Screening z „Nowych" i stawka kandydata z weryfikacji idą z kartą na
    kolejne etapy; stawkę do klienta widzi DL, a rekruter — nie (D2)."""
    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    dl_id, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead)
    job_id, _ = await _seed_job(rec_id, collaborator_ids=(dl_id,))
    cand_id = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    dl_h = await _login(api_client, dl_email, dl_pw)
    try:
        await _add(api_client, rec_h, job_id, cand_id, "manual_search")
        async with AsyncSessionLocal() as db:
            new_stage_id = await db.scalar(
                select(CandidateStage.id).where(
                    CandidateStage.candidate_id == cand_id,
                    CandidateStage.job_id == job_id,
                )
            )
        saved = await api_client.post(
            f"/api/pipeline/stages/{new_stage_id}/screening",
            headers=rec_h,
            json={
                "answers": [{"question_id": "q1", "response": "5 lat Kafka"}],
                "overall_fit": "fit",
            },
        )
        assert saved.status_code == 200, saved.text
        verified = await api_client.post(
            "/api/pipeline/move",
            headers=rec_h,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "140",
                "expected_rate_unit": "hourly",
            },
        )
        assert verified.status_code == 200, verified.text
        sent = await api_client.post(
            "/api/pipeline/move",
            headers=dl_h,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "cv_sent",
                "client_rate_value": "175",
                "client_rate_unit": "hourly",
            },
        )
        assert sent.status_code == 200, sent.text
        interview = await api_client.post(
            "/api/pipeline/move",
            headers=dl_h,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "client_interview",
            },
        )
        assert interview.status_code == 200, interview.text
        # Odpowiedź ruchu rekrutera też nie niesie stawki do klienta.
        assert verified.json()["client_rate_value"] is None

        rec_board = await api_client.get(
            f"/api/pipeline/kanban/{job_id}", headers=rec_h
        )
        assert rec_board.status_code == 200, rec_board.text
        rec_card = _card(rec_board.json(), cand_id)
        assert rec_card["stage"] == "client_interview"
        assert rec_card["screening_done"] is True
        assert Decimal(str(rec_card["expected_rate_value"])) == Decimal("140")
        assert rec_card["client_rate_value"] is None

        dl_board = await api_client.get(f"/api/pipeline/kanban/{job_id}", headers=dl_h)
        dl_card = _card(dl_board.json(), cand_id)
        assert Decimal(str(dl_card["client_rate_value"])) == Decimal("175")

        # Arkusz przeszedł na wiersz „Rozmowy u klienta" (portal klienta,
        # generator CV i przegląd DL czytają bieżący etap).
        async with AsyncSessionLocal() as db:
            current = await db.scalar(
                select(CandidateStage)
                .where(
                    CandidateStage.candidate_id == cand_id,
                    CandidateStage.job_id == job_id,
                )
                .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
                .limit(1)
            )
        assert current.stage == PipelineStage.client_interview
        assert current.screening_answers["answers"][0]["response"] == "5 lat Kafka"

        history = await api_client.get(
            f"/api/candidates/{cand_id}/history", headers=rec_h
        )
        assert history.status_code == 200, history.text
        assert history.json()["can_view_client_rate"] is False
        assert all(j.get("client_rate") is None for j in history.json()["jobs"])
        dl_history = await api_client.get(
            f"/api/candidates/{cand_id}/history", headers=dl_h
        )
        assert dl_history.json()["can_view_client_rate"] is True

        # Właściciel-rekruter nie zapisze już stawki do klienta (D2).
        patch = await api_client.patch(
            f"/api/candidates/{cand_id}/recruitments/{job_id}/client-rate",
            headers=rec_h,
            json={"client_rate_value": "200", "client_rate_unit": "hourly"},
        )
        assert patch.status_code == 403, patch.text
        job = await api_client.get(f"/api/jobs/{job_id}", headers=rec_h)
        assert job.json()["can_write_client_rate"] is False
    finally:
        await _cleanup([cand_id], job_id)


async def test_screening_read_falls_back_to_the_pairs_latest_sheet(api_client):
    """Etap bez własnego arkusza (np. wiersz z importu) pokazuje arkusz pary."""
    rec_id, rec_email, rec_pw = await _seed_user(UserRole.recruiter)
    job_id, _ = await _seed_job(rec_id)
    cand_id = await _seed_candidate()
    rec_h = await _login(api_client, rec_email, rec_pw)
    try:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            filled = CandidateStage(
                candidate_id=cand_id,
                job_id=job_id,
                stage=PipelineStage.new,
                moved_at=now - timedelta(hours=2),
                screening_answers={
                    "answers": [{"question_id": "q1", "response": "tak"}],
                    "overall_fit": "fit",
                },
            )
            bare = CandidateStage(
                candidate_id=cand_id,
                job_id=job_id,
                stage=PipelineStage.verified,
                moved_at=now,
            )
            db.add_all([filled, bare])
            await db.commit()
            filled_id, bare_id = filled.id, bare.id
        resp = await api_client.get(
            f"/api/pipeline/stages/{bare_id}/screening", headers=rec_h
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["screening_answers"]["answers"][0]["response"] == "tak"
        assert body["screening_source_stage_id"] == filled_id
    finally:
        await _cleanup([cand_id], job_id)


def test_integration_request_is_detected_by_oauth_client_state() -> None:
    from app.services import candidate_claim

    human = SimpleNamespace(state=SimpleNamespace())
    integration = SimpleNamespace(state=SimpleNamespace(oauth_client_id="scraper"))
    assert candidate_claim.is_integration_request(human) is False
    assert candidate_claim.is_integration_request(integration) is True
    assert candidate_claim.is_integration_request(object()) is False
