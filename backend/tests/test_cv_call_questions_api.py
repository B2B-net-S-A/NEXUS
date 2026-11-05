"""Pytania pod CV w ściądze: trasy, zapis, odmowy i brak wywołania modelu.

Reguły mapy i walidację pytań sprawdza ``test_cv_call_questions.py``. Dane fikcyjne.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.api import cv_call_questions_refresh
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.cv_call_question import CvCallQuestions
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import cv_call_questions as cq


async def _seed(
    *, stage: PipelineStage = PipelineStage.screening, with_cv: bool = True
) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient pytań {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Programista {tag}",
            status=JobStatus.published,
            client_id=client.id,
            must_skills=["Oracle", "Kafka", "Liquibase"],
        )
        candidate = Candidate(
            name="Kandydat",
            lastname=f"Testowy{tag}",
            email=f"cv-questions-{tag}@example.com",
            raw_cv_text="Oracle, Kafka" if with_cv else None,
            experience=[
                {
                    "company": "Firma Alfa",
                    "role": "Developer",
                    "description": "Pisał procedury w Oracle.",
                    "technologies": ["Kafka"],
                }
            ],
        )
        db.add_all([job, candidate])
        await db.flush()
        db.add(CandidateStage(candidate_id=candidate.id, job_id=job.id, stage=stage))
        await db.commit()
        return {"candidate_id": candidate.id, "job_id": job.id}


def _url(world: dict) -> str:
    return (
        f"/api/candidates/{world['candidate_id']}/jobs/{world['job_id']}/call-questions"
    )


@pytest.fixture
def model(monkeypatch):
    state = {"calls": 0, "payloads": [], "raw": None, "error": None}

    def fake(payload, _request_id):
        state["calls"] += 1
        state["payloads"].append(payload)
        if state["error"]:
            raise state["error"]
        return state["raw"] or json.dumps(
            {
                "questions": [
                    {
                        "requirement": "Kafka",
                        "company": "Firma Alfa",
                        "question": "Jak wyglądała Twoja praca z Kafką w Firmie Alfa?",
                    },
                    {
                        "requirement": "Liquibase",
                        "company": "",
                        "question": "W której pracy był u Ciebie Liquibase i do czego?",
                    },
                ]
            }
        )

    monkeypatch.setattr(cq, "_call_model", fake)
    return state


async def _row(world: dict):
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CvCallQuestions).where(
                CvCallQuestions.candidate_id == world["candidate_id"],
                CvCallQuestions.job_id == world["job_id"],
            )
        )


@pytest.mark.asyncio
async def test_get_reads_without_writing_or_calling_the_model(
    app_client, app_auth_headers, model
) -> None:
    world = await _seed()
    resp = await app_client.get(_url(world), headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "none" and body["can_refresh"] is True
    assert model["calls"] == 0
    assert await _row(world) is None


@pytest.mark.asyncio
async def test_refresh_stores_questions_and_does_not_pay_twice(
    app_client, app_auth_headers, model
) -> None:
    world = await _seed()
    first = await app_client.post(f"{_url(world)}/refresh", headers=app_auth_headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "ready" and body["stale"] is False
    assert [q["requirement"] for q in body["questions"]] == ["Kafka", "Liquibase"]
    assert body["questions"][0]["state"] == cq.LISTED
    assert body["questions"][1]["state"] == cq.ABSENT
    wanted = [w["nazwa"] for w in model["payloads"][0]["wymagania"]]
    assert "Oracle" not in wanted, "opisane wymaganie nie idzie do modelu"

    second = await app_client.post(f"{_url(world)}/refresh", headers=app_auth_headers)
    assert second.status_code == 200
    assert model["calls"] == 1


@pytest.mark.asyncio
async def test_changed_requirements_make_questions_stale(
    app_client, app_auth_headers, model
) -> None:
    world = await _seed()
    await app_client.post(f"{_url(world)}/refresh", headers=app_auth_headers)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.must_skills = ["Oracle", "Kafka", "Flyway"]
        await db.commit()
    body = (await app_client.get(_url(world), headers=app_auth_headers)).json()
    assert body["stale"] is True


@pytest.mark.asyncio
async def test_model_failure_is_a_state_with_retry_not_an_error(
    app_client, app_auth_headers, model
) -> None:
    world = await _seed()
    model["error"] = RuntimeError("awaria dostawcy")
    resp = await app_client.post(f"{_url(world)}/refresh", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "failed"
    assert resp.json()["questions"] == []

    model["error"] = None
    again = await app_client.post(f"{_url(world)}/refresh", headers=app_auth_headers)
    assert again.json()["status"] == "ready"
    assert model["calls"] == 2


@pytest.mark.asyncio
async def test_broken_model_answer_is_failed_not_an_empty_list(
    app_client, app_auth_headers, model
) -> None:
    world = await _seed()
    model["raw"] = "to nie jest json"
    resp = await app_client.post(f"{_url(world)}/refresh", headers=app_auth_headers)
    assert resp.json()["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", [PipelineStage.verified, PipelineStage.cv_sent])
async def test_later_stage_has_no_section_and_no_model_call(
    app_client, app_auth_headers, model, stage
) -> None:
    world = await _seed(stage=stage)
    resp = await app_client.post(f"{_url(world)}/refresh", headers=app_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_applicable"
    assert resp.json()["can_refresh"] is False
    assert model["calls"] == 0


@pytest.mark.asyncio
async def test_pair_that_does_not_exist_has_no_section(
    app_client, app_auth_headers, model
) -> None:
    world = await _seed()
    other = await _seed()
    url = (
        f"/api/candidates/{other['candidate_id']}/jobs/{world['job_id']}/call-questions"
    )
    resp = await app_client.post(f"{url}/refresh", headers=app_auth_headers)
    assert resp.json()["status"] == "not_applicable"
    assert model["calls"] == 0


@pytest.mark.asyncio
async def test_closed_recruitment_has_no_section(
    app_client, app_auth_headers, model
) -> None:
    world = await _seed()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.status = JobStatus.closed
        await db.commit()
    resp = await app_client.post(f"{_url(world)}/refresh", headers=app_auth_headers)
    assert resp.json()["status"] == "not_applicable"
    assert model["calls"] == 0


@pytest.mark.asyncio
async def test_candidate_without_cv_is_not_sent_to_the_model(
    app_client, app_auth_headers, model
) -> None:
    world = await _seed(with_cv=False)
    resp = await app_client.post(f"{_url(world)}/refresh", headers=app_auth_headers)
    assert resp.json()["status"] == "no_cv"
    assert model["calls"] == 0


@pytest.mark.asyncio
async def test_preview_as_another_user_does_not_pay_for_the_model(
    app_client, app_auth_headers, model, monkeypatch
) -> None:
    world = await _seed()
    monkeypatch.setattr(cv_call_questions_refresh, "is_previewing", lambda _: True)
    resp = await app_client.post(f"{_url(world)}/refresh", headers=app_auth_headers)
    assert resp.status_code == 403
    assert model["calls"] == 0


@pytest.mark.asyncio
async def test_question_answered_in_screening_disappears(
    app_client, app_auth_headers, model
) -> None:
    world = await _seed()
    await app_client.post(f"{_url(world)}/refresh", headers=app_auth_headers)
    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == world["candidate_id"],
                CandidateStage.job_id == world["job_id"],
            )
        )
        stage.screening_answers = {
            "answers": [
                {"question_id": "q1", "response": "Używam Liquibase do migracji baz."}
            ]
        }
        await db.commit()
    body = (await app_client.get(_url(world), headers=app_auth_headers)).json()
    assert [q["requirement"] for q in body["questions"]] == ["Kafka"]
