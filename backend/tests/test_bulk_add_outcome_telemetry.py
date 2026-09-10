"""HTTP contract: adding a shown candidate to the pipeline records an outcome
joined to the full-search run the recruiter saw them in.

C2 (the job page's full search) adds through ``POST /api/jobs/{id}/proposals/
bulk``. The outcome is written after the commit, only for candidates that were
actually added, in the telemetry service's own session.

Uses the in-process ``app_client`` / ``app_auth_headers`` fixtures.
"""

from __future__ import annotations

import uuid

import app.models  # noqa: F401  (register every mapper)
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import match_telemetry_service as tel
from app.services.match_telemetry_service import ImpressionEntry


async def _seed_job_and_candidates() -> dict:
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
    )

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"TelClient-{tag}")
        template = PipelineTemplate(name=f"TelTpl-{tag}")
        db.add_all([client, template])
        await db.commit()
        await db.refresh(client)
        await db.refresh(template)
        job = Job(
            title=f"TelJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            pipeline_template_id=template.id,
        )
        stage = PipelineStageDef(
            template_id=template.id,
            name="new",
            order=0,
            category=StageCategoryEnum.internal,
            legacy_enum_value="new",
            is_terminal=False,
        )
        shown = Candidate(
            name="Shown",
            lastname=f"Tel-{tag}",
            email=f"tel-shown-{tag}@example.com",
            status=CandidateStatus.active,
        )
        blocked = Candidate(
            name="Blocked",
            lastname=f"Tel-{tag}",
            email=f"tel-blocked-{tag}@example.com",
            status=CandidateStatus.blacklisted,
        )
        db.add_all([job, stage, shown, blocked])
        await db.commit()
        for row in (job, shown, blocked):
            await db.refresh(row)
        return {"job_id": job.id, "shown": shown.id, "blocked": blocked.id}


async def test_bulk_add_records_an_outcome_joined_to_the_seen_run(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.models.user import User

    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    world = await _seed_job_and_candidates()
    async with AsyncSessionLocal() as db:
        admin_id = await db.scalar(
            select(User.id).where(
                User.email == app_client.headers.get("X-Test-Admin-Email")
            )
        )
    run_id = f"test-{uuid.uuid4().hex[:16]}"
    # The recruiter was shown both candidates on a C2 results page.
    await tel.record_full_search_page(
        None,
        run_id=run_id,
        job_id=world["job_id"],
        client_id=None,
        user_id=admin_id,
        version_trace=None,
        entries=[
            ImpressionEntry(candidate_id=world["shown"], rank=0),
            ImpressionEntry(candidate_id=world["blocked"], rank=1),
        ],
        degraded=False,
    )
    try:
        resp = await app_client.post(
            f"/api/jobs/{world['job_id']}/proposals/bulk",
            headers=app_auth_headers,
            json={"candidate_ids": [world["shown"], world["blocked"]]},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["added"] == [world["shown"]]
        assert [s["candidate_id"] for s in body["skipped"]] == [world["blocked"]]
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    text(
                        "SELECT candidate_id, run_id, event_type"
                        " FROM match_outcomes WHERE job_id = :j"
                    ),
                    {"j": world["job_id"]},
                )
            ).all()
        # Only the candidate that actually entered the pipeline, on the run
        # that showed them — the skipped one leaves no outcome.
        assert [(r.candidate_id, r.run_id, r.event_type) for r in rows] == [
            (world["shown"], run_id, "add_to_pipeline")
        ]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("DELETE FROM match_impressions WHERE run_id = :r"), {"r": run_id}
            )
            await db.execute(
                text("DELETE FROM match_outcomes WHERE job_id = :j"),
                {"j": world["job_id"]},
            )
            await db.commit()
