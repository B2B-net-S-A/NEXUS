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
        resp = await app_client.get(
            "/api/talent-pools", headers=app_auth_headers
        )
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
