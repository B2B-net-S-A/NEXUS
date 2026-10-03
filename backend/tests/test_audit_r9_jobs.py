"""Runda 9 audytu — rekrutacje (kod JOBS).

Testy bez bazy sprawdzają kształt klauzul i schematów; testy z ``app_client``
potrzebują Postgresa (CI). Rejestr rekrutacji jest wspólny dla całej bazy
testowej, więc listy zawężamy unikalnym tokenem w tytule (``q=``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.dialects import postgresql

# ── Bez bazy ─────────────────────────────────────────────────────────────────


def _sql(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_mine_clause_includes_active_work_assignments() -> None:
    """R9-N15-2: „Moje” widzi request przydzielony w ``job_work_assignments``.

    Od 02.10.2026 liczy się przypisanie AKTYWNE (``state = 'active'``) — do
    tej daty każde niezwolnione, czyli także propozycja automatu, która czeka
    na akceptację Head of Recruitment i pracą jeszcze nie jest.
    """
    from app.api.jobs import jobs_mine_clause, jobs_mine_scope_clause

    user = SimpleNamespace(id=7, roles=["recruiter"], role="recruiter")
    for clause in (jobs_mine_clause(user), jobs_mine_scope_clause(user)):
        sql = _sql(clause)
        assert "job_work_assignments.state = 'active'" in sql, sql
        assert "released" not in sql, sql


@pytest.mark.parametrize(
    "field,limit",
    [
        ("title", 255),
        ("location", 255),
        ("reference_number", 50),
        ("industry", 50),
        ("subcategory", 100),
        ("train_name", 128),
    ],
)
def test_job_schemas_reject_values_longer_than_the_column(field, limit) -> None:
    """R9-N15-5: za długi napis = 422 z walidacji, nie 500 z bazy."""
    from pydantic import ValidationError

    from app.schemas.job import JobCreate, JobUpdate

    base = {"title": "Java Developer", "client_id": 1}
    JobCreate(**{**base, field: "x" * limit})
    JobUpdate(**{field: "x" * limit})
    with pytest.raises(ValidationError):
        JobCreate(**{**base, field: "x" * (limit + 1)})
    with pytest.raises(ValidationError):
        JobUpdate(**{field: "x" * (limit + 1)})


# ── Pomocnicy (baza) ─────────────────────────────────────────────────────────


async def _me_id(app_client: AsyncClient, headers: dict) -> int:
    response = await app_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _seed_job(token: str, **fields) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"R9Jobs-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"{token}-{uuid.uuid4().hex[:4]}",
            status=fields.pop("status", JobStatus.published),
            client_id=client.id,
            **fields,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _assign(job_id: int, user_id: int, state: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job_work_assignment import JobWorkAssignment

    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=user_id,
                role="recruiter",
                source="manual",
                state=state,
                released_at=datetime.now(timezone.utc) if state == "released" else None,
            )
        )
        await db.commit()


async def _cleanup(job_ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.job_work_assignment import JobWorkAssignment

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(JobWorkAssignment).where(JobWorkAssignment.job_id.in_(job_ids))
        )
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.commit()


async def _ids(app_client: AsyncClient, headers: dict, query: str) -> set[int]:
    response = await app_client.get(f"/api/jobs?page_size=100&{query}", headers=headers)
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["items"]}


async def _quick_counts(app_client: AsyncClient, headers: dict) -> dict:
    response = await app_client.get("/api/jobs/quick-counts", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ── R9-N15-2 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mine_scope_lists_and_counts_live_assignments(
    app_client: AsyncClient, app_auth_headers: dict
):
    me = await _me_id(app_client, app_auth_headers)
    token = f"R9Mine{uuid.uuid4().hex[:8]}"
    before = await _quick_counts(app_client, app_auth_headers)
    live = await _seed_job(token)
    released = await _seed_job(token)
    await _assign(live, me, "active")
    await _assign(released, me, "released")
    try:
        mine = await _ids(
            app_client, app_auth_headers, f"q={token}&mine=true&open_only=true"
        )
        assert live in mine
        assert released not in mine
        after = await _quick_counts(app_client, app_auth_headers)
        assert after["mine"] == before["mine"] + 1
    finally:
        await _cleanup([live, released])


# ── R9-N15-4 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_closing_a_closed_job_is_refused_and_keeps_closed_at(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    closed_at = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
    job_id = await _seed_job(
        f"R9Close{uuid.uuid4().hex[:8]}",
        status=JobStatus.closed,
        closed_at=closed_at,
    )
    try:
        response = await app_client.post(
            f"/api/jobs/{job_id}/close",
            json={"reason": "budget"},
            headers=app_auth_headers,
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "job_already_closed"
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            assert job.closed_at == closed_at
            assert job.close_reason is None
    finally:
        await _cleanup([job_id])


# ── R9-N15-5 ─────────────────────────────────────────────────────────────────


async def _new_client_id() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(name=f"R9Refs-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        return client.id


@pytest.mark.asyncio
async def test_create_job_with_missing_template_or_category_is_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _new_client_id()
    for extra in (
        {"pipeline_template_id": 2_000_000_000},
        {"competence_category_id": 2_000_000_000},
    ):
        response = await app_client.post(
            "/api/jobs",
            json={"title": "R9 refs", "client_id": client_id, **extra},
            headers=app_auth_headers,
        )
        assert response.status_code == 422, (extra, response.text)


@pytest.mark.asyncio
async def test_taken_reference_number_is_409_on_create_and_update(
    app_client: AsyncClient, app_auth_headers: dict
):
    reference = f"R9-{uuid.uuid4().hex[:10]}"
    taken = await _seed_job(f"R9Ref{uuid.uuid4().hex[:8]}", reference_number=reference)
    other = await _seed_job(f"R9Ref{uuid.uuid4().hex[:8]}")
    client_id = await _new_client_id()
    try:
        created = await app_client.post(
            "/api/jobs",
            json={
                "title": "R9 ref",
                "client_id": client_id,
                "reference_number": reference,
            },
            headers=app_auth_headers,
        )
        assert created.status_code == 409, created.text
        assert created.json()["detail"]["code"] == "reference_number_taken"

        patched = await app_client.patch(
            f"/api/jobs/{other}",
            json={"reference_number": reference},
            headers=app_auth_headers,
        )
        assert patched.status_code == 409, patched.text

        # Odesłanie własnego numeru bez zmiany przechodzi.
        same = await app_client.patch(
            f"/api/jobs/{taken}",
            json={"reference_number": reference, "title": "R9 ref bez zmiany"},
            headers=app_auth_headers,
        )
        assert same.status_code == 200, same.text
    finally:
        await _cleanup([taken, other])
