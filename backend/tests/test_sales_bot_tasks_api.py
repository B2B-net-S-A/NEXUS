"""Zadania bota z bazą: przyjęcie raportu per rodzaj i wyniki do decyzji handlowca."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.sales import SalesBotResult, SalesSignalRun
from app.services.sales import bot_tasks, signals
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_signals_api import URL, _company, _run

RESULTS = "/api/sales/bot-results"


class _Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_ref: int
    note: bot_tasks.RequiredText = Field(max_length=200)
    url: bot_tasks.SourceUrl = Field(max_length=1000)


class _Report(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[_Item] = Field(default_factory=list, max_length=10)


async def _ingest(db, run, report, now) -> dict[str, Any]:
    allowed = {int(ref) for ref in run.company_ids}
    rows = [
        {
            "company_id": item.company_ref,
            "payload": {"note": item.note, "url": item.url},
            "fingerprint": bot_tasks.result_fingerprint(
                run.kind, item.company_ref, item.url
            ),
        }
        for item in report.items
        if item.company_ref in allowed
    ]
    new = await bot_tasks.save_results(db, run, rows, now)
    return {"results": len(rows), "results_new": new}


FAKE = bot_tasks.BotTask(
    kind="enrich",
    task_text=lambda run, ctx: "Uzupełnij kartę firmy.",
    report_format=lambda: {"items": [{"company_ref": 1, "note": "...", "url": "..."}]},
    report_model=_Report,
    ingest=_ingest,
)


def _report(company: int, tag: str) -> dict:
    return {
        "items": [
            {"company_ref": company, "note": "Nowa siedziba", "url": f"e.com/{tag}"}
        ]
    }


@pytest.mark.asyncio
async def test_fake_kind_round_trip_and_decision_survives_rerun(
    app_client, monkeypatch
) -> None:
    monkeypatch.setitem(bot_tasks.REGISTRY, "enrich", FAKE)
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    tag = uuid.uuid4().hex[:8]
    company = await _company(f"Zadanie {tag}")
    run_id, token = await _run([company], kind="enrich")

    sent = await app_client.post(
        f"{URL}/{run_id}", json=_report(company, tag), headers={"X-Run-Token": token}
    )
    assert sent.status_code == 200, sent.text
    assert sent.json() == {"status": "received", "results": 1, "results_new": 1}

    viewer = await _user("sales_view")
    listed = (
        await app_client.get(
            RESULTS,
            params={"kind": "enrich", "company_id": company},
            headers=_headers(viewer),
        )
    ).json()
    assert listed["enabled"] is True
    [item] = listed["items"]
    assert (item["kind"], item["status"], item["run_id"]) == ("enrich", "new", run_id)
    assert item["company"] == {"id": company, "name": f"Zadanie {tag}"}
    assert item["payload"]["url"] == f"https://e.com/{tag}"

    editor = await _user("sales_edit")
    accepted = await app_client.post(
        f"{RESULTS}/{item['id']}/accept", headers=_headers(editor)
    )
    assert accepted.status_code == 409
    assert accepted.json()["detail"] == "Ten rodzaj nie ma jeszcze akcji."

    rejected = await app_client.post(
        f"{RESULTS}/{item['id']}/reject",
        json={"reason": "Nieaktualne"},
        headers=_headers(editor),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    # Ten sam wynik z kolejnego biegu nie wraca do „new”.
    second, token2 = await _run([company], kind="enrich")
    again = await app_client.post(
        f"{URL}/{second}", json=_report(company, tag), headers={"X-Run-Token": token2}
    )
    assert again.json()["results_new"] == 0
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesBotResult, item["id"])
        assert (row.status, row.decided_by_user_id, row.decision_reason) == (
            "rejected",
            editor.id,
            "Nieaktualne",
        )
        assert row.decided_at is not None
        rows = (
            await db.execute(
                select(SalesBotResult).where(SalesBotResult.company_id == company)
            )
        ).all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_run_of_unregistered_kind_is_refused_and_closed(app_client) -> None:
    assert "question" not in bot_tasks.REGISTRY
    company = await _company(f"Pytanie {uuid.uuid4().hex[:8]}")
    run_id, token = await _run([company], kind="question")
    resp = await app_client.post(
        f"{URL}/{run_id}", json={"items": []}, headers={"X-Run-Token": token}
    )
    assert resp.status_code == 409
    async with AsyncSessionLocal() as db:
        run = await db.get(SalesSignalRun, run_id)
        assert (run.status, run.token_hash) == ("failed", None)


@pytest.mark.asyncio
async def test_oversize_report_is_413_and_keeps_the_token(app_client) -> None:
    company = await _company(f"Duży {uuid.uuid4().hex[:8]}")
    run_id, token = await _run([company])
    big = b'{"checked_firms": 1, "pad": "' + b"x" * (600 * 1024) + b'"}'
    resp = await app_client.post(
        f"{URL}/{run_id}",
        content=big,
        headers={"X-Run-Token": token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    async with AsyncSessionLocal() as db:
        run = await db.get(SalesSignalRun, run_id)
        assert run.status == "started" and run.token_hash is not None
    # Zły kształt to 422, token dalej ważny; poprawny raport przechodzi.
    bad = await app_client.post(
        f"{URL}/{run_id}",
        json={"checked_firms": 1, "people": []},
        headers={"X-Run-Token": token},
    )
    assert bad.status_code == 422
    ok = await app_client.post(
        f"{URL}/{run_id}", json={"checked_firms": 1}, headers={"X-Run-Token": token}
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_results_follow_the_flag_and_need_sales_permissions(
    app_client, monkeypatch
) -> None:
    viewer = await _user("sales_view")
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    off = await app_client.get(RESULTS, headers=_headers(viewer))
    assert off.json() == {"enabled": False, "items": []}

    stranger = await _user()
    assert (
        await app_client.get(RESULTS, headers=_headers(stranger))
    ).status_code == 403
    assert (
        await app_client.post(f"{RESULTS}/1/reject", headers=_headers(viewer))
    ).status_code == 403
    editor = await _user("sales_edit")
    missing = await app_client.post(
        f"{RESULTS}/999999999/reject", headers=_headers(editor)
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_start_run_stores_request_and_requester(monkeypatch) -> None:
    class _Req(BaseModel):
        model_config = ConfigDict(extra="forbid")
        limit: int = Field(ge=1, le=5)

    task = bot_tasks.BotTask(
        kind="enrich",
        task_text=lambda run, ctx: f"limit {ctx.request['limit']}",
        report_format=lambda: {},
        report_model=_Report,
        ingest=_ingest,
        request_model=_Req,
    )
    monkeypatch.setitem(bot_tasks.REGISTRY, "enrich", task)
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_URL", "https://bot.example/hook")
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_KEY", "test-key")
    user = await _user("sales_edit")
    company = await _company(f"Zlecenie {uuid.uuid4().hex[:8]}")
    seen: list[dict] = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200)

    async with (
        AsyncSessionLocal() as db,
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client,
    ):
        run = await signals.start_run(
            db,
            "enrich",
            [company],
            now=datetime.now(timezone.utc),
            client=client,
            request={"limit": 2},
            requested_by_user_id=user.id,
        )
        run_id = run.id
    assert seen[0]["request"] == {"limit": 2} and seen[0]["task"] == "limit 2"
    assert (seen[0]["rejected"], seen[0]["seen_urls"]) == ([], [])
    async with AsyncSessionLocal() as db:
        stored = await db.get(SalesSignalRun, run_id)
        assert (stored.kind, stored.request, stored.requested_by_user_id) == (
            "enrich",
            {"limit": 2},
            user.id,
        )
