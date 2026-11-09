"""Pas „Czeka na odpowiedź klienta” (S-C2, 08.11.2026)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import hash_password
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.services import client_wait
from app.services.client_wait import (
    WaitSettings,
    WaitingPerson,
    closes_on,
    due_for_close,
    JobWait,
    panel_state_for,
    reminder_text,
    wait_payload,
    workdays_noun,
)
from tests.test_job_close import _create_draft_job, _seed_candidate_in_job

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def _person(
    candidate_id: int = 1,
    *,
    workdays: int = 7,
    column: str = "cv_sent",
    closes: date | None = None,
    name: str = "Anna Nowak",
) -> WaitingPerson:
    moment = datetime(2026, 10, 20, 10, tzinfo=timezone.utc)
    return WaitingPerson(
        candidate_id=candidate_id,
        name=name,
        column=column,
        entered_at=moment,
        silent_since=moment,
        workdays=workdays,
        panel=client_wait.PANEL_OFF,
        reminded_at=None,
        closes_on=closes,
        added_by=None,
    )


@pytest.mark.parametrize(
    ("count", "text"),
    [
        (1, "1 dzień roboczy"),
        (2, "2 dni robocze"),
        (5, "5 dni roboczych"),
        (12, "12 dni roboczych"),
        (22, "22 dni robocze"),
    ],
)
def test_workdays_noun(count: int, text: str):
    assert workdays_noun(count) == text


def test_action_starts_on_the_sixth_workday():
    assert _person(workdays=5).needs_action is False
    assert _person(workdays=6).needs_action is True


def test_auto_close_is_off_by_default_and_gives_backlog_a_grace_week():
    since = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    assert closes_on(since, WaitSettings()) is None
    on = WaitSettings(auto_close=True, auto_close_since=date(2026, 11, 9))
    assert closes_on(since, on) == date(2026, 11, 16)
    fresh = datetime(2026, 11, 8, 10, tzinfo=timezone.utc)
    assert closes_on(fresh, on) == date(2026, 12, 8)


def test_due_for_close_needs_the_date_and_only_when_due():
    today = date(2026, 11, 16)
    wait = JobWait(
        (
            _person(1, closes=today),
            _person(2, closes=date(2026, 11, 17)),
            _person(3, closes=None),
        ),
        False,
        WaitSettings(auto_close=True),
    )
    assert [p.candidate_id for p in due_for_close(wait, today)] == [1]


def test_payload_counts_only_people_needing_action_and_longest():
    wait = JobWait(
        (_person(1, workdays=73), _person(2, workdays=6), _person(3, workdays=2)),
        True,
        WaitSettings(),
    )
    payload = wait_payload(wait, today=date(2026, 11, 8))
    assert payload["count"] == 2
    assert payload["longest_workdays"] == 73
    assert payload["after_workdays"] == 5
    assert payload["nearest_close_on"] is None
    assert len(payload["people"]) == 3


def test_panel_state_sentences():
    at = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)
    assert panel_state_for(False, 3, at, None).label == "Panel wyłączony"
    assert panel_state_for(True, 0, None, None).label == "Panel: klient nie otworzył"
    assert panel_state_for(True, 3, at, None).label == (
        "Panel: otwarty 3× · ostatnio 05.11 · bez decyzji"
    )
    assert panel_state_for(True, 3, at, ("interview", [], at)).label == (
        "Panel: klient chce rozmowy 05.11"
    )
    assert panel_state_for(True, 3, at, ("not_fit", ["Brak Kafki"], at)).label == (
        "Panel: nie pasuje: Brak Kafki"
    )


def test_reminder_never_invents_a_link():
    subject, body = reminder_text(
        job_title="Java Dev", people=[_person()], panel_url=None, sender_name="Ewa"
    )
    assert subject == "Prośba o informację zwrotną: Java Dev"
    assert "Anna Nowak, CV przesłane 20.10.2026" in body
    assert "/k/" not in body
    assert body.endswith("Pozdrawiam,\nEwa")


def test_reminder_with_panel_link():
    _, body = reminder_text(
        job_title="Java Dev",
        people=[_person()],
        panel_url="https://nexus.example/k/abc",
        sender_name="Ewa",
    )
    assert "https://nexus.example/k/abc" in body


def test_reminder_does_not_send_anything():
    source = open(client_wait.__file__, encoding="utf-8").read()
    for marker in ("send_mail", "send_email", "smtp", "email_outbox"):
        assert marker not in source


async def _age(job_id: int, candidate_id: int, days: int) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(CandidateStage).where(
                CandidateStage.job_id == job_id,
                CandidateStage.candidate_id == candidate_id,
            )
        )
        moment = datetime.now(timezone.utc) - timedelta(days=days)
        for row in rows.all():
            row.moved_at = moment
        job = await db.get(Job, job_id)
        job.cycle_started_at = None
        await db.commit()


async def _recruiter_headers(app_client: AsyncClient) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal

    suffix = uuid.uuid4().hex[:8]
    email = f"wait-recruiter-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Wait Recruiter",
                role=UserRole.recruiter,
                is_active=True,
                email_verified=True,
                profile_completed=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _job_with_waiting(
    app_client: AsyncClient, headers: dict[str, str], days: int = 20
) -> tuple[int, int]:
    job_id = await _create_draft_job(
        app_client, headers, f"pytest-wait-{uuid.uuid4().hex[:6]}"
    )
    candidate_id = await _seed_candidate_in_job(job_id, "new", "cv_sent")
    await _age(job_id, candidate_id, days)
    return job_id, candidate_id


@pytest.mark.asyncio
async def test_get_lists_people_over_threshold(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id, candidate_id = await _job_with_waiting(app_client, app_auth_headers)
    fresh = await _seed_candidate_in_job(job_id, "new", "cv_sent")
    response = await app_client.get(
        f"/api/client-wait/jobs/{job_id}", headers=app_auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    assert body["longest_workdays"] > 5
    assert body["panel_enabled"] is False
    by_id = {p["candidate_id"]: p for p in body["people"]}
    assert by_id[candidate_id]["needs_action"] is True
    assert by_id[candidate_id]["panel_label"] == "Panel wyłączony"
    assert by_id[fresh]["needs_action"] is False


@pytest.mark.asyncio
async def test_reminder_writes_audit_and_refuses_when_nobody_waits(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id, _ = await _job_with_waiting(app_client, app_auth_headers)
    with patch("app.services.client_wait.logger"):
        ok = await app_client.post(
            f"/api/client-wait/jobs/{job_id}/reminder",
            json={},
            headers=app_auth_headers,
        )
    assert ok.status_code == 200, ok.text
    assert "Prośba o informację zwrotną" in ok.json()["subject"]
    assert ok.json()["panel_url"] is None

    empty = await _create_draft_job(
        app_client, app_auth_headers, f"pytest-wait-empty-{uuid.uuid4().hex[:6]}"
    )
    refused = await app_client.post(
        f"/api/client-wait/jobs/{empty}/reminder",
        json={},
        headers=app_auth_headers,
    )
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_responded_resets_the_clock_and_rejects_strangers(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id, candidate_id = await _job_with_waiting(app_client, app_auth_headers)
    done = await app_client.post(
        f"/api/client-wait/jobs/{job_id}/candidates/{candidate_id}/responded",
        headers=app_auth_headers,
    )
    assert done.status_code == 200, done.text
    body = (
        await app_client.get(
            f"/api/client-wait/jobs/{job_id}", headers=app_auth_headers
        )
    ).json()
    assert body["count"] == 0

    stranger = await app_client.post(
        f"/api/client-wait/jobs/{job_id}/candidates/999999999/responded",
        headers=app_auth_headers,
    )
    assert stranger.status_code == 404


def _board_card(view: dict[str, Any], candidate_id: int) -> dict[str, Any]:
    return next(
        item
        for column in view["columns"]
        for item in column["items"]
        if item["candidate_id"] == candidate_id
    )


@pytest.mark.asyncio
async def test_board_card_carries_silence_until_client_responded(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id, candidate_id = await _job_with_waiting(app_client, app_auth_headers)
    board = await app_client.get(
        f"/api/pipeline/kanban/{job_id}", headers=app_auth_headers
    )
    assert board.status_code == 200, board.text
    card = _board_card(board.json(), candidate_id)
    assert card["client_silent_workdays"] > 5
    # Jedna liczba na karcie: wiersz ruchu i dymek „Klient milczy”.
    assert card["waiting_workdays"] == card["client_silent_workdays"]

    await app_client.post(
        f"/api/client-wait/jobs/{job_id}/candidates/{candidate_id}/responded",
        headers=app_auth_headers,
    )
    after = await app_client.get(
        f"/api/pipeline/kanban/{job_id}", headers=app_auth_headers
    )
    card = _board_card(after.json(), candidate_id)
    assert card["client_silent_workdays"] is None
    # „Klient odpowiedział” zeruje zegar też w wierszu ruchu.
    assert card["waiting_workdays"] == 0


@pytest.mark.asyncio
async def test_board_card_has_no_silence_within_five_workdays(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id, candidate_id = await _job_with_waiting(app_client, app_auth_headers, days=1)
    board = await app_client.get(
        f"/api/pipeline/kanban/{job_id}", headers=app_auth_headers
    )
    assert _board_card(board.json(), candidate_id)["client_silent_workdays"] is None


@pytest.mark.asyncio
async def test_broken_silence_query_does_not_take_the_board_down(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id, candidate_id = await _job_with_waiting(app_client, app_auth_headers)
    with patch.object(client_wait, "client_clocks", side_effect=RuntimeError("awaria")):
        board = await app_client.get(
            f"/api/pipeline/kanban/{job_id}", headers=app_auth_headers
        )
    assert board.status_code == 200, board.text
    assert _board_card(board.json(), candidate_id)["client_silent_workdays"] is None


@pytest.mark.asyncio
async def test_recruiter_without_manage_is_refused(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    job_id, _ = await _job_with_waiting(app_client, app_auth_headers)
    response = await app_client.get(
        f"/api/client-wait/jobs/{job_id}",
        headers=await _recruiter_headers(app_client),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_settings_only_for_head_of_recruitment(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    refused = await app_client.put(
        "/api/client-wait/settings",
        json={"auto_close": True},
        headers=await _recruiter_headers(app_client),
    )
    assert refused.status_code == 403
    allowed = await app_client.put(
        "/api/client-wait/settings",
        json={"auto_close": False},
        headers=app_auth_headers,
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["auto_close"] is False


@pytest.mark.asyncio
async def test_auto_close_does_nothing_without_the_switch(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.core.database import AsyncSessionLocal

    job_id, candidate_id = await _job_with_waiting(
        app_client, app_auth_headers, days=60
    )
    async with AsyncSessionLocal() as db:
        await client_wait.write_settings(db, False, user_id=None)
        await db.commit()
        result = await client_wait.run_auto_close(db)
    assert result == {"closed": 0, "skipped": 0}
    latest: Any = await _stage(job_id, candidate_id)
    assert latest == ("cv_sent", None)


async def _stage(job_id: int, candidate_id: int) -> tuple[str, Any]:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.job_id == job_id,
                CandidateStage.candidate_id == candidate_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
    return getattr(row.stage, "value", row.stage), row.ended_by


@pytest.mark.asyncio
async def test_auto_close_ends_cv_sent_as_client_silent_after_grace(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.core.database import AsyncSessionLocal

    job_id, candidate_id = await _job_with_waiting(
        app_client, app_auth_headers, days=60
    )
    interview = await _seed_candidate_in_job(
        job_id, "new", "cv_sent", "client_interview"
    )
    await _age(job_id, interview, 60)
    today = date(2027, 1, 20)
    async with AsyncSessionLocal() as db:
        await client_wait.write_settings(
            db, True, user_id=None, today=date(2026, 11, 1)
        )
        await db.commit()
        try:
            await client_wait.run_auto_close(db, today=today)
        finally:
            await client_wait.write_settings(db, False, user_id=None)
            await db.commit()
    assert await _stage(job_id, candidate_id) == ("rejected", "client_silent")
    assert (await _stage(job_id, interview))[0] != "rejected"
