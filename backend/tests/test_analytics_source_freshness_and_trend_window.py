"""Audyt statystyk 14.09.2026 — A07, A08, A09 (PR 2, obszar G6).

A07: `finance_trend` nie miesza w jednej kolumnie marży kontraktowej (live)
     z wynikiem po pozostałych kosztach (legacy) ani MRR z przychodem
     miesięcznym — osobne pola + ostrzeżenie o zmianie źródła w serii.
A08: koperta v1 niesie `source_watermarks` z ostatniego udanego biegu
     Traffita i obniża jakość, gdy import nie ma udanego biegu, padł albo
     jest starszy niż 36 h; `_calls_quality` patrzy na ślad synchronizacji
     CloudTalka, nie tylko na flagę włączenia.
A09: `/finance/trend` kotwiczy serię na końcu żądanego okresu — koperta
     `period` i punkty opisują to samo okno.

Dane syntetyczne; lata 2007/2008 celowo spoza zakresu innych testów (baza
testowa jest wspólna dla przebiegu).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.analytics import metrics
from app.analytics.cache import _PREFIX as ANALYTICS_CACHE_PREFIX
from app.api.analytics_v1 import _calls_quality
from app.core.cache import cache_invalidate
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.analytics_snapshot import AnalyticsCutover, AnalyticsMetricSnapshot
from app.models.call import Call, CallDirection, CallStatus
from app.models.traffit_sync_state import TraffitSyncState
from app.models.user import User, UserRole
from app.services.analytics_snapshots import BOARD_MODULE

pytestmark = pytest.mark.asyncio

DAILY = "__daily__"


# ── Pomocnicze ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def v1_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def analytics_shadow(monkeypatch):
    monkeypatch.setattr(settings, "ANALYTICS_V1_MODE", "shadow")


async def _headers(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"a07-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!A"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Audyt {role.value}",
                role=role,
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _clear_cache() -> None:
    await cache_invalidate(ANALYTICS_CACHE_PREFIX)


@pytest_asyncio.fixture
async def daily_marker():
    """Kontrolowany wiersz `__daily__`; po teście przywraca stan zastany."""
    async with AsyncSessionLocal() as db:
        existing = await db.get(TraffitSyncState, DAILY)
        saved = (
            None
            if existing is None
            else {
                "last_run_finished_at": existing.last_run_finished_at,
                "last_status": existing.last_status,
            }
        )
        if existing is not None:
            await db.delete(existing)
            await db.commit()

    async def _set(finished_at: datetime | None, status: str | None) -> None:
        async with AsyncSessionLocal() as db:
            row = await db.get(TraffitSyncState, DAILY)
            if row is None:
                row = TraffitSyncState(phase=DAILY)
                db.add(row)
            row.last_run_finished_at = finished_at
            row.last_status = status
            await db.commit()
        await _clear_cache()

    yield _set

    async with AsyncSessionLocal() as db:
        row = await db.get(TraffitSyncState, DAILY)
        if row is not None:
            await db.delete(row)
        if saved is not None:
            db.add(TraffitSyncState(phase=DAILY, **saved))
        await db.commit()
    await _clear_cache()


# ── A09: seria kotwiczona na końcu okresu ────────────────────────────────────


async def test_finance_trend_series_ends_at_requested_period_end():
    async with AsyncSessionLocal() as db:
        data, _warnings, _flag = await metrics.finance_trend(
            db, months=3, end=date(2007, 6, 30)
        )
    assert [p["month"] for p in data["months"]] == ["2007-04", "2007-05", "2007-06"]
    assert data["window"] == {"from": "2007-04", "to": "2007-06"}


async def test_finance_trend_endpoint_points_match_period_envelope(
    v1_client: AsyncClient, analytics_shadow
):
    """Okres custom w przeszłości: punkty z TEGO okna, nie z ostatnich
    miesięcy względem daty wykonania."""
    headers = await _headers(v1_client, UserRole.admin)
    await _clear_cache()
    resp = await v1_client.get(
        "/api/analytics/v1/finance/trend",
        params={
            "period": "custom",
            "date_from": "2007-04-01",
            "date_to": "2007-06-30",
            "months": 3,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"]["start"].startswith("2007-04-01")
    assert [p["month"] for p in body["data"]["months"]] == [
        "2007-04",
        "2007-05",
        "2007-06",
    ]
    assert body["data"]["window"] == {"from": "2007-04", "to": "2007-06"}


# ── A07: legacy i live pod różnymi polami + ostrzeżenie o zmianie źródła ────


async def test_finance_trend_keeps_legacy_and_live_definitions_apart():
    cutover = date(2008, 5, 1)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AnalyticsCutover))
        await db.execute(
            delete(AnalyticsMetricSnapshot).where(
                AnalyticsMetricSnapshot.period_label == "2008-04"
            )
        )
        db.add(AnalyticsCutover(module=BOARD_MODULE, cutover_date=cutover))
        db.add(
            AnalyticsMetricSnapshot(
                module=BOARD_MODULE,
                metric="board_monthly",
                period_label="2008-04",
                value={
                    "revenue": "10000",
                    "consultant_costs": "7000",
                    "other_costs": "1000",
                    "active_consultants": 4,
                },
                checksum="0" * 64,
            )
        )
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            data, warnings, _flag = await metrics.finance_trend(
                db, months=2, end=date(2008, 5, 31)
            )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AnalyticsCutover))
            await db.execute(
                delete(AnalyticsMetricSnapshot).where(
                    AnalyticsMetricSnapshot.period_label == "2008-04"
                )
            )
            await db.commit()

    legacy, live = data["months"]
    assert (legacy["source"], live["source"]) == ("legacy", "live")
    assert legacy["basis"] == "legacy_monthly_report"
    assert live["basis"] == "contracts"

    # Przychód miesięczny legacy NIE udaje MRR.
    assert legacy["mrr"] is None
    assert legacy["monthly_revenue"] == "10000.00"
    assert live["monthly_revenue"] is None
    # Marża = przychód − koszt konsultantów w OBU źródłach (3 000, nie 2 000).
    assert legacy["monthly_margin"] == "3000.00"
    # Wynik po pozostałych kosztach zna tylko legacy.
    assert legacy["result_after_other_costs"] == "2000.00"
    assert live["result_after_other_costs"] is None
    assert Decimal(live["monthly_margin"]) >= 0

    assert any("Seria łączy dwa źródła" in w for w in warnings), warnings


# ── A08: watermark i świeżość źródeł ─────────────────────────────────────────


async def _overview_quality(client: AsyncClient, headers: dict[str, str]) -> dict:
    await _clear_cache()
    resp = await client.get("/api/analytics/v1/overview", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["quality"]


async def test_traffit_watermark_and_staleness_reach_the_envelope(
    v1_client: AsyncClient, analytics_shadow, monkeypatch, daily_marker
):
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENABLED", True)
    headers = await _headers(v1_client, UserRole.admin)

    # Włączony, bez udanego biegu — zero nie jest potwierdzone.
    q = await _overview_quality(v1_client, headers)
    assert q["status"] == "partial"
    assert any("nie ma jeszcze udanego biegu" in w for w in q["warnings"]), q
    assert "traffit" not in q["source_watermarks"]

    # Świeży, udany bieg — watermark, bez obniżania jakości.
    fresh = datetime.now(timezone.utc) - timedelta(hours=1)
    await daily_marker(fresh, "ok")
    q = await _overview_quality(v1_client, headers)
    assert q["status"] == "complete", q
    assert q["source_watermarks"]["traffit"] == fresh.isoformat()

    # Przeterminowany (> 36 h) — partial + ostrzeżenie, watermark zostaje.
    stale = datetime.now(timezone.utc) - timedelta(days=3)
    await daily_marker(stale, "ok")
    q = await _overview_quality(v1_client, headers)
    assert q["status"] == "partial"
    assert any("nieaktualne" in w for w in q["warnings"]), q
    assert q["source_watermarks"]["traffit"] == stale.isoformat()

    # Ostatni bieg z błędami — partial, nawet gdy świeży.
    await daily_marker(fresh, "errors")
    q = await _overview_quality(v1_client, headers)
    assert q["status"] == "partial"
    assert any("'errors'" in w for w in q["warnings"]), q

    # Finanse liczą z kontraktów NEXUSA — świeżość Traffita ich nie dotyczy.
    await _clear_cache()
    fin = await v1_client.get("/api/analytics/v1/finance/summary", headers=headers)
    assert fin.status_code == 200, fin.text
    assert "traffit" not in fin.json()["quality"]["source_watermarks"]


async def test_traffit_disabled_means_live_ats_only(
    v1_client: AsyncClient, analytics_shadow, monkeypatch
):
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENABLED", False)
    headers = await _headers(v1_client, UserRole.admin)
    q = await _overview_quality(v1_client, headers)
    assert q["status"] == "complete"
    assert "traffit" not in q["source_watermarks"]


async def test_calls_quality_reads_sync_trace_not_only_the_flag(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", True)
    async with AsyncSessionLocal() as db:
        had_calls = (await db.scalar(select(Call.id).limit(1))) is not None
        if not had_calls:
            q = await _calls_quality(db)
            assert q.status.value == "partial"
            assert any("nie została jeszcze zsynchronizowana" in w for w in q.warnings)

        call = Call(
            direction=list(CallDirection)[0],
            status=list(CallStatus)[0],
            cloudtalk_call_id=f"a08-{uuid.uuid4().hex[:12]}",
        )
        db.add(call)
        await db.commit()
        await db.refresh(call)
        try:
            q = await _calls_quality(db)
            assert q.status.value == "complete"
            assert "cloudtalk" in q.source_watermarks
            assert (
                q.source_watermarks["cloudtalk"]
                >= (
                    call.updated_at.replace(tzinfo=timezone.utc)
                    if call.updated_at.tzinfo is None
                    else call.updated_at
                ).isoformat()[:19]
            )
        finally:
            await db.delete(call)
            await db.commit()

    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", False)
    async with AsyncSessionLocal() as db:
        q = await _calls_quality(db)
    assert q.status.value == "unavailable"
