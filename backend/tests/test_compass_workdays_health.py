"""Sonda `checks.compass_workdays` — drabina konfiguracji i werdykt świeżości.

Do 09.2026 `compass_workdays_sync` był jedynym integratorem bez wpisu
w `/api/health.checks` i jedynym, którego awarii nie dało się wykryć niczym
innym: pętla `return`uje czysto przy wyłączonej fladze i przy braku sekretu
(`classify_background_tasks` → `exited_cleanly`, stan cichy), a jej ciało łyka
każdy wyjątek, więc nigdy nie osiąga `crashed`.

Testy dzielą się na dwie grupy, bo dwie rzeczy mogą się zepsuć niezależnie:

* **drabina** (`unconfigured` / `misconfigured`) — przez HTTP, bo rozstrzyga się
  przed jakimkolwiek I/O; wzorzec z trójki `autenti` w `test_health_v2.py`;
* **werdykt** (`healthy` / `degraded`) — na czystej funkcji, NIE przez HTTP.
  Wersja wpleciona w handler daje się bez bazy przetestować wyłącznie przez
  gałąź `except`, czyli zwracałaby właściwy wynik z niewłaściwego powodu.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.insights_workdays import workdays_sync_verdict

_INTERVAL = 21_600  # 6 h — wartość domyślna z config.py
_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


# ── drabina konfiguracji (przez HTTP) ───────────────────────────────────────


@pytest.fixture
def env_with_metadata(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("BUILT_AT", "2099-12-31T12:00:00Z")


@pytest.mark.asyncio
async def test_unconfigured_when_kill_switch_off(env_with_metadata, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.COMPASS_WORKDAYS_ENABLED", False)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")
    assert response.json()["checks"].get("compass_workdays") == "unconfigured"


@pytest.mark.asyncio
async def test_misconfigured_when_enabled_without_url_or_secret(
    env_with_metadata, monkeypatch
):
    monkeypatch.setattr("app.core.config.settings.COMPASS_WORKDAYS_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.COMPASS_WORKDAYS_URL", "")
    monkeypatch.setattr("app.core.config.settings.COMPASS_WORKDAYS_SECRET", "")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")
    assert response.json()["checks"].get("compass_workdays") == "misconfigured"


@pytest.mark.asyncio
async def test_secret_alone_is_not_enough(env_with_metadata, monkeypatch):
    """Sam sekret bez URL-a to nadal `misconfigured`.

    Pętla sprawdza OBA (`compass_workdays_sync_loop`), więc sonda, która
    pytałaby o jedno, raportowałaby gotowość do biegu, który nie wystartuje.
    """
    monkeypatch.setattr("app.core.config.settings.COMPASS_WORKDAYS_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.COMPASS_WORKDAYS_URL", "")
    monkeypatch.setattr("app.core.config.settings.COMPASS_WORKDAYS_SECRET", "s3cret")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")
    assert response.json()["checks"].get("compass_workdays") == "misconfigured"


@pytest.mark.asyncio
async def test_compass_outage_never_turns_nexus_red(env_with_metadata, monkeypatch):
    """`status` liczy się WYŁĄCZNIE z `database` — nie z tej sondy.

    Bez tego awaria cudzej aplikacji zwracałaby 503 z naszego healthchecku,
    który konsumuje docker healthcheck i smoke test deployu.
    """
    monkeypatch.setattr("app.core.config.settings.COMPASS_WORKDAYS_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.COMPASS_WORKDAYS_URL", "")
    monkeypatch.setattr("app.core.config.settings.COMPASS_WORKDAYS_SECRET", "")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")
    body = response.json()
    assert body["checks"]["compass_workdays"] == "misconfigured"
    assert body["status"] == (
        "healthy" if body["checks"]["database"] == "healthy" else "unhealthy"
    )


# ── werdykt świeżości (czysta funkcja) ──────────────────────────────────────


def test_never_ran_is_degraded():
    """Wiersz-kotwica istnieje, ale pętla nigdy nie doszła do końca."""
    assert (
        workdays_sync_verdict(
            finished_at=None, last_status=None, interval_seconds=_INTERVAL, now=_NOW
        )
        == "degraded"
    )


def test_fresh_ok_is_healthy():
    assert (
        workdays_sync_verdict(
            finished_at=_NOW - timedelta(hours=2),
            last_status="ok",
            interval_seconds=_INTERVAL,
            now=_NOW,
        )
        == "healthy"
    )


def test_one_late_run_does_not_degrade():
    """Próg to doba, nie jeden odstęp — inaczej nocny przestój alarmuje."""
    assert (
        workdays_sync_verdict(
            finished_at=_NOW - timedelta(hours=20),
            last_status="ok",
            interval_seconds=_INTERVAL,
            now=_NOW,
        )
        == "healthy"
    )


def test_stale_run_degrades():
    assert (
        workdays_sync_verdict(
            finished_at=_NOW - timedelta(days=2),
            last_status="ok",
            interval_seconds=_INTERVAL,
            now=_NOW,
        )
        == "degraded"
    )


@pytest.mark.parametrize("status", ["errors", "error", "running", None])
def test_fresh_run_that_did_not_succeed_degrades(status):
    """NAJWAŻNIEJSZY test tego pliku.

    `sync_workdays` wraca z `fetch_failed:` i `basis_mismatch:` NORMALNIE —
    nic nie zapisawszy i nie rzucając wyjątku. Gdyby `healthy` zależało od
    samej świeżości biegu, niedostępny COMPASS raportowałby zdrowie tak długo,
    jak długo pętla się budzi. To jest dokładnie ta ślepa plamka, dla której
    ta sonda powstała, więc świeży bieg bez `ok` MUSI degradować.
    """
    assert (
        workdays_sync_verdict(
            finished_at=_NOW - timedelta(minutes=5),
            last_status=status,
            interval_seconds=_INTERVAL,
            now=_NOW,
        )
        == "degraded"
    )


def test_threshold_scales_with_a_longer_interval():
    """Przy odstępie 12 h próg to 36 h, nie podłoga 24 h."""
    assert (
        workdays_sync_verdict(
            finished_at=_NOW - timedelta(hours=30),
            last_status="ok",
            interval_seconds=43_200,
            now=_NOW,
        )
        == "healthy"
    )
