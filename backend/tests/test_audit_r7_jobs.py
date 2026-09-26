"""Runda 7 audytu (26.09.2026) — lista ``/jobs`` i usuwanie rekrutacji.

* R7-N8-1 — zakres „Moje” = moje NIEZAMKNIĘTE (decyzja Artura 26.09.2026):
  liczniki ``quick-counts`` zakresu „Moje” nie liczą archiwum.
* R7-N8-2 — „Kto pracuje / Nikt nie pracuje” widzi prowadzącego
  (``jobs.recruiter_id``), nie tylko przypisania z puli przydziału.
* R7-N8-3 — zamkniętej rekrutacji nie da się usunąć (mianownik hit ratio
  Ligi DL), a usunięcie trafia do Historii zdarzeń.
* R7-N8-4 — rekrutacji z Traffita nie da się usunąć (wróciłaby z importem).
* R7-N8-5 — spotkanie w kalendarzu = 409, nie 500.
* R7-X1-5 — HM zdejmowany tylko przy ZMIANIE klienta, nie przy samym kluczu.

Rejestr jest wspólny dla bazy testowej: listy zawężamy unikalnym tokenem
w tytule (``q=``), liczniki porównujemy przed i po zasianiu wiersza.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today


# ── Bez bazy: kształt klauzul ────────────────────────────────────────────────


def test_mine_scope_clause_excludes_closed_jobs() -> None:
    from types import SimpleNamespace

    from sqlalchemy.dialects import postgresql

    from app.api.jobs import jobs_mine_scope_clause

    user = SimpleNamespace(id=7, roles=["recruiter"], role="recruiter")
    sql = str(
        jobs_mine_scope_clause(user).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "jobs.status !=" in sql or "jobs.status <>" in sql, sql


def test_nobody_working_clause_reads_the_job_owner() -> None:
    from app.api.jobs import jobs_nobody_working_clause, jobs_worked_by_clause

    assert "jobs.recruiter_id" in str(jobs_nobody_working_clause())
    assert "jobs.recruiter_id" in str(jobs_worked_by_clause([1]))


# ── Pomocnicy ────────────────────────────────────────────────────────────────


async def _me_id(app_client: AsyncClient, headers: dict) -> int:
    response = await app_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _seed_client() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(name=f"R7Jobs-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.commit()
        return client.id


async def _seed_job(token: str = "R7", **fields) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    client_id = fields.pop("client_id", None) or await _seed_client()
    status = JobStatus(fields.pop("status", "published"))
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"{token}-{uuid.uuid4().hex[:6]}",
            status=status,
            client_id=client_id,
            **fields,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _seed_user(*, active: bool = True) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        marker = uuid.uuid4().hex[:10]
        user = User(
            email=f"r7-jobs-{marker}@example.com",
            name=f"R7 Jobs {marker}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=active,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _ids(app_client: AsyncClient, headers: dict, query: str) -> set[int]:
    response = await app_client.get(f"/api/jobs?page_size=100&{query}", headers=headers)
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["items"]}


async def _quick_counts(app_client: AsyncClient, headers: dict, overdue_to) -> dict:
    response = await app_client.get(
        f"/api/jobs/quick-counts?overdue_to={overdue_to.isoformat()}", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _critical_events(job_id: int) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.critical_event import CriticalEvent

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(CriticalEvent.event_type, CriticalEvent.outcome).where(
                CriticalEvent.entity_type == "job", CriticalEvent.entity_id == job_id
            )
        )
        return [(row.event_type, row.outcome) for row in rows]


# ── R7-N8-1 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mine_scope_counts_skip_my_closed_jobs(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    me = await _me_id(app_client, app_auth_headers)
    yesterday = business_today() - timedelta(days=1)
    token = f"R7Mine{uuid.uuid4().hex[:8]}"
    open_job = await _seed_job(token, recruiter_id=me, deadline=yesterday)

    before = await _quick_counts(app_client, app_auth_headers, yesterday)
    closed_job = await _seed_job(
        token, status="closed", recruiter_id=me, deadline=yesterday
    )
    after = await _quick_counts(app_client, app_auth_headers, yesterday)

    # Moja zamknięta rekrutacja z minionym terminem nie jest „Po terminie”
    # w zakresie „Moje” ani nie podbija licznika zakresu.
    assert after["mine"] == before["mine"]
    assert after["attention_mine"] == before["attention_mine"]
    assert after["request_stage_mine"] == before["request_stage_mine"]
    # Lista zakresu „Moje” (mine + open_only) jej nie pokazuje, „Wszystkie” tak.
    assert await _ids(
        app_client, app_auth_headers, f"q={token}&mine=true&open_only=true"
    ) == {open_job}
    assert await _ids(app_client, app_auth_headers, f"q={token}") == {
        open_job,
        closed_job,
    }


# ── R7-N8-2 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_owner_counts_as_working_outside_the_allocation_pool(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job_work_assignment import JobWorkAssignment

    me = await _me_id(app_client, app_auth_headers)
    dead = await _seed_user(active=False)
    token = f"R7Work{uuid.uuid4().hex[:8]}"
    owned = await _seed_job(token, recruiter_id=me, work_state="to_review")
    dead_owner = await _seed_job(token, recruiter_id=dead, work_state="to_review")
    released = await _seed_job(token, recruiter_id=me, work_state="searching")
    nobody = await _seed_job(token, work_state="to_review")
    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=released,
                user_id=me,
                role="recruiter",
                source="owner",
                state="released",
                release_reason="manual",
                released_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    assert await _ids(app_client, app_auth_headers, f"q={token}&worked_by={me}") == {
        owned
    }
    assert await _ids(
        app_client, app_auth_headers, f"q={token}&nobody_working=true"
    ) == {dead_owner, released, nobody}
    assert await _ids(
        app_client, app_auth_headers, f"q={token}&nobody_working=false"
    ) == {owned}


# ── R7-N8-3 / N8-4 / N8-5: DELETE ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_closed_job_cannot_be_deleted_and_the_refusal_is_logged(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id = await _seed_job(status="closed", closed_at=datetime.now(timezone.utc))

    resp = await app_client.delete(f"/api/jobs/{job_id}", headers=app_auth_headers)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "job_is_closed"
    assert ("job.delete", "blocked") in await _critical_events(job_id)


@pytest.mark.asyncio
async def test_deleted_job_lands_in_event_history(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id = await _seed_job()

    resp = await app_client.delete(f"/api/jobs/{job_id}", headers=app_auth_headers)

    assert resp.status_code == 204, resp.text
    assert ("job.delete", "executed") in await _critical_events(job_id)


@pytest.mark.asyncio
async def test_traffit_job_cannot_be_deleted(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id = await _seed_job(
        external_source="traffit", external_id=f"r7-{uuid.uuid4().hex[:10]}"
    )

    resp = await app_client.delete(f"/api/jobs/{job_id}", headers=app_auth_headers)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "job_from_traffit"


@pytest.mark.asyncio
async def test_job_with_calendar_event_returns_409_not_500(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.calendar_event import CalendarEvent, EventType

    job_id = await _seed_job()
    async with AsyncSessionLocal() as db:
        db.add(
            CalendarEvent(
                title="R7 spotkanie",
                event_type=EventType.meeting,
                start_time=datetime.now(timezone.utc) + timedelta(days=1),
                job_id=job_id,
            )
        )
        await db.commit()

    resp = await app_client.delete(f"/api/jobs/{job_id}", headers=app_auth_headers)

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "job_has_calendar_events"
    assert detail["calendar_event_rows"] == 1


# ── R7-X1-5 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_resending_the_same_client_keeps_the_hiring_manager(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.contact import Contact
    from app.models.job import Job

    other_client = await _seed_client()
    job_client = await _seed_client()
    async with AsyncSessionLocal() as db:
        contact = Contact(client_id=other_client, name="R7 HM")
        db.add(contact)
        await db.commit()
        contact_id = contact.id
    # Stan po przeniesieniu rekrutacji między klientami bez kontaktów.
    job_id = await _seed_job(client_id=job_client, hiring_manager_contact_id=contact_id)

    resp = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"client_id": job_client, "title": "R7 nowy tytuł"},
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.hiring_manager_contact_id == contact_id
