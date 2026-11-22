"""`checks.workforce_availability` czyta przełącznik źródła urlopów z bazy.

22.11.2026, po wdrożeniu #3696: sonda pokazywała `disabled` przy włączonym
źródle `local`, bo czytała pamięć procesu (`availability_local._SOURCE`),
którą odświeżają tylko żądania przez `workforce_context` i pętla lidera.
Świeży proces po wdrożeniu raportował więc „wyłączone”, dopóki ktoś nie
skorzystał z aplikacji.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from app import main
from app.services.hr import availability_local


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

    def __getattr__(self, _name):
        raise RuntimeError("inna sonda")


async def test_cold_process_reads_the_switch_before_reporting(monkeypatch) -> None:
    import app.core.database as database

    monkeypatch.setattr(database, "AsyncSessionLocal", type("S", (_Session,), {"opened": 0}))
    monkeypatch.setitem(availability_local._SOURCE, "local", False)
    monkeypatch.setitem(availability_local._SOURCE, "checked", None)

    async def refresh(db, *, force: bool = False) -> bool:
        availability_local._SOURCE.update(local=True)
        return True

    spy = AsyncMock(side_effect=refresh)
    monkeypatch.setattr(availability_local, "refresh_source", spy)

    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")

    spy.assert_awaited()
    # Źródło włączone: sonda sprawdza stan pętli (tu sesja rzuca → degraded),
    # a nie mówi „disabled”.
    assert response.json()["checks"]["workforce_availability"] != "disabled"
