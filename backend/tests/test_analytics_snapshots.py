"""Testy snapshotów + cutoveru (plan PR 7).

Pokrywa: idempotentny backfill (drugi przebieg = zero insertów), brak
nadpisywania snapshotów, resolver legacy/live na granicy cutoveru
(brak overlap — jeden miesiąc = jedno źródło), 410 przy
DYNAREPORTER_MODE=off, walidację cutover_date (1. dzień miesiąca).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.analytics_snapshot import AnalyticsCutover, AnalyticsMetricSnapshot
from app.models.dr_board import DrBoardMonthlyReport
from app.models.user import User, UserRole
from app.services.analytics_snapshots import (
    BOARD_MODULE,
    backfill_board_snapshots,
    resolve_month_source,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def board_history():
    """Dwa miesiące legacy Board + czysty stan snapshotów/cutoverów."""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AnalyticsMetricSnapshot))
        await db.execute(delete(AnalyticsCutover))
        for month, revenue in (
            (date(2026, 4, 1), "100000"),
            (date(2026, 5, 1), "120000"),
        ):
            exists = await db.scalar(
                select(DrBoardMonthlyReport).where(
                    DrBoardMonthlyReport.report_month == month
                )
            )
            if exists is None:
                db.add(
                    DrBoardMonthlyReport(
                        report_month=month,
                        revenue=Decimal(revenue),
                        consultant_costs=Decimal("60000"),
                        other_costs=Decimal("10000"),
                        active_consultants=12,
                        placements=3,
                        avg_margin_per_hour=Decimal("50"),
                    )
                )
        await db.commit()
    yield


async def test_backfill_idempotent(board_history):
    async with AsyncSessionLocal() as db:
        first = await backfill_board_snapshots(db)
    assert first["inserted"] >= 2
    assert first["source_rows"] >= 2

    async with AsyncSessionLocal() as db:
        second = await backfill_board_snapshots(db)
    # Drugi przebieg: zero nowych insertów, wszystko skip (bez nadpisywania).
    assert second["inserted"] == 0
    assert second["skipped_existing"] == second["source_rows"]

    async with AsyncSessionLocal() as db:
        snap = await db.scalar(
            select(AnalyticsMetricSnapshot).where(
                AnalyticsMetricSnapshot.period_label == "2026-04"
            )
        )
    assert snap is not None
    assert snap.value["revenue"] == "100000.00"  # Numeric(12,2) -> 2 miejsca
    assert len(snap.checksum) == 64


async def test_cutover_resolver_no_overlap(board_history):
    """Granica cutoveru: miesiąc przed = legacy, od cutoveru = live."""
    async with AsyncSessionLocal() as db:
        db.add(AnalyticsCutover(module=BOARD_MODULE, cutover_date=date(2026, 6, 1)))
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert (
            await resolve_month_source(
                db, module=BOARD_MODULE, month_start=date(2026, 5, 1)
            )
            == "legacy"
        )
        assert (
            await resolve_month_source(
                db, module=BOARD_MODULE, month_start=date(2026, 6, 1)
            )
            == "live"
        )
        # moduł bez cutoveru = zawsze live
        assert (
            await resolve_month_source(
                db, module="nonexistent", month_start=date(2020, 1, 1)
            )
            == "live"
        )


# ── API: 410 przy mode=off + walidacja cutoveru ─────────────────────────────


async def _seed_admin() -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"snap-admin-{unique}@example.com"
    password = f"T3st_{unique}!S"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Snap Admin",
                role=UserRole.admin,
                is_active=True,
            )
        )
        await db.commit()
    return email, password


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


async def test_dynareporter_mode_off_gives_410(api_client, monkeypatch):
    email, password = await _seed_admin()
    resp = await api_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "off")
    r = await api_client.get("/api/dynareporter/profile/me", headers=headers)
    assert r.status_code == 410, r.text

    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "read_only")
    r2 = await api_client.get("/api/dynareporter/profile/me", headers=headers)
    assert r2.status_code == 200, r2.text


async def test_cutover_requires_first_of_month(api_client, monkeypatch):
    monkeypatch.setattr(settings, "ANALYTICS_V1_MODE", "shadow")
    email, password = await _seed_admin()
    resp = await api_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    bad = await api_client.post(
        "/api/analytics/v1/admin/cutover",
        json={"module": "finance", "cutover_date": "2026-07-15"},
        headers=headers,
    )
    assert bad.status_code == 422

    ok = await api_client.post(
        "/api/analytics/v1/admin/cutover",
        json={"module": "finance", "cutover_date": "2026-07-01"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    # sprzątanie — cutover globalnie wpływa na finance_trend w innych testach
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AnalyticsCutover))
        await db.commit()
