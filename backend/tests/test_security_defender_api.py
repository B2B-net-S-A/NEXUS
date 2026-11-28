"""Źródło „Microsoft Defender” na Postgresie: odczyt Graph (MockTransport),
znaleziska, zamykanie, dzwonek do adminów, kafelek i tabela źródeł.

Dane fikcyjne: ``tests/data/security/defender_*_example.json``.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType
from app.models.security import SecurityEvent, SecurityFinding, SecuritySourceState
from app.models.user import User, UserRole
from app.services import security_defender as d
from app.services.m365 import defender_auth

DATA = Path(__file__).resolve().parent / "data" / "security"
INCIDENTS = json.loads((DATA / "defender_incidents_example.json").read_text())
SCORE = json.loads((DATA / "defender_secure_score_example.json").read_text())
API = "/api/security"
NOW = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
async def _clean(monkeypatch: pytest.MonkeyPatch):
    s = defender_auth.settings
    monkeypatch.setattr(s, "DEFENDER_CLIENT_ID", "test-client")
    monkeypatch.setattr(s, "DEFENDER_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(s, "DEFENDER_TENANT_ID", "example.onmicrosoft.com")
    monkeypatch.setattr(
        defender_auth, "acquire_defender_token", lambda force_refresh=False: "t"
    )
    async with AsyncSessionLocal() as db:
        for model in (SecurityFinding, SecurityEvent, SecuritySourceState):
            await db.execute(delete(model).where(model.source == "defender"))
        await db.execute(
            delete(Notification).where(
                Notification.notification_type
                == NotificationType.security_defender_incident
            )
        )
        await db.commit()
    yield


def _client(incidents: list[dict], *, fail: int | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail is not None:
            return httpx.Response(fail, text="szczegóły, których nie zapisujemy")
        if request.url.path.endswith("/security/secureScores"):
            return httpx.Response(200, json=SCORE)
        flt = request.url.params.get("$filter", "")
        rows = [
            i
            for i in incidents
            if (flt.startswith("status eq") and f"'{i.get('status')}'" in flt)
            or flt.startswith("lastUpdateDateTime")
        ]
        return httpx.Response(200, json={"value": rows})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _sync(incidents: list[dict], **kw) -> d.DefenderSyncResult:
    async with AsyncSessionLocal() as db, _client(incidents, **kw) as client:
        return await d.sync_defender(db, client, now=NOW)


async def _findings() -> dict[str, SecurityFinding]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(SecurityFinding).where(SecurityFinding.source == "defender")
        )
        return {r.fingerprint: r for r in rows}


async def _bells() -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(Notification).where(
                    Notification.notification_type
                    == NotificationType.security_defender_incident
                )
            )
        )


async def _admin() -> User:
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"def-admin-{uuid.uuid4().hex[:8]}@example.com",
            name="Admin testowy",
            role=UserRole.admin,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def test_first_read_opens_findings_rings_admins_and_second_read_is_quiet() -> (
    None
):
    admin = await _admin()
    result = await _sync(INCIDENTS["value"])
    assert result.ok and result.open == 2 and result.new == 2

    rows = await _findings()
    assert set(rows) == {"101", "102"}
    assert rows["101"].severity == "high" and rows["101"].status == "open"
    assert "[e-mail]" in rows["101"].title and "@" not in rows["101"].title
    assert rows["101"].scanner == "defender"

    bells = await _bells()
    mine = [b for b in bells if b.user_id == admin.id]
    assert len(mine) == 1  # tylko High (101); informacja (102) nie dzwoni
    assert mine[0].related_entity_id == rows["101"].id
    assert "203.0.113" not in mine[0].message and "osoba@" not in mine[0].message
    assert "· nieprzypisany. Otwórz go" in mine[0].message

    again = await _sync(INCIDENTS["value"])
    assert again.new == 0 and again.bells == 0
    assert len(await _bells()) == len(bells)

    async with AsyncSessionLocal() as db:
        refs = set(
            await db.scalars(
                select(SecurityEvent.ref).where(SecurityEvent.source == "defender")
            )
        )
        state = await db.get(SecuritySourceState, "defender")
    assert "defender:101:open" in refs and "defender:103:resolved" in refs
    assert state.detail["secure_score"] == 69.45 and state.last_error is None


async def test_resolved_in_defender_closes_finding_even_with_exception() -> None:
    await _sync(INCIDENTS["value"])
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(SecurityFinding).where(
                SecurityFinding.source == "defender",
                SecurityFinding.fingerprint == "101",
            )
        )
        row.status = "excepted"
        row.exception_reason = "sprawdzamy z dostawcą"
        row.exception_until = (NOW + timedelta(days=10)).date()
        await db.commit()

    later = copy.deepcopy(INCIDENTS["value"])
    for incident in later:
        if incident["id"] == "101":
            incident["status"] = "resolved"
            incident["lastUpdateDateTime"] = "2026-11-28T11:00:00Z"
    result = await _sync(later)
    rows = await _findings()
    assert rows["101"].status == "fixed"
    assert rows["101"].closed_note == "Incydent zamknięty w Defenderze"
    assert rows["102"].status == "open"
    assert result.closed >= 1


async def test_incident_gone_from_full_read_is_closed() -> None:
    """Oba odczyty z tym samym zegarem (NOW) — zamykanie nie może zależeć od czasu biegu."""
    await _sync(INCIDENTS["value"])
    only_101 = [i for i in INCIDENTS["value"] if i["id"] == "101"]
    await _sync(only_101)
    rows = await _findings()
    assert rows["101"].status == "open" and rows["102"].status == "fixed"


async def test_reopened_high_incident_rings_again() -> None:
    admin = await _admin()
    await _sync(INCIDENTS["value"])
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Notification).where(
                Notification.notification_type
                == NotificationType.security_defender_incident
            )
        )
        await db.commit()
    resolved = copy.deepcopy(INCIDENTS["value"])
    resolved[0]["status"] = "resolved"
    await _sync(resolved)
    assert (await _findings())["101"].status == "fixed"
    await _sync(INCIDENTS["value"])
    assert (await _findings())["101"].status == "open"
    assert any(b.user_id == admin.id for b in await _bells())


async def test_graph_error_keeps_findings_and_shows_failing(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    await _sync(INCIDENTS["value"])
    result = await _sync([], fail=403)
    assert result.configured and not result.ok
    rows = await _findings()
    assert rows["101"].status == "open"  # błąd odczytu niczego nie zamyka
    overview = (
        await app_client.get(f"{API}/overview", headers=app_auth_headers)
    ).json()
    source = next(s for s in overview["sources"] if s["key"] == "defender")
    assert source["state"] == "failing" and source["detail"] == "HTTP 403"
    assert "szczegóły" not in json.dumps(overview, ensure_ascii=False)


async def test_overview_tile_source_and_portal_link(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    async with AsyncSessionLocal() as db, _client(INCIDENTS["value"]) as client:
        await d.sync_defender(db, client)  # teraz — źródło „na żywo”
    overview = (
        await app_client.get(f"{API}/overview", headers=app_auth_headers)
    ).json()
    tile = overview["tiles"]["defender"]
    assert tile["configured"] and tile["connected"]
    assert tile["open"] == 2 and tile["urgent"] == 1
    assert tile["secure_score"] == 69.45
    source = next(s for s in overview["sources"] if s["key"] == "defender")
    assert source["state"] == "live"
    finding = next(
        f
        for f in overview["waiting"]
        if f["source"] == "defender" and f["severity"] == "high"
    )
    assert finding["link"].startswith("https://security.microsoft.com/incidents/")
    assert "tid=" not in finding["link"]


async def test_unconfigured_source_is_not_an_error(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(defender_auth.settings, "DEFENDER_CLIENT_ID", "")
    overview = (
        await app_client.get(f"{API}/overview", headers=app_auth_headers)
    ).json()
    source = next(s for s in overview["sources"] if s["key"] == "defender")
    assert source["state"] == "unconfigured"
    assert source["state_label"] == "nieskonfigurowane"
    assert overview["tiles"]["defender"]["configured"] is False
