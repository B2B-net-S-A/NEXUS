"""Runy integracji (scrapery pracuj.pl / JJIT): kontrakt zapisu, odczytu i zastoju.

Trzy rzeczy, których złamanie jest defektem:

1. **Reguła zastoju jest jedna** — Insights i alert Slack liczą to samo
   (``services.integration_runs.is_stale``): brak udanego runu od N godzin
   ALBO źródło nigdy nie raportowało = zastój; run ``failed`` nie ratuje.
2. **Zapis wymaga roli operacyjnej, nie admina** — scraper raportuje tokenem
   klienta OAuth działającego jako user serwisowy (migracja 0311). Viewer
   ``user`` nie może wpisać runu (403), a start → zdarzenia → finish daje
   spójne podsumowanie z licznikami i błędami per kandydat.
3. **Alert ma cooldown w bazie** — po restarcie backendu (każdy deploy)
   drugi przebieg pętli nie wysyła drugiego alertu tego samego dnia.

Router montujemy na własnej instancji FastAPI (konwencja repo — patrz
``test_insights_performance_flags.py``), prefiksy = te z ``main.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.integration_run import IntegrationAlertState, IntegrationRun
from app.models.user import User, UserRole
from app.services.integration_runs import is_stale

_WRITE = "/api/integrations"
_READ = "/api/insights/integrations"


def _build_app() -> FastAPI:
    from app.api import integrations_runs

    test_app = FastAPI()
    test_app.include_router(integrations_runs.writer, prefix=_WRITE)
    test_app.include_router(integrations_runs.reader, prefix=_READ)
    return test_app


async def _seed_user(role: UserRole) -> User:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"integ-{role.value}-{unique}@example.com",
            name=f"Integ {role.value} {unique}",
            password_hash=hash_password(f"T3st_{unique}!Integ"),
            role=role,
            is_active=True,
            profile_completed=True,
        )
        user.ensure_roles_invariant()
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.expunge(user)
        return user


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(
        subject=user.id,
        role=user.role.value,
        roles=list(user.roles or []),
        authorization_version=user.authorization_version,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def integ_client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=_build_app(), raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


# ── 1. Reguła zastoju (bez bazy) ────────────────────────────────────────────


def test_stale_when_never_reported():
    assert is_stale(None, stale_after_hours=26) is True


def test_stale_boundary_is_hours_not_days():
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(hours=25)
    old = now - timedelta(hours=27)
    assert is_stale(fresh, stale_after_hours=26, now=now) is False
    assert is_stale(old, stale_after_hours=26, now=now) is True


def test_naive_timestamp_is_treated_as_utc():
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 9, 16, 10, 0)  # brak tz — jak z fixture/SQLite
    assert is_stale(naive, stale_after_hours=26, now=now) is False


# ── 2. Zapis przez rolę operacyjną, odczyt w Insights ───────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_report_a_run(integ_client: AsyncClient):
    headers = _headers(await _seed_user(UserRole.user))
    resp = await integ_client.post(
        f"{_WRITE}/runs", headers=headers, json={"source": "jjit", "mode": "import"}
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_run_lifecycle_shows_up_in_summary(integ_client: AsyncClient):
    """start → zdarzenia → finish; podsumowanie ma liczniki, błąd i rekrutację."""
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    reader = _headers(await _seed_user(UserRole.recruiter))

    started = await integ_client.post(
        f"{_WRITE}/runs",
        headers=writer,
        json={"source": "jjit", "mode": "import", "host": "mac-artur", "version": "1.0"},
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]
    assert started.json()["status"] == "running"

    events = await integ_client.post(
        f"{_WRITE}/runs/{run_id}/events",
        headers=writer,
        json=[
            {
                "action": "created",
                "external_id": "app-1",
                "traffit_id": 62601,
                "candidate_name": "Jan Testowy",
                "offer_title": "DevOps Engineer",
                "matched_jobs": [{"job_id": 3, "title": "DevOps / Cloud Engineer", "score": 71.0}],
            },
            {
                "action": "error",
                "external_id": "app-2",
                "candidate_name": "Anna Błąd",
                "offer_title": "Java Developer",
                "error": "LLM parse error",
            },
        ],
    )
    assert events.status_code == 201, events.text
    assert events.json()["inserted"] == 2

    finished = await integ_client.patch(
        f"{_WRITE}/runs/{run_id}",
        headers=writer,
        json={
            "status": "errors",
            "stats": {"created": 1, "duplicates": 0, "errors": 1, "nexus_jobs": 1},
        },
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "errors"
    assert finished.json()["finished_at"] is not None

    summary = await integ_client.get(f"{_READ}/summary", headers=reader, params={"days": 1})
    assert summary.status_code == 200, summary.text
    body = summary.json()
    jjit = next(s for s in body["sources"] if s["source"] == "jjit")
    assert jjit["stale"] is False, "run 'errors' to nadal udany run — scraper żyje"
    assert jjit["last_run"]["id"] == run_id
    assert jjit["totals"]["created"] >= 1
    assert jjit["totals"]["errors"] >= 1
    assert any(e["external_id"] == "app-2" for e in body["recent_errors"])
    assert any(j["job_id"] == 3 for j in body["top_jobs"])

    run_events = await integ_client.get(f"{_READ}/runs/{run_id}/events", headers=reader)
    assert run_events.status_code == 200
    assert {e["action"] for e in run_events.json()} == {"created", "error"}


@pytest.mark.asyncio
async def test_failed_run_does_not_count_as_success(integ_client: AsyncClient):
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    started = await integ_client.post(
        f"{_WRITE}/runs", headers=writer, json={"source": "pracuj", "mode": "import"}
    )
    run_id = started.json()["id"]
    await integ_client.patch(
        f"{_WRITE}/runs/{run_id}",
        headers=writer,
        json={"status": "failed", "error": "login failed"},
    )
    async with AsyncSessionLocal() as db:
        from app.services.integration_runs import last_success_per_source

        last = await last_success_per_source(db)
    # Mogą istnieć inne udane runy pracuj z innych testów — ale ten konkretny
    # (failed) nie może być tym, który podniósł znacznik.
    run = None
    async with AsyncSessionLocal() as db:
        run = await db.get(IntegrationRun, run_id)
    assert run is not None and run.status == "failed"
    assert last["pracuj"] is None or last["pracuj"] != run.finished_at


@pytest.mark.asyncio
async def test_unknown_source_is_rejected(integ_client: AsyncClient):
    writer = _headers(await _seed_user(UserRole.talent_community_manager))
    resp = await integ_client.post(
        f"{_WRITE}/runs", headers=writer, json={"source": "linkedin", "mode": "import"}
    )
    assert resp.status_code == 422


# ── 3. Cooldown alertu przeżywa restart ─────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_cooldown_persists_in_db(monkeypatch):
    from app.tasks import integration_stale_alerts as task

    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        state = await db.get(IntegrationAlertState, "pracuj")
        if state is None:
            state = IntegrationAlertState(source="pracuj")
            db.add(state)
        state.last_alert_at = None
        await db.commit()

    first = await task.run_once(now=now)
    # Bez udanego runu pracuj w testowej bazie źródło jest w zastoju → 'stale'
    # (bez webhooka nie 'alerted'); jeśli inny test wpisał świeży run, 'ok'.
    assert first["pracuj"] in {"stale", "ok"}
    if first["pracuj"] == "stale":
        second = await task.run_once(now=now + timedelta(minutes=30))
        assert second["pracuj"] == "cooldown", "drugi przebieg w tej samej dobie = cooldown"
