"""„Z historii klienta” — blok sekcji 8 profilu Championa (09.2026).

Pilnuje: anonimizacji przed modelem, braku wywołania przy zbyt małej historii
i przy niezmienionych danych, tego że awaria modelu nie jest błędem trasy,
oraz tego że blok nie wychodzi publiczną kartą Championa.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.interview_feedback import (
    FeedbackSource,
    InterviewDecision,
    InterviewFeedback,
)
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import champion_client_history as history
from app.services import champion_draft_service

NOW = datetime.now(timezone.utc)


def test_scrub_names_replaces_known_names_as_whole_words() -> None:
    text = "Grzegorz Nowak nie znał procesów kartowych, a Grzegorzewski tak."
    out = history.scrub_names(text, {"Grzegorz", "Nowak"})
    assert (
        out == "[kandydat] [kandydat] nie znał procesów kartowych, a Grzegorzewski tak."
    )


async def _seed(events: int) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"History Client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Tester płatności {tag}",
            status=JobStatus.published,
            client_id=client.id,
        )
        db.add(job)
        await db.flush()
        for i in range(events):
            candidate = Candidate(
                name="Zbigniew",
                lastname=f"Historyk{tag}{i}",
                email=f"hist-{tag}-{i}@example.com",
                status=CandidateStatus.active,
            )
            db.add(candidate)
            await db.flush()
            db.add(
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=NOW,
                )
            )
            db.add(
                InterviewFeedback(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    feedback_source=FeedbackSource.client_side,
                    decision=InterviewDecision.reject,
                    concerns=f"Zbigniew Historyk{tag}{i} słabo zna procesy kartowe",
                )
            )
        await db.commit()
        return {"client_id": client.id, "job_id": job.id, "tag": tag}


@pytest.mark.asyncio
async def test_too_little_history_does_not_call_the_model(monkeypatch) -> None:
    world = await _seed(events=1)

    async def boom(**_):
        raise AssertionError("model nie powinien być wołany")

    monkeypatch.setattr(champion_draft_service, "_call_claude_json", boom)
    async with AsyncSessionLocal() as db:
        summary = await history.summarize_client_history(
            db, client_id=world["client_id"], role="Tester"
        )
    assert summary["status"] == "ready"
    assert summary["items"] == []
    assert summary["message"] == history.TOO_LITTLE


@pytest.mark.asyncio
async def test_names_never_reach_the_model_and_same_inputs_skip_the_call(
    monkeypatch,
) -> None:
    world = await _seed(events=3)
    calls: list[str] = []

    async def fake_call(*, prompt, **_):
        calls.append(prompt)
        return {
            "items": [
                {
                    "topic": "rejections",
                    "text": "Klient odrzucał za słabą znajomość procesów kartowych.",
                    "basis_count": 3,
                }
            ]
        }

    monkeypatch.setattr(champion_draft_service, "_call_claude_json", fake_call)
    async with AsyncSessionLocal() as db:
        first = await history.summarize_client_history(
            db, client_id=world["client_id"], role="Tester"
        )
    assert first["status"] == "ready"
    assert first["items"][0]["basis_count"] == 3
    assert "procesy kartowe" in calls[0]
    assert "Zbigniew" not in calls[0]
    assert f"Historyk{world['tag']}" not in calls[0]

    async with AsyncSessionLocal() as db:
        second = await history.summarize_client_history(
            db, client_id=world["client_id"], role="Tester", stored=first
        )
    assert len(calls) == 1
    assert second["items"] == first["items"]


@pytest.mark.asyncio
async def test_model_failure_is_a_status_not_an_error(monkeypatch) -> None:
    world = await _seed(events=3)

    async def fail(**_):
        raise RuntimeError("provider down")

    monkeypatch.setattr(champion_draft_service, "_call_claude_json", fail)
    async with AsyncSessionLocal() as db:
        summary = await history.summarize_client_history(
            db, client_id=world["client_id"], role="Tester"
        )
    assert summary["status"] == "failed"
    assert summary["message"] == history.FAILED
    # Bez hasha: następne „Odśwież” spróbuje ponownie.
    assert summary["inputs_hash"] is None


@pytest.mark.asyncio
async def test_route_stores_the_block_and_the_public_card_never_carries_it(
    app_client, app_auth_headers, monkeypatch
) -> None:
    from app.api.public_share import _public_champion_projection

    world = await _seed(events=3)

    async def fake_call(**_):
        return {
            "items": [
                {"topic": "needs", "text": "Liczy się acquiring.", "basis_count": 3}
            ]
        }

    monkeypatch.setattr(champion_draft_service, "_call_claude_json", fake_call)
    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/champion-profile/client-history",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    block = resp.json()["champion_profile"]["client_history"]
    assert block["status"] == "ready"
    assert block["items"][0]["text"] == "Liczy się acquiring."

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        public = _public_champion_projection(job)
    # Karta dla hiring managera to biała lista — nowe bloki maszynowe
    # i notatki zespołu nie mają w niej pola.
    assert set(public) == {"basics", "project", "stack", "screening_questions"}
