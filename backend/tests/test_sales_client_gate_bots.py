"""Bramka klienta przed botem researchu: punkty, haczyki, teczki i sygnały.

Kopia produkcji z 23.11.2026: bieg ``briefing`` (punkty do rozmowy, haczyk,
teczka) wysyłał botowi karty aktywnych klientów, bo ``start_run`` nie pytał
bramki, a karta „<klient> Polska” albo „<klient> sp. z o.o” (bez kropki na
końcu) nie pasowała do klienta „<klient>”. Popyt u klienta idzie do jego
Delivery Leada (decyzja Artura 22.10.2026), bot klienta nie researchuje.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.sales import SalesCompany
from app.services.company_names import normalize_company_name
from app.services.sales import client_gate, signals


def _tag() -> str:
    return uuid.uuid4().hex[:8]


async def _client(name: str, **fields) -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=name, **fields)
        db.add(client)
        await db.commit()
        return client.id


async def _company(name: str, **fields) -> int:
    async with AsyncSessionLocal() as db:
        company = SalesCompany(
            name=name, normalized_name=normalize_company_name(name), **fields
        )
        db.add(company)
        await db.commit()
        return company.id


async def _matches(*company_ids: int) -> dict[int, client_gate.ClientMatch]:
    async with AsyncSessionLocal() as db:
        cards = [await db.get(SalesCompany, cid) for cid in company_ids]
        return await client_gate.match_companies(
            db,
            [
                client_gate.CompanyIdentity(c.id, c.client_id, c.normalized_name)
                for c in cards
            ],
        )


@pytest.mark.asyncio
async def test_card_with_country_or_legal_form_is_the_client(app_client) -> None:
    tag = _tag()
    await _client(f"Bocian {tag}")
    await _client(f"Czapla {tag} Polska")
    country = await _company(f"Bocian {tag} Polska")
    no_dot = await _company(f"Bocian {tag} sp. z o.o")
    stock = await _company(f"BOCIAN {tag} S.A. Polska")
    short = await _company(f"Czapla {tag}")
    other = await _company(f"Bocianowo {tag} Polska")

    found = await _matches(country, no_dot, stock, short, other)

    assert set(found) == {country, no_dot, stock, short}
    assert found[country].client_name == f"Bocian {tag}"
    assert found[short].client_name == f"Czapla {tag} Polska"


@pytest.mark.asyncio
async def test_bare_country_word_is_nobodys_client(app_client) -> None:
    tag = _tag()
    await _client(f"Polska {tag}")
    card = await _company("Polska")
    assert await _matches(card) == {}


def _bot(monkeypatch) -> list[dict]:
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_URL", "https://bot.example/hook")
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_KEY", "test-key")
    return []


def _transport(seen: list[dict]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["briefing", "signals"])
async def test_bot_run_skips_client_cards(app_client, monkeypatch, kind) -> None:
    seen = _bot(monkeypatch)
    tag = _tag()
    client_id = await _client(f"Klientowy Bank {tag}")
    linked = await _company(f"Karta powiązana {tag}", client_id=client_id)
    by_name = await _company(f"Klientowy Bank {tag} Polska")
    prospect = await _company(f"Nowa Firma {tag}")
    ids = [linked, by_name, prospect]

    async with AsyncSessionLocal() as db, _transport(seen) as client:
        run = await signals.start_run(
            db,
            kind,
            ids,
            now=datetime.now(timezone.utc),
            modes={cid: "ongoing" for cid in ids} if kind == "briefing" else None,
            client=client,
        )
        assert run is not None
        assert [int(cid) for cid in run.company_ids] == [prospect]
        order = await signals.request_body(db, run)
    assert seen[0]["run_id"] == run.id
    assert [firm["ref"] for firm in order["firms"]] == [prospect]


@pytest.mark.asyncio
async def test_briefing_of_clients_only_does_not_start(app_client, monkeypatch) -> None:
    seen = _bot(monkeypatch)
    tag = _tag()
    await _client(f"Klient Bez Biegu {tag}")
    card = await _company(f"Klient Bez Biegu {tag} sp. z o.o")

    async with AsyncSessionLocal() as db, _transport(seen) as client:
        run = await signals.start_run(
            db,
            "briefing",
            [card],
            now=datetime.now(timezone.utc),
            modes={card: "meeting_prep"},
            client=client,
        )
    assert run is None
    assert seen == []
