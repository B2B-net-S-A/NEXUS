"""Interactive draft guards and persistence; no portal or webhook calls."""

from __future__ import annotations

import asyncio
import copy
import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date
from app.models.cpro_bot import CproBotRun
from app.services.cpro_bot import flow, runs
from app.services.cpro_bot import items as bot_items


@pytest.fixture
def interactive_ready(monkeypatch):
    account_name, vault_entry = bot_items.CPRO_ACCOUNTS[27]
    item = bot_items.BotItem(
        stage_id=101,
        candidate_id=102,
        job_id=103,
        candidate_name="Test candidate",
        process_state_version=0,
        target_stage_def_id=5,
        blockers=(),
        payload={
            "ref": 101,
            "request_number": "42511",
            "cpro_account": {
                "delivery_lead_id": 27,
                "delivery_lead_name": account_name,
                "vault_entry": vault_entry,
            },
            "offer": {},
        },
        extra={"delivery_lead_id": 27},
    )
    monkeypatch.setattr(settings, "CPRO_BOT_ENABLED", False)
    monkeypatch.setattr(settings, "GROK_BOT_CPRO_WEBHOOK_URL", "")
    monkeypatch.setattr(settings, "GROK_BOT_CPRO_WEBHOOK_KEY", "")
    monkeypatch.setattr(bot_items, "load_items", AsyncMock(return_value=[item]))
    monkeypatch.setattr(
        httpx.AsyncClient, "post", AsyncMock(side_effect=AssertionError)
    )
    return item


async def _create(db, item, **over):
    now = datetime.now(timezone.utc)
    args = {"delivery_lead_id": 27, "request_number": "42511"}
    return await flow.create_interactive_draft(
        db,
        item.stage_id,
        **{**args, **over},
        now=now,
        today=business_date(now),
    )


@pytest.mark.asyncio
async def test_interactive_draft_works_disabled_without_webhook_or_old_run_changes(
    interactive_ready,
) -> None:
    now = datetime.now(timezone.utc)
    old, _ = runs.new_run(
        [{"ref": 999, "offer": {}}], now=now - timedelta(days=31), submit=False
    )
    old.status = "expired"
    old.token_hash = None
    old.error = "prior pilot expired"
    ids = []
    try:
        async with AsyncSessionLocal() as db:
            db.add(old)
            await db.commit()
            ids.append(old.id)
            before = (old.status, old.submit, old.token_hash, old.error, old.report)
            run, token = await _create(db, interactive_ready)
            ids.append(run.id)
            assert run.id != old.id
            assert run.status == "started" and run.submit is False
            assert run.stage_ids == [interactive_ready.stage_id]
            assert run.request["items"] == [interactive_ready.payload]
            assert run.token_hash == runs.hash_token(token)
            assert runs.token_matches(run, token, datetime.now(timezone.utc))
            assert settings.CPRO_BOT_ENABLED is False
            httpx.AsyncClient.post.assert_not_called()
            await db.refresh(old)
            assert (
                old.status,
                old.submit,
                old.token_hash,
                old.error,
                old.report,
            ) == before
        # The fresh run survives the CLI's database session closing.
        async with AsyncSessionLocal() as db:
            stored = await db.get(CproBotRun, run.id)
            assert stored is not None and stored.token_hash == runs.hash_token(token)
            assert stored.submit is False
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CproBotRun).where(CproBotRun.id.in_(ids)))
            await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    ["enabled", "blocked", "wrong_dl", "unknown_dl", "wrong_request", "gone", "many"],
)
async def test_interactive_requires_exactly_one_ready_matching_card(
    interactive_ready, monkeypatch, case
) -> None:
    item = interactive_ready
    kwargs = {}
    if case == "enabled":
        monkeypatch.setattr(settings, "CPRO_BOT_ENABLED", True)
    elif case == "blocked":
        monkeypatch.setattr(
            bot_items,
            "load_items",
            AsyncMock(
                return_value=[
                    replace(item, payload=None, blockers=(bot_items.BLOCK_NO_CV,))
                ]
            ),
        )
    elif case == "wrong_dl":
        kwargs["delivery_lead_id"] = 14
    elif case == "unknown_dl":
        kwargs["delivery_lead_id"] = 999
    elif case == "wrong_request":
        kwargs["request_number"] = "42512"
    elif case == "gone":
        monkeypatch.setattr(bot_items, "load_items", AsyncMock(return_value=[]))
    elif case == "many":
        monkeypatch.setattr(
            bot_items, "load_items", AsyncMock(return_value=[item, item])
        )
    async with AsyncSessionLocal() as db:
        before = list((await db.scalars(select(CproBotRun.id))).all())
        with pytest.raises(flow.NotReady):
            await _create(db, item, **kwargs)
        assert list((await db.scalars(select(CproBotRun.id))).all()) == before
        httpx.AsyncClient.post.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["draft", "submitted"])
async def test_interactive_rejects_any_prior_completed_offer_even_if_latest_failed(
    interactive_ready, outcome
) -> None:
    now = datetime.now(timezone.utc)
    completed, _ = runs.new_run(
        [interactive_ready.payload], now=now - timedelta(days=31), submit=False
    )
    completed.status = "received"
    completed.token_hash = None
    completed.report = {"items": {"101": {"outcome": outcome}}}
    later, _ = runs.new_run(
        [interactive_ready.payload], now=now - timedelta(days=1), submit=False
    )
    later.status = "failed"
    later.token_hash = None
    ids = []
    try:
        async with AsyncSessionLocal() as db:
            db.add_all([completed, later])
            await db.commit()
            ids = [completed.id, later.id]
            with pytest.raises(flow.NotReady):
                await _create(db, interactive_ready)
            await db.refresh(completed)
            await db.refresh(later)
            assert completed.status == "received" and later.status == "failed"
            httpx.AsyncClient.post.assert_not_called()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CproBotRun).where(CproBotRun.id.in_(ids)))
            await db.commit()


@pytest.mark.asyncio
async def test_interactive_never_expires_or_revokes_an_existing_open_run(
    interactive_ready,
) -> None:
    now = datetime.now(timezone.utc)
    old, token = runs.new_run(
        [{"ref": 999, "offer": {}}], now=now - timedelta(days=1), submit=False
    )
    run_id = None
    try:
        async with AsyncSessionLocal() as db:
            db.add(old)
            await db.commit()
            run_id = old.id
            with pytest.raises(flow.NotReady):
                await _create(db, interactive_ready)
            await db.refresh(old)
            assert old.status == "started" and old.token_hash == runs.hash_token(token)
            assert old.submit is False
    finally:
        if run_id is not None:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(CproBotRun).where(CproBotRun.id == run_id))
                await db.commit()


@pytest.mark.asyncio
async def test_simultaneous_interactive_attempts_create_only_one_run(
    interactive_ready,
) -> None:
    async def attempt():
        async with AsyncSessionLocal() as db:
            return await _create(db, interactive_ready)

    results = await asyncio.gather(attempt(), attempt(), return_exceptions=True)
    created = [result for result in results if isinstance(result, tuple)]
    try:
        assert len(created) == 1
        assert sum(isinstance(result, flow.NotReady) for result in results) == 1
        assert created[0][0].submit is False
        httpx.AsyncClient.post.assert_not_called()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CproBotRun).where(
                    CproBotRun.id.in_([run.id for run, _ in created])
                )
            )
            await db.commit()


@pytest.mark.asyncio
async def test_closed_token_pipe_revokes_only_the_new_committed_draft(
    interactive_ready, monkeypatch, capsys
) -> None:
    from scripts import cpro_bot_run as cli

    # Keep the shared pytest engine available after this CLI invocation.
    monkeypatch.setattr(cli, "engine", SimpleNamespace(dispose=AsyncMock()))
    now = datetime.now(timezone.utc)
    old, _ = runs.new_run(
        [{"ref": 999, "offer": {}}], now=now - timedelta(days=1), submit=True
    )
    old.status = "expired"
    old.token_hash = None
    ids = []
    new_tokens = []
    original_new_run = runs.new_run

    def capture_new_token(*args, **kwargs):
        run, token = original_new_run(*args, **kwargs)
        new_tokens.append(token)
        return run, token

    monkeypatch.setattr(runs, "new_run", capture_new_token)
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    try:
        async with AsyncSessionLocal() as db:
            db.add(old)
            await db.commit()

            ids.append(old.id)
        result = await cli.interactive_draft(
            interactive_ready.stage_id,
            delivery_lead_id=27,
            request_number="42511",
            token_fd=write_fd,
        )
        assert result["started"] is False
        assert result["status"] == "token_delivery_failed"
        ids.append(result["run_id"])
        assert result["run_id"] != old.id and len(new_tokens) == 1
        async with AsyncSessionLocal() as db:
            # A separate session sees the committed row and its revocation.
            created = await db.get(CproBotRun, result["run_id"])
            assert created is not None and created.status == "failed"
            assert created.submit is False and created.token_hash is None
            stored_old = await db.get(CproBotRun, old.id)
            assert stored_old.status == "expired" and stored_old.submit is True
        captured = capsys.readouterr()
        assert new_tokens[0] not in captured.out + captured.err
        assert new_tokens[0] not in json.dumps(result)
        httpx.AsyncClient.post.assert_not_called()
    finally:
        os.close(write_fd)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CproBotRun).where(CproBotRun.id.in_(ids)))
            await db.commit()


def _completed_draft(item, **over):
    run, _ = runs.new_run(
        [copy.deepcopy(item.payload)], now=datetime.now(timezone.utc), submit=False
    )
    run.status = "received"
    run.token_hash = None
    run.report = {
        "items": {
            str(item.stage_id): {
                "outcome": "draft",
                "cpro_status": "DRAFT",
                "offer_url": "https://nordea.onevms.se/nordea/vendor/OfferController?id=42",
            }
        }
    }
    for name, value in over.items():
        setattr(run, name, value)
    return run


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "offer_url",
    [
        "https://nordea.onevms.se/nordea/vendor/OfferController?id=42",
        None,
        "https://evil.example/offer",
        "https://user@nordea.onevms.se/offer",
    ],
)
async def test_repair_creates_only_an_edit_instruction_for_the_same_confirmed_draft(
    interactive_ready, offer_url
):
    source = _completed_draft(interactive_ready)
    source.report["items"]["101"]["offer_url"] = offer_url
    ids = []
    try:
        async with AsyncSessionLocal() as db:
            db.add(source)
            await db.commit()
            ids.append(source.id)
            before = copy.deepcopy(source.request), copy.deepcopy(source.report)
            repaired, token = await _create(
                db, interactive_ready, repair_draft_run_id=source.id
            )
            ids.append(repaired.id)
            assert repaired.id != source.id and repaired.submit is False
            assert repaired.stage_ids == [interactive_ready.stage_id]
            payload = repaired.request["items"][0]
            assert payload["edit_existing_draft_only"] is True
            assert payload["repair_draft_run_id"] == source.id
            assert payload["request_number"] == "42511"
            assert payload["cpro_account"] == interactive_ready.payload["cpro_account"]
            if offer_url and offer_url.startswith("https://nordea.onevms.se/"):
                assert payload["existing_offer_url"] == offer_url
            else:
                assert "existing_offer_url" not in payload
            assert runs.token_matches(repaired, token, datetime.now(timezone.utc))
            await db.refresh(source)
            assert (source.request, source.report) == before
            assert source.status == "received" and source.token_hash is None
            httpx.AsyncClient.post.assert_not_called()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CproBotRun).where(CproBotRun.id.in_(ids)))
            await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch",
    [
        "missing_run",
        "wrong_stage",
        "wrong_ref",
        "wrong_request",
        "wrong_dl",
        "not_received",
        "submit_enabled",
        "not_draft",
        "duplicate_items",
    ],
)
async def test_repair_rejects_unconfirmed_or_mismatched_drafts_without_a_new_run(
    interactive_ready, mismatch
):
    source = _completed_draft(interactive_ready)
    if mismatch == "wrong_stage":
        source.stage_ids = [999]
    elif mismatch == "wrong_ref":
        source.request["items"][0]["ref"] = 999
    elif mismatch == "wrong_request":
        source.request["items"][0]["request_number"] = "42512"
    elif mismatch == "wrong_dl":
        source.request["items"][0]["cpro_account"] = {
            "delivery_lead_id": 14,
            "delivery_lead_name": "Igor",
            "vault_entry": "Nordea Cpro – Igor",
        }
    elif mismatch == "not_received":
        source.status = "failed"
    elif mismatch == "submit_enabled":
        source.submit = True
    elif mismatch == "not_draft":
        source.report["items"]["101"]["cpro_status"] = "SELECTION"
    elif mismatch == "duplicate_items":
        source.request["items"].append(copy.deepcopy(source.request["items"][0]))
    source_id = None
    try:
        async with AsyncSessionLocal() as db:
            db.add(source)
            await db.commit()
            source_id = source.id
            before = list((await db.scalars(select(CproBotRun.id))).all())
            with pytest.raises(flow.NotReady):
                await _create(
                    db,
                    interactive_ready,
                    repair_draft_run_id=source.id + 100000
                    if mismatch == "missing_run"
                    else source.id,
                )
            assert list((await db.scalars(select(CproBotRun.id))).all()) == before
            httpx.AsyncClient.post.assert_not_called()
    finally:
        if source_id is not None:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(CproBotRun).where(CproBotRun.id == source_id))
                await db.commit()


@pytest.mark.asyncio
async def test_repair_cannot_hide_an_older_submitted_offer(interactive_ready):
    source = _completed_draft(interactive_ready)
    submitted = _completed_draft(interactive_ready)
    submitted.report["items"]["101"]["outcome"] = "submitted"
    submitted.report["items"]["101"]["cpro_status"] = "SELECTION"
    ids = []
    try:
        async with AsyncSessionLocal() as db:
            db.add_all([submitted, source])
            await db.commit()
            ids = [submitted.id, source.id]
            with pytest.raises(flow.NotReady):
                await _create(db, interactive_ready, repair_draft_run_id=source.id)
            assert (
                set(
                    (
                        await db.scalars(
                            select(CproBotRun.id).where(CproBotRun.id.in_(ids))
                        )
                    ).all()
                )
                == set(ids)
            )
            httpx.AsyncClient.post.assert_not_called()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CproBotRun).where(CproBotRun.id.in_(ids)))
            await db.commit()


@pytest.mark.asyncio
async def test_dominik_interactive_draft_keeps_owner_32_and_rejects_account_owner_27(
    interactive_ready,
):
    payload = copy.deepcopy(interactive_ready.payload)
    payload["cpro_account"] = {
        "delivery_lead_id": 32,
        "delivery_lead_name": "Dominik",
        "vault_entry": "Nordea Cpro – Marcin",
    }
    item = replace(interactive_ready, payload=payload, extra={"delivery_lead_id": 32})
    bot_items.load_items.return_value = [item]
    run_id = None
    try:
        async with AsyncSessionLocal() as db:
            with pytest.raises(flow.NotReady, match="Delivery Lead"):
                await _create(db, item, delivery_lead_id=27)
            run, token = await _create(db, item, delivery_lead_id=32)
            run_id = run.id
            assert run.request["items"][0]["cpro_account"] == payload["cpro_account"]
            assert run.submit is False and runs.token_matches(
                run, token, datetime.now(timezone.utc)
            )
            httpx.AsyncClient.post.assert_not_called()
    finally:
        if run_id is not None:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(CproBotRun).where(CproBotRun.id == run_id))
                await db.commit()
