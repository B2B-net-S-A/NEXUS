"""Wycofywany Viewer (``user``) nie ma żadnej sekcji (0632, audyt 02.11.2026).

Rola bez nowych kont przechodziła bramki sekcji jak do odczytu, także imienne
Insights. Na kopii produkcji z 02.11.2026 nie ma ani jednego konta tej roli,
więc zerowanie nikomu nie odbiera pracy. Test pilnuje zasiewu, jednorazowego
lustra w ``entrypoint.sh`` i tego, że rola nie czyta więcej niż „Pracownik”,
który też nie ma sekcji.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.section_permission import RoleSectionPermission
from app.models.user import UserRole
from app.services import hr_schema_bundle, viewer_role_schema
from app.services.section_permissions import (
    DEFAULT_ROLE_SECTION_ACCESS,
    ProductSection,
    SectionAccess,
)

BACKEND = Path(__file__).resolve().parents[1]
GOLDEN = BACKEND / "tests" / "data" / "authz_golden"
PASSES = frozenset("PB")


def _matrix() -> dict[str, dict[str, str]]:
    routes: dict[str, dict[str, str]] = {}
    for path in sorted(GOLDEN.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for route, letters in data["routes"].items():
            routes[route] = dict(zip(data["personas"], letters, strict=True))
    return routes


def test_seed_gives_the_viewer_no_section() -> None:
    policy = DEFAULT_ROLE_SECTION_ACCESS[UserRole.user]
    assert {policy[section] for section in ProductSection} == {SectionAccess.none}


def test_viewer_passes_nothing_beyond_the_sectionless_employee() -> None:
    extra = sorted(
        route
        for route, verdicts in _matrix().items()
        if verdicts["user"] in PASSES and verdicts["employee"] not in PASSES
    )
    assert extra == []


def test_named_insights_are_closed_for_the_viewer() -> None:
    matrix = _matrix()
    insights = [
        route
        for route in matrix
        if route.startswith("GET /api/insights") or "/api/reports/" in route
    ]
    assert insights
    opened = sorted(route for route in insights if matrix[route]["user"] in PASSES)
    assert opened == []


def test_entrypoint_takes_the_one_time_statement_from_the_bundle() -> None:
    assert viewer_role_schema.ZERO_SECTIONS in hr_schema_bundle.DATA_DDL
    assert f"key = '{viewer_role_schema.MARKER}'" in viewer_role_schema.ZERO_SECTIONS


def test_migration_runs_the_same_statement() -> None:
    source = (BACKEND / "alembic/versions/0632_viewer_role_no_sections.py").read_text(
        encoding="utf-8"
    )
    assert "viewer_role_schema" in source
    assert "op.execute(schema.ZERO_SECTIONS)" in source


async def _viewer_access(db, section: str) -> str | None:
    return await db.scalar(
        select(RoleSectionPermission.access).where(
            RoleSectionPermission.role == UserRole.user.value,
            RoleSectionPermission.section == section,
        )
    )


@pytest.mark.asyncio
async def test_zeroing_runs_once_and_later_admin_decision_survives_restart() -> None:
    marker = viewer_role_schema.MARKER
    set_access = text(
        "UPDATE rbac_role_section_permissions SET access = :access "
        "WHERE role = 'user' AND section = 'insights'"
    )
    drop_marker = text("DELETE FROM app_settings WHERE key = :key")
    async with AsyncSessionLocal() as db:
        original = await _viewer_access(db, "insights")
        try:
            # Baza sprzed zmiany: wiersz „read”, bez znacznika.
            await db.execute(set_access, {"access": "read"})
            await db.execute(drop_marker, {"key": marker})
            await db.execute(text(viewer_role_schema.ZERO_SECTIONS))
            assert await _viewer_access(db, "insights") == "none"

            # Admin świadomie otwiera sekcję; kolejny start tego nie cofa.
            await db.execute(set_access, {"access": "read"})
            await db.execute(text(viewer_role_schema.ZERO_SECTIONS))
            assert await _viewer_access(db, "insights") == "read"
        finally:
            await db.rollback()
    assert original is not None
