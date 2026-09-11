"""CI PostgreSQL: a Champion save keeps the budget and every requirement.

The regressions of #1477 were invisible in the editor — the profile still
opened; only `rate_value` / `jobs.rate_budget_hourly` and `jobs.must_skills`
quietly lost what the Delivery Lead had written.
"""

import uuid

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job, JobStatus
from tests.test_champion_intake_retention import LONG, legacy_profile


async def _seed() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Synthetic Champion retention {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        job = Job(
            title="Synthetic Java role",
            status=JobStatus.draft,
            client_id=client.id,
            champion_profile=legacy_profile(),
        )
        db.add(job)
        await db.commit()
        return job.id


async def _job(job_id: int) -> Job:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Job).where(Job.id == job_id))


async def test_save_keeps_the_budget_and_long_requirements(
    app_client, app_auth_headers, monkeypatch
):
    async def no_refresh(*args, **kwargs):
        pass

    monkeypatch.setattr(
        "app.services.job_matching_refresh.refresh_job_matching", no_refresh
    )
    job_id = await _seed()
    route = f"/api/jobs/{job_id}/champion-profile"

    edited = await app_client.put(
        route,
        json={"project": {"about": "Nowy opis projektu."}},
        headers=app_auth_headers,
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["champion_profile"]["basics"]["rate_value"] == 140.0
    assert body["job_values"]["rate_value"] == 140.0
    codes = {issue["code"] for issue in body["validation"]["issues"]}
    assert "rate_source_ambiguous" in codes
    assert "missing_budget" not in codes

    stack = await app_client.put(
        route,
        json={
            "stack": {
                "must": [{"name": "Java 17"}, {"name": "Docker"}, {"name": LONG}],
                "nice": [],
                "notes": "",
            }
        },
        headers=app_auth_headers,
    )
    assert stack.status_code == 200, stack.text
    saved = await _job(job_id)
    assert [s["name"] for s in saved.must_skills] == ["Java 17", "Docker", LONG]
    assert [s["name"] for s in saved.champion_profile["stack"]["must"]] == [
        "Java 17",
        "Docker",
        LONG,
    ]

    # The kept long requirement must not take the search contract down.
    requirements = await app_client.get(
        f"/api/candidate-search/jobs/{job_id}/requirements",
        headers=app_auth_headers,
    )
    assert requirements.status_code == 200, requirements.text


async def test_no_op_save_of_a_stamped_profile_writes_nothing(
    app_client, app_auth_headers, monkeypatch
):
    """A stored intake without the newer `advisory` key is not a change."""

    async def no_refresh(*args, **kwargs):
        pass

    monkeypatch.setattr(
        "app.services.job_matching_refresh.refresh_job_matching", no_refresh
    )
    job_id = await _seed()
    route = f"/api/jobs/{job_id}/champion-profile"
    first = await app_client.put(
        route, json={"project": {"about": "Opis."}}, headers=app_auth_headers
    )
    assert first.status_code == 200, first.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        profile = dict(job.champion_profile)
        intake = dict(profile["intake"])
        intake.pop("advisory", None)
        profile["intake"] = intake
        job.champion_profile = profile
        await db.commit()

    again = await app_client.put(
        route, json={"project": {"about": "Opis."}}, headers=app_auth_headers
    )

    assert again.status_code == 200, again.text
    assert "advisory" not in (await _job(job_id)).champion_profile["intake"]
