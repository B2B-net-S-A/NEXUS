"""503 z `/api/health` tylko przy awarii bazy, nie przy nasyconej pętli zdarzeń."""

from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient

from app import main


class _Session:
    """Pierwsza sesja to sonda bazy; pozostałe sondy dostają od razu błąd."""

    opened = 0

    async def __aenter__(self):
        type(self).opened += 1
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, *_args, **_kwargs):
        if type(self).opened > 1:
            raise RuntimeError("inna sonda")
        await asyncio.sleep(self.delay)

    def __getattr__(self, _name):
        raise RuntimeError("inna sonda")


async def _status(monkeypatch, *, delay: float, timeout: float) -> tuple[int, str]:
    import app.core.database as database

    session = type("S", (_Session,), {"opened": 0, "delay": delay})
    monkeypatch.setattr(database, "AsyncSessionLocal", session)
    monkeypatch.setattr(main, "HEALTH_DB_PING_TIMEOUT_SECONDS", timeout)
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")
    return response.status_code, response.json()["checks"]["database"]


async def test_slow_ping_inside_the_limit_is_healthy(monkeypatch) -> None:
    assert await _status(monkeypatch, delay=0.01, timeout=1.0) == (200, "healthy")


async def test_ping_over_the_limit_is_still_503(monkeypatch) -> None:
    assert await _status(monkeypatch, delay=5.0, timeout=0.01) == (503, "unhealthy")


def test_limit_outlasts_a_saturated_event_loop() -> None:
    # Zmierzone 04.11.2026: przestój pętli do 2,5 s plus wypożyczenie do 2,2 s.
    assert main.HEALTH_DB_PING_TIMEOUT_SECONDS >= 5.0
