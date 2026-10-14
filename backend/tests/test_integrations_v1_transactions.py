"""Błąd trasy v1 wycofuje transakcję żądania (bez bazy).

Przegląd PR 2A (14.10.2026): ``IntegrationRoute`` zamieniał ``HTTPException``
w odpowiedź JSON wewnątrz handlera trasy. Stos zależności (``get_db``) widział
wtedy normalny koniec i robił COMMIT zamiast ROLLBACK — paragon idempotencji
zostawał ``pending`` na zawsze (każda powtórka = 409 „trwa”), a import MD
przerwany konfliktem zostawiał zatwierdzoną partię bez zużycia. Wyjątek musi
przejść przez stos zależności; kopertę v1 buduje handler aplikacji.
"""

from __future__ import annotations

from unittest import mock

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException

import app.core.database as dbmod
from app.api.integrations_v1.common import (
    IntegrationApiError,
    IntegrationRoute,
    integration_error_handler,
)

pytestmark = pytest.mark.asyncio


class _FakeSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        self.events.append("COMMIT")

    async def rollback(self):
        self.events.append("ROLLBACK")

    async def close(self):
        self.events.append("close")


def _app(events: list[str]) -> FastAPI:
    router = APIRouter(route_class=IntegrationRoute)

    async def failing(db=Depends(dbmod.get_db)):
        events.append("flushed")
        raise HTTPException(409, detail={"error": "duplicate_import", "message": "x"})

    async def ok(db=Depends(dbmod.get_db)):
        events.append("flushed")
        return {"ok": True}

    router.add_api_route("/fail", failing, methods=["POST"])
    router.add_api_route("/ok", ok, methods=["POST"])
    app = FastAPI()
    app.add_exception_handler(IntegrationApiError, integration_error_handler)
    app.include_router(router)
    return app


async def _call(path: str) -> tuple[httpx.Response, list[str]]:
    events: list[str] = []
    with mock.patch.object(dbmod, "AsyncSessionLocal", lambda: _FakeSession(events)):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app(events)), base_url="http://t"
        ) as client:
            return await client.post(path), events


async def test_error_rolls_back_and_keeps_the_v1_envelope():
    resp, events = await _call("/fail")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "duplicate_import"
    assert "ROLLBACK" in events
    assert "COMMIT" not in events


async def test_success_still_commits():
    resp, events = await _call("/ok")
    assert resp.status_code == 200
    assert "COMMIT" in events
    assert "ROLLBACK" not in events
