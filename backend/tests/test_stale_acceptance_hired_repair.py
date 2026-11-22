"""„Zatrudniony” z datą akceptacji dla par z podpisaną umową (zgłoszenie 18.11.2026).

Osoba podpisana 17.09 stała w kafelku „Kandydaci do zamknięcia” jako
„Zaakceptowany od 62 dni”: kontrakt założono poza Generatorem, karta została
na „Akceptacji”, a ponowne otwarcie rekrutacji wróciło ją do kafelka.
Testy idą drogą produkcji: etapy przez ``transition_process``, kafelek przez
``closing_candidates.load``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.user import UserRole
from tests._jarvis_helpers import make_user

pytestmark = pytest.mark.asyncio

ACCEPTED_AT = datetime(2026, 9, 17, 9, 10, tzinfo=timezone.utc)


async def _seed_signed_pair(
    actor_id: int, *, last_stage: str = "acceptance"
) -> dict[str, int]:
    """Opublikowana rekrutacja, karta na ``last_stage`` od 17.09, żywy kontrakt pary."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import PipelineStage
    from app.services.recruitment_process_commands import transition_process

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Stale Acceptance {unique}")
        candidate = Candidate(
            name="Akcept",
            lastname=f"Osoba{unique}",
            email=f"stale-acceptance-{unique}@example.com",
        )
        db.add_all([client, candidate])
        await db.flush()
        job = Job(
            title=f"Tester {unique}", client_id=client.id, status=JobStatus.published
        )
        db.add(job)
        await db.flush()
        stages = ["new", "screening", last_stage]
        for offset, stage in enumerate(stages):
            await transition_process(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage(stage),
                actor_user_id=actor_id,
                moved_at=ACCEPTED_AT - timedelta(days=len(stages) - 1 - offset),
                **({"ended_by": "recruiter"} if stage == "rejected" else {}),
            )
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            job_id=job.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=date(2026, 11, 2),
            rate_unit=RateUnit.hourly,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        return {
            "candidate_id": candidate.id,
            "job_id": job.id,
            "contract_id": contract.id,
        }


async def _latest(candidate_id: int, job_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )


async def _closing_candidate_ids(admin_id: int) -> set[int]:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User
    from app.services import closing_candidates

    async with AsyncSessionLocal() as db:
        admin = await db.get(User, admin_id)
        result = await closing_candidates.load(db, admin)
        return {row.candidate_id for row in result.rows}


async def test_targets_are_the_four_pairs_from_production():
    from app.services.stale_acceptance_hired_repair import TARGETS

    assert TARGETS == (
        (111481, 484836, 669),
        (34783, 493163, 668),
        (18880, 4235, 672),
        (12858, 404749, 716),
    )


async def test_repair_hires_on_the_acceptance_day_and_clears_the_tile_once():
    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting
    from app.models.recruitment_pipeline import PipelineStage
    from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
    from app.services.stale_acceptance_hired_repair import (
        run_stale_acceptance_hired_repair,
    )

    recruiter_id, _ = await make_user(UserRole.recruiter)
    admin_id, _ = await make_user(UserRole.admin)
    seed = await _seed_signed_pair(recruiter_id)
    assert seed["candidate_id"] in await _closing_candidate_ids(admin_id)

    marker = f"test_stale_acceptance_{uuid.uuid4().hex[:8]}"
    targets = ((seed["candidate_id"], seed["job_id"], seed["contract_id"]),)
    async with AsyncSessionLocal() as db:
        summary = await run_stale_acceptance_hired_repair(
            db, targets=targets, marker=marker
        )
        await db.commit()
    assert summary["hired"] == 1
    assert summary["results"][0]["hired_on"] == "2026-09-17"

    latest = await _latest(seed["candidate_id"], seed["job_id"])
    assert latest.stage == PipelineStage.hired
    assert latest.moved_at == ACCEPTED_AT + timedelta(minutes=1)
    assert latest.moved_by is None
    async with AsyncSessionLocal() as db:
        process = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.candidate_id == seed["candidate_id"],
                RecruitmentProcess.job_id == seed["job_id"],
            )
        )
        assert process.status == ProcessStatus.closed
    assert seed["candidate_id"] not in await _closing_candidate_ids(admin_id)

    async with AsyncSessionLocal() as db:
        assert (
            await run_stale_acceptance_hired_repair(db, targets=targets, marker=marker)
            is None
        )
        await db.rollback()
        assert await db.get(AppSetting, marker) is not None


async def test_repair_skips_pairs_that_moved_on_or_do_not_match_the_contract():
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import PipelineStage
    from app.services.stale_acceptance_hired_repair import (
        run_stale_acceptance_hired_repair,
        summarize_for_log,
    )

    recruiter_id, _ = await make_user(UserRole.recruiter)
    moved_on = await _seed_signed_pair(recruiter_id, last_stage="rejected")
    other = await _seed_signed_pair(recruiter_id)

    marker = f"test_stale_acceptance_{uuid.uuid4().hex[:8]}"
    targets = (
        (moved_on["candidate_id"], moved_on["job_id"], moved_on["contract_id"]),
        (other["candidate_id"], other["job_id"], moved_on["contract_id"]),
        (other["candidate_id"], other["job_id"], 0),
    )
    async with AsyncSessionLocal() as db:
        summary = await run_stale_acceptance_hired_repair(
            db, targets=targets, marker=marker
        )
        await db.commit()
    assert summary["hired"] == 0
    assert [r["skipped"] for r in summary["results"]] == [
        "not_on_acceptance",
        "identity_mismatch",
        "contract_missing",
    ]
    assert "hired 0/3" in summarize_for_log(summary)
    assert (await _latest(moved_on["candidate_id"], moved_on["job_id"])).stage == (
        PipelineStage.rejected
    )
    assert (await _latest(other["candidate_id"], other["job_id"])).stage == (
        PipelineStage.acceptance
    )
