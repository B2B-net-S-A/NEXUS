"""`/api/health/live` — the container probe must not depend on the database.

Docker's healthcheck used to call `/api/health`, which runs a dozen database
and external probes. During a heavy full candidate search it missed the 5 s
window three times in a row, Docker marked a working backend unhealthy and
Traefik stopped routing to it ("no available server").
"""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

yaml = pytest.importorskip("yaml")


class _Unreachable:
    """Any attempt to open a session or connection fails loudly."""

    def __call__(self, *args, **kwargs):
        raise AssertionError("/api/health/live must not touch the database")

    def __getattr__(self, name):
        raise AssertionError("/api/health/live must not touch the database")


async def test_live_answers_without_the_database(monkeypatch):
    import app.core.database as database

    # `/api/health` imports these inside the handler; a liveness handler that
    # started doing the same would now hit the tripwire instead of the pool.
    monkeypatch.setattr(database, "AsyncSessionLocal", _Unreachable())
    monkeypatch.setattr(database, "engine", _Unreachable())
    monkeypatch.setenv("GIT_SHA", "abc1234")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive", "version": "abc1234"}


async def test_live_needs_no_authentication():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health/live")

    assert response.status_code == 200


def test_container_probe_asks_liveness_and_smoke_keeps_the_full_check():
    repo = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((repo / "docker-compose.yml").read_text("utf-8"))
    probe = " ".join(compose["services"]["backend"]["healthcheck"]["test"])
    assert probe.endswith("/api/health/live")

    deploy = (repo / ".github" / "workflows" / "deploy.yml").read_text("utf-8")
    assert '"$APP_URL/api/health"' in deploy, (
        "the post-deploy smoke test must keep checking the database-backed "
        "/api/health — liveness says nothing about a broken database"
    )
