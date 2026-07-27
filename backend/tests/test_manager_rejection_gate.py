"""HTTP contract for the hiring-manager veto.

A manager who interviewed a candidate and turned them down must not be handed
that person again. These tests pin *where* that blocks and — just as important —
where it deliberately does not:

* assign / bulk-add / shortlist-promote → blocked, because that is the moment
  the candidate enters the manager's recruitment;
* a move onto ``cv_sent`` / ``client_interview`` → blocked, because that is the
  moment we put them back in front of the client;
* everything else (internal moves, ``hired``, closing the candidate out) → must
  keep working. Blocking those would freeze every pipeline that predates the
  feature, and blocking ``hired`` would be absurd: the manager has just said yes.

Uses the in-process ``app_client`` / ``app_auth_headers`` fixtures.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  (register every mapper — see verdicts test)
from app.models.skill import Skill  # noqa: F401
from httpx import AsyncClient

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


async def _seed_vetoed_candidate(*, disqualifying: bool = True) -> dict:
    """Candidate rejected after an interview by the manager of *both* jobs."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.contact import Contact
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineTemplate,
        RejectionReason,
        TerminalType,
    )
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"GateClient-{tag}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        manager = Contact(client_id=client.id, name=f"Anna Gate-{tag}")
        template = PipelineTemplate(name=f"GateTpl-{tag}")
        db.add_all([manager, template])
        await db.commit()
        await db.refresh(manager)
        await db.refresh(template)

        # Both jobs run the same template as the rejection reason — otherwise a
        # terminal move 422s on "reason belongs to another template".
        source = Job(
            title=f"GateSource-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            hiring_manager_contact_id=manager.id,
            pipeline_template_id=template.id,
        )
        target = Job(
            title=f"GateTarget-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            hiring_manager_contact_id=manager.id,
            pipeline_template_id=template.id,
        )
        reason = RejectionReason(
            template_id=template.id,
            name=f"Powod-{tag}",
            category=TerminalType.rejected,
            disqualifies_person=disqualifying,
        )
        candidate = Candidate(
            name="Jan",
            lastname=f"Gate-{tag}",
            email=f"gate-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([source, target, reason, candidate])
        await db.commit()
        await db.refresh(source)
        await db.refresh(target)
        await db.refresh(reason)
        await db.refresh(candidate)

        db.add_all(
            [
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=source.id,
                    stage=PipelineStage.client_interview,
                    moved_at=NOW - timedelta(days=40),
                ),
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=source.id,
                    stage=PipelineStage.rejected,
                    moved_at=NOW - timedelta(days=39),
                    rejection_reason_id=reason.id,
                ),
            ]
        )
        await db.commit()

        return {
            "candidate_id": candidate.id,
            "source_job_id": source.id,
            "target_job_id": target.id,
            "manager_name": manager.name,
            "reason_id": reason.id,
        }


async def _place_in_target(world: dict, stage: str = "screening") -> None:
    """Put the candidate into the target job so moves have something to move."""
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=world["candidate_id"],
                job_id=world["target_job_id"],
                stage=PipelineStage(stage),
                moved_at=NOW - timedelta(days=1),
            )
        )
        await db.commit()


async def _move(
    app_client: AsyncClient, headers: dict, world: dict, stage: str, **extra
):
    payload = {
        "candidate_id": world["candidate_id"],
        "job_id": world["target_job_id"],
        "stage": stage,
    }
    payload.update(extra)
    return await app_client.post("/api/pipeline/move", headers=headers, json=payload)


# ── Entering the manager's recruitment ──────────────────────────────────────


async def test_single_assign_is_blocked_and_names_the_manager(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed_vetoed_candidate()

    resp = await app_client.post(
        f"/api/candidates/{world['candidate_id']}"
        f"/assign-to-job/{world['target_job_id']}",
        headers=app_auth_headers,
    )

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    # "Blocked" alone would send the recruiter digging for the reason.
    assert world["manager_name"] in detail
    assert "po rozmowie" in detail


async def test_bulk_add_reports_the_veto_not_a_blacklist(
    app_client: AsyncClient, app_auth_headers: dict
):
    """The skip reason must not fall through to the "blacklisted" default."""
    world = await _seed_vetoed_candidate()

    resp = await app_client.post(
        f"/api/jobs/{world['target_job_id']}/proposals/bulk",
        headers=app_auth_headers,
        json={"candidate_ids": [world["candidate_id"]]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["added"] == []
    assert len(body["skipped"]) == 1
    row = body["skipped"][0]
    assert row["reason"] == "rejected_by_hiring_manager"
    assert world["manager_name"] in row["reason_label"]


async def test_situational_rejection_does_not_block_assign(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Rejected only because they were too expensive → still assignable."""
    world = await _seed_vetoed_candidate(disqualifying=False)

    resp = await app_client.post(
        f"/api/candidates/{world['candidate_id']}"
        f"/assign-to-job/{world['target_job_id']}",
        headers=app_auth_headers,
    )

    assert resp.status_code in (200, 201), resp.text


# ── Moving inside a pipeline ────────────────────────────────────────────────


async def test_move_to_cv_sent_is_blocked(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed_vetoed_candidate()
    await _place_in_target(world)

    resp = await _move(app_client, app_auth_headers, world, "cv_sent")

    assert resp.status_code == 409, resp.text
    assert world["manager_name"] in resp.json()["detail"]


async def test_move_to_client_interview_is_blocked(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed_vetoed_candidate()
    await _place_in_target(world)

    resp = await _move(app_client, app_auth_headers, world, "client_interview")

    assert resp.status_code == 409, resp.text


async def test_internal_move_still_works(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Otherwise every pipeline predating the feature freezes on its next step."""
    world = await _seed_vetoed_candidate()
    await _place_in_target(world, stage="new")

    resp = await _move(app_client, app_auth_headers, world, "screening")

    assert resp.status_code == 200, resp.text


async def test_hired_is_never_blocked(
    app_client: AsyncClient, app_auth_headers: dict
):
    """The manager just accepted them — blocking that would be absurd."""
    world = await _seed_vetoed_candidate()
    await _place_in_target(world, stage="negotiation")

    resp = await _move(app_client, app_auth_headers, world, "hired")

    assert resp.status_code == 200, resp.text


async def test_candidate_can_always_be_closed_out(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A vetoed candidate must still be removable from the pipeline."""
    world = await _seed_vetoed_candidate()
    await _place_in_target(world)

    resp = await _move(
        app_client,
        app_auth_headers,
        world,
        "rejected",
        rejection_reason_id=world["reason_id"],
    )

    assert resp.status_code == 200, resp.text


async def test_move_on_the_job_that_rejected_them_is_not_self_blocked(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Re-opening the very recruitment that rejected them must still work.

    The rejection row lives on that job forever; if it vetoed its own job, the
    pipeline would be frozen with no way for the recruiter to unstick it.
    """
    world = await _seed_vetoed_candidate()

    resp = await app_client.post(
        "/api/pipeline/move",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "job_id": world["source_job_id"],
            "stage": "cv_sent",
        },
    )

    assert resp.status_code == 200, resp.text
