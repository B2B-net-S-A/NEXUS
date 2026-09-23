"""Plik-ofiara dla ``test_conftest_live_skip_heuristic``.

Nadpisuje fixture ``client`` LOKALNIE (transport ASGI, bez serwera na :8000).
Reguła skipowania live-server w ``conftest.py`` nie może go wyciszyć —
``test_conftest_live_skip_heuristic`` uruchamia ten plik w podprocesie
i wymaga ``passed`` bez ``skipped``. Do 23.09.2026 tę rolę grał
``test_dynareporter_readonly.py`` (usunięty razem z DynaReporterem).
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


async def test_local_client_override_runs_in_process(client: AsyncClient):
    resp = await client.get("/api/health/live")
    assert resp.status_code == 200
