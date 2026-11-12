"""G-A i G-B z bazą: „Uzupełnij z bota” i „Zapytaj bota” na karcie firmy."""

from __future__ import annotations

import json
import random
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.sales import SalesBotResult, SalesCompany, SalesSignalRun
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_signals_api import URL, _company, _run

COMPANIES = "/api/sales/companies"
RESULTS = "/api/sales/bot-results"
_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def _nip() -> str:
    """Losowy NIP z poprawną sumą kontrolną (numer fikcyjny, unikalny w biegu testów)."""

    while True:
        head = "".join(random.choice("0123456789") for _ in range(9))
        control = sum(int(d) * w for d, w in zip(head, _WEIGHTS)) % 11
        if control != 10:
            return f"{head}{control}"


@pytest.fixture
def bot_on(monkeypatch):
    """Flaga zadań, adres bota i webhook bez sieci; zwraca treści wysłane do bota."""

    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_URL", "https://bot.example/hook")
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_KEY", "test-key")
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200)

    real = httpx.AsyncClient

    def client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(handler))

    from app.services.sales import signals

    monkeypatch.setattr(signals.httpx, "AsyncClient", client)
    return sent


# ── Zapytaj bota ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_round_trip_shows_pending_then_answer(app_client, bot_on) -> None:
    company = await _company(f"Pytana {uuid.uuid4().hex[:8]}")
    editor = await _user("sales_edit")
    asked = await app_client.post(
        f"{COMPANIES}/{company}/ask",
        json={"question": "  Czy mają centrum IT w Polsce?  "},
        headers=_headers(editor),
    )
    assert asked.status_code == 201, asked.text
    body = asked.json()
    assert (body["status"], body["question"]) == (
        "started",
        "Czy mają centrum IT w Polsce?",
    )
    assert body["asked_by"]["id"] == editor.id
    [webhook] = bot_on
    assert webhook["kind"] == "question"
    assert webhook["request"] == {"question": "Czy mają centrum IT w Polsce?"}
    assert [firm["ref"] for firm in webhook["firms"]] == [company]

    viewer = await _user("sales_view")
    pending = (
        await app_client.get(
            f"{COMPANIES}/{company}/questions", headers=_headers(viewer)
        )
    ).json()
    assert pending["enabled"] is True
    [item] = pending["items"]
    assert (item["status"], item["answer"], item["minutes"]) == ("started", None, None)

    report = {
        "answer": [
            {"text": "Centrum w Krakowie od 2024", "url": "firma.example/news"},
            {"text": "Wniosek: rosną"},
        ]
    }
    sent = await app_client.post(
        f"{URL}/{webhook['run_id']}",
        json=report,
        headers={"X-Run-Token": webhook["token"]},
    )
    assert sent.status_code == 200, sent.text
    [item] = (
        await app_client.get(
            f"{COMPANIES}/{company}/questions", headers=_headers(viewer)
        )
    ).json()["items"]
    assert item["status"] == "received" and item["minutes"] == 0
    assert item["answer"] == [
        {
            "text": "Centrum w Krakowie od 2024",
            "url": "https://firma.example/news",
            "published": None,
        },
        {"text": "Wniosek: rosną", "url": None, "published": None},
    ]
    async with AsyncSessionLocal() as db:
        run = await db.get(SalesSignalRun, webhook["run_id"])
        assert run.requested_by_user_id == editor.id
        result = (
            await db.execute(
                select(SalesBotResult).where(SalesBotResult.run_id == run.id)
            )
        ).scalar_one()
        assert (result.kind, result.company_id) == ("question", company)


@pytest.mark.asyncio
async def test_ask_refuses_personal_data_short_text_and_viewers(
    app_client, bot_on
) -> None:
    company = await _company(f"Pytana {uuid.uuid4().hex[:8]}")
    editor = await _user("sales_edit")
    for text, fragment in (
        ("Kto odbiera pod 600 700 800?", "telefonu"),
        ("Czy ewa@firma.example tam pracuje?", "e-mail"),
        ("co?", "co najmniej"),
    ):
        resp = await app_client.post(
            f"{COMPANIES}/{company}/ask",
            json={"question": text},
            headers=_headers(editor),
        )
        assert resp.status_code == 422
        assert fragment in resp.json()["detail"]
    assert bot_on == []
    viewer = await _user("sales_view")
    forbidden = await app_client.post(
        f"{COMPANIES}/{company}/ask",
        json={"question": "Kogo teraz rekrutują?"},
        headers=_headers(viewer),
    )
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_flag_off_refuses_starts_and_hides_state(app_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    company = await _company(f"Wyłączona {uuid.uuid4().hex[:8]}")
    editor = await _user("sales_edit")
    for path, payload in (("ask", {"question": "Kogo rekrutują?"}), ("enrich", None)):
        resp = await app_client.post(
            f"{COMPANIES}/{company}/{path}", json=payload, headers=_headers(editor)
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Zadania bota są wyłączone."
    assert (
        await app_client.get(
            f"{COMPANIES}/{company}/questions", headers=_headers(editor)
        )
    ).json() == {"enabled": False, "items": []}
    assert (
        await app_client.get(f"{COMPANIES}/{company}/enrich", headers=_headers(editor))
    ).json() == {"enabled": False, "run": None, "result": None}


# ── Uzupełnij z bota ─────────────────────────────────────────────────────


async def _enrich_result(app_client, company: int, firm: dict[str, Any]) -> int:
    run_id, token = await _run([company], kind="enrich")
    sent = await app_client.post(
        f"{URL}/{run_id}",
        json={"checked_firms": 1, "firms": [{"company_ref": company, **firm}]},
        headers={"X-Run-Token": token},
    )
    assert sent.status_code == 200, sent.text
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(SalesBotResult.id).where(
                    SalesBotResult.company_id == company,
                    SalesBotResult.kind == "enrich",
                    SalesBotResult.status == "new",
                )
            )
        ).scalar_one()


def _f(value: str) -> dict[str, str]:
    return {"value": value, "source": "https://rejestr.example/karta"}


@pytest.mark.asyncio
async def test_enrich_button_starts_once_per_two_hours(app_client, bot_on) -> None:
    company = await _company(f"Karta {uuid.uuid4().hex[:8]}")
    editor = await _user("sales_edit")
    first = await app_client.post(
        f"{COMPANIES}/{company}/enrich", headers=_headers(editor)
    )
    assert first.status_code == 200, first.text
    assert first.json()["run"]["status"] == "started"
    assert bot_on[0]["kind"] == "enrich" and bot_on[0]["request"] == {}
    again = await app_client.post(
        f"{COMPANIES}/{company}/enrich", headers=_headers(editor)
    )
    assert again.status_code == 409
    assert "2 godziny" in again.json()["detail"]
    assert len(bot_on) == 1


@pytest.mark.asyncio
async def test_enrich_accept_applies_chosen_fields_and_refuses_conflicts(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    tag = uuid.uuid4().hex[:8]
    taken_domain = f"zajeta-{tag}.example"
    await _company(f"Inna {tag}", domain=taken_domain)
    parent = await _company(f"Grupa Matka {tag}")
    company = await _company(f"Karta {tag}", hq_city="Gdańsk")
    nip = _nip()
    result_id = await _enrich_result(
        app_client,
        company,
        {
            "domain": _f(f"https://www.{taken_domain}/o-nas"),
            "nip": _f(f"PL{nip}"),
            "hq_city": _f("Kraków"),
            "size": _f("250-999"),
            "parent_name": _f(f"Grupa Matka {tag} S.A."),
        },
    )
    editor = await _user("sales_edit")
    state = (
        await app_client.get(f"{COMPANIES}/{company}/enrich", headers=_headers(editor))
    ).json()
    assert state["result"]["id"] == result_id
    assert set(state["result"]["payload"]["fields"]) == {
        "domain",
        "nip",
        "hq_city",
        "tier",
        "parent_name",
    }

    conflict = await app_client.post(
        f"{RESULTS}/{result_id}/accept",
        json={"fields": ["domain", "nip"]},
        headers=_headers(editor),
    )
    assert conflict.status_code == 409
    assert f"„Inna {tag}”" in conflict.json()["detail"]
    async with AsyncSessionLocal() as db:
        card = await db.get(SalesCompany, company)
        assert (card.domain, card.nip) == (None, None)

    # „Przyjmij wszystkie” bez domeny: tylko puste pola, miasto zostaje.
    accepted = await app_client.post(
        f"{RESULTS}/{result_id}/accept",
        json={"fields": ["nip", "tier", "parent_name"], "reject": ["domain"]},
        headers=_headers(editor),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "partial"
    async with AsyncSessionLocal() as db:
        card = await db.get(SalesCompany, company)
        assert (card.nip, card.tier, card.size_range) == (nip, "mid_market", "250-999")
        assert (card.parent_company_id, card.hq_city) == (parent, "Gdańsk")

    closed = await app_client.post(
        f"{RESULTS}/{result_id}/reject", headers=_headers(editor)
    )
    assert closed.status_code == 200
    state = (
        await app_client.get(f"{COMPANIES}/{company}/enrich", headers=_headers(editor))
    ).json()
    assert state["result"] is None


@pytest.mark.asyncio
async def test_newer_enrich_replaces_undecided_older_proposal(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    company = await _company(f"Karta {uuid.uuid4().hex[:8]}")
    first = await _enrich_result(app_client, company, {"hq_city": _f("Kraków")})
    second = await _enrich_result(app_client, company, {"hq_city": _f("Poznań")})
    assert first != second
    async with AsyncSessionLocal() as db:
        assert await db.get(SalesBotResult, first) is None
