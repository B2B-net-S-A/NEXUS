"""„Cofnij” po „+ Dodaj” w oknie „Kandydaci do dodania” (14.10.2026).

`DELETE /api/candidates/{cid}/recruitments/{job_id}` do 15 minut od wejścia
osoby do rekrutacji oddaje jej propozycję (`added` → `proposed`), więc osoba
wraca na listę, z której ją dodano. Późniejsze usunięcie to korekta procesu —
propozycja zostaje `added`. Para bez propozycji: usunięcie jak dotąd.

Testy serwisu bez bazy sprawdzają okno czasu; testy trasy wymagają Postgresa
(CI).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.services import job_proposals as proposals

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)


class _NoDb:
    """Sesja, która nie może być użyta — poza oknem serwis nie pyta bazy."""

    async def execute(self, *_args, **_kwargs):  # pragma: no cover - asercja
        raise AssertionError("poza oknem cofnięcia nie ma zapisu")


async def test_outside_window_does_not_touch_proposals():
    entered = NOW - proposals.UNDO_ADD_WINDOW - timedelta(seconds=1)
    assert (
        await proposals.reopen_after_quick_undo(
            _NoDb(), job_id=1, candidate_id=2, entered_at=entered, now=NOW
        )
        == 0
    )


async def test_unknown_entry_time_does_not_touch_proposals():
    assert (
        await proposals.reopen_after_quick_undo(
            _NoDb(), job_id=1, candidate_id=2, entered_at=None, now=NOW
        )
        == 0
    )


def test_window_is_fifteen_minutes():
    assert proposals.UNDO_ADD_WINDOW == timedelta(minutes=15)


# ── Trasa (Postgres) ────────────────────────────────────────────────────────


async def _world(*, entered_minutes_ago: int, proposal_status: str | None) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.job_proposal import JobProposal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    entered = datetime.now(timezone.utc) - timedelta(minutes=entered_minutes_ago)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Undo client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Undo job {tag}", client_id=client.id, status=JobStatus.published
        )
        candidate = Candidate(
            name="Cofnij", lastname=f"Test-{tag}", email=f"undo-{tag}@example.com"
        )
        db.add_all([job, candidate])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.new,
                moved_at=entered,
                created_at=entered,
            )
        )
        if proposal_status is not None:
            db.add(
                JobProposal(
                    job_id=job.id,
                    candidate_id=candidate.id,
                    source="full_base",
                    status=proposal_status,
                )
            )
        await db.commit()
        return {"job_id": job.id, "candidate_id": candidate.id}


async def _proposal_statuses(job_id: int, candidate_id: int) -> list[str]:
    from app.core.database import AsyncSessionLocal
    from app.models.job_proposal import JobProposal

    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(JobProposal.status).where(
                JobProposal.job_id == job_id, JobProposal.candidate_id == candidate_id
            )
        )
        return list(rows.all())


async def _remove(app_client: AsyncClient, headers: dict, world: dict) -> None:
    response = await app_client.delete(
        f"/api/candidates/{world['candidate_id']}/recruitments/{world['job_id']}",
        headers=headers,
    )
    assert response.status_code == 200, response.text


async def test_undo_within_window_returns_person_to_proposals(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world(entered_minutes_ago=2, proposal_status="added")
    await _remove(app_client, app_auth_headers, world)
    assert await _proposal_statuses(world["job_id"], world["candidate_id"]) == [
        "proposed"
    ]


async def test_removal_after_window_keeps_proposal_added(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world(entered_minutes_ago=20, proposal_status="added")
    await _remove(app_client, app_auth_headers, world)
    assert await _proposal_statuses(world["job_id"], world["candidate_id"]) == [
        "added"
    ]


async def test_undo_without_proposal_is_plain_removal(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _world(entered_minutes_ago=1, proposal_status=None)
    await _remove(app_client, app_auth_headers, world)
    assert await _proposal_statuses(world["job_id"], world["candidate_id"]) == []


async def test_undo_does_not_resurrect_a_dismissed_proposal(
    app_client: AsyncClient, app_auth_headers: dict
):
    # „Pomiń” to decyzja zespołu — cofnięcie dodania jej nie zdejmuje.
    world = await _world(entered_minutes_ago=1, proposal_status="dismissed")
    await _remove(app_client, app_auth_headers, world)
    assert await _proposal_statuses(world["job_id"], world["candidate_id"]) == [
        "dismissed"
    ]
