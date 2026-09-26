"""Runda 8 audytu (ALLOC): nieaktywne konto = brak osoby w przydziale,
follow-upach i powiadomieniach; tryb ``off``; champion; nazwa robocza.

Baza testowa jest wspólna i nieczyszczona — testy z bazą zakładają własne
rekrutacje i osoby i asertują wyłącznie po nich.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.interview_feedback import InterestLevel, InterviewDecision
from app.models.user import User, UserRole

# ── R8-X1-1: werdykt klienta — adresat bez nieaktywnych (bez bazy) ──────────


def _feedback(**kw):
    base = dict(
        id=1,
        job_id=10,
        candidate_id=20,
        author_id=7,
        decision=InterviewDecision.advance,
        interest_level=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _db_with_job(job):
    async def get(model, key):
        return job if model.__name__ == "Job" else None

    return SimpleNamespace(get=get)


@pytest.mark.asyncio
async def test_feedback_goes_to_the_operational_recipient(monkeypatch) -> None:
    from app.services import interview_feedback_actions as actions

    job = SimpleNamespace(id=10, recruiter_id=3, title="Java", delivery_lead_id=None)
    seen = {}

    async def recipient(_db, owners):
        seen["owners"] = list(owners)
        return 7  # prowadzący (3) nieaktywny → autor feedbacku

    emit = AsyncMock(return_value=object())
    monkeypatch.setattr(actions, "_operational_recipient", recipient)
    monkeypatch.setattr(actions, "_delivery_lead_targets", AsyncMock(return_value=[]))
    monkeypatch.setattr(actions, "emit", emit)
    assert (
        await actions.apply_post_feedback_actions(_db_with_job(job), _feedback()) == 1
    )
    assert seen["owners"] == [3, 7]
    assert emit.await_args.kwargs["user_id"] == 7


@pytest.mark.asyncio
async def test_feedback_without_anyone_falls_back_to_delivery_lead(monkeypatch) -> None:
    from app.services import interview_feedback_actions as actions

    job = SimpleNamespace(id=10, recruiter_id=3, title="Java", delivery_lead_id=5)
    emit = AsyncMock(return_value=object())
    monkeypatch.setattr(actions, "_operational_recipient", AsyncMock(return_value=None))
    monkeypatch.setattr(
        actions, "_delivery_lead_targets", AsyncMock(return_value=[5, 6])
    )
    monkeypatch.setattr(actions, "emit", emit)
    sent = await actions.apply_post_feedback_actions(
        _db_with_job(job),
        _feedback(decision=InterviewDecision.reject, interest_level=InterestLevel.dead),
    )
    assert sent == 4  # dwie akcje × dwóch adresatów
    assert {c.kwargs["user_id"] for c in emit.await_args_list} == {5, 6}


@pytest.mark.asyncio
async def test_feedback_without_action_does_not_look_for_recipients(
    monkeypatch,
) -> None:
    from app.services import interview_feedback_actions as actions

    lookup = AsyncMock(return_value=7)
    monkeypatch.setattr(actions, "_operational_recipient", lookup)
    assert (
        await actions.apply_post_feedback_actions(
            SimpleNamespace(), _feedback(decision=None, interest_level=None)
        )
        == 0
    )
    lookup.assert_not_awaited()


# ── R8-X1-6: „podobny request” — adresaci (bez bazy) ─────────────────────────


@pytest.mark.asyncio
async def test_similar_job_recipients_skip_the_dead_and_tac(monkeypatch) -> None:
    from app.services import similar_job_notify as notify

    job = SimpleNamespace(recruiter_id=1, created_by=2, tac_id=9, delivery_lead_id=5)
    active = {2: 2}

    async def recipient(_db, owners):
        return active.get(owners[0])

    monkeypatch.setattr(notify, "_operational_recipient", recipient)
    monkeypatch.setattr(notify, "_delivery_lead_targets", AsyncMock(return_value=[5]))
    assert await notify._recipients(SimpleNamespace(), job) == [2]
    active.clear()
    assert await notify._recipients(SimpleNamespace(), job) == [5]


# ── Testy z bazą ─────────────────────────────────────────────────────────────


async def _seed_user(*, active: bool = True, role: UserRole = UserRole.recruiter):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        marker = uuid.uuid4().hex[:10]
        user = User(
            email=f"r8-alloc-{marker}@example.com",
            name=f"R8 Alloc {marker}",
            role=role,
            roles=[role.value],
            is_active=active,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _seed_job(**fields) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"r8-alloc-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=fields.pop("title", f"R8 Alloc {uuid.uuid4().hex[:6]}"),
            client_id=client.id,
            status=JobStatus.published,
            work_state=fields.pop("work_state", "searching"),
            **fields,
        )
        db.add(job)
        await db.commit()
        return job.id


@pytest.mark.asyncio
async def test_db_dead_owner_counts_as_empty(app_client: AsyncClient) -> None:
    """R8-N7-2: rekruter automatu zostaje prowadzącym zamiast martwego konta."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.request_allocation import _set_owner_if_empty

    dead = await _seed_user(active=False)
    alive = await _seed_user()
    other = await _seed_user()
    job_id = await _seed_job(recruiter_id=dead)
    async with AsyncSessionLocal() as db:
        await _set_owner_if_empty(db, job_id, alive)
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).recruiter_id == alive
        # Żywego prowadzącego nie nadpisujemy.
        await _set_owner_if_empty(db, job_id, other)
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).recruiter_id == alive


@pytest.mark.asyncio
async def test_db_owner_set_by_the_automat_is_adopted_as_automat(
    app_client: AsyncClient,
) -> None:
    """R8-N7-3: po powrocie requestu do puli prowadzący z automatu wraca jako
    wiersz ``auto`` (zwalniany za urlop), a z Traffita/ręki — jako ``owner``."""
    from app.core.database import AsyncSessionLocal
    from app.models.job_work_assignment import JobWorkAssignment
    from app.services.request_allocation import _last_assignment_was_auto

    auto_person = await _seed_user()
    owner_person = await _seed_user()
    auto_job = await _seed_job(recruiter_id=auto_person)
    owner_job = await _seed_job(recruiter_id=owner_person)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        for job_id, user_id, source in (
            (auto_job, auto_person, "auto"),
            (owner_job, owner_person, "owner"),
        ):
            db.add(
                JobWorkAssignment(
                    job_id=job_id,
                    user_id=user_id,
                    role="recruiter",
                    source=source,
                    state="released",
                    assigned_at=now - timedelta(days=3),
                    released_at=now - timedelta(days=1),
                    release_reason="client_silent",
                )
            )
        await db.commit()
    async with AsyncSessionLocal() as db:
        found = await _last_assignment_was_auto(
            db, [(auto_job, auto_person), (owner_job, owner_person)]
        )
    assert found == frozenset({(auto_job, auto_person)})


@pytest.mark.asyncio
async def test_db_removing_the_champion_brings_manual_people_back(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """R8-N7-5: zdjęcie „Mamy championa” przywraca ręcznie dodanych i
    stempluje zmianę stanu requestu."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.job_work_assignment import JobWorkAssignment

    person = await _seed_user()
    job_id = await _seed_job()
    added = await app_client.post(
        f"/api/request-board/jobs/{job_id}/people",
        json={"user_id": person, "role": "recruiter"},
        headers=app_auth_headers,
    )
    assert added.status_code == 200, added.text
    found = await app_client.post(
        f"/api/jobs/{job_id}/champion-found",
        json={"found": True},
        headers=app_auth_headers,
    )
    assert found.status_code == 200, found.text
    # Przebieg automatu zwalnia wszystkich przy championie — tu wprost.
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobWorkAssignment).where(
                JobWorkAssignment.job_id == job_id,
                JobWorkAssignment.state != "released",
            )
        )
        row.state = "released"
        row.release_reason = "champion"
        row.released_at = datetime.now(timezone.utc)
        stamped = (await db.get(Job, job_id)).work_state_changed_at
        await db.commit()
    assert stamped is not None

    dropped = await app_client.post(
        f"/api/jobs/{job_id}/champion-found",
        json={"found": False},
        headers=app_auth_headers,
    )
    assert dropped.status_code == 200, dropped.text
    async with AsyncSessionLocal() as db:
        live = (
            await db.scalars(
                select(JobWorkAssignment).where(
                    JobWorkAssignment.job_id == job_id,
                    JobWorkAssignment.state != "released",
                )
            )
        ).all()
        job = await db.get(Job, job_id)
    assert [(r.user_id, r.source) for r in live] == [(person, "manual")]
    assert job.work_state_changed_at > stamped


@pytest.mark.asyncio
async def test_db_board_and_review_use_the_working_title(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """R8-N7-6: ekrany wewnętrzne pokazują nazwę roboczą i po niej szukają."""
    marker = uuid.uuid4().hex[:6]
    job_id = await _seed_job(
        title=f"ZOB-{marker}",
        working_title=f"Java Spring {marker}",
        work_state="to_review",
    )
    review = await app_client.get(
        "/api/request-work-states",
        params={"tab": "to_review", "q": f"Spring {marker}"},
        headers=app_auth_headers,
    )
    assert review.status_code == 200, review.text
    rows = {r["job_id"]: r for r in review.json()["rows"]}
    assert rows[job_id]["title"] == f"Java Spring {marker}"

    searching = await _seed_job(
        title=f"ZOB-{marker}-b", working_title=f"Kotlin {marker}"
    )
    board = await app_client.get("/api/request-board", headers=app_auth_headers)
    assert board.status_code == 200, board.text
    requests = {r["job_id"]: r for r in board.json()["requests"]}
    assert requests[searching]["title"] == f"Kotlin {marker}"


@pytest.mark.asyncio
async def test_db_recruiter_id_is_validated_only_when_it_changes(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """R8-X1-3: nieistniejący prowadzący = 404 (nie 500), nieaktywny = 400,
    a niezmieniony (także nieaktywny) przechodzi."""
    dead = await _seed_user(active=False)
    job_id = await _seed_job(recruiter_id=dead)

    missing = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"recruiter_id": 2_000_000_000},
        headers=app_auth_headers,
    )
    assert missing.status_code == 404, missing.text

    other_dead = await _seed_user(active=False)
    inactive = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"recruiter_id": other_dead},
        headers=app_auth_headers,
    )
    assert inactive.status_code == 400, inactive.text
    assert "nieaktywne" in inactive.json()["detail"]

    unchanged = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"recruiter_id": dead},
        headers=app_auth_headers,
    )
    assert unchanged.status_code == 200, unchanged.text

    alive = await _seed_user()
    ok = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"recruiter_id": alive},
        headers=app_auth_headers,
    )
    assert ok.status_code == 200, ok.text
