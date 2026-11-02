"""Automat maili CPro: zamknięcia, odrzucenia, dzwonki, sprawdzenie nadawcy (02.11.2026)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.cpro_mail import CproMailEvent
from app.models.job import Job, JobCloseReason, JobStatus
from app.models.m365 import Email, EmailDirection, EmailMatchMethod
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import cpro_mail
from app.services.cpro_mail import VerifiedMail, close_reason_for

CPRO_HTML = '<a href="https://nordea.onevms.se/r/1">Show request</a>'


def test_close_reason_mapping():
    assert close_reason_for("consultant contracted") == JobCloseReason.competitor
    assert close_reason_for(" Demand  Change ") == JobCloseReason.budget
    assert close_reason_for("cokolwiek") == JobCloseReason.other
    assert close_reason_for(None) == JobCloseReason.other


def _ok(body: str = ""):
    async def verifier(_db, _email):
        return VerifiedMail(
            found=True, authenticated=True, body_text=body, body_html=CPRO_HTML
        )

    return verifier


@pytest.fixture(autouse=True)
def _nordea_everywhere(monkeypatch):
    monkeypatch.setattr(cpro_mail, "cpro_enabled_for_client", lambda _client_id: True)
    monkeypatch.setattr(
        cpro_mail.settings, "CPRO_MAIL_SINCE", "2020-01-01", raising=False
    )
    monkeypatch.setattr(cpro_mail, "BATCH_LIMIT", 100_000)


def _number() -> str:
    return str(uuid.uuid4().int % 900_000 + 100_000)


async def _user(db, role: UserRole = UserRole.recruiter) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"cpro-{suffix}@example.com",
        password_hash=hash_password("P@ssw0rd"),
        name=f"Osoba {suffix}",
        role=role,
        roles=[role.value],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _job(db, number: str, lead: User, **kwargs) -> Job:
    client = Client(name=f"Nordea-{uuid.uuid4().hex[:8]}")
    db.add(client)
    await db.flush()
    job = Job(
        title=f"pytest-cpro-{number}",
        client_id=client.id,
        client_reference=number,
        status=JobStatus.published,
        is_open=True,
        delivery_lead_id=lead.id,
        **kwargs,
    )
    db.add(job)
    await db.flush()
    return job


async def _card(
    db,
    job: Job,
    owner: User,
    stage: PipelineStage = PipelineStage.cv_sent,
    moved_at: Optional[datetime] = None,
) -> Candidate:
    suffix = uuid.uuid4().hex[:8]
    candidate = Candidate(
        name="Jan",
        lastname=f"Test{suffix}",
        email=f"kand-{suffix}@example.com",
    )
    db.add(candidate)
    await db.flush()
    db.add(
        CandidateStage(
            candidate_id=candidate.id,
            job_id=job.id,
            stage=stage,
            moved_by=owner.id,
            moved_at=moved_at or datetime.now(timezone.utc) - timedelta(days=3),
        )
    )
    await db.flush()
    return candidate


async def _mail(
    db,
    owner: User,
    subject: str,
    *,
    key: Optional[str] = None,
    received_at: Optional[datetime] = None,
) -> str:
    message_id = uuid.uuid4().hex
    key = key or f"<{message_id}@onevms>"
    db.add(
        Email(
            user_id=owner.id,
            m365_message_id=message_id,
            m365_internet_message_id=key,
            m365_conversation_id=message_id,
            subject=subject,
            from_address="noreply@onevms.se",
            from_name="NOREPLY CPro",
            received_at=received_at or datetime.now(timezone.utc) - timedelta(hours=1),
            direction=EmailDirection.received,
            match_method=EmailMatchMethod.unmatched,
        )
    )
    await db.flush()
    return key


async def _event(db, key: str) -> CproMailEvent:
    return await db.scalar(
        select(CproMailEvent).where(CproMailEvent.message_key == key)
    )


async def _bells(db, user_id: int, ntype: NotificationType) -> list[Notification]:
    return (
        await db.scalars(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.notification_type == ntype,
            )
        )
    ).all()


CLOSED_BODY = "Dear Supplier. Close reason: consultant contracted--Anna"


@pytest.mark.asyncio
async def test_closed_mail_closes_all_twins_and_tells_every_recruiter():
    async with AsyncSessionLocal() as db:
        number = _number()
        lead = await _user(db, UserRole.delivery_lead)
        at_client = await _user(db)
        early = await _user(db)
        first = await _job(db, number, lead)
        twin = await _job(db, number, lead)
        await _card(db, first, at_client, PipelineStage.cv_sent)
        await _card(db, first, early, PipelineStage.new)
        key = await _mail(db, lead, f"Tester was closed. ({number})")
        # Ten sam mail w drugiej skrzynce to jedno zdarzenie.
        await _mail(db, at_client, f"Tester was closed. ({number})", key=key)
        await db.commit()
        ids = (first.id, twin.id, at_client.id, early.id)

    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=_ok(CLOSED_BODY))

    async with AsyncSessionLocal() as db:
        first_row = await db.get(Job, ids[0])
        twin_row = await db.get(Job, ids[1])
        assert first_row.status == JobStatus.closed
        assert twin_row.status == JobStatus.closed
        assert first_row.close_reason == JobCloseReason.competitor
        assert "consultant contracted" in first_row.close_notes
        event = await _event(db, key)
        assert event.outcome == cpro_mail.OUTCOME_DONE
        assert event.notified == 2
        rows = (
            await db.scalars(
                select(CproMailEvent).where(CproMailEvent.message_key == key)
            )
        ).all()
        assert len(rows) == 1
        told = await _bells(db, ids[2], NotificationType.job_closed_people_waiting)
        assert "daj znać 1 osobie" in told[0].title
        told_early = await _bells(
            db, ids[3], NotificationType.job_closed_people_waiting
        )
        assert "nie dzwoń" in told_early[0].title


@pytest.mark.asyncio
async def test_person_in_contract_stops_closing_and_asks_lead():
    async with AsyncSessionLocal() as db:
        number = _number()
        lead = await _user(db, UserRole.delivery_lead)
        job = await _job(db, number, lead)
        await _card(db, job, lead, PipelineStage.acceptance)
        key = await _mail(db, lead, f"Tester was closed. ({number})")
        await db.commit()
        ids = (job.id, lead.id)

    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=_ok(CLOSED_BODY))

    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, ids[0])).status == JobStatus.published
        assert (await _event(db, key)).outcome == cpro_mail.OUTCOME_MANUAL
        assert await _bells(db, ids[1], NotificationType.cpro_close_needs_decision)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "check",
    [
        VerifiedMail(found=True, authenticated=False, body_html=CPRO_HTML),
        VerifiedMail(found=True, authenticated=True, body_html="<a href='x'>x</a>"),
        VerifiedMail(found=False),
    ],
    ids=["bez-podpisu", "bez-linku", "brak-w-skrzynce"],
)
async def test_unverified_sender_changes_nothing(check):
    async def verifier(_db, _email):
        return check

    async with AsyncSessionLocal() as db:
        number = _number()
        lead = await _user(db, UserRole.delivery_lead)
        job = await _job(db, number, lead)
        key = await _mail(db, lead, f"Tester was closed. ({number})")
        await db.commit()
        job_id = job.id

    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=verifier)

    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).status == JobStatus.published
        assert (await _event(db, key)).outcome == cpro_mail.OUTCOME_MANUAL


@pytest.mark.asyncio
async def test_graph_outage_leaves_mail_for_next_pass():
    async def outage(_db, _email):
        return None

    async with AsyncSessionLocal() as db:
        lead = await _user(db, UserRole.delivery_lead)
        key = await _mail(db, lead, f"Tester was closed. ({_number()})")
        await db.commit()

    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=outage)

    async with AsyncSessionLocal() as db:
        assert await _event(db, key) is None


@pytest.mark.asyncio
async def test_unknown_number_goes_to_manual():
    async with AsyncSessionLocal() as db:
        lead = await _user(db, UserRole.delivery_lead)
        key = await _mail(db, lead, f"Tester was closed. ({_number()})")
        await db.commit()

    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=_ok(CLOSED_BODY))

    async with AsyncSessionLocal() as db:
        event = await _event(db, key)
        assert event.outcome == cpro_mail.OUTCOME_MANUAL
        assert "nie ma w NEXUSIE" in event.outcome_text


@pytest.mark.asyncio
async def test_rule_switched_off_changes_nothing():
    async with AsyncSessionLocal() as db:
        number = _number()
        lead = await _user(db, UserRole.delivery_lead)
        job = await _job(db, number, lead)
        key = await _mail(db, lead, f"Tester was closed. ({number})")
        await cpro_mail.save_rules(db, {"closed": False}, actor_id=lead.id)
        await db.commit()
        job_id = job.id

    try:
        async with AsyncSessionLocal() as db:
            await cpro_mail.run_sweep(db, verifier=_ok(CLOSED_BODY))
        async with AsyncSessionLocal() as db:
            assert (await db.get(Job, job_id)).status == JobStatus.published
            assert (await _event(db, key)).outcome == cpro_mail.OUTCOME_MANUAL
    finally:
        async with AsyncSessionLocal() as db:
            await cpro_mail.save_rules(db, {"closed": True}, actor_id=lead.id)
            await db.commit()


REJECT_BODY = "Urgent Rejected: osoba (43084) Profile not matching Offer: osoba"


@pytest.mark.asyncio
async def test_rejection_moves_card_and_tells_owner_without_candidate_mail():
    async with AsyncSessionLocal() as db:
        number = _number()
        lead = await _user(db, UserRole.delivery_lead)
        owner = await _user(db)
        job = await _job(db, number, lead)
        person = await _card(db, job, owner)
        key = await _mail(
            db, lead, f"Rejected: {person.name} {person.lastname} ({number})"
        )
        await db.commit()
        ids = (job.id, person.id, owner.id)

    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=_ok(REJECT_BODY))

    async with AsyncSessionLocal() as db:
        latest = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.job_id == ids[0],
                CandidateStage.candidate_id == ids[1],
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        assert latest.stage == PipelineStage.rejected
        assert latest.ended_by == "client"
        assert latest.moved_by is None
        assert "Profile not matching" in latest.notes
        event = await _event(db, key)
        assert event.outcome == cpro_mail.OUTCOME_DONE
        assert event.candidate_id == ids[1]
        bells = await _bells(db, ids[2], NotificationType.cpro_candidate_rejected)
        assert len(bells) == 1
        assert f"/jobs/{ids[0]}?candidate={ids[1]}" == bells[0].link


@pytest.mark.asyncio
async def test_rejection_tells_lead_when_owner_has_left():
    async with AsyncSessionLocal() as db:
        number = _number()
        lead = await _user(db, UserRole.delivery_lead)
        owner = await _user(db)
        owner.is_active = False
        job = await _job(db, number, lead)
        person = await _card(db, job, owner)
        await _mail(db, lead, f"Rejected: {person.name} {person.lastname} ({number})")
        await db.commit()
        lead_id = lead.id

    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=_ok(REJECT_BODY))

    async with AsyncSessionLocal() as db:
        assert await _bells(db, lead_id, NotificationType.cpro_candidate_rejected)


@pytest.mark.asyncio
async def test_card_moved_after_mail_stays():
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        number = _number()
        lead = await _user(db, UserRole.delivery_lead)
        job = await _job(db, number, lead)
        person = await _card(db, job, lead, moved_at=now - timedelta(minutes=5))
        key = await _mail(
            db,
            lead,
            f"Rejected: {person.name} {person.lastname} ({number})",
            received_at=now - timedelta(hours=2),
        )
        await db.commit()
        ids = (job.id, person.id)

    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=_ok(REJECT_BODY))

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(CandidateStage).where(
                    CandidateStage.job_id == ids[0],
                    CandidateStage.candidate_id == ids[1],
                )
            )
        ).all()
        assert [row.stage for row in rows] == [PipelineStage.cv_sent]
        assert (await _event(db, key)).outcome == cpro_mail.OUTCOME_ALREADY


@pytest.mark.asyncio
async def test_rejection_of_unknown_person_goes_to_manual():
    async with AsyncSessionLocal() as db:
        number = _number()
        lead = await _user(db, UserRole.delivery_lead)
        await _job(db, number, lead)
        key = await _mail(db, lead, f"Rejected: Nieznana Osoba ({number})")
        await db.commit()

    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=_ok(REJECT_BODY))

    async with AsyncSessionLocal() as db:
        event = await _event(db, key)
        assert event.outcome == cpro_mail.OUTCOME_MANUAL
        assert "Nie ma tej osoby" in event.outcome_text


@pytest.mark.asyncio
async def test_interview_request_only_rings_lead_and_owner():
    async with AsyncSessionLocal() as db:
        number = _number()
        lead = await _user(db, UserRole.delivery_lead)
        owner = await _user(db)
        job = await _job(db, number, lead)
        person = await _card(db, job, owner)
        name = f"{person.name} {person.lastname}"
        key = await _mail(
            db, lead, f"I would like to interview {name}, Request {number}"
        )
        old_key = await _mail(
            db,
            lead,
            f"I would like to interview {name}, Request {number}",
            received_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        await db.commit()
        ids = (job.id, person.id, lead.id, owner.id)

    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=_ok(""))

    async with AsyncSessionLocal() as db:
        event = await _event(db, key)
        assert event.outcome == cpro_mail.OUTCOME_NOTIFIED
        assert (await _event(db, old_key)).outcome == cpro_mail.OUTCOME_ALREADY
        for user_id in ids[2:]:
            bells = await _bells(db, user_id, NotificationType.cpro_interview_change)
            assert len(bells) == 1
        rows = (
            await db.scalars(
                select(CandidateStage).where(
                    CandidateStage.job_id == ids[0],
                    CandidateStage.candidate_id == ids[1],
                )
            )
        ).all()
        assert [row.stage for row in rows] == [PipelineStage.cv_sent]


@pytest.mark.asyncio
async def test_rejection_bell_goes_to_verifier_not_to_who_added_the_card():
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        number = _number()
        lead = await _user(db, UserRole.delivery_lead)
        added = await _user(db)
        verified = await _user(db)
        job = await _job(db, number, lead)
        person = await _card(db, job, added, moved_at=now - timedelta(days=5))
        db.add(
            CandidateStage(
                candidate_id=person.id,
                job_id=job.id,
                stage=PipelineStage.verified,
                moved_by=verified.id,
                moved_at=now - timedelta(days=4),
            )
        )
        await _mail(db, lead, f"Rejected: {person.name} {person.lastname} ({number})")
        await db.commit()
        ids = (added.id, verified.id)

    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=_ok(REJECT_BODY))

    async with AsyncSessionLocal() as db:
        ntype = NotificationType.cpro_candidate_rejected
        assert await _bells(db, ids[1], ntype)
        assert not await _bells(db, ids[0], ntype)


@pytest.mark.asyncio
async def test_mailbox_without_connection_waits_then_gives_up():
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        lead = await _user(db, UserRole.delivery_lead)
        recent = Email(user_id=lead.id, received_at=now - timedelta(days=1))
        assert await cpro_mail.verify_with_graph(db, recent) is None
        old = Email(user_id=lead.id, received_at=now - timedelta(days=30))
        assert await cpro_mail.verify_with_graph(db, old) == VerifiedMail(found=False)
        await db.rollback()


def _db_error(sqlstate: str) -> DBAPIError:
    class Orig(Exception):
        pass

    orig = Orig()
    orig.sqlstate = sqlstate
    return DBAPIError("SELECT 1", {}, orig)


def test_transient_errors_are_retried():
    assert cpro_mail.is_transient(_db_error("40P01"))
    assert cpro_mail.is_transient(TimeoutError())
    assert not cpro_mail.is_transient(_db_error("23505"))
    assert not cpro_mail.is_transient(ValueError("zły mail"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "stored"),
    [(_db_error("40P01"), False), (ValueError("zły mail"), True)],
    ids=["zakleszczenie", "trwaly"],
)
async def test_only_lasting_error_consumes_the_mail(monkeypatch, error, stored):
    async def boom(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(cpro_mail, "_process_one", boom)
    async with AsyncSessionLocal() as db:
        lead = await _user(db, UserRole.delivery_lead)
        key = await _mail(db, lead, f"Tester was closed. ({_number()})")
        await db.commit()

    async with AsyncSessionLocal() as db:
        await cpro_mail.run_sweep(db, verifier=_ok(CLOSED_BODY))

    async with AsyncSessionLocal() as db:
        assert (await _event(db, key) is not None) is stored


async def _headers(app_client, role: UserRole) -> dict[str, str]:
    async with AsyncSessionLocal() as db:
        user = await _user(db, role)
        email = user.email
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": "P@ssw0rd"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_log_and_rules_gates(app_client):
    hor = await _headers(app_client, UserRole.head_of_recruitment)
    lead = await _headers(app_client, UserRole.delivery_lead)
    recruiter = await _headers(app_client, UserRole.recruiter)

    assert (await app_client.get("/api/cpro/log", headers=hor)).status_code == 200
    read = await app_client.get("/api/cpro/log", headers=lead)
    assert read.status_code == 200
    assert read.json()["can_edit"] is False
    assert (await app_client.get("/api/cpro/log", headers=recruiter)).status_code == 403

    body = {"interview": True}
    assert (
        await app_client.put("/api/cpro/rules", json=body, headers=lead)
    ).status_code == 403
    assert (
        await app_client.put("/api/cpro/rules", json=body, headers=hor)
    ).status_code == 200
