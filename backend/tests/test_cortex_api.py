"""API tests for /api/cortex/* (RBAC, shapes, single-flight backfill guard)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.cortex import CortexExtractionRun, CortexUnmatchedTerm
from app.models.skill import Skill, SkillAlias
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_tech_map_shape(app_client: AsyncClient, app_auth_headers):
    resp = await app_client.get("/api/cortex/tech-map", headers=app_auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    for key in (
        "cells",
        "skills",
        "skill_totals",
        "seniorities",
        "candidates_covered",
        "candidates_total",
        "fill_rate_pct",
        "sources",
        "data_as_of",
    ):
        assert key in data
    assert data["seniorities"] == ["junior", "mid", "senior", "unknown"]


@pytest.mark.asyncio
async def test_coverage_shape(app_client: AsyncClient, app_auth_headers):
    resp = await app_client.get("/api/cortex/coverage", headers=app_auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "candidates" in data and "facts" in data and "processes" in data
    assert "data_as_of" in data
    assert "with_any_fact_pct" in data["candidates"]
    assert set(data["facts"]["freshness"]) == {"lt_1y", "y1_3", "gt_3y", "unknown"}


@pytest.mark.asyncio
async def test_tech_map_rejects_recruiter(app_client: AsyncClient):
    unique = uuid.uuid4().hex[:8]
    email = f"pytest-recruiter-{unique}@example.com"
    password = f"T3st_{unique}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Pytest Recruiter",
                role=UserRole.recruiter,
                is_active=True,
            )
        )
        await db.commit()

    try:
        login = await app_client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await app_client.get("/api/cortex/tech-map", headers=headers)
        assert resp.status_code == 403
        resp = await app_client.post(
            "/api/cortex/admin/backfill-traffit", headers=headers
        )
        assert resp.status_code == 403
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(User).where(User.email == email))
            await db.commit()


@pytest.mark.asyncio
async def test_backfill_double_start_guard(app_client: AsyncClient, app_auth_headers):
    # Single-flight jest teraz trwały (partial unique `status='running'` na
    # cortex_extraction_runs): wstaw aktywny run i sprawdź że POST → 409.
    # started_at=now() (server_default) → orphan reaper go nie sprzątnie.
    async with AsyncSessionLocal() as db:
        run = CortexExtractionRun(
            run_type="manual", source="traffit", status="running"
        )
        db.add(run)
        await db.commit()
        run_id = run.id
    try:
        resp = await app_client.post(
            "/api/cortex/admin/backfill-traffit", headers=app_auth_headers
        )
        assert resp.status_code == 409
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CortexExtractionRun).where(CortexExtractionRun.id == run_id)
            )
            await db.commit()


@pytest.mark.asyncio
async def test_unmatched_terms_admin_only(app_client: AsyncClient, app_auth_headers):
    resp = await app_client.get(
        "/api/cortex/unmatched-terms", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Etap 1: Action Layer ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cortex_skills_shape(app_client: AsyncClient, app_auth_headers):
    resp = await app_client.get("/api/cortex/skills", headers=app_auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    for key in ("skills", "total", "limit", "offset"):
        assert key in data
    assert isinstance(data["skills"], list)


@pytest.mark.asyncio
async def test_cortex_client_stack_and_successors_shape(
    app_client: AsyncClient, app_auth_headers
):
    cs = await app_client.get("/api/cortex/client-stack", headers=app_auth_headers)
    assert cs.status_code == 200
    assert {"cells", "clients", "min_count"} <= set(cs.json())

    su = await app_client.get(
        "/api/cortex/successors?days=30", headers=app_auth_headers
    )
    assert su.status_code == 200
    assert "ending_contracts" in su.json()


@pytest.mark.asyncio
async def test_cortex_drilldown_rejects_recruiter(app_client: AsyncClient):
    unique = uuid.uuid4().hex[:8]
    email = f"pytest-recruiter-dd-{unique}@example.com"
    password = f"T3st_{unique}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Pytest Recruiter DD",
                role=UserRole.recruiter,
                is_active=True,
            )
        )
        await db.commit()
    try:
        login = await app_client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        # Drill-down (nazwiska) i kuracja niedostępne dla recruitera.
        assert (
            await app_client.get("/api/cortex/skill/1/candidates", headers=headers)
        ).status_code == 403
        assert (
            await app_client.post(
                "/api/cortex/skills",
                headers=headers,
                json={"canonical_name": "x"},
            )
        ).status_code == 403
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(User).where(User.email == email))
            await db.commit()


@pytest.mark.asyncio
async def test_cortex_curation_create_skill_from_term(
    app_client: AsyncClient, app_auth_headers
):
    unique = uuid.uuid4().hex[:8]
    term_text = f"kurtest-{unique}"
    canonical = f"KurTest-{unique}"
    async with AsyncSessionLocal() as db:
        t = CortexUnmatchedTerm(term=term_text, occurrences=3)
        db.add(t)
        await db.commit()
        term_id = t.id

    skill_id = None
    try:
        resp = await app_client.post(
            "/api/cortex/skills",
            headers=app_auth_headers,
            json={"canonical_name": canonical, "from_term_id": term_id},
        )
        assert resp.status_code == 200
        skill_id = resp.json()["id"]

        async with AsyncSessionLocal() as db:
            term = await db.get(CortexUnmatchedTerm, term_id)
            assert term.status == "mapped"
            alias = await db.scalar(
                select(SkillAlias).where(SkillAlias.alias == term_text)
            )
            assert alias is not None and alias.skill_id == skill_id

        # Idempotencja tworzenia: duplikat (case-insensitive) → 400.
        dup = await app_client.post(
            "/api/cortex/skills",
            headers=app_auth_headers,
            json={"canonical_name": canonical.lower()},
        )
        assert dup.status_code == 400
    finally:
        async with AsyncSessionLocal() as db:
            if skill_id:
                await db.execute(
                    delete(SkillAlias).where(SkillAlias.skill_id == skill_id)
                )
                await db.execute(delete(Skill).where(Skill.id == skill_id))
            await db.execute(
                delete(CortexUnmatchedTerm).where(CortexUnmatchedTerm.id == term_id)
            )
            await db.commit()
