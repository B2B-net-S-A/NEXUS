"""API-level tests for /api/talent-pools — response shape with CC fields (Phase 10 A2)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.competence_category import CompetenceCategory
from app.models.talent_pool import TalentPool


pytestmark = pytest.mark.asyncio


async def _cleanup_pool_by_name(name: str) -> None:
    async with AsyncSessionLocal() as db:
        pool = await db.scalar(select(TalentPool).where(TalentPool.name == name))
        if pool is not None:
            await db.delete(pool)
            await db.commit()


async def test_list_pools_returns_cc_slug_when_set(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Pool with competence_category_id populated → response includes slug."""
    suffix = uuid.uuid4().hex[:6]
    name_with_cc = f"APITestCC-{suffix} With"
    name_without_cc = f"APITestCC-{suffix} Without"

    # Fetch a seeded CC id
    async with AsyncSessionLocal() as db:
        cc = await db.scalar(
            select(CompetenceCategory).where(
                CompetenceCategory.slug == "software_development"
            )
        )
        assert cc is not None
        cc_id = cc.id
        cc_slug = cc.slug

        # Seed two pools — one with CC, one without
        pool_with = TalentPool(
            name=name_with_cc,
            description="API test pool with CC",
            criteria={},
            competence_category_id=cc_id,
        )
        pool_without = TalentPool(
            name=name_without_cc,
            description="API test pool without CC",
            criteria={},
        )
        db.add_all([pool_with, pool_without])
        await db.commit()

    try:
        resp = await app_client.get("/api/talent-pools", headers=app_auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        pool_with_data = next((p for p in data if p["name"] == name_with_cc), None)
        pool_without_data = next(
            (p for p in data if p["name"] == name_without_cc), None
        )

        assert pool_with_data is not None, "Seeded pool with CC not in response"
        assert pool_without_data is not None, "Seeded pool without CC not in response"

        assert pool_with_data["competence_category_id"] == cc_id
        assert pool_with_data["competence_category_slug"] == cc_slug

        assert pool_without_data["competence_category_id"] is None
        assert pool_without_data["competence_category_slug"] is None
    finally:
        await _cleanup_pool_by_name(name_with_cc)
        await _cleanup_pool_by_name(name_without_cc)


async def test_pool_candidate_pages_with_one_added_at_have_no_repeats(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Audyt r5: wpisy z jednej transakcji mają to samo ``added_at``;
    przejście stron listy członków puli nie dubluje ani nie gubi osób."""
    from datetime import datetime, timezone

    from sqlalchemy import delete

    from app.models.candidate import Candidate, CandidateStatus
    from app.models.talent_pool import TalentPoolMembership

    suffix = uuid.uuid4().hex[:6]
    name = f"APITestPage-{suffix}"
    stamp = datetime(2026, 11, 24, 3, 0, tzinfo=timezone.utc)
    cand_ids: set[int] = set()
    async with AsyncSessionLocal() as db:
        pool = TalentPool(name=name, description="paging", criteria={})
        db.add(pool)
        await db.flush()
        pool_id = pool.id
        for n in range(13):
            cand = Candidate(
                name="Test",
                lastname=f"page{suffix}_{n}",
                email=f"page{suffix}_{n}@example.com",
                status=CandidateStatus.active,
            )
            db.add(cand)
            await db.flush()
            cand_ids.add(cand.id)
            db.add(
                TalentPoolMembership(
                    talent_pool_id=pool_id, candidate_id=cand.id, added_at=stamp
                )
            )
        await db.commit()
    try:
        seen: list[int] = []
        for offset in (0, 3, 6, 9, 12):
            resp = await app_client.get(
                f"/api/talent-pools/{pool_id}/candidates",
                params={"limit": 3, "offset": offset},
                headers=app_auth_headers,
            )
            assert resp.status_code == 200, resp.text
            seen.extend(c["id"] for c in resp.json()["candidates"])
        assert len(seen) == len(set(seen)) == 13
        assert set(seen) == cand_ids
    finally:
        await _cleanup_pool_by_name(name)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Candidate).where(Candidate.id.in_(cand_ids)))
            await db.commit()
