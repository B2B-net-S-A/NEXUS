"""Championi rekrutacji — osoby, kilku naraz, P1 wstrzymany (D1–D9, 15.10.2026).

Prawdziwy Postgres. Baza testowa jest wspólna i nieczyszczona, więc każdy test
zakłada własnego klienta, rekrutację i osoby, a asercje dotyczą tylko ich.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobPriority, JobStatus
from app.models.job_champion import JobChampion
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole

MOVE = "/api/pipeline/move"


async def _user(role: UserRole) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"champion-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Champion"),
            name=f"Champion {role.value} {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id, {
            "Authorization": f"Bearer {create_access_token(user.id, role.value)}"
        }


async def _world(
    *, headcount: int = 1, work_state: str = "searching", status=JobStatus.published
) -> dict:
    """Rekrutacja P1 z rekruterem i DL oraz czterema osobami na różnych etapach."""
    tag = uuid.uuid4().hex[:8]
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    dl_id, dl = await _user(UserRole.delivery_lead)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Champion client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Champion Developer {tag}",
            client_id=client.id,
            status=status,
            priority=JobPriority.urgent,
            work_state=work_state,
            headcount=headcount,
            recruiter_id=recruiter_id,
            delivery_lead_id=dl_id,
        )
        people = [
            Candidate(
                name="Champion",
                lastname=f"{label}-{tag}",
                email=f"champion-{label}-{tag}@example.com",
            )
            for label in ("sent", "interview", "fresh", "other")
        ]
        db.add_all([job, *people])
        await db.flush()
        sent, interview, fresh, other = people
        now = datetime.now(timezone.utc)
        for person, stage in (
            (sent, PipelineStage.cv_sent),
            (interview, PipelineStage.client_interview),
            (fresh, PipelineStage.screening),
            (other, PipelineStage.cv_sent),
        ):
            db.add(
                CandidateStage(
                    candidate_id=person.id,
                    job_id=job.id,
                    stage=PipelineStage.screening,
                    moved_at=now - timedelta(days=5),
                )
            )
            if stage != PipelineStage.screening:
                db.add(
                    CandidateStage(
                        candidate_id=person.id,
                        job_id=job.id,
                        stage=stage,
                        moved_at=now - timedelta(days=1),
                    )
                )
        await db.commit()
        return {
            "tag": tag,
            "job": job.id,
            "sent": sent.id,
            "interview": interview.id,
            "fresh": fresh.id,
            "other": other.id,
            "recruiter_id": recruiter_id,
            "recruiter": recruiter,
            "dl_id": dl_id,
            "dl": dl,
        }


async def _save(app_client: AsyncClient, headers: dict, job_id: int, ids: list[int]):
    return await app_client.put(
        f"/api/jobs/{job_id}/champions",
        json={"candidate_ids": ids},
        headers=headers,
    )


async def _bells(user_id: int, job_id: int, ntype: NotificationType) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count(Notification.id)).where(
                    Notification.user_id == user_id,
                    Notification.notification_type == ntype,
                    Notification.link == f"/jobs/{job_id}",
                )
            )
        )


async def _live(job_id: int) -> dict[int, JobChampion]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(select(JobChampion).where(JobChampion.job_id == job_id))
        ).all()
    return {row.candidate_id: row for row in rows}


async def _reject(app_client: AsyncClient, headers: dict, world: dict, cid: int):
    return await app_client.post(
        MOVE,
        json={
            "candidate_id": cid,
            "job_id": world["job"],
            "stage": "rejected",
            "rejection_reason": "klient wybrał inną osobę",
            "ended_by": "client",
            "send_rejection_email": False,
        },
        headers=headers,
    )


@pytest.mark.asyncio
async def test_only_delivery_lead_saves_and_recruiter_reads_without_choices(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    world = await _world()
    denied = await _save(app_client, world["recruiter"], world["job"], [world["sent"]])
    assert denied.status_code == 403, denied.text
    assert await _live(world["job"]) == {}

    ok = await _save(app_client, app_auth_headers, world["job"], [world["sent"]])
    assert ok.status_code == 200, ok.text

    read = await app_client.get(
        f"/api/jobs/{world['job']}/champions", headers=world["recruiter"]
    )
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["can_edit"] is False
    assert body["eligible"] == []
    assert [c["candidate_id"] for c in body["champions"]] == [world["sent"]]
    assert body["champions"][0]["column"] == "cv_sent"


@pytest.mark.asyncio
async def test_only_people_at_the_client_can_be_marked(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    world = await _world()
    view = await app_client.get(
        f"/api/jobs/{world['job']}/champions", headers=app_auth_headers
    )
    assert view.status_code == 200, view.text
    eligible = [p["candidate_id"] for p in view.json()["eligible"]]
    # Od najdalszej kolumny; „Screening” nie jest na liście (D4).
    assert eligible[0] == world["interview"]
    assert set(eligible) == {world["interview"], world["sent"], world["other"]}

    for refused_id in (world["fresh"], 999_999_999):
        refused = await _save(
            app_client, app_auth_headers, world["job"], [world["sent"], refused_id]
        )
        assert refused.status_code == 422, refused.text
        detail = refused.json()["detail"]
        assert detail["code"] == "champion_not_eligible"
        assert detail["candidate_ids"] == [refused_id]
    # Zero zapisu przy odmowie — także dla osoby, która była poprawna.
    assert await _live(world["job"]) == {}


@pytest.mark.asyncio
async def test_two_champions_stop_the_search_pause_p1_and_ring_the_team(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    world = await _world()
    saved = await _save(
        app_client, app_auth_headers, world["job"], [world["interview"], world["sent"]]
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["search_stopped"] is True
    assert body["changed"] is True
    assert [c["candidate_id"] for c in body["champions"]] == [
        world["interview"],
        world["sent"],
    ]

    detail = await app_client.get(f"/api/jobs/{world['job']}", headers=app_auth_headers)
    assert detail.status_code == 200, detail.text
    job = detail.json()
    assert job["request_status"] == "champion"
    assert job["priority_paused"] is True
    assert job["champion_seats"] == 1
    assert {c["candidate_id"] for c in job["champions"]} == {
        world["interview"],
        world["sent"],
    }

    board = await app_client.get(
        f"/api/pipeline/kanban/{world['job']}", headers=app_auth_headers
    )
    assert board.status_code == 200, board.text
    flags = {
        item["candidate_id"]: item["is_champion"]
        for column in board.json()["columns"]
        for item in column["items"]
    }
    assert flags[world["interview"]] is True
    assert flags[world["sent"]] is True
    assert flags[world["fresh"]] is False

    async def _listed(level: str) -> set[int]:
        listed = await app_client.get(
            "/api/jobs",
            params={"q": world["tag"], "priority_level": level},
            headers=app_auth_headers,
        )
        assert listed.status_code == 200, listed.text
        return {row["id"] for row in listed.json()["items"]}

    # D6: P1 z championem filtruje się jak „Bez priorytetu”.
    assert world["job"] not in await _listed("p1")
    assert world["job"] in await _listed("p2")
    row = next(
        r
        for r in (
            await app_client.get(
                "/api/jobs", params={"q": world["tag"]}, headers=app_auth_headers
            )
        ).json()["items"]
        if r["id"] == world["job"]
    )
    assert row["priority_paused"] is True
    assert len(row["champions"]) == 2

    # D8: rekruter i DL dostają dzwonek, autor zapisu — nie.
    assert (
        await _bells(
            world["recruiter_id"], world["job"], NotificationType.champions_changed
        )
        == 1
    )
    assert (
        await _bells(world["dl_id"], world["job"], NotificationType.champions_changed)
        == 1
    )

    # Druga zmiana tego samego dnia też dzwoni — dzwonki championów nie mają
    # dobowego klucza dedupu (przegląd 15.10.2026).
    swapped = await _save(app_client, app_auth_headers, world["job"], [world["other"]])
    assert swapped.status_code == 200, swapped.text
    assert (
        await _bells(
            world["recruiter_id"], world["job"], NotificationType.champions_changed
        )
        == 2
    )
    back = await _save(
        app_client, app_auth_headers, world["job"], [world["interview"], world["sent"]]
    )
    assert back.status_code == 200, back.text

    # Ten sam zapis drugi raz nic nie zmienia.
    again = await _save(
        app_client, app_auth_headers, world["job"], [world["interview"], world["sent"]]
    )
    assert again.status_code == 200, again.text
    assert again.json()["changed"] is False


@pytest.mark.asyncio
async def test_saving_wakes_a_silent_request_and_finished_refuses(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    silent = await _world(work_state="client_silent")
    saved = await _save(app_client, app_auth_headers, silent["job"], [silent["sent"]])
    assert saved.status_code == 200, saved.text
    assert saved.json()["work_state_changed"] is True
    assert saved.json()["work_state"] == "searching"
    assert saved.json()["search_stopped"] is True

    finished = await _world(work_state="finished")
    refused = await _save(
        app_client, app_auth_headers, finished["job"], [finished["sent"]]
    )
    assert refused.status_code == 409, refused.text
    assert await _live(finished["job"]) == {}


@pytest.mark.asyncio
async def test_two_seats_keep_searching_until_the_second_champion(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    world = await _world(headcount=2)
    one = await _save(app_client, app_auth_headers, world["job"], [world["sent"]])
    assert one.status_code == 200, one.text
    assert one.json()["search_stopped"] is False
    assert one.json()["seats"] == 2
    detail = await app_client.get(f"/api/jobs/{world['job']}", headers=app_auth_headers)
    assert detail.json()["request_status"] == "searching"
    assert detail.json()["priority_paused"] is False

    two = await _save(
        app_client, app_auth_headers, world["job"], [world["sent"], world["other"]]
    )
    assert two.status_code == 200, two.text
    assert two.json()["search_stopped"] is True


@pytest.mark.asyncio
async def test_rejecting_champions_clears_them_and_the_last_one_resumes_search(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    world = await _world()
    saved = await _save(
        app_client, app_auth_headers, world["job"], [world["sent"], world["interview"]]
    )
    assert saved.status_code == 200, saved.text

    first = await _reject(app_client, app_auth_headers, world, world["sent"])
    assert first.status_code == 200, first.text
    rows = await _live(world["job"])
    assert rows[world["sent"]].cleared_reason == "card_closed"
    assert rows[world["interview"]].cleared_at is None
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, world["job"])).champion_found_at is not None
    # Zostaje inny champion — bez dzwonka o powrocie do szukania.
    assert (
        await _bells(
            world["recruiter_id"],
            world["job"],
            NotificationType.champion_search_resumed,
        )
        == 0
    )

    last = await _reject(app_client, app_auth_headers, world, world["interview"])
    assert last.status_code == 200, last.text
    rows = await _live(world["job"])
    assert rows[world["interview"]].cleared_reason == "card_closed"
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job"])
        assert job.champion_found_at is None
    assert (
        await _bells(
            world["recruiter_id"],
            world["job"],
            NotificationType.champion_search_resumed,
        )
        == 1
    )
    # Odrzucenie zwykłej osoby nie rusza championów ani flagi.
    other = await _reject(app_client, app_auth_headers, world, world["fresh"])
    assert other.status_code == 200, other.text


@pytest.mark.asyncio
async def test_removing_the_champion_from_the_recruitment_clears_it(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    world = await _world()
    saved = await _save(app_client, app_auth_headers, world["job"], [world["sent"]])
    assert saved.status_code == 200, saved.text
    removed = await app_client.delete(
        f"/api/candidates/{world['sent']}/recruitments/{world['job']}",
        headers=app_auth_headers,
    )
    assert removed.status_code in (200, 204), removed.text
    rows = await _live(world["job"])
    assert rows[world["sent"]].cleared_reason == "removed_from_job"
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, world["job"])).champion_found_at is None


@pytest.mark.asyncio
async def test_old_flag_without_people_survives_hooks_until_cleared(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job"])
        job.champion_found_at = datetime.now(timezone.utc) - timedelta(days=3)
        await db.commit()

    view = await app_client.get(
        f"/api/jobs/{world['job']}/champions", headers=app_auth_headers
    )
    assert view.json()["legacy_flag"] is True

    # Odrzucenie osoby, która championem nie była, nie gasi starej flagi.
    rejected = await _reject(app_client, app_auth_headers, world, world["other"])
    assert rejected.status_code == 200, rejected.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, world["job"])).champion_found_at is not None

    # D1: „oznacz” bez osoby już nie istnieje; cofnięcie zostało.
    marked = await app_client.post(
        f"/api/jobs/{world['job']}/champion-found",
        json={"found": True},
        headers=app_auth_headers,
    )
    assert marked.status_code == 422, marked.text
    dropped = await app_client.post(
        f"/api/jobs/{world['job']}/champion-found",
        json={"found": False},
        headers=app_auth_headers,
    )
    assert dropped.status_code == 200, dropped.text
    assert dropped.json()["champion_found"] is False
    assert dropped.json()["changed"] is True
