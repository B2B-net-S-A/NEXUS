"""Rekrutacja własna: cała ścieżka przez API, z zaślepionym Microsoftem."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.candidate import Candidate
from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel
from app.models.m365 import Email, EmailDirection, M365Connection
from app.models.own_hiring import (
    OwnHiringApplication,
    OwnHiringBooking,
    OwnHiringProcess,
)
from app.models.user import User, UserRole
from app.services import prep_availability, prep_meetings
from app.services.m365 import sender as m365_sender
from app.services.m365 import teams_prep_graph
from app.services.own_hiring import service, sweep

pytestmark = pytest.mark.asyncio

AD = "IT Rekruter / IT Rekruterka"


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.role.value, roles=[user.role.value])
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: UserRole, label: str) -> User:
    user = User(
        email=f"own-{label}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        name=f"Test {label}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _applicant(db, role: str, *, note: str = f"Źródło: Pracuj.pl — oferta: {AD}"):
    candidate = Candidate(
        name="Testowa",
        lastname=f"Osoba-{uuid.uuid4().hex[:6]}",
        email=f"kand-{uuid.uuid4().hex[:8]}@example.com",
        phone="+48500100200",
        experience=[
            {"role": role, "company": "Firma", "start": "2023-01", "end": "2024-12"}
        ],
    )
    db.add(candidate)
    await db.flush()
    db.add(
        CandidateSourceEvent(
            candidate_id=candidate.id,
            channel=SourceChannel.posting,
            note=note,
            captured_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    await db.refresh(candidate)
    return candidate


@pytest.fixture
def microsoft(monkeypatch):
    """Zaślepia kalendarz i wysyłkę: testy nie wychodzą do Microsoftu."""
    state = SimpleNamespace(
        mails=[], events=[], cancelled=[], fail_calendar=False, busy=[]
    )

    async def busy_blocks(emails, *, start, end):
        return {email.strip().lower(): list(state.busy) for email in emails}

    async def send_new(
        db, connection, *, to, subject, body_html, client_request_id=None, **_
    ):
        state.mails.append(SimpleNamespace(to=to, subject=subject, body=body_html))
        return SimpleNamespace(id=1)

    async def create_event(upn, payload):
        if state.fail_calendar:
            raise RuntimeError("graph down")
        state.events.append(payload)
        return SimpleNamespace(
            graph_event_id=f"evt-{len(state.events)}",
            join_url="https://teams.example/x",
        )

    async def cancel_event(upn, event_id, comment):
        state.cancelled.append(event_id)
        return "cancelled"

    monkeypatch.setattr(prep_availability, "busy_blocks", busy_blocks)
    monkeypatch.setattr(m365_sender, "send_new", send_new)
    monkeypatch.setattr(teams_prep_graph, "create_event", create_event)
    monkeypatch.setattr(teams_prep_graph, "cancel_event", cancel_event)
    monkeypatch.setattr(prep_meetings, "app_only_ready", lambda: True)
    return state


@pytest_asyncio.fixture
async def world(app_client):
    async with AsyncSessionLocal() as db:
        await db.execute(delete(OwnHiringProcess))
        await db.commit()
        owner = await _user(db, UserRole.admin, "owner")
        assistant = await _user(db, UserRole.finance, "assistant")
        other_admin = await _user(db, UserRole.admin, "other")
        db.add(
            M365Connection(
                user_id=owner.id,
                tenant_id="t",
                mailbox_upn=owner.email,
                is_active=True,
                access_token_ct="x",
                refresh_token_ct="x",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        await db.commit()
    created = await app_client.post(
        "/api/own-hiring/process",
        headers=_headers(owner),
        json={
            "title": "IT Rekruter",
            "ad_titles": [AD],
            "intake_since": (datetime.now(timezone.utc) - timedelta(days=1))
            .date()
            .isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    windows = {str(day): [["00:00", "23:30"]] for day in range(7)}
    process = created.json()
    settings = {**process["settings"], "windows": windows, "lead_hours": 1}
    saved = await app_client.put(
        "/api/own-hiring/process",
        headers=_headers(owner),
        json={
            "title": "IT Rekruter",
            "ad_titles": [AD],
            "assistant_user_id": assistant.id,
            "settings": settings,
        },
    )
    assert saved.status_code == 200, saved.text
    return SimpleNamespace(
        owner=owner,
        assistant=assistant,
        other_admin=other_admin,
        process_id=process["id"],
        client=app_client,
    )


async def _import(world, role: str = "IT Recruiter") -> tuple[Candidate, int]:
    async with AsyncSessionLocal() as db:
        candidate = await _applicant(db, role)
        await sweep.run_once(db)
        app_id = await db.scalar(
            select(OwnHiringApplication.id).where(
                OwnHiringApplication.candidate_id == candidate.id
            )
        )
    return candidate, app_id


async def _token(app_id: int) -> str:
    async with AsyncSessionLocal() as db:
        application = await db.get(OwnHiringApplication, app_id)
        token = service.current_token(application)
    assert token
    return token


async def _invite(world, app_id: int) -> str:
    resp = await world.client.post(
        "/api/own-hiring/applications/invite",
        headers=_headers(world.owner),
        json={"ids": [app_id]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["outcome"] == "sent"
    return await _token(app_id)


async def _first_slot(world, token: str) -> str:
    view = (await world.client.get(f"/api/public/own-hiring/{token}")).json()
    return view["days"][0]["slots"][0]


async def test_intake_sorts_by_filter_and_ignores_other_ads(world, microsoft):
    match, match_id = await _import(world, "IT Recruiter")
    filtered, filtered_id = await _import(world, "Kelner")
    async with AsyncSessionLocal() as db:
        other = await _applicant(
            db, "Recruiter", note="Źródło: Pracuj.pl — oferta: Java Developer"
        )
        await sweep.run_once(db)
        assert (
            await db.scalar(
                select(func.count())
                .select_from(OwnHiringApplication)
                .where(OwnHiringApplication.candidate_id == other.id)
            )
            == 0
        )
        assert (await db.get(OwnHiringApplication, match_id)).bucket == "match"
        assert (await db.get(OwnHiringApplication, filtered_id)).bucket == "filtered"

    board = await world.client.get(
        "/api/own-hiring/board", headers=_headers(world.owner)
    )
    ids = [card["id"] for card in board.json()["cards"]]
    assert match_id in ids
    assert filtered_id not in ids
    hidden = await world.client.get(
        "/api/own-hiring/new?bucket=filtered", headers=_headers(world.owner)
    )
    assert [row["id"] for row in hidden.json()] == [filtered_id]


async def test_intake_twice_does_not_duplicate(world, microsoft):
    candidate, _ = await _import(world)
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSourceEvent(
                candidate_id=candidate.id,
                channel=SourceChannel.posting,
                note=f"Źródło: RocketJobs/JJIT — oferta: {AD}",
                captured_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        await sweep.run_once(db)
        count = await db.scalar(
            select(func.count())
            .select_from(OwnHiringApplication)
            .where(OwnHiringApplication.candidate_id == candidate.id)
        )
    assert count == 1


async def test_access_is_by_process_membership_not_role(world, microsoft):
    other = _headers(world.other_admin)
    assistant = _headers(world.assistant)
    assert (
        await world.client.get("/api/own-hiring/board", headers=other)
    ).status_code == 403
    assert (
        await world.client.get("/api/own-hiring/queue", headers=other)
    ).status_code == 403
    assert (
        await world.client.get("/api/own-hiring/board", headers=assistant)
    ).status_code == 403
    assert (
        await world.client.get("/api/own-hiring/queue", headers=assistant)
    ).status_code == 200
    me = (await world.client.get("/api/own-hiring/me", headers=assistant)).json()
    assert me["role"] == "assistant"


async def test_assistant_payload_has_no_cv_or_money(world, microsoft):
    _, app_id = await _import(world)
    await _invite(world, app_id)
    await world.client.post(
        "/api/own-hiring/applications/hand-off",
        headers=_headers(world.owner),
        json={"ids": [app_id]},
    )
    rows = (
        await world.client.get(
            "/api/own-hiring/queue", headers=_headers(world.assistant)
        )
    ).json()
    assert set(rows[0]) == {
        "id",
        "name",
        "phone",
        "ad_title",
        "invited_at",
        "handed_off_at",
        "call_attempts",
        "callback_at",
        "max_attempts",
    }
    detail = await world.client.get(
        f"/api/own-hiring/applications/{app_id}", headers=_headers(world.assistant)
    )
    assert detail.status_code == 403


async def test_full_path_from_link_to_signed(world, microsoft):
    candidate, app_id = await _import(world)
    token = await _invite(world, app_id)
    assert microsoft.mails[0].to == [candidate.email]
    assert f"/t/{token}" in microsoft.mails[0].body

    slot = await _first_slot(world, token)
    booked = await world.client.post(
        f"/api/public/own-hiring/{token}/book", json={"start": slot}
    )
    assert booked.status_code == 200, booked.text
    assert booked.json()["state"] == "booked"
    assert microsoft.events[0]["isOnlineMeeting"] is True
    assert (
        microsoft.events[0]["attendees"][0]["emailAddress"]["address"]
        == candidate.email
    )

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(OwnHiringBooking).where(OwnHiringBooking.application_id == app_id)
        )
        assert row.sync_status == "ok"
        row.start_at = datetime.now(timezone.utc) - timedelta(hours=2)
        row.end_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()

    headers = _headers(world.owner)
    office = (
        (datetime.now(timezone.utc) + timedelta(days=3))
        .replace(microsecond=0)
        .isoformat()
    )
    outcome = await world.client.post(
        f"/api/own-hiring/applications/{app_id}/teams-outcome",
        headers=headers,
        json={
            "availability": "month",
            "expected_money": "11 000 netto",
            "tech_level": "good",
            "note": "ok",
            "decision": "office",
            "office_start": office,
        },
    )
    assert outcome.status_code == 200, outcome.text
    assert outcome.json()["stage"] == "office"
    assert microsoft.events[1].get("isOnlineMeeting") is None

    contract = await world.client.post(
        f"/api/own-hiring/applications/{app_id}/office-outcome",
        headers=headers,
        json={"decision": "contract", "contract_kind": "b2b"},
    )
    assert contract.json()["stage"] == "contract"
    signed = await world.client.post(
        f"/api/own-hiring/applications/{app_id}/contract-outcome",
        headers=headers,
        json={"decision": "signed"},
    )
    assert signed.json()["stage"] == "signed"
    assert (await world.client.get(f"/api/public/own-hiring/{token}")).json()[
        "state"
    ] == "finished"


async def test_two_people_cannot_take_one_slot(world, microsoft):
    _, first_id = await _import(world)
    _, second_id = await _import(world)
    first = await _invite(world, first_id)
    second = await _invite(world, second_id)
    slot = await _first_slot(world, first)
    assert (
        await world.client.post(
            f"/api/public/own-hiring/{first}/book", json={"start": slot}
        )
    ).status_code == 200
    taken = await world.client.post(
        f"/api/public/own-hiring/{second}/book", json={"start": slot}
    )
    assert taken.status_code == 409
    assert taken.json()["detail"]["code"] == "slot_taken"


async def test_busy_calendar_slot_is_rejected_on_booking(world, microsoft):
    _, app_id = await _import(world)
    token = await _invite(world, app_id)
    slot = await _first_slot(world, token)
    start = datetime.fromisoformat(slot.replace("Z", "+00:00"))
    microsoft.busy.append((start, start + timedelta(minutes=30)))
    response = await world.client.post(
        f"/api/public/own-hiring/{token}/book", json={"start": slot}
    )
    assert response.status_code == 409


async def test_calendar_unreadable_shows_no_slots(world, microsoft, monkeypatch):
    _, app_id = await _import(world)
    token = await _invite(world, app_id)

    async def unreadable(emails, *, start, end):
        return {email.strip().lower(): None for email in emails}

    monkeypatch.setattr(prep_availability, "busy_blocks", unreadable)
    view = (await world.client.get(f"/api/public/own-hiring/{token}")).json()
    assert view["calendar_available"] is False
    assert view["days"] == []


async def test_public_view_exposes_no_personal_fields(world, microsoft):
    candidate, app_id = await _import(world)
    token = await _invite(world, app_id)
    response = await world.client.get(f"/api/public/own-hiring/{token}")
    assert set(response.json()) == {
        "state",
        "role_title",
        "owner_name",
        "minutes",
        "calendar_available",
        "days",
        "booking",
    }
    assert candidate.email not in response.text
    assert response.headers["x-robots-tag"] == "noindex"
    assert response.headers["cache-control"] == "no-store"


async def test_unknown_and_expired_tokens(world, microsoft):
    assert (
        await world.client.get("/api/public/own-hiring/nieznany")
    ).status_code == 404
    _, app_id = await _import(world)
    token = await _invite(world, app_id)
    async with AsyncSessionLocal() as db:
        application = await db.get(OwnHiringApplication, app_id)
        application.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    assert (
        await world.client.get(f"/api/public/own-hiring/{token}")
    ).status_code == 410


async def test_silence_moves_to_no_response_but_link_still_works(world, microsoft):
    _, app_id = await _import(world)
    token = await _invite(world, app_id)
    async with AsyncSessionLocal() as db:
        application = await db.get(OwnHiringApplication, app_id)
        application.response_due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
        await sweep.run_once(db)
        await db.refresh(application)
        assert application.stage == "no_response"
    slot = await _first_slot(world, token)
    booked = await world.client.post(
        f"/api/public/own-hiring/{token}/book", json={"start": slot}
    )
    assert booked.status_code == 200
    async with AsyncSessionLocal() as db:
        assert (await db.get(OwnHiringApplication, app_id)).stage == "teams"


async def test_reply_by_mail_stops_the_clock(world, microsoft):
    candidate, app_id = await _import(world)
    await _invite(world, app_id)
    async with AsyncSessionLocal() as db:
        application = await db.get(OwnHiringApplication, app_id)
        application.response_due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.add(
            Email(
                user_id=world.owner.id,
                candidate_id=candidate.id,
                m365_message_id=uuid.uuid4().hex,
                m365_conversation_id=uuid.uuid4().hex,
                from_address=candidate.email,
                subject="Re",
                body_preview="Mogę w środę",
                received_at=datetime.now(timezone.utc) + timedelta(seconds=5),
                direction=EmailDirection.received,
            )
        )
        await db.commit()
        await sweep.run_once(db)
        await db.refresh(application)
        assert application.replied_at is not None
        assert application.stage == "invited"


async def test_assistant_books_and_three_failed_calls_return_to_owner(world, microsoft):
    _, booked_id = await _import(world)
    _, silent_id = await _import(world)
    owner = _headers(world.owner)
    assistant = _headers(world.assistant)
    for app_id in (booked_id, silent_id):
        await _invite(world, app_id)
    await world.client.post(
        "/api/own-hiring/applications/hand-off",
        headers=owner,
        json={"ids": [booked_id, silent_id]},
    )
    slots = (
        await world.client.get("/api/own-hiring/slots?kind=teams", headers=assistant)
    ).json()
    start = slots["days"][0]["slots"][0]
    response = await world.client.post(
        f"/api/own-hiring/queue/{booked_id}/book",
        headers=assistant,
        json={"start": start},
    )
    assert response.status_code == 200, response.text
    for _ in range(3):
        await world.client.post(
            f"/api/own-hiring/queue/{silent_id}/result",
            headers=assistant,
            json={"result": "no_answer"},
        )
    async with AsyncSessionLocal() as db:
        booked = await db.get(OwnHiringApplication, booked_id)
        silent = await db.get(OwnHiringApplication, silent_id)
        assert booked.stage == "teams"
        assert silent.stage == "no_response"


async def test_calendar_failure_keeps_booking_and_retries(world, microsoft):
    _, app_id = await _import(world)
    token = await _invite(world, app_id)
    microsoft.fail_calendar = True
    slot = await _first_slot(world, token)
    response = await world.client.post(
        f"/api/public/own-hiring/{token}/book", json={"start": slot}
    )
    assert response.status_code == 200
    microsoft.fail_calendar = False
    async with AsyncSessionLocal() as db:
        await sweep.run_once(db)
        row = await db.scalar(
            select(OwnHiringBooking).where(OwnHiringBooking.application_id == app_id)
        )
    assert row.sync_status == "ok"
    assert row.join_url == "https://teams.example/x"


async def test_candidate_withdraw_cancels_meeting(world, microsoft):
    _, app_id = await _import(world)
    token = await _invite(world, app_id)
    slot = await _first_slot(world, token)
    await world.client.post(
        f"/api/public/own-hiring/{token}/book", json={"start": slot}
    )
    response = await world.client.post(f"/api/public/own-hiring/{token}/withdraw")
    assert response.json()["state"] == "closed"
    assert microsoft.cancelled == ["evt-1"]


async def test_invite_without_mailbox_is_412(world, microsoft):
    _, app_id = await _import(world)
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(M365Connection).where(M365Connection.user_id == world.owner.id)
        )
        await db.commit()
    response = await world.client.post(
        "/api/own-hiring/applications/invite",
        headers=_headers(world.owner),
        json={"ids": [app_id]},
    )
    assert response.status_code == 412
