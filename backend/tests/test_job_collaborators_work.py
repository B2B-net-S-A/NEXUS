"""„Kto pracuje” liczy ręcznie dopisanych współpracowników (decyzja 29.09.2026).

Rekrutację prowadzi jedna osoba (``jobs.recruiter_id``), ale pracuje nad nią
kilka — współpracownicy dopisani w oknie edycji. Filtr „Kto pracuje: X”
i „Nikt nie pracuje” (lista ``/jobs`` i liczniki ``quick-counts``) widzi
współpracownika ``manual``. Wiersz ``auto_cc`` to cała kategoria kompetencji,
nie osoba przy tej rekrutacji — nie liczy się.

Rejestr jest wspólny dla bazy testowej: listy zawężamy tokenem w tytule (``q=``).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.test_audit_r7_jobs import _ids, _seed_job, _seed_user


def test_work_clauses_read_manual_collaborators_only() -> None:
    from sqlalchemy.dialects import postgresql

    from app.api.jobs import jobs_nobody_working_clause, jobs_worked_by_clause

    for clause in (jobs_nobody_working_clause(), jobs_worked_by_clause([1])):
        sql = str(
            clause.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        assert "job_collaborators.source = 'manual'" in sql, sql
        assert "job_collaborators.removed_from_auto_cc IS false" in sql, sql


async def _add_collaborator(job_id: int, user_id: int, source: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource

    async with AsyncSessionLocal() as db:
        db.add(
            JobCollaborator(
                job_id=job_id,
                user_id=user_id,
                source=JobCollaboratorSource(source),
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_manual_collaborator_counts_as_working_and_auto_cc_does_not(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    person = await _seed_user()
    dead = await _seed_user(active=False)
    token = f"Collab{uuid.uuid4().hex[:8]}"
    manual_job = await _seed_job(token, work_state="to_review")
    auto_job = await _seed_job(token, work_state="to_review")
    dead_job = await _seed_job(token, work_state="to_review")
    await _add_collaborator(manual_job, person, "manual")
    await _add_collaborator(auto_job, person, "auto_cc")
    await _add_collaborator(dead_job, dead, "manual")

    assert await _ids(
        app_client, app_auth_headers, f"q={token}&worked_by={person}"
    ) == {manual_job}
    assert await _ids(
        app_client, app_auth_headers, f"q={token}&nobody_working=true"
    ) == {auto_job, dead_job}
    assert await _ids(
        app_client, app_auth_headers, f"q={token}&nobody_working=false"
    ) == {manual_job}


@pytest.mark.asyncio
async def test_list_marks_the_collaborator_source(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    person = await _seed_user()
    other = await _seed_user()
    token = f"CollabSrc{uuid.uuid4().hex[:8]}"
    job_id = await _seed_job(token)
    await _add_collaborator(job_id, person, "manual")
    await _add_collaborator(job_id, other, "auto_cc")

    response = await app_client.get(
        f"/api/jobs?page_size=10&q={token}", headers=app_auth_headers
    )
    assert response.status_code == 200, response.text
    (row,) = response.json()["items"]
    assert {(c["id"], c["source"]) for c in row["collaborators"]} == {
        (person, "manual"),
        (other, "auto_cc"),
    }
