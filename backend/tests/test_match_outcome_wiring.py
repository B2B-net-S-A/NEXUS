"""P0-B: downstream match outcomes are recorded (record_outcome is wired).

record_outcome had zero call sites, so match_outcomes was never written and the
"learn from what users did" loop could not work. The shortlist / assign /
promote actions now emit an outcome (correlated with the job's latest ranking
run_id), gated by AI_MATCH_TELEMETRY_ENABLED.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import AsyncSessionLocal


async def _seed_job() -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"OutClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Out-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_candidate() -> int:
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Out",
            lastname=f"Cand-{uuid.uuid4().hex[:6]}",
            email=f"out-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_snapshot(job_id: int, run_id: str) -> None:
    from app.models.proposal_snapshot import ProposalSnapshot

    async with AsyncSessionLocal() as db:
        db.add(
            ProposalSnapshot(
                job_id=job_id,
                source="handoff",
                status="ready",
                top_k=20,
                run_id=run_id,
                candidate_ids=[],
                breakdowns=[],
            )
        )
        await db.commit()


async def _outcome_row(job_id: int, candidate_id: int):
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                text(
                    "SELECT event_type, run_id FROM match_outcomes "
                    "WHERE job_id = :j AND candidate_id = :c"
                ),
                {"j": job_id, "c": candidate_id},
            )
        ).first()


async def test_shortlist_add_records_outcome_when_enabled(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    monkeypatch.setattr(
        "app.services.match_telemetry_service.telemetry_enabled", lambda: True
    )

    job_id = await _seed_job()
    cand_id = await _seed_candidate()
    await _seed_snapshot(job_id, run_id="run-xyz")

    resp = await app_client.post(
        f"/api/jobs/{job_id}/shortlist",
        headers=app_auth_headers,
        json={"candidate_ids": [cand_id]},
    )
    assert resp.status_code == 200, resp.text

    row = await _outcome_row(job_id, cand_id)
    assert row is not None
    assert row.event_type == "shortlist"
    assert row.run_id == "run-xyz"  # correlated with the latest ranking run


async def test_no_outcome_when_flag_off(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _seed_job()
    cand_id = await _seed_candidate()

    resp = await app_client.post(
        f"/api/jobs/{job_id}/shortlist",
        headers=app_auth_headers,
        json={"candidate_ids": [cand_id]},
    )
    assert resp.status_code == 200, resp.text

    assert await _outcome_row(job_id, cand_id) is None


async def test_outcome_is_recorded_per_ranking_run(monkeypatch):
    # PR #1036 follow-up: event_id is scoped by run_id, so the same (event, job,
    # candidate) acted on after a NEW ranking run is captured again — one row per
    # run, not one forever.
    monkeypatch.setattr(
        "app.services.match_telemetry_service.telemetry_enabled", lambda: True
    )
    from app.services.match_telemetry_service import emit_match_outcome

    job_id = await _seed_job()
    cand_id = await _seed_candidate()

    await _seed_snapshot(job_id, run_id="runA")
    async with AsyncSessionLocal() as db:
        await emit_match_outcome(
            db, event_type="shortlist", candidate_id=cand_id, job_id=job_id
        )
    # A second run — same pair acted on again.
    await _seed_snapshot(job_id, run_id="runB")
    async with AsyncSessionLocal() as db:
        await emit_match_outcome(
            db, event_type="shortlist", candidate_id=cand_id, job_id=job_id
        )

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT run_id FROM match_outcomes "
                    "WHERE job_id = :j AND candidate_id = :c"
                ),
                {"j": job_id, "c": cand_id},
            )
        ).all()
    assert {r.run_id for r in rows} == {"runA", "runB"}
