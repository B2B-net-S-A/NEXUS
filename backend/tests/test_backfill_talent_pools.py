"""Tests for backfill_talent_pools script (Phase 10 A2).

Covers:
  Phase A (CC backfill):
    - Pools get CC from source jobs' mode (lineage takes priority)
    - Pools get CC from a deterministic name classification when lineage lacks CC
    - Pools stay NULL when neither lineage nor the name yields a CC
  Phase B (memberships backfill):
    - Idempotent (run 2×, identical counts)
    - Skip jobs without subcategory + seniority
    - Dry-run writes nothing
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.competence_category import CompetenceCategory
from app.models.job import Job, Seniority
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.talent_pool import TalentPool, TalentPoolMembership
from scripts.backfill_talent_pools import (
    _backfill_cc,
    _backfill_memberships,
)


pytestmark = pytest.mark.asyncio


async def _get_cc_id(slug: str) -> int:
    async with AsyncSessionLocal() as db:
        cc = await db.scalar(
            select(CompetenceCategory).where(CompetenceCategory.slug == slug)
        )
        assert cc is not None, f"CC {slug} not seeded"
        return cc.id


async def _seed_candidate() -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Backfill",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"bf-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _seed_job(
    *,
    subcategory: str | None,
    seniority: Seniority | None,
    cc_id: int | None,
) -> int:
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"BFClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"BF Job {uuid.uuid4().hex[:6]}",
            subcategory=subcategory,
            seniority=seniority,
            competence_category_id=cc_id,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_candidate_stage_cv_sent(
    candidate_id: int, job_id: int, moved_at: datetime | None = None
) -> int:
    async with AsyncSessionLocal() as db:
        cs = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage.cv_sent,
            moved_at=moved_at or datetime.now(timezone.utc),
        )
        db.add(cs)
        await db.commit()
        await db.refresh(cs)
        return cs.id


async def _cleanup_pool_by_name(name: str) -> None:
    async with AsyncSessionLocal() as db:
        pool = await db.scalar(select(TalentPool).where(TalentPool.name == name))
        if pool is not None:
            await db.delete(pool)
            await db.commit()


# ── Phase A: CC backfill ──────────────────────────────────────────────────────


async def test_backfill_cc_populates_from_source_jobs() -> None:
    """Pool with CC=NULL and memberships tied to a CC-bearing job gets CC."""
    subcategory = f"BFCC-{uuid.uuid4().hex[:6]}"
    pool_name = f"{subcategory} Senior"
    cc_id = await _get_cc_id("data_ai")

    job_id = await _seed_job(
        subcategory=subcategory, seniority=Seniority.senior, cc_id=cc_id
    )
    candidate_id = await _seed_candidate()

    # Seed pool with CC=NULL and a membership pointing to CC-bearing job
    async with AsyncSessionLocal() as db:
        pool = TalentPool(
            name=pool_name,
            description="BF test",
            criteria={},
            competence_category_id=None,
        )
        db.add(pool)
        await db.commit()
        await db.refresh(pool)

        m = TalentPoolMembership(
            talent_pool_id=pool.id,
            candidate_id=candidate_id,
            source_event="cv_sent",
            source_job_id=job_id,
        )
        db.add(m)
        await db.commit()

    try:
        updated = await _backfill_cc(commit=True)
        assert updated >= 1

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            assert pool.competence_category_id == cc_id
    finally:
        await _cleanup_pool_by_name(pool_name)


async def test_backfill_cc_leaves_null_when_source_jobs_lack_cc() -> None:
    """Pool stays NULL when neither lineage nor the name yields a CC.

    The synthetic ``BFCC-<hex>`` subcategory is intentionally a non-role name
    so the name-classifier fallback also returns None — otherwise the fallback
    would categorise it (see test_backfill_cc_falls_back_to_name_when_no_lineage_cc).
    """
    subcategory = f"BFCC-{uuid.uuid4().hex[:6]}"
    pool_name = f"{subcategory} Junior"

    job_id = await _seed_job(
        subcategory=subcategory, seniority=Seniority.junior, cc_id=None
    )
    candidate_id = await _seed_candidate()

    async with AsyncSessionLocal() as db:
        pool = TalentPool(
            name=pool_name,
            description="BF test null",
            criteria={},
            competence_category_id=None,
        )
        db.add(pool)
        await db.commit()
        await db.refresh(pool)

        m = TalentPoolMembership(
            talent_pool_id=pool.id,
            candidate_id=candidate_id,
            source_event="cv_sent",
            source_job_id=job_id,
        )
        db.add(m)
        await db.commit()

    try:
        await _backfill_cc(commit=True)

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            assert pool.competence_category_id is None
    finally:
        await _cleanup_pool_by_name(pool_name)


async def test_backfill_cc_falls_back_to_name_when_no_lineage_cc() -> None:
    """No source-job CC → pool CC is derived from a name classification.

    Mirrors production, where every job has CC=NULL: lineage yields nothing, so
    the deterministic name classifier ("DevOps …" → infrastructure_operations)
    is what actually categorises the legacy pools.
    """
    infra_id = await _get_cc_id("infrastructure_operations")
    pool_name = f"DevOps {uuid.uuid4().hex[:6]}"

    job_id = await _seed_job(
        subcategory="DevOps", seniority=Seniority.senior, cc_id=None
    )
    candidate_id = await _seed_candidate()

    async with AsyncSessionLocal() as db:
        pool = TalentPool(
            name=pool_name,
            description="BF test name-fallback",
            criteria={},
            competence_category_id=None,
        )
        db.add(pool)
        await db.commit()
        await db.refresh(pool)

        m = TalentPoolMembership(
            talent_pool_id=pool.id,
            candidate_id=candidate_id,
            source_event="cv_sent",
            source_job_id=job_id,
        )
        db.add(m)
        await db.commit()

    try:
        await _backfill_cc(commit=True)

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            assert pool.competence_category_id == infra_id
    finally:
        await _cleanup_pool_by_name(pool_name)


# ── Phase B: memberships backfill ─────────────────────────────────────────────


async def test_backfill_memberships_idempotent() -> None:
    """Running the backfill twice must not duplicate memberships."""
    subcategory = f"BFMem-{uuid.uuid4().hex[:6]}"
    pool_name = f"{subcategory} Mid"
    cc_id = await _get_cc_id("software_development")

    job_id = await _seed_job(
        subcategory=subcategory, seniority=Seniority.mid, cc_id=cc_id
    )
    candidate_id = await _seed_candidate()
    await _seed_candidate_stage_cv_sent(candidate_id, job_id)

    try:
        # 1st run — should add
        added1, already1 = await _backfill_memberships(
            commit=True, since=None
        )

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            assert pool is not None
            memberships_after_1st = (
                (
                    await db.execute(
                        select(TalentPoolMembership).where(
                            TalentPoolMembership.talent_pool_id == pool.id,
                            TalentPoolMembership.candidate_id == candidate_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            count_1st = len(memberships_after_1st)

        # 2nd run — should be no-op for this pair
        await _backfill_memberships(commit=True, since=None)

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            memberships_after_2nd = (
                (
                    await db.execute(
                        select(TalentPoolMembership).where(
                            TalentPoolMembership.talent_pool_id == pool.id,
                            TalentPoolMembership.candidate_id == candidate_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(memberships_after_2nd) == count_1st == 1
    finally:
        await _cleanup_pool_by_name(pool_name)


async def test_backfill_skips_jobs_without_subcategory_and_seniority() -> None:
    """Jobs with neither subcategory nor seniority → skipped (no pool created)."""
    job_id = await _seed_job(subcategory=None, seniority=None, cc_id=None)
    candidate_id = await _seed_candidate()
    await _seed_candidate_stage_cv_sent(candidate_id, job_id)

    # Before: no pool should exist for this candidate via this job
    async with AsyncSessionLocal() as db:
        memberships_before = (
            (
                await db.execute(
                    select(TalentPoolMembership).where(
                        TalentPoolMembership.candidate_id == candidate_id,
                        TalentPoolMembership.source_job_id == job_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(memberships_before) == 0

    await _backfill_memberships(commit=True, since=None)

    # After: still nothing — job lacks category
    async with AsyncSessionLocal() as db:
        memberships_after = (
            (
                await db.execute(
                    select(TalentPoolMembership).where(
                        TalentPoolMembership.candidate_id == candidate_id,
                        TalentPoolMembership.source_job_id == job_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(memberships_after) == 0


async def test_backfill_dry_run_no_writes() -> None:
    """Dry-run must not persist any new memberships."""
    subcategory = f"BFDryRun-{uuid.uuid4().hex[:6]}"
    pool_name = f"{subcategory} Architect"

    cc_id = await _get_cc_id("security_quality")
    job_id = await _seed_job(
        subcategory=subcategory, seniority=Seniority.architect, cc_id=cc_id
    )
    candidate_id = await _seed_candidate()
    await _seed_candidate_stage_cv_sent(candidate_id, job_id)

    try:
        # Dry-run
        await _backfill_memberships(commit=False, since=None)

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            # Pool creation is inside the backfill session which is rolled
            # back in dry-run, so no pool should exist.
            assert pool is None, (
                f"Dry-run should NOT create pool, but {pool_name!r} exists"
            )
    finally:
        await _cleanup_pool_by_name(pool_name)
