"""`next_action_owner` w `GET /api/candidates/{id}/history` (04.10.2026).

Profil kandydata pokazuje w „Teraz” kto ma ruch w procesie w toku — tą samą
regułą co karta na Tablicy (`pipeline_next_action.next_action_for`).
Zakończone procesy (zamknięta rekrutacja, odrzucenie, wycofanie,
zatrudnienie) nie mają właściciela: `None`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from httpx import AsyncClient

from app.api.candidates import _history_next_action_owner, _history_stage_column
from app.models.recruitment_pipeline import PipelineStage

TODAY = date(2026, 10, 4)


def _owner(stage: PipelineStage, *, job_status: str = "published", days: int = 0):
    column = _history_stage_column(
        stage,
        stage_def_id=None,
        name=None,
        legacy=None,
        category=None,
        terminal=None,
        order=None,
    )
    moved = datetime(2026, 10, 4, 10, tzinfo=timezone.utc) - timedelta(days=days)
    return _history_next_action_owner(
        {"job_status": job_status, "latest_stage": stage.value},
        (column, moved),
        today=TODAY,
    )


def test_verified_card_is_the_recruiters_move() -> None:
    assert _owner(PipelineStage.verified) == "recruiter"


def test_cv_sent_waits_for_the_client_until_the_nudge() -> None:
    assert _owner(PipelineStage.cv_sent, days=1) == "client"
    assert _owner(PipelineStage.cv_sent, days=30) == "recruiter"


def test_ended_processes_have_no_owner() -> None:
    assert _owner(PipelineStage.rejected) is None
    assert _owner(PipelineStage.withdrawn) is None
    assert _owner(PipelineStage.hired) is None
    assert _owner(PipelineStage.verified, job_status="closed") is None


def test_stage_definition_wins_over_the_enum() -> None:
    column = _history_stage_column(
        PipelineStage.interview,
        stage_def_id=7,
        name="QC CV",
        legacy="interview",
        category="internal",
        terminal=None,
        order=4,
    )
    assert column.stage == "interview"
    assert column.name == "QC CV"
    assert column.stage_def_id == 7
    assert (
        _history_next_action_owner(
            {"job_status": "published", "latest_stage": "interview"},
            (column, datetime(2026, 10, 3, tzinfo=timezone.utc)),
            today=TODAY,
        )
        is not None
    )


def test_missing_latest_column_has_no_owner() -> None:
    assert (
        _history_next_action_owner(
            {"job_status": "published", "latest_stage": "verified"}, None, today=TODAY
        )
        is None
    )


async def test_history_endpoint_carries_next_action_owner(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Ruch", lastname=f"Test-{suffix}", email=f"ruch-{suffix}@example.com"
        )
        cli = Client(name=f"RuchClient-{suffix}")
        db.add_all([cand, cli])
        await db.flush()
        open_job = Job(
            title=f"Ruch-{suffix}", status=JobStatus.published, client_id=cli.id
        )
        closed_job = Job(
            title=f"Ruch-closed-{suffix}", status=JobStatus.closed, client_id=cli.id
        )
        db.add_all([open_job, closed_job])
        await db.flush()
        now = datetime.now(timezone.utc)
        db.add_all(
            [
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=open_job.id,
                    stage=PipelineStage.verified,
                    moved_at=now,
                ),
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=closed_job.id,
                    stage=PipelineStage.verified,
                    moved_at=now,
                ),
            ]
        )
        await db.commit()
        candidate_id, open_id, closed_id = cand.id, open_job.id, closed_job.id

    r = await app_client.get(
        f"/api/candidates/{candidate_id}/history", headers=app_auth_headers
    )
    assert r.status_code == 200, r.text
    by_job = {job["job_id"]: job for job in r.json()["jobs"]}
    assert by_job[open_id]["next_action_owner"] == "recruiter"
    assert by_job[closed_id]["next_action_owner"] is None
