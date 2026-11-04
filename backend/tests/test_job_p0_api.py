"""P0 na rekrutacji (27.10.2026) — trasy na prawdziwym Postgresie.

Baza testowa jest wspólna i nieczyszczona, więc każdy test zakłada własnego
klienta, rekrutację i osoby, a asercje dotyczą tylko ich.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.activity import Activity
from app.models.client import Client
from app.models.job import Job, JobPriority, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole


async def _user(role: UserRole) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"p0-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!P0"),
            name=f"P0 {role.value} {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id, {
            "Authorization": f"Bearer {create_access_token(user.id, role.value)}"
        }


async def _world(priority: JobPriority = JobPriority.medium) -> dict:
    tag = uuid.uuid4().hex[:8]
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    dl_id, dl = await _user(UserRole.delivery_lead)
    hor_id, hor = await _user(UserRole.head_of_recruitment)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"P0 client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"P0 Developer {tag}",
            client_id=client.id,
            status=JobStatus.published,
            priority=priority,
            work_state="searching",
            recruiter_id=recruiter_id,
            delivery_lead_id=dl_id,
        )
        db.add(job)
        await db.commit()
        return {
            "job": job.id,
            "recruiter_id": recruiter_id,
            "recruiter": recruiter,
            "dl_id": dl_id,
            "dl": dl,
            "hor_id": hor_id,
            "hor": hor,
        }


async def _set(app_client: AsyncClient, headers: dict, job_id: int, **body):
    return await app_client.post(
        f"/api/jobs/{job_id}/p0",
        json={"reason": "Klient chce 2 CV do jutra 12:00", **body},
        headers=headers,
    )


@pytest.mark.asyncio
async def test_delivery_lead_and_recruiter_cannot_set_p0(app_client: AsyncClient):
    world = await _world()
    for who in ("dl", "recruiter"):
        denied = await _set(app_client, world[who], world["job"])
        assert denied.status_code == 403, denied.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job"])
        assert job.p0_until is None


@pytest.mark.asyncio
async def test_head_of_recruitment_sets_p0_and_team_gets_bell(
    app_client: AsyncClient,
):
    world = await _world()
    resp = await _set(app_client, world["hor"], world["job"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_p0"] is True
    assert body["p0_reason"] == "Klient chce 2 CV do jutra 12:00"
    assert body["p0_set_by_name"].startswith("P0 head_of_recruitment")
    until = datetime.fromisoformat(body["p0_until"])
    assert (
        timedelta(hours=23) < until - datetime.now(timezone.utc) <= timedelta(hours=24)
    )
    async with AsyncSessionLocal() as db:
        bells = set(
            (
                await db.scalars(
                    select(Notification.user_id).where(
                        Notification.notification_type == NotificationType.job_p0_set,
                        Notification.related_entity_id == world["job"],
                    )
                )
            ).all()
        )
        # Zespół: rekruter i DL; bez osoby, która ustawiła.
        assert bells == {world["recruiter_id"], world["dl_id"]}
        job = await db.get(Job, world["job"])
        # Priorytet zostaje — P0 to nakładka z terminem.
        assert job.priority == JobPriority.medium


@pytest.mark.asyncio
async def test_p0_is_visible_to_the_team_and_first_on_the_list(
    app_client: AsyncClient,
):
    world = await _world()
    assert (await _set(app_client, world["hor"], world["job"])).status_code == 200

    listed = await app_client.get("/api/p0-jobs", headers=world["recruiter"])
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["can_set"] is False
    mine = [item for item in payload["items"] if item["job_id"] == world["job"]]
    assert len(mine) == 1 and mine[0]["recruiters"]

    detail = await app_client.get(f"/api/jobs/{world['job']}", headers=world["hor"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["is_p0"] is True
    assert detail.json()["can_set_p0"] is True

    jobs = await app_client.get(
        "/api/jobs",
        params={"status": "published", "sort": "deadline", "page_size": 5},
        headers=world["hor"],
    )
    assert jobs.status_code == 200, jobs.text
    assert jobs.json()["items"][0]["is_p0"] is True


@pytest.mark.asyncio
async def test_extend_adds_a_day_and_clear_removes_p0(app_client: AsyncClient):
    world = await _world()
    first = (await _set(app_client, world["hor"], world["job"])).json()
    extended = await app_client.post(
        f"/api/jobs/{world['job']}/p0/extend", headers=world["hor"]
    )
    assert extended.status_code == 200, extended.text
    delta = datetime.fromisoformat(
        extended.json()["p0_until"]
    ) - datetime.fromisoformat(first["p0_until"])
    assert delta == timedelta(hours=24)

    cleared = await app_client.delete(
        f"/api/jobs/{world['job']}/p0", headers=world["hor"]
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["is_p0"] is False

    again = await app_client.post(
        f"/api/jobs/{world['job']}/p0/extend", headers=world["hor"]
    )
    assert again.status_code == 409
    async with AsyncSessionLocal() as db:
        actions = (
            await db.scalars(
                select(Activity.action)
                .where(
                    Activity.entity_type == "job", Activity.entity_id == world["job"]
                )
                .order_by(Activity.id)
            )
        ).all()
        assert [a for a in actions if a.startswith("p0_")] == [
            "p0_set",
            "p0_extended",
            "p0_cleared",
        ]


@pytest.mark.asyncio
async def test_missing_reason_and_closed_job_are_refused(app_client: AsyncClient):
    world = await _world()
    blank = await app_client.post(
        f"/api/jobs/{world['job']}/p0", json={"reason": "  "}, headers=world["hor"]
    )
    assert blank.status_code == 422
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job"])
        job.status = JobStatus.closed
        await db.commit()
    closed = await _set(app_client, world["hor"], world["job"])
    assert closed.status_code == 409


# ── 28.10.2026: P0 widzi zespół rekrutacji, DL prosi, HoR zatwierdza ─────────


def _listed(payload: dict, job_id: int) -> bool:
    return any(item["job_id"] == job_id for item in payload["items"])


@pytest.mark.asyncio
async def test_p0_on_dashboard_only_for_team_hor_and_admin(app_client: AsyncClient):
    world = await _world()
    _, outsider = await _user(UserRole.recruiter)
    _, other_dl = await _user(UserRole.delivery_lead)
    assert (await _set(app_client, world["hor"], world["job"])).status_code == 200

    for who, expected in (
        (world["recruiter"], True),
        (world["dl"], True),
        (world["hor"], True),
        (outsider, False),
        (other_dl, False),
    ):
        listed = await app_client.get("/api/p0-jobs", headers=who)
        assert listed.status_code == 200, listed.text
        assert _listed(listed.json(), world["job"]) is expected

    # Lista rekrutacji bez zmian: osoba spoza zespołu dalej widzi P0 na górze.
    jobs = await app_client.get(
        "/api/jobs",
        params={"status": "published", "sort": "deadline", "page_size": 5},
        headers=outsider,
    )
    assert jobs.status_code == 200, jobs.text
    assert jobs.json()["items"][0]["is_p0"] is True


async def _request(app_client: AsyncClient, headers: dict, job_id: int, **body):
    return await app_client.post(
        f"/api/jobs/{job_id}/p0/request",
        json={"reason": "Klient zamyka listę w piątek", "duration": "48h", **body},
        headers=headers,
    )


@pytest.mark.asyncio
async def test_only_the_jobs_delivery_lead_requests_p0(app_client: AsyncClient):
    world = await _world()
    _, other_dl = await _user(UserRole.delivery_lead)
    for who in (world["recruiter"], other_dl):
        denied = await _request(app_client, who, world["job"])
        assert denied.status_code == 403, denied.text

    detail = await app_client.get(f"/api/jobs/{world['job']}", headers=world["dl"])
    assert detail.json()["can_request_p0"] is True
    assert detail.json()["can_set_p0"] is False


@pytest.mark.asyncio
async def test_dl_request_bells_hor_and_hor_approves(app_client: AsyncClient):
    world = await _world()
    asked = await _request(app_client, world["dl"], world["job"])
    assert asked.status_code == 200, asked.text
    assert asked.json()["p0_requested"] is True

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job"])
        assert job.p0_until is None  # prośba to jeszcze nie P0
        bells = set(
            (
                await db.scalars(
                    select(Notification.user_id).where(
                        Notification.notification_type
                        == NotificationType.job_p0_requested,
                        Notification.related_entity_id == world["job"],
                    )
                )
            ).all()
        )
        assert world["hor_id"] in bells
        assert world["dl_id"] not in bells

    for who in (world["hor"], world["dl"]):
        payload = (await app_client.get("/api/p0-jobs", headers=who)).json()
        mine = [r for r in payload["requests"] if r["job_id"] == world["job"]]
        assert len(mine) == 1 and mine[0]["duration"] == "48h"
    recruiter_view = (
        await app_client.get("/api/p0-jobs", headers=world["recruiter"])
    ).json()
    assert all(r["job_id"] != world["job"] for r in recruiter_view["requests"])

    # DL nie zatwierdza sam sobie.
    self_approve = await app_client.post(
        f"/api/jobs/{world['job']}/p0/request/approve", headers=world["dl"]
    )
    assert self_approve.status_code == 403

    approved = await app_client.post(
        f"/api/jobs/{world['job']}/p0/request/approve", headers=world["hor"]
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["is_p0"] is True
    assert body["p0_reason"] == "Klient zamyka listę w piątek"
    until = datetime.fromisoformat(body["p0_until"])
    assert until - datetime.now(timezone.utc) > timedelta(hours=47)

    again = await app_client.post(
        f"/api/jobs/{world['job']}/p0/request/approve", headers=world["hor"]
    )
    assert again.status_code == 409
    second = await _request(app_client, world["dl"], world["job"])
    assert second.status_code == 409  # już jest P0


@pytest.mark.asyncio
async def test_hor_rejects_request_and_no_p0_appears(app_client: AsyncClient):
    world = await _world()
    assert (await _request(app_client, world["dl"], world["job"])).status_code == 200
    rejected = await app_client.delete(
        f"/api/jobs/{world['job']}/p0/request", headers=world["hor"]
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["p0_requested"] is False
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job"])
        assert job.p0_until is None and job.p0_requested_at is None
        actions = (
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == "job", Activity.entity_id == world["job"]
                )
            )
        ).all()
        assert {"p0_requested", "p0_request_rejected"} <= set(actions)

    outsider_reject = await app_client.delete(
        f"/api/jobs/{world['job']}/p0/request", headers=world["recruiter"]
    )
    assert outsider_reject.status_code == 403
