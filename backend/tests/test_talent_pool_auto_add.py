"""Tests for auto-add candidate to talent pool on cv_sent stage change.

Coverage:
  1. Pure helpers (_derive_pool_name, _seniority_label) — no DB.
  2. Service integration: creates pool, reuses pool, idempotent, skip-no-category.
  3. Centroid invalidation on membership add.

Service module: app.services.talent_pool_auto_add
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.competence_category import CompetenceCategory
from app.models.job import Job, Seniority
from app.models.talent_pool import TalentPool, TalentPoolMembership
from sqlalchemy import select


# ── Pure unit tests (no DB) ───────────────────────────────────────────────────


def test_seniority_label_maps_enum_to_pl_label() -> None:
    from app.services.talent_pool_auto_add import _seniority_label

    assert _seniority_label(Seniority.junior) == "Junior"
    assert _seniority_label(Seniority.mid) == "Mid"
    assert _seniority_label(Seniority.senior) == "Senior"
    assert _seniority_label(Seniority.lead) == "Lead"
    assert _seniority_label(Seniority.architect) == "Architect"


def test_derive_pool_name_both_fields_present() -> None:
    from app.services.talent_pool_auto_add import _derive_pool_name

    job = Job(subcategory="Java Backend", seniority=Seniority.senior)
    assert _derive_pool_name(job) == "Java Backend Senior"


def test_derive_pool_name_only_subcategory() -> None:
    from app.services.talent_pool_auto_add import _derive_pool_name

    job = Job(subcategory="DevOps", seniority=None)
    assert _derive_pool_name(job) == "DevOps"


def test_derive_pool_name_only_seniority() -> None:
    from app.services.talent_pool_auto_add import _derive_pool_name

    job = Job(subcategory=None, seniority=Seniority.lead)
    # Fallback — seniority alone + marker
    assert _derive_pool_name(job) == "Lead — Inne"


def test_derive_pool_name_both_missing_returns_none() -> None:
    from app.services.talent_pool_auto_add import _derive_pool_name

    job = Job(subcategory=None, seniority=None)
    assert _derive_pool_name(job) is None


def test_derive_pool_name_empty_string_subcategory_treated_as_missing() -> None:
    """Trimmed empty strings should behave like NULL."""
    from app.services.talent_pool_auto_add import _derive_pool_name

    job = Job(subcategory="   ", seniority=None)
    assert _derive_pool_name(job) is None


# ── Integration tests (require DB) ────────────────────────────────────────────


async def _seed_job(
    *,
    subcategory: str | None,
    seniority: Seniority | None,
    title: str | None = None,
    competence_category_id: int | None = None,
) -> int:
    """Insert minimal Job row for tests; returns job_id."""
    async with AsyncSessionLocal() as db:
        job = Job(
            title=title or f"Test job {uuid.uuid4().hex[:6]}",
            subcategory=subcategory,
            seniority=seniority,
            competence_category_id=competence_category_id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _get_cc_id(slug: str = "software_development") -> int:
    """Return id of a seeded CompetenceCategory (migration 0033 seeds all 5)."""
    async with AsyncSessionLocal() as db:
        cc = await db.scalar(
            select(CompetenceCategory).where(CompetenceCategory.slug == slug)
        )
        assert cc is not None, f"CompetenceCategory slug={slug} not seeded"
        return cc.id


async def _seed_candidate() -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Test",
            lastname=f"Pool-{uuid.uuid4().hex[:6]}",
            email=f"pool-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _cleanup_pool_by_name(name: str) -> None:
    async with AsyncSessionLocal() as db:
        pool = await db.scalar(select(TalentPool).where(TalentPool.name == name))
        if pool is not None:
            await db.delete(pool)
            await db.commit()


@pytest.mark.asyncio
async def test_creates_new_pool_and_adds_candidate(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.services.talent_pool_auto_add import auto_add_on_cv_sent

    # Unique pool name so test is isolated
    subcategory = f"AutoTest-{uuid.uuid4().hex[:6]}"
    pool_name = f"{subcategory} Senior"

    job_id = await _seed_job(subcategory=subcategory, seniority=Seniority.senior)
    candidate_id = await _seed_candidate()

    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            assert job is not None
            result = await auto_add_on_cv_sent(
                db=db, candidate_id=candidate_id, job=job, user_id=None
            )
            await db.commit()

        assert result.status == "added"
        assert result.pool_created is True
        assert result.pool_name == pool_name

        # Verify DB state
        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            assert pool is not None
            assert (pool.criteria or {}).get("auto_source") == "cv_sent_trigger"

            membership = await db.scalar(
                select(TalentPoolMembership).where(
                    TalentPoolMembership.talent_pool_id == pool.id,
                    TalentPoolMembership.candidate_id == candidate_id,
                )
            )
            assert membership is not None
            assert membership.source_event == "cv_sent"
            assert membership.source_job_id == job_id
    finally:
        await _cleanup_pool_by_name(pool_name)


@pytest.mark.asyncio
async def test_reuses_existing_pool_for_second_candidate(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.services.talent_pool_auto_add import auto_add_on_cv_sent

    subcategory = f"AutoTest-{uuid.uuid4().hex[:6]}"
    pool_name = f"{subcategory} Mid"

    job_id = await _seed_job(subcategory=subcategory, seniority=Seniority.mid)
    c1 = await _seed_candidate()
    c2 = await _seed_candidate()

    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            r1 = await auto_add_on_cv_sent(
                db=db, candidate_id=c1, job=job, user_id=None
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            r2 = await auto_add_on_cv_sent(
                db=db, candidate_id=c2, job=job, user_id=None
            )
            await db.commit()

        assert r1.pool_created is True
        assert r2.pool_created is False
        assert r1.pool_id == r2.pool_id

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            assert pool is not None
            memberships = (
                (
                    await db.execute(
                        select(TalentPoolMembership).where(
                            TalentPoolMembership.talent_pool_id == pool.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            cand_ids = {m.candidate_id for m in memberships}
            assert c1 in cand_ids and c2 in cand_ids
    finally:
        await _cleanup_pool_by_name(pool_name)


@pytest.mark.asyncio
async def test_idempotent_same_candidate_twice(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.services.talent_pool_auto_add import auto_add_on_cv_sent

    subcategory = f"AutoTest-{uuid.uuid4().hex[:6]}"
    pool_name = f"{subcategory} Junior"

    job_id = await _seed_job(subcategory=subcategory, seniority=Seniority.junior)
    candidate_id = await _seed_candidate()

    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            r1 = await auto_add_on_cv_sent(
                db=db, candidate_id=candidate_id, job=job, user_id=None
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            r2 = await auto_add_on_cv_sent(
                db=db, candidate_id=candidate_id, job=job, user_id=None
            )
            await db.commit()

        assert r1.status == "added"
        assert r2.status == "already_in_pool"

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            count = (
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
            assert len(count) == 1
    finally:
        await _cleanup_pool_by_name(pool_name)


@pytest.mark.asyncio
async def test_skips_when_no_category(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.services.talent_pool_auto_add import auto_add_on_cv_sent

    job_id = await _seed_job(subcategory=None, seniority=None)
    candidate_id = await _seed_candidate()

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        result = await auto_add_on_cv_sent(
            db=db, candidate_id=candidate_id, job=job, user_id=None
        )
        await db.commit()

    assert result.status == "skipped_no_category"
    assert result.pool_id is None


@pytest.mark.asyncio
async def test_centroid_invalidated_on_add(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """After adding a new membership, pool.centroid_updated_at must be None."""
    from datetime import datetime, timezone
    from app.services.talent_pool_auto_add import auto_add_on_cv_sent

    subcategory = f"AutoTest-{uuid.uuid4().hex[:6]}"
    pool_name = f"{subcategory} Architect"

    job_id = await _seed_job(subcategory=subcategory, seniority=Seniority.architect)
    c1 = await _seed_candidate()
    c2 = await _seed_candidate()

    try:
        # First add creates pool
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            await auto_add_on_cv_sent(db=db, candidate_id=c1, job=job, user_id=None)
            await db.commit()

        # Simulate pool already had a computed centroid
        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            pool.centroid_updated_at = datetime.now(timezone.utc)
            pool.centroid_vector_id = "vec-123"
            await db.commit()

        # Second candidate add must invalidate centroid
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            await auto_add_on_cv_sent(db=db, candidate_id=c2, job=job, user_id=None)
            await db.commit()

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            assert pool.centroid_updated_at is None
    finally:
        await _cleanup_pool_by_name(pool_name)


# ── CC population tests (Phase 10 A2) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_add_sets_cc_id_from_job(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """New pool inherits competence_category_id from source Job."""
    from app.services.talent_pool_auto_add import auto_add_on_cv_sent

    subcategory = f"AutoTestCC-{uuid.uuid4().hex[:6]}"
    pool_name = f"{subcategory} Senior"
    cc_id = await _get_cc_id("software_development")

    job_id = await _seed_job(
        subcategory=subcategory,
        seniority=Seniority.senior,
        competence_category_id=cc_id,
    )
    candidate_id = await _seed_candidate()

    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            await auto_add_on_cv_sent(
                db=db, candidate_id=candidate_id, job=job, user_id=None
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            assert pool is not None
            assert pool.competence_category_id == cc_id
    finally:
        await _cleanup_pool_by_name(pool_name)


@pytest.mark.asyncio
async def test_auto_add_heals_missing_cc_on_existing_pool(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Pool pre-exists with CC=NULL; second cv_sent with CC-bearing job heals it."""
    from app.services.talent_pool_auto_add import auto_add_on_cv_sent

    subcategory = f"AutoTestHeal-{uuid.uuid4().hex[:6]}"
    pool_name = f"{subcategory} Mid"
    cc_id = await _get_cc_id("data_ai")

    # First job — NO CC
    job1_id = await _seed_job(
        subcategory=subcategory,
        seniority=Seniority.mid,
        competence_category_id=None,
    )
    # Second job — WITH CC
    job2_id = await _seed_job(
        subcategory=subcategory,
        seniority=Seniority.mid,
        competence_category_id=cc_id,
    )
    c1 = await _seed_candidate()
    c2 = await _seed_candidate()

    try:
        # 1st call — creates pool with CC=NULL
        async with AsyncSessionLocal() as db:
            job1 = await db.get(Job, job1_id)
            await auto_add_on_cv_sent(
                db=db, candidate_id=c1, job=job1, user_id=None
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            assert pool.competence_category_id is None

        # 2nd call — same pool, job has CC → heal
        async with AsyncSessionLocal() as db:
            job2 = await db.get(Job, job2_id)
            await auto_add_on_cv_sent(
                db=db, candidate_id=c2, job=job2, user_id=None
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            assert pool.competence_category_id == cc_id
    finally:
        await _cleanup_pool_by_name(pool_name)


@pytest.mark.asyncio
async def test_auto_add_leaves_cc_untouched_when_job_has_no_cc(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Existing pool has CC set; incoming job has CC=NULL → pool CC untouched."""
    from app.services.talent_pool_auto_add import auto_add_on_cv_sent

    subcategory = f"AutoTestKeep-{uuid.uuid4().hex[:6]}"
    pool_name = f"{subcategory} Lead"
    cc_id = await _get_cc_id("infrastructure_operations")

    job1_id = await _seed_job(
        subcategory=subcategory,
        seniority=Seniority.lead,
        competence_category_id=cc_id,
    )
    job2_id = await _seed_job(
        subcategory=subcategory,
        seniority=Seniority.lead,
        competence_category_id=None,
    )
    c1 = await _seed_candidate()
    c2 = await _seed_candidate()

    try:
        # 1st — pool gets CC
        async with AsyncSessionLocal() as db:
            job1 = await db.get(Job, job1_id)
            await auto_add_on_cv_sent(
                db=db, candidate_id=c1, job=job1, user_id=None
            )
            await db.commit()

        # 2nd — job has no CC; pool must keep its CC
        async with AsyncSessionLocal() as db:
            job2 = await db.get(Job, job2_id)
            await auto_add_on_cv_sent(
                db=db, candidate_id=c2, job=job2, user_id=None
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            assert pool.competence_category_id == cc_id
    finally:
        await _cleanup_pool_by_name(pool_name)


@pytest.mark.asyncio
async def test_auto_add_accepts_extra_activity_details(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Backfill uses extra_activity_details={'backfill': True} to tag Activity rows."""
    from app.models.activity import Activity
    from app.services.talent_pool_auto_add import auto_add_on_cv_sent

    subcategory = f"AutoTestExtra-{uuid.uuid4().hex[:6]}"
    pool_name = f"{subcategory} Junior"

    job_id = await _seed_job(subcategory=subcategory, seniority=Seniority.junior)
    candidate_id = await _seed_candidate()

    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            await auto_add_on_cv_sent(
                db=db,
                candidate_id=candidate_id,
                job=job,
                user_id=None,
                extra_activity_details={"backfill": True},
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            pool = await db.scalar(
                select(TalentPool).where(TalentPool.name == pool_name)
            )
            activities = (
                (
                    await db.execute(
                        select(Activity).where(
                            Activity.entity_type == "talent_pool",
                            Activity.entity_id == pool.id,
                            Activity.action == "candidate_auto_added",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert any(
                (a.details or {}).get("backfill") is True for a in activities
            )
    finally:
        await _cleanup_pool_by_name(pool_name)
