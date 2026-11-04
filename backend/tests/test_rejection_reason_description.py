"""Odrzucenie z uzasadnieniem i wcześniejsze rozmowy u klienta (20.10.2026).

Delivery Lead odrzucał osobę, bo była już na rozmowie u managera tej
rekrutacji, i nie miał gdzie tego napisać: przy „Inne” w historii zostawało
samo słowo. Teraz „Inne” i „Już po rozmowie u tego hiring managera” wymagają
opisu, a przegląd DL zna rozmowy osoby w innych rekrutacjach klienta.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.contact import Contact
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.pipeline_template import (
    PipelineStageDef,
    RejectionReason,
    StageCategoryEnum,
    TerminalType,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from app.services import dl_review, earlier_client_interviews
from app.services.rejection_reason_labels import HM_ALREADY_INTERVIEWED
from tests.test_board_tasks import (  # noqa: F401 — api_client to fixture
    _cleanup,
    _login,
    _seed_user,
    _seed_world,
    api_client,
    seed_entry_row,
)


async def _rejected_def(template_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(PipelineStageDef.id).where(
                PipelineStageDef.template_id == template_id,
                PipelineStageDef.terminal_type == TerminalType.rejected,
            )
        )


async def _reason(template_id: int, name: str) -> int:
    async with AsyncSessionLocal() as db:
        reason = RejectionReason(
            template_id=template_id, name=name, category=TerminalType.rejected
        )
        db.add(reason)
        await db.commit()
        return reason.id


@pytest.mark.asyncio
async def test_reasons_that_say_nothing_alone_refuse_a_move_without_description(
    api_client: AsyncClient,  # noqa: F811 — fixture z test_board_tasks
) -> None:
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    admin_id, admin_creds = await _seed_user(UserRole.admin)
    rejected = await _rejected_def(world["template_id"])
    other = await _reason(world["template_id"], "Inne (rejected)")
    hm = await _reason(world["template_id"], HM_ALREADY_INTERVIEWED)
    base = {
        "candidate_id": world["candidate_id"],
        "job_id": world["job_id"],
        "stage_def_id": rejected,
    }
    try:
        admin = await _login(api_client, admin_creds)
        for reason_id, label in ((other, "Inne"), (hm, "Już po rozmowie")):
            refused = await api_client.post(
                "/api/pipeline/move",
                headers=admin,
                json={**base, "rejection_reason_id": reason_id, "notes": "   "},
            )
            assert refused.status_code == 422, refused.text
            assert label in refused.json()["detail"]

        text = "Była 21.08 na rozmowie u tego managera (Rating & Limit)."
        ok = await api_client.post(
            "/api/pipeline/move",
            headers=admin,
            json={**base, "rejection_reason_id": hm, "notes": text},
        )
        assert ok.status_code == 200, ok.text
        async with AsyncSessionLocal() as db:
            row = await db.get(CandidateStage, ok.json()["id"])
            assert row.rejection_reason_id == hm
            assert row.notes == text
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateStage).where(
                    CandidateStage.candidate_id == world["candidate_id"]
                )
            )
            await db.execute(
                delete(RejectionReason).where(
                    RejectionReason.template_id == world["template_id"]
                )
            )
            await db.commit()
        await _cleanup(world, [admin_id])


@pytest.mark.asyncio
async def test_earlier_interviews_at_the_client_mark_the_same_hiring_manager() -> None:
    world = await _seed_world()
    cid = world["candidate_id"]
    now = datetime.now(timezone.utc)
    extra_jobs: list[int] = []
    async with AsyncSessionLocal() as db:
        manager = Contact(client_id=world["client_id"], name="Anna Manager")
        other_manager = Contact(client_id=world["client_id"], name="Piotr Inny")
        db.add_all([manager, other_manager])
        await db.flush()
        job = await db.get(Job, world["job_id"])
        job.hiring_manager_contact_id = manager.id

        def _job(title: str, contact_id: int) -> Job:
            return Job(
                title=title,
                location="Warszawa",
                status=JobStatus.published,
                remote_policy=RemotePolicy.hybrid,
                client_id=world["client_id"],
                hiring_manager_contact_id=contact_id,
            )

        prep_def = PipelineStageDef(
            template_id=world["template_id"],
            name="Interview - Prep",
            order=50,
            category=StageCategoryEnum.internal,
            legacy_enum_value="interview",
        )
        db.add(prep_def)
        same = _job("Rating & Limit", manager.id)
        different = _job("SD Collateral", other_manager.id)
        only_cv = _job("ICART", manager.id)
        only_prep = _job("Prep only", manager.id)
        db.add_all([same, different, only_cv, only_prep])
        await db.flush()
        extra_jobs = [same.id, different.id, only_cv.id, only_prep.id]

        def _row(job_id: int, stage: PipelineStage, days_ago: int) -> CandidateStage:
            return CandidateStage(
                candidate_id=cid,
                job_id=job_id,
                stage=stage,
                moved_at=now - timedelta(days=days_ago),
            )

        db.add_all(
            [
                _row(same.id, PipelineStage.cv_sent, 62),
                _row(same.id, PipelineStage.client_interview, 60),
                _row(same.id, PipelineStage.rejected, 30),
                _row(different.id, PipelineStage.cv_sent, 50),
                _row(different.id, PipelineStage.client_interview, 45),
                # Samo CV u managera to nie rozmowa.
                _row(only_cv.id, PipelineStage.cv_sent, 10),
                # Prep leży w kolumnie rozmowy, ale manager osoby nie widział.
                CandidateStage(
                    candidate_id=cid,
                    job_id=only_prep.id,
                    stage=PipelineStage.interview,
                    stage_def_id=prep_def.id,
                    moved_at=now - timedelta(days=5),
                ),
                # Ta sama rekrutacja nigdy nie jest „wcześniejszą”.
                _row(world["job_id"], PipelineStage.client_interview, 1),
            ]
        )
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, world["job_id"])
            found = await earlier_client_interviews.load(
                db,
                job=job,
                candidate_id=cid,
                client_ids={world["client_id"]},
                stage_labels=dl_review.OUTCOME_LABELS,
            )
        assert [(i.job_title, i.same_hiring_manager) for i in found] == [
            ("SD Collateral", False),
            ("Rating & Limit", True),
        ]
        assert found[1].latest_stage == "Odrzucony"
        assert found[0].latest_stage == "Rozmowa u klienta"
        assert (now - found[1].interview_at).days == 60
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.candidate_id == cid)
            )
            job = await db.get(Job, world["job_id"])
            job.hiring_manager_contact_id = None
            await db.execute(delete(Job).where(Job.id.in_(extra_jobs)))
            await db.flush()
            await db.execute(
                delete(Contact).where(Contact.client_id == world["client_id"])
            )
            await db.commit()
        await _cleanup(world, [])
