"""R10-N7-6: „Odśwież kryteria" to zmiana wejść dopasowania.

Do rundy 10 trasa zapisywała nowe must/nice i robiła sam ``embed_job`` —
cache wyników i migawka propozycji zostawały przy starych wymaganiach, a
automaty (auto-match, nocny przegląd) nie dostawały zdarzenia. PATCH
rekrutacji przy tej samej zmianie robi wszystko naraz.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job, JobStatus

pytestmark = pytest.mark.asyncio


async def _job(status: JobStatus) -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Refresh criteria {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Refresh criteria {tag}",
            description="Szukamy Python + Django",
            client_id=client.id,
            status=status,
            must_skills=["Java"],
        )
        db.add(job)
        await db.commit()
        return job.id


@pytest.mark.parametrize(
    "status,enqueued", [(JobStatus.published, True), (JobStatus.draft, False)]
)
async def test_refresh_criteria_refreshes_matching_and_wakes_automations(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, status, enqueued
):
    from app.api import recommendations
    from app.core.config import settings
    from app.services import auto_match_outbox, job_matching_refresh

    refreshed: list[int] = []
    queued: list[int] = []

    async def fake_criteria(job):
        return {
            "must_skills": [{"name": "Python", "level": None}],
            "nice_skills": [{"name": "Django", "level": None}],
        }

    async def fake_refresh(job_id, db):
        refreshed.append(job_id)
        await db.commit()

    async def fake_enqueue(job_id, trigger="job_publish"):
        queued.append(job_id)

    monkeypatch.setattr(
        recommendations, "_generate_criteria_with_ollama", fake_criteria
    )
    monkeypatch.setattr(job_matching_refresh, "refresh_job_matching", fake_refresh)
    monkeypatch.setattr(auto_match_outbox, "enqueue_job_safe", fake_enqueue)
    monkeypatch.setattr(settings, "MARKETPLACE_ENABLED", False)

    job_id = await _job(status)
    response = await app_client.post(
        f"/api/jobs/{job_id}/refresh-criteria", headers=app_auth_headers
    )
    assert response.status_code == 200, response.text
    assert [s["name"] for s in response.json()["must_skills"]] == ["Python"]
    assert refreshed == [job_id]
    assert queued == ([job_id] if enqueued else [])
