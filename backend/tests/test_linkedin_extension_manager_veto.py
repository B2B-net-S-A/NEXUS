"""Extension-key assignments honor the same hiring-manager veto as the ATS.

All records are synthetic and created in the disposable test database. The
HTTP contract is per-job skipping: a veto explains the refusal without adding
a process, changing the existing candidate or recording assignment side effects.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from tests.test_hiring_manager_verdicts import _reject_after_interview, _seed_world

EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"


@pytest.fixture(autouse=True)
def _allow_test_extension(monkeypatch):
    monkeypatch.setattr(settings, "LINKEDIN_EXTENSION_IDS", EXTENSION_ID)
    monkeypatch.setattr(settings, "LINKEDIN_EXTENSION_ENABLED", True)


async def _connect(client, headers):
    response = await client.post(
        "/api/extension/connect",
        headers=headers,
        json={"extension_id": EXTENSION_ID, "extension_version": "1.0.1"},
    )
    assert response.status_code == 200, response.text
    return {"X-Extension-Key": response.json()["key"]}


async def _world(*, two_managers=False, reason_key="disqualifying_reason_id"):
    world = await _seed_world(two_managers=two_managers)
    await _reject_after_interview(world, reason_key=reason_key)
    link = f"https://www.linkedin.com/in/extension-veto-synthetic-{uuid.uuid4().hex}/"
    async with AsyncSessionLocal() as db:
        target = await db.get(Job, world["target_job_id"])
        target.is_open = True
        candidate = await db.get(Candidate, world["candidate_id"])
        candidate.linkedin = link
        candidate.linkedin_current_company = "Firma Fikcyjna"
        candidate.linkedin_current_title = "Original synthetic title"
        await db.commit()
        world["profile"] = {
            "full_name": f"{candidate.name} {candidate.lastname}",
            "public_url": link,
            "page_url": link,
            "current_company": "Firma Fikcyjna",
            "current_title": "Changed title must not overwrite the candidate",
            "headline": "Synthetic LinkedIn preview",
        }
    return world


async def _snapshot(world):
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, world["candidate_id"])
        return {
            "stages": await db.scalar(
                select(func.count())
                .select_from(CandidateStage)
                .where(
                    CandidateStage.candidate_id == candidate.id,
                    CandidateStage.job_id == world["target_job_id"],
                )
            ),
            "processes": await db.scalar(
                select(func.count())
                .select_from(RecruitmentProcess)
                .where(
                    RecruitmentProcess.candidate_id == candidate.id,
                    RecruitmentProcess.job_id == world["target_job_id"],
                )
            ),
            "activities": await db.scalar(
                select(func.count())
                .select_from(Activity)
                .where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == candidate.id,
                )
            ),
            "notes": await db.scalar(
                select(func.count())
                .select_from(Note)
                .where(Note.candidate_id == candidate.id)
            ),
            "candidate": (
                candidate.name,
                candidate.lastname,
                candidate.linkedin,
                candidate.linkedin_current_company,
                candidate.linkedin_current_title,
            ),
        }


async def _assign(client, key, world, ingress):
    if ingress == "existing_candidate_jobs":
        return await client.post(
            f"/api/extension/candidates/{world['candidate_id']}/jobs",
            headers=key,
            json={"job_ids": [world["target_job_id"]]},
        )
    return await client.post(
        "/api/extension/candidates",
        headers=key,
        json={"profile": world["profile"], "job_ids": [world["target_job_id"]]},
    )


@pytest.mark.parametrize(
    "ingress", ["existing_candidate_jobs", "add_existing_linkedin"]
)
async def test_extension_skips_manager_veto_without_assignment_writes(
    app_client,
    app_auth_headers,
    ingress,
):
    world = await _world()
    before = await _snapshot(world)
    key = await _connect(app_client, app_auth_headers)

    response = await _assign(app_client, key, world, ingress)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assigned_job_ids"] == []
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["job_id"] == world["target_job_id"]
    assert world["manager_name"] in body["skipped"][0]["reason"]
    assert "odrzucił(a) tego kandydata" in body["skipped"][0]["reason"]
    if ingress == "add_existing_linkedin":
        assert body["created"] is False
        assert body["candidate_id"] == world["candidate_id"]
    assert await _snapshot(world) == before


@pytest.mark.parametrize(
    "ingress", ["existing_candidate_jobs", "add_existing_linkedin"]
)
@pytest.mark.parametrize("policy_case", ["different_manager", "situational_reason"])
async def test_extension_does_not_veto_an_unrelated_manager_or_situational_rejection(
    app_client,
    app_auth_headers,
    ingress,
    policy_case,
):
    world = await _world(
        two_managers=policy_case == "different_manager",
        reason_key="situational_reason_id"
        if policy_case == "situational_reason"
        else "disqualifying_reason_id",
    )
    key = await _connect(app_client, app_auth_headers)

    response = await _assign(app_client, key, world, ingress)

    assert response.status_code == 200, response.text
    assert response.json()["assigned_job_ids"] == [world["target_job_id"]]
    assert response.json()["skipped"] == []
    after = await _snapshot(world)
    assert after["stages"] == 1
    assert after["processes"] == 1
