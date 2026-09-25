"""Pasek filtrów listy rekrutacji (25.09.2026): stan requestu i „Kto pracuje”.

Dwie reguły, które łatwo cofnąć:

* ``request_stage`` daje JEDNĄ wartość na rekrutację, więc kilka pigułek
  naraz to LUB. Stare ``request_status`` + ``work_state`` łączyły się przez
  AND i nie dało się nimi zrobić jednego rzędu.
* „Kto pracuje” czyta przypisania niezwolnione (``state <> 'released'``),
  jak pulpit „Requesty i obłożenie” — propozycja z trybu cienia się liczy,
  zwolnione przypisanie nie.

Rejestr jest wspólny dla całej bazy testowej, więc zapytania o listę
zawężamy unikalnym tokenem w tytule (``q=``), a liczniki porównujemy
z ``total`` listy z tym samym filtrem (oba są globalne).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today


async def _me_id(app_client: AsyncClient, headers: dict) -> int:
    response = await app_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _seed_job(
    token: str,
    *,
    status: str = "published",
    work_state: str = "to_review",
    champion: bool = False,
    deadline=None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"StageClient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"{token}-{uuid.uuid4().hex[:4]}",
            status=JobStatus(status),
            work_state=work_state,
            champion_found_at=datetime.now(timezone.utc) if champion else None,
            deadline=deadline,
            client_id=client.id,
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


async def _total(app_client: AsyncClient, headers: dict, query: str) -> int:
    response = await app_client.get(f"/api/jobs?page_size=1&{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["total"]


@pytest.mark.asyncio
async def test_each_job_has_exactly_one_stage_and_chips_combine_with_or(
    app_client: AsyncClient, app_auth_headers: dict
):
    token = f"Stage{uuid.uuid4().hex[:8]}"
    jobs = {
        "incomplete": await _seed_job(token, status="draft", work_state="searching"),
        "to_review": await _seed_job(token),
        "searching": await _seed_job(token, work_state="searching"),
        "champion": await _seed_job(token, work_state="client_silent", champion=True),
        "client_silent": await _seed_job(token, work_state="client_silent"),
        "finished": await _seed_job(token, work_state="finished"),
        "closed": await _seed_job(token, status="closed", work_state="searching"),
    }
    try:
        response = await app_client.get(
            f"/api/jobs?page_size=100&q={token}", headers=app_auth_headers
        )
        assert response.status_code == 200, response.text
        stage_by_id = {
            row["id"]: row["request_stage"] for row in response.json()["items"]
        }
        assert stage_by_id == {job_id: stage for stage, job_id in jobs.items()}

        for stage, job_id in jobs.items():
            assert await _ids(
                app_client, app_auth_headers, f"q={token}&request_stage={stage}"
            ) == {job_id}

        # Dwie pigułki naraz = LUB, nie część wspólna.
        assert await _ids(
            app_client,
            app_auth_headers,
            f"q={token}&request_stage=incomplete&request_stage=client_silent",
        ) == {jobs["incomplete"], jobs["client_silent"]}
    finally:
        await _cleanup(list(jobs.values()))


@pytest.mark.asyncio
async def test_unknown_request_stage_is_rejected(
    app_client: AsyncClient, app_auth_headers: dict
):
    response = await app_client.get(
        "/api/jobs?request_stage=cokolwiek", headers=app_auth_headers
    )
    assert response.status_code == 422
    assert "cokolwiek" in response.text


@pytest.mark.asyncio
async def test_worked_by_counts_live_assignments_only(
    app_client: AsyncClient, app_auth_headers: dict
):
    me = await _me_id(app_client, app_auth_headers)
    token = f"Work{uuid.uuid4().hex[:8]}"
    active = await _seed_job(token, work_state="searching")
    proposed = await _seed_job(token, work_state="searching")
    released = await _seed_job(token, work_state="searching")
    nobody = await _seed_job(token, work_state="searching")
    await _assign(active, me, "active")
    await _assign(proposed, me, "proposed")
    await _assign(released, me, "released")
    try:
        assert await _ids(
            app_client, app_auth_headers, f"q={token}&worked_by={me}"
        ) == {active, proposed}
        assert await _ids(
            app_client, app_auth_headers, f"q={token}&nobody_working=true"
        ) == {released, nobody}
        assert await _ids(
            app_client, app_auth_headers, f"q={token}&nobody_working=false"
        ) == {active, proposed}
    finally:
        await _cleanup([active, proposed, released, nobody])


@pytest.mark.asyncio
async def test_quick_counts_for_stages_and_toggles_agree_with_the_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Liczba przy pigułce i przełączniku == ``total`` listy z tym filtrem."""
    me = await _me_id(app_client, app_auth_headers)
    token = f"Cnt{uuid.uuid4().hex[:8]}"
    yesterday = business_today() - timedelta(days=1)
    seeded = [
        await _seed_job(token, work_state="searching", deadline=yesterday),
        await _seed_job(token, work_state="client_silent"),
        await _seed_job(token, status="draft"),
    ]
    await _assign(seeded[0], me, "active")
    try:
        response = await app_client.get(
            f"/api/jobs/quick-counts?overdue_to={yesterday.isoformat()}",
            headers=app_auth_headers,
        )
        assert response.status_code == 200, response.text
        counts = response.json()

        for stage in (
            "incomplete",
            "to_review",
            "searching",
            "champion",
            "contract",
            "client_silent",
        ):
            assert counts["request_stage"][stage] == await _total(
                app_client, app_auth_headers, f"request_stage={stage}"
            ), stage
            assert counts["request_stage_mine"][stage] == await _total(
                app_client, app_auth_headers, f"mine=true&request_stage={stage}"
            ), stage

        toggles = {
            "overdue": f"deadline_to={yesterday.isoformat()}",
            "nobody_working": "nobody_working=true",
            "nobody_sent": "max_sent=0",
        }
        for flag, query in toggles.items():
            assert counts["attention"][flag] == await _total(
                app_client, app_auth_headers, f"open_only=true&{query}"
            ), flag
            assert counts["attention_mine"][flag] == await _total(
                app_client, app_auth_headers, f"mine=true&{query}"
            ), flag
    finally:
        await _cleanup(seeded)
