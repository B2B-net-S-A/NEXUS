"""Webhook v2 z bazą: paczka Research 25+ firm przechodzi w całości (24.11.2026).

Biegi Research 261–718 wygasały, bo treść webhooka z całym zleceniem 25–40 firm
docierała do bota ucięta. W v2 webhook to sama koperta, a bot pobiera zlecenie
GET-em na ``request_url`` z ``X-Run-Token`` i odsyła raport POST-em.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
import pytest

from app.api.integrations_sales_signals import EMPTY_REPORT_DETAIL
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.sales import SalesSignalRun
from app.services.sales import bots, signals
from tests.test_sales_signals_api import URL, _company, _order, _run

ENVELOPE = {"schema_version", "run_id", "request_url", "token", "expires_at"}


def _bot(monkeypatch, schema_v1: str = "") -> list[bytes]:
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_URL", "https://bot.example/hook")
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_KEY", "test-key")
    monkeypatch.setattr(settings, "GROK_BOT_RESEARCH_WEBHOOK_URL", "")
    monkeypatch.setattr(settings, "GROK_BOT_RESEARCH_WEBHOOK_KEY", "")
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_V1", schema_v1)
    return []


def _transport(sent: list[bytes]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return httpx.Response(200)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _firms(count: int) -> list[int]:
    tag = uuid.uuid4().hex[:8]
    return [
        await _company(f"Paczka {tag} {n}", domain=f"paczka-{tag}-{n}.example.pl")
        for n in range(count)
    ]


async def _start(ids: list[int], sent: list[bytes], **kwargs) -> SalesSignalRun:
    async with AsyncSessionLocal() as db, _transport(sent) as client:
        await bots.set_paused(db, bots.RESEARCH, False, user_id=None)
        await db.commit()
        run = await signals.start_run(
            db,
            "briefing",
            ids,
            now=datetime.now(timezone.utc),
            modes={cid: "first_call" for cid in ids},
            client=client,
            **kwargs,
        )
        assert run is not None
        return run


@pytest.mark.asyncio
async def test_research_package_of_thirty_firms_goes_whole_through_v2(
    app_client, monkeypatch
) -> None:
    sent = _bot(monkeypatch)
    ids = await _firms(30)
    run = await _start(ids, sent)
    assert run.status == "started" and len(run.company_ids) == 30

    [raw] = sent
    envelope = json.loads(raw)
    assert set(envelope) == ENVELOPE
    assert envelope["schema_version"] == 2 and envelope["run_id"] == run.id
    assert len(raw) < 512

    order = await _order(app_client, envelope)
    assert sorted(firm["ref"] for firm in order["firms"]) == sorted(ids)
    assert order["callback_url"] == envelope["request_url"]
    assert {"task", "report_format", "request", "rejected", "seen_urls"} <= set(order)
    assert order["task"].endswith("ze statusem received.")
    assert envelope["token"] not in json.dumps(order)
    # Ponowne pobranie (bot może ponowić GET) nie zużywa tokenu.
    assert (await _order(app_client, envelope))["run_id"] == run.id

    path = urlsplit(envelope["request_url"]).path
    headers = {"X-Run-Token": envelope["token"]}
    report = {
        "checked_firms": 30,
        "briefings": [{"company_ref": ids[0], "points": [{"text": "Nowy program"}]}],
        "no_signal": ids[1:],
    }
    received = await app_client.post(path, json=report, headers=headers)
    assert received.status_code == 200, received.text
    assert received.json()["status"] == "received"
    assert received.json()["briefings"] == 1
    # Po raporcie token jest zużyty: zlecenia już nie ma.
    assert (await app_client.get(path, headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_v1_fallback_splits_research_into_packages_of_ten(
    app_client, monkeypatch
) -> None:
    sent = _bot(monkeypatch, schema_v1="research")
    ids = sorted(await _firms(25))
    run = await _start(ids, sent, request={"first_meeting": [ids[0], ids[12]]})

    bodies = [json.loads(raw) for raw in sent]
    assert [len(body["firms"]) for body in bodies] == [10, 10, 5]
    assert all(body["schema_version"] == 1 and body["token"] for body in bodies)
    assert run.id == bodies[0]["run_id"]
    assert [ref for body in bodies for ref in (f["ref"] for f in body["firms"])] == ids
    assert [body["request"]["first_meeting"] for body in bodies] == [
        [ids[0]],
        [ids[12]],
        [],
    ]
    async with AsyncSessionLocal() as db:
        for body in bodies:
            stored = await db.get(SalesSignalRun, body["run_id"])
            assert stored.status == "started"
            assert len(stored.company_ids) == len(body["firms"])


@pytest.mark.asyncio
async def test_empty_first_post_is_a_clear_422_and_keeps_the_token(
    app_client,
) -> None:
    company = await _company(f"Pusta treść {uuid.uuid4().hex[:8]}")
    run_id, token = await _run([company])
    headers = {"X-Run-Token": token, "Content-Type": "application/json"}
    for body in (b"", b"\n"):
        empty = await app_client.post(f"{URL}/{run_id}", content=body, headers=headers)
        assert empty.status_code == 422
        assert empty.json()["detail"] == EMPTY_REPORT_DETAIL
    received = await app_client.post(
        f"{URL}/{run_id}", json={"checked_firms": 1}, headers=headers
    )
    assert received.status_code == 200, received.text


@pytest.mark.asyncio
async def test_order_get_refuses_missing_wrong_and_cross_run_tokens(
    app_client,
) -> None:
    company = await _company(f"Zlecenie {uuid.uuid4().hex[:8]}")
    run_id, token = await _run([company])
    other_id, _ = await _run([company])
    for rid, auth in (
        (run_id, {}),
        (run_id, {"X-Run-Token": "zly"}),
        (other_id, {"X-Run-Token": token}),
        (run_id + 100_000, {"X-Run-Token": token}),
    ):
        response = await app_client.get(f"{URL}/{rid}", headers=auth)
        assert response.status_code == 401, (rid, response.text)
        assert response.json()["detail"] == signals.INVALID_TOKEN_DETAIL
    ok = await app_client.get(f"{URL}/{run_id}", headers={"X-Run-Token": token})
    assert ok.status_code == 200
    assert "no-store" in ok.headers.get("cache-control", "")
    assert [firm["ref"] for firm in ok.json()["firms"]] == [company]
