"""HTTP contract: an add to the pipeline records an outcome, joined to a
full-search run ONLY when the caller declares that run and it verifiably
showed the candidate to this user for this job.

``POST /api/jobs/{id}/proposals/bulk`` is shared by manual search, the
historical section, quick-add and the job page's full search (C2), so the
server cannot infer which ranking an add followed from. Until 11.09 it guessed
("the latest impression this user saw for this job"), which credited adds made
on other screens to unrelated C2 runs. Now C2 sends its ``run_id``; anything
unverifiable is stored with ``run_id = NULL``. The outcome is written after the
commit, only for candidates that were actually added, in the telemetry
service's own session.

Uses the in-process ``app_client`` / ``app_auth_headers`` fixtures.
"""

from __future__ import annotations

import uuid

import app.models  # noqa: F401  (register every mapper)
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import match_telemetry_service as tel
from app.services.match_telemetry_service import ImpressionEntry


async def _admin_id(app_client: AsyncClient) -> int:
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(User.id).where(
                User.email == app_client.headers.get("X-Test-Admin-Email")
            )
        )


async def _seed(owner_id: int) -> dict:
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.candidate_search_run import CandidateSearchRun
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
    )
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"TelClient-{tag}")
        template = PipelineTemplate(name=f"TelTpl-{tag}")
        colleague = User(
            email=f"tel-colleague-{tag}@example.com",
            name="Colleague",
            role=UserRole.recruiter,
        )
        db.add_all([client, template, colleague])
        await db.commit()
        for row in (client, template, colleague):
            await db.refresh(row)
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
        candidates = [
            Candidate(
                name=name,
                lastname=f"Tel-{tag}",
                email=f"tel-{name.lower()}-{tag}@example.com",
                status=status,
            )
            for name, status in (
                ("Shown", CandidateStatus.active),
                ("Blocked", CandidateStatus.blacklisted),
                ("Manual", CandidateStatus.active),
                ("Foreign", CandidateStatus.active),
            )
        ]
        db.add_all([job, stage, *candidates])
        await db.commit()
        for row in (job, *candidates):
            await db.refresh(row)

        def run(created_by: int) -> CandidateSearchRun:
            return CandidateSearchRun(
                id=str(uuid.uuid4()),
                created_by=created_by,
                client_id=client.id,
                job_id=job.id,
                state="complete",
                request_fingerprint="f" * 64,
                request_context={},
                version_trace={},
                population_size=0,
                metrics={},
            )

        mine, foreign = run(owner_id), run(colleague.id)
        db.add_all([mine, foreign])
        await db.commit()
        shown, blocked, manual, foreign_candidate = (c.id for c in candidates)
        return {
            "job_id": job.id,
            "shown": shown,
            "blocked": blocked,
            "manual": manual,
            "foreign_candidate": foreign_candidate,
            "run": mine.id,
            "foreign_run": foreign.id,
            "colleague_id": colleague.id,
        }


async def _outcomes(job_id: int) -> list[tuple]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT candidate_id, run_id, event_type, reason_code"
                    " FROM match_outcomes WHERE job_id = :j ORDER BY candidate_id"
                ),
                {"j": job_id},
            )
        ).all()
    return [(r.candidate_id, r.run_id, r.event_type, r.reason_code) for r in rows]


async def _cleanup(world: dict) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM match_impressions WHERE job_id = :j"),
            {"j": world["job_id"]},
        )
        await db.execute(
            text("DELETE FROM match_outcomes WHERE job_id = :j"),
            {"j": world["job_id"]},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_adds_join_only_the_run_that_verifiably_showed_them(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    monkeypatch.setattr(settings, "AI_MATCH_TELEMETRY_ENABLED", True)
    admin_id = await _admin_id(app_client)
    world = await _seed(admin_id)
    job_id = world["job_id"]

    async def page(run_id: str, user_id: int, candidate_ids: list[int]) -> None:
        await tel.record_full_search_page(
            None,
            run_id=run_id,
            job_id=job_id,
            client_id=None,
            user_id=user_id,
            version_trace=None,
            entries=[
                ImpressionEntry(candidate_id=cid, rank=i)
                for i, cid in enumerate(candidate_ids)
            ],
            degraded=False,
        )

    # This recruiter saw all four on their own C2 page; a colleague's run
    # showed the "foreign" candidate too.
    await page(
        world["run"],
        admin_id,
        [world["shown"], world["blocked"], world["manual"], world["foreign_candidate"]],
    )
    await page(world["foreign_run"], world["colleague_id"], [world["foreign_candidate"]])

    async def add(candidate_ids: list[int], **telemetry) -> dict:
        resp = await app_client.post(
            f"/api/jobs/{job_id}/proposals/bulk",
            headers=app_auth_headers,
            json={"candidate_ids": candidate_ids, **telemetry},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    try:
        # C2: the full-search screen declares its run.
        body = await add(
            [world["shown"], world["blocked"]],
            run_id=world["run"],
            source="full_search",
        )
        assert body["added"] == [world["shown"]]
        assert [s["candidate_id"] for s in body["skipped"]] == [world["blocked"]]
        # Manual search: no run. The impression above must NOT be picked up.
        await add([world["manual"]], source="manual_search")
        # A run id that is someone else's is not this user's exposure.
        await add(
            [world["foreign_candidate"]],
            run_id=world["foreign_run"],
            source="full_search",
        )

        assert await _outcomes(job_id) == sorted(
            [
                (world["shown"], world["run"], "add_to_pipeline", "full_search"),
                (world["manual"], None, "add_to_pipeline", "manual_search"),
                (world["foreign_candidate"], None, "add_to_pipeline", "full_search"),
            ]
        )
    finally:
        await _cleanup(world)


@pytest.mark.asyncio
async def test_telemetry_fields_are_validated_at_the_boundary(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A closed vocabulary lands in the analytics table — never free text."""
    resp = await app_client.post(
        "/api/jobs/1/proposals/bulk",
        headers=app_auth_headers,
        json={"candidate_ids": [1], "source": "cokolwiek"},
    )
    assert resp.status_code == 422, resp.text
    resp = await app_client.post(
        "/api/jobs/1/proposals/bulk",
        headers=app_auth_headers,
        json={"candidate_ids": [1], "run_id": "x" * 65},
    )
    assert resp.status_code == 422, resp.text
