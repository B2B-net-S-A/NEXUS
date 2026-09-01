"""Historyczny backfill kursów NBP — `POST /api/fx/backfill`.

Powstał z realnej luki na produkcji: kokpit zarządu raportował siedem
kolejnych miesięcy (2025-10 … 2026-04) z kwotami EUR POMINIĘTYMI w sumach,
a komunikat podpowiadał `POST /api/fx/refresh` — który pobiera WYŁĄCZNIE
dzisiejszą tabelę NBP i tej luki nie ruszał. Podpowiedź, po której nic się
nie zmienia, uczy ignorować cały komunikat.

Testy NIE wychodzą do NBP: podmieniają `httpx.AsyncClient` w module serwisu.
Test uderzający w zewnętrzne API byłby czerwony przy każdej awarii NBP
i zielony przy naszym błędzie, gdyby NBP akurat oddało dane.
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.fx_rate import FxRate
from app.services import fx_service


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Atrapa `httpx.AsyncClient` — zapamiętuje URL-e i oddaje zadane odpowiedzi."""

    def __init__(self, responses: list[_Resp]):
        self._responses = list(responses)
        self.urls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, params=None):
        self.urls.append(url)
        return self._responses.pop(0) if self._responses else _Resp(404)


def _install(monkeypatch, client: _FakeClient) -> None:
    monkeypatch.setattr(
        fx_service.httpx, "AsyncClient", lambda *a, **k: client, raising=True
    )


@pytest.mark.asyncio
async def test_backfill_inserts_history_and_is_idempotent(monkeypatch):
    """Drugi przebieg NIE dubluje wierszy — arbitrem jest UNIQUE w bazie."""
    currency = "XTS"  # kod testowy ISO 4217, nigdy nie użyty przez NBP
    rates = {
        "rates": [
            {"effectiveDate": "2019-03-01", "mid": 4.1234},
            {"effectiveDate": "2019-03-04", "mid": 4.2345},
        ]
    }

    _install(monkeypatch, _FakeClient([_Resp(200, rates)]))
    first = await fx_service.backfill_nbp_rates(
        currency, date(2019, 3, 1), date(2019, 3, 5)
    )
    assert first["fetched"] == 2
    assert first["inserted"] == 2
    assert first["failed_ranges"] == []

    _install(monkeypatch, _FakeClient([_Resp(200, rates)]))
    second = await fx_service.backfill_nbp_rates(
        currency, date(2019, 3, 1), date(2019, 3, 5)
    )
    assert second["fetched"] == 2
    assert second["inserted"] == 0, "powtórka dołożyła duplikaty"

    async with AsyncSessionLocal() as db:
        rows = (
            (await db.execute(select(FxRate).where(FxRate.currency == currency)))
            .scalars()
            .all()
        )
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_backfill_splits_long_ranges(monkeypatch):
    """NBP odrzuca zakresy dłuższe niż rok — dzielimy je, zamiast dostać 400."""
    client = _FakeClient([_Resp(404), _Resp(404), _Resp(404), _Resp(404)])
    _install(monkeypatch, client)

    await fx_service.backfill_nbp_rates("XTS", date(2019, 1, 1), date(2021, 1, 1))

    assert len(client.urls) >= 3, f"zakres nie został podzielony: {client.urls}"


@pytest.mark.asyncio
async def test_backfill_reports_failed_ranges_instead_of_silent_zero(monkeypatch):
    """`inserted: 0` nie odróżnia „już było" od „NBP nic nie oddał"."""
    _install(monkeypatch, _FakeClient([_Resp(500)]))

    out = await fx_service.backfill_nbp_rates("XTS", date(2019, 5, 1), date(2019, 5, 2))

    assert out["inserted"] == 0
    assert out["failed_ranges"], "awaria NBP przeszła jako cicha zerowa wstawka"
    assert "500" in out["failed_ranges"][0]


@pytest.mark.asyncio
async def test_backfill_treats_404_as_no_quotes_not_failure(monkeypatch):
    """404 z NBP znaczy „brak notowań w tym zakresie", a nie awarię."""
    _install(monkeypatch, _FakeClient([_Resp(404)]))

    out = await fx_service.backfill_nbp_rates("XTS", date(2019, 6, 1), date(2019, 6, 2))

    assert out["inserted"] == 0
    assert out["failed_ranges"] == []


@pytest.mark.asyncio
async def test_backfill_rejects_nonsense_currency(monkeypatch):
    _install(monkeypatch, _FakeClient([]))
    with pytest.raises(ValueError):
        await fx_service.backfill_nbp_rates("EU", date(2019, 1, 1), date(2019, 1, 2))
    with pytest.raises(ValueError):
        await fx_service.backfill_nbp_rates("EUR", date(2019, 2, 1), date(2019, 1, 1))


@pytest.mark.asyncio
async def test_backfill_endpoint_is_admin_only(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Ten sam próg co `POST /refresh` — pobranie pisze do wspólnego cache'u."""
    anon = await app_client.post("/api/fx/backfill", params={"currency": "EUR"})
    assert anon.status_code == 401, anon.text

    # Admin przechodzi bramkę; samo pobranie jest podmienione w testach
    # jednostkowych wyżej, więc tu sprawdzamy WYŁĄCZNIE autoryzację i kształt.
    resp = await app_client.post(
        "/api/fx/backfill",
        headers=app_auth_headers,
        params={"currency": "XTS", "start": "2019-09-01", "end": "2019-09-02"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["currency"] == "XTS"
    assert set(body) >= {"fetched", "inserted", "failed_ranges"}
