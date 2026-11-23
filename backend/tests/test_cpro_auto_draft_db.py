"""Automatic draft mode never submits, repeats a card, or hides an old draft."""

import asyncio
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.api.board_tasks import bot_item_view
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date
from app.models.cpro_bot import CproBotRun
from app.services.cpro_bot import flow, ingest, runs
from app.services.cpro_bot import items as bot_items
from tests.test_cpro_interactive_draft_db import interactive_ready  # noqa: F401


@pytest_asyncio.fixture
async def auto_draft(interactive_ready, monkeypatch):  # noqa: F811 — imported pytest fixture
    monkeypatch.setattr(settings, "CPRO_BOT_ENABLED", False)
    monkeypatch.setattr(settings, "CPRO_BOT_AUTO_DRAFT_ENABLED", True)
    monkeypatch.setattr(
        settings, "GROK_BOT_CPRO_WEBHOOK_URL", "https://bot.example/cpro"
    )
    monkeypatch.setattr(settings, "GROK_BOT_CPRO_WEBHOOK_KEY", "test-key")
    sent = []

    async def post(client, url, *, json, headers):
        sent.append(json)
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    async with AsyncSessionLocal() as db:
        before = set((await db.scalars(select(CproBotRun.id))).all())
    yield SimpleNamespace(item=interactive_ready, sent=sent)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(CproBotRun).where(CproBotRun.id.not_in(before)))
        await db.commit()


async def _tick(now=None):
    now = now or datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        return await flow.start_due(db, now=now, today=business_date(now))


async def _report(run_id, *, outcome="draft", cpro_status="DRAFT"):
    async with AsyncSessionLocal() as db:
        run = await db.get(CproBotRun, run_id)
        return await ingest.apply_report(
            db,
            run,
            ingest.CproReport.model_validate(
                {
                    "items": [
                        {
                            "ref": 101,
                            "outcome": outcome,
                            "cpro_status": cpro_status,
                            "offer_url": "https://nordea.onevms.se/nordea/vendor/OfferController?id=42",
                        }
                    ]
                }
            ),
            now=datetime.now(timezone.utc),
        )


@pytest.mark.asyncio
async def test_two_ticks_do_not_duplicate_a_confirmed_draft(auto_draft):
    now = datetime.now(timezone.utc)
    created = await _tick(now)
    assert created is not None and created.submit is False
    assert created.request["auto_draft"] is True
    assert len(auto_draft.sent) == 1
    summary = await _report(created.id)
    assert summary["counts"]["draft"] == 1
    assert await _tick(now + timedelta(minutes=5)) is None
    assert await _tick(now + timedelta(days=40)) is None
    assert len(auto_draft.sent) == 1
    async with AsyncSessionLocal() as db:
        stored = await db.get(CproBotRun, created.id)
        assert stored.status == "received"
        assert stored.report["items"]["101"]["cpro_status"] == "DRAFT"


@pytest.mark.asyncio
async def test_auto_mode_wins_over_submit_flag_and_takes_only_one_card(
    auto_draft, monkeypatch
):
    monkeypatch.setattr(settings, "CPRO_BOT_ENABLED", True)
    second_payload = {**copy.deepcopy(auto_draft.item.payload), "ref": 201}
    second = replace(auto_draft.item, stage_id=201, payload=second_payload)
    monkeypatch.setattr(
        bot_items, "load_items", AsyncMock(return_value=[auto_draft.item, second])
    )
    created = await _tick()
    assert created.submit is False and created.stage_ids == [101]
    assert created.request["auto_draft"] is True
    assert runs.task_body(created)["submit"] is False
    assert runs.worker_enabled() is True
    assert len(auto_draft.sent) == 1


@pytest.mark.asyncio
async def test_parallel_ticks_create_a_single_draft_run(auto_draft):
    results = await asyncio.gather(_tick(), _tick())
    created = [run for run in results if run is not None]
    assert len(created) == 1 and created[0].submit is False
    assert len(auto_draft.sent) == 1


@pytest.mark.asyncio
async def test_explicit_submit_request_cannot_bypass_auto_draft_mode(
    auto_draft, monkeypatch
):
    monkeypatch.setattr(settings, "CPRO_BOT_ENABLED", True)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        created = await flow.start_for(db, [auto_draft.item], now=now, submit=True)
        assert created.submit is False
        assert created.request["auto_draft"] is True
        assert runs.task_body(created)["submit"] is False


@pytest.mark.asyncio
async def test_old_submit_run_is_not_exposed_as_submit_while_auto_mode_is_active(
    auto_draft,
):
    old = CproBotRun(
        id=7,
        status="started",
        submit=True,
        stage_ids=[101],
        request={"items": [auto_draft.item.payload], "cards": {}},
        report={},
        started_at=datetime.now(timezone.utc),
    )
    assert runs.task_body(old)["submit"] is False
    assert old.submit is True, "Task rendering must not rewrite historical records"


@pytest.mark.asyncio
async def test_confirmed_old_draft_survives_a_later_failed_run_and_missing_current_data(
    auto_draft, monkeypatch
):
    now = datetime.now(timezone.utc)
    old, _ = runs.new_run(
        [auto_draft.item.payload], now=now - timedelta(days=40), submit=False
    )
    old.status, old.token_hash = "received", None
    old.report = {
        "items": {
            "101": {
                "outcome": "draft",
                "cpro_status": "DRAFT",
                "offer_url": "https://nordea.onevms.se/offer/42",
            }
        }
    }
    later, _ = runs.new_run(
        [auto_draft.item.payload], now=now - timedelta(days=1), submit=False
    )
    later.status, later.token_hash = "failed", None
    async with AsyncSessionLocal() as db:
        db.add_all([old, later])
        await db.commit()
        assert await flow.due_items(db, now=now, today=business_date(now)) == []
        states = await runs.item_states(db, [101], now=now)
        assert states[101].state == "draft"
        blocked = replace(
            auto_draft.item, payload=None, blockers=(bot_items.BLOCK_NO_CV,)
        )
        view = bot_item_view(blocked, states[101], draft_only=True)
        assert view.mode == "draft" and view.state == "draft"
        assert view.offer_url == "https://nordea.onevms.se/offer/42"
        assert view.blockers == [bot_items.BLOCK_NO_CV]
        with pytest.raises(flow.NotReady):
            await flow.start_chosen(
                db, [101], now=now, today=business_date(now), submit=True
            )
    assert auto_draft.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted_only", [False, True])
async def test_submitted_report_is_failed_without_a_pipeline_move_even_after_flag_change(
    auto_draft, monkeypatch, persisted_only
):
    monkeypatch.setattr(settings, "CPRO_BOT_ENABLED", True)
    created = await _tick()
    if persisted_only:
        monkeypatch.setattr(settings, "CPRO_BOT_AUTO_DRAFT_ENABLED", False)
    move = AsyncMock(side_effect=AssertionError("Draft mode must not move a candidate"))
    monkeypatch.setattr(ingest, "_move_sent", move)
    summary = await _report(created.id, outcome="submitted", cpro_status="SELECTION")
    assert summary["counts"]["submitted"] == 0
    assert summary["counts"]["failed"] == 1
    assert summary["items"]["101"]["reason"] == "submit_disallowed"
    assert summary["items"]["101"]["reported_outcome"] == "submitted"
    move.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("cpro_status", [None, "SELECTION", "draft"])
async def test_auto_draft_requires_exact_portal_confirmation(auto_draft, cpro_status):
    created = await _tick()
    summary = await _report(created.id, cpro_status=cpro_status)
    assert summary["counts"]["draft"] == 0
    assert summary["counts"]["failed"] == 1
    assert summary["items"]["101"]["reason"] == "draft_unconfirmed"
    assert summary["items"]["101"]["reported_outcome"] == "draft"
    assert await _tick(datetime.now(timezone.utc) + timedelta(hours=1)) is None
    assert len(auto_draft.sent) == 1
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        assert await runs.recorded_offer_stage_ids(db, [101]) == {101}
        with pytest.raises(flow.NotReady):
            await flow.start_chosen(db, [101], now=now, today=business_date(now))


@pytest.mark.asyncio
async def test_expired_ambiguous_attempt_is_not_automatically_repeated(auto_draft):
    now = datetime.now(timezone.utc)
    first = await _tick(now)
    async with AsyncSessionLocal() as db:
        assert await runs.expire_runs(db, now=now + runs.TOKEN_TTL) == 1
    assert await _tick(now + runs.TOKEN_TTL + timedelta(minutes=5)) is None
    assert len(auto_draft.sent) == 1
    async with AsyncSessionLocal() as db:
        expired = await db.get(CproBotRun, first.id)
        assert expired.status == "expired" and expired.token_hash is None


@pytest.mark.asyncio
async def test_submission_violation_is_not_hidden_by_an_old_draft_or_later_failure(
    auto_draft,
):
    now = datetime.now(timezone.utc)
    history = []
    for offset in (40, 2, 1):
        run, _ = runs.new_run(
            [auto_draft.item.payload], now=now - timedelta(days=offset), submit=False
        )
        run.status, run.token_hash = "received" if offset != 1 else "failed", None
        history.append(run)
    history[0].report = {"items": {"101": {"outcome": "draft", "cpro_status": "DRAFT"}}}
    history[1].report = {
        "items": {
            "101": {
                "outcome": "failed",
                "reason": "submit_disallowed",
                "reported_outcome": "submitted",
                "cpro_status": "SELECTION",
            }
        }
    }
    async with AsyncSessionLocal() as db:
        db.add_all(history)
        await db.commit()
        states = await runs.item_states(db, [101], now=now)
        assert states[101].state == "failed"
        assert states[101].run_id == history[1].id
        assert states[101].message
        assert await flow.due_items(db, now=now, today=business_date(now)) == []
    assert auto_draft.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["draft_unconfirmed", "submit_disallowed"])
async def test_reason_only_receipt_still_blocks_new_and_manual_attempts(
    auto_draft, reason
):
    now = datetime.now(timezone.utc)
    receipt, _ = runs.new_run([auto_draft.item.payload], now=now, submit=False)
    receipt.status, receipt.token_hash = "received", None
    receipt.report = {"items": {"101": {"outcome": "failed", "reason": reason}}}
    async with AsyncSessionLocal() as db:
        db.add(receipt)
        await db.commit()
        assert await runs.recorded_offer_stage_ids(db, [101]) == {101}
        assert await flow.due_items(db, now=now, today=business_date(now)) == []
        states = await runs.item_states(db, [101], now=now)
        assert states[101].state == "failed" and states[101].message
        with pytest.raises(flow.NotReady):
            await flow.start_chosen(db, [101], now=now, today=business_date(now))
    assert auto_draft.sent == []
