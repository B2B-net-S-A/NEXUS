"""Rozmowa bez Prepu 2 przez API (0480): zapis z powodem i telefonem, odmowy
poza wyjątkiem, odhaczenie telefonu, dzwonek DL i kolumny raportu."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.notification import Notification, NotificationType
from app.models.prep_meeting import Prep2Skip
from app.models.user import UserRole
from tests.test_interview_cycle import _job_with_candidate, _user


async def _event(
    *,
    kind: EventType,
    owner_id: int,
    cand_id: int,
    job_id: int,
    client_id: int,
    start: datetime,
) -> int:
    async with AsyncSessionLocal() as db:
        ev = CalendarEvent(
            title="Rozmowa u klienta" if kind == EventType.client_interview else "Prep",
            event_type=kind,
            start_time=start,
            end_time=start + timedelta(minutes=45),
            status=EventStatus.scheduled,
            created_by=owner_id,
            operational_owner_id=owner_id,
            candidate_id=cand_id,
            job_id=job_id,
            client_id=client_id,
            attendees=[],
        )
        db.add(ev)
        await db.commit()
        return ev.id


async def _pair_with_prep1(*, interview_in: timedelta):
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, dl_h = await _user(UserRole.delivery_lead)
    job_id, cand_id, client_id = await _job_with_candidate(
        recruiter_id=rec_id, dl_id=dl_id
    )
    now = datetime.now(timezone.utc)
    common = {
        "owner_id": rec_id,
        "cand_id": cand_id,
        "job_id": job_id,
        "client_id": client_id,
    }
    await _event(kind=EventType.prep_call, start=now - timedelta(hours=2), **common)
    iv_id = await _event(
        kind=EventType.client_interview, start=now + interview_in, **common
    )
    return rec_h, dl_id, dl_h, job_id, cand_id, iv_id


async def test_skip_is_saved_with_reason_and_call_and_reaches_the_dl(
    app_client: AsyncClient,
):
    # Rozmowa za 3 godziny jest zawsze dziś albo w najbliższy dzień roboczy.
    rec_h, dl_id, _dl_h, job_id, cand_id, iv_id = await _pair_with_prep1(
        interview_in=timedelta(hours=3)
    )
    call_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    created = await app_client.post(
        "/api/interview-cycle/prep2-skip",
        headers=rec_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "reason": "no_slot",
            "call_at": call_at,
        },
    )
    assert created.status_code == 201, created.text
    skip = created.json()
    assert skip["interview_event_id"] == iv_id
    assert skip["call_done_at"] is None

    overview = await app_client.get("/api/interview-cycle?scope=mine", headers=rec_h)
    assert overview.status_code == 200, overview.text
    item = next(i for i in overview.json()["items"] if i["candidate_id"] == cand_id)
    assert item["prep2_skip_status"] == "skipped"
    assert item["prep2_skip"]["reason"] == "no_slot"
    steps = {s["key"]: s for s in item["steps"]}
    assert steps["prep2"]["state"] == "skipped"
    kinds = [
        t["kind"] for t in overview.json()["todos"] if t["candidate_id"] == cand_id
    ]
    assert "precall_due" in kinds and "prep2_missing" not in kinds

    again = await app_client.post(
        "/api/interview-cycle/prep2-skip",
        headers=rec_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "reason": "no_slot",
            "call_at": call_at,
        },
    )
    assert again.status_code == 409, again.text

    async with AsyncSessionLocal() as db:
        bell = await db.scalar(
            select(Notification).where(
                Notification.user_id == dl_id,
                Notification.notification_type == NotificationType.prep2_skipped,
                Notification.related_entity_id == skip["id"],
            )
        )
    assert bell is not None

    done = await app_client.post(
        f"/api/interview-cycle/prep2-skip/{skip['id']}/call-done",
        headers=rec_h,
        json={"note": "Omówiliśmy Power Apps."},
    )
    assert done.status_code == 200, done.text
    assert done.json()["call_done_at"] is not None
    twice = await app_client.post(
        f"/api/interview-cycle/prep2-skip/{skip['id']}/call-done",
        headers=rec_h,
        json={},
    )
    assert twice.status_code == 409, twice.text


async def test_skip_is_refused_when_there_is_time_for_prep2(app_client: AsyncClient):
    rec_h, _dl_id, _dl_h, job_id, cand_id, _iv = await _pair_with_prep1(
        interview_in=timedelta(days=10)
    )
    resp = await app_client.post(
        "/api/interview-cycle/prep2-skip",
        headers=rec_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "reason": "no_slot",
            "call_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "PREP2_SKIP_TOO_EARLY"


async def test_other_reason_needs_words_and_call_must_be_before_interview(
    app_client: AsyncClient,
):
    rec_h, _dl_id, _dl_h, job_id, cand_id, _iv = await _pair_with_prep1(
        interview_in=timedelta(hours=3)
    )
    now = datetime.now(timezone.utc)
    bare_other = await app_client.post(
        "/api/interview-cycle/prep2-skip",
        headers=rec_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "reason": "other",
            "reason_note": "   ",
            "call_at": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert bare_other.status_code == 422, bare_other.text

    after = await app_client.post(
        "/api/interview-cycle/prep2-skip",
        headers=rec_h,
        json={
            "candidate_id": cand_id,
            "job_id": job_id,
            "reason": "short_notice",
            "call_at": (now + timedelta(hours=5)).isoformat(),
        },
    )
    assert after.status_code == 422, after.text
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(select(Prep2Skip.id).where(Prep2Skip.job_id == job_id))
            is None
        )


async def test_only_people_of_the_pair_can_skip(app_client: AsyncClient):
    """Pominięcie zwalnia konkretną rozmowę z prepu — zapisują je ludzie pary.

    Bramki `POST /preps` wpuszczały Finanse i rekrutera spoza rekrutacji
    (CI 20.10.2026: 201 zamiast 403)."""
    _rec_h, _dl_id, dl_h, job_id, cand_id, _iv = await _pair_with_prep1(
        interview_in=timedelta(hours=3)
    )
    body = {
        "candidate_id": cand_id,
        "job_id": job_id,
        "reason": "no_slot",
        "call_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    for role in (UserRole.recruiter, UserRole.finance):
        _other_id, other_h = await _user(role)
        resp = await app_client.post(
            "/api/interview-cycle/prep2-skip", headers=other_h, json=body
        )
        assert resp.status_code == 403, (role, resp.text)

    by_dl = await app_client.post(
        "/api/interview-cycle/prep2-skip", headers=dl_h, json=body
    )
    assert by_dl.status_code == 201, by_dl.text
