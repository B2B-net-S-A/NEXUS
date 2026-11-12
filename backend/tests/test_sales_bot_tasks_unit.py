"""Zadania bota bez bazy: rejestr rodzajów, treść webhooka v2, przyjęcie raportu."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from app.api import integrations_sales_signals as intake
from app.core.config import settings
from app.models.sales import SalesCompany
from app.services import sales_schema as schema
from app.services.sales import bot_tasks, signals

NOW = datetime(2026, 11, 16, 7, 10, tzinfo=timezone.utc)


class _FakeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[bot_tasks.SourceUrl] = Field(default_factory=list, max_length=3)


class _FakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Uzasadnienie pola: bot musi wiedzieć, ile wyników ma zwrócić.
    limit: int = Field(ge=1, le=5)


async def _fake_ingest(db, run, report, now) -> dict[str, Any]:
    return {
        "items": len(report.items),
        "first": report.items[0] if report.items else "",
    }


FAKE = bot_tasks.BotTask(
    kind="enrich",
    task_text=lambda run, ctx: (
        f"Sprawdź {len(ctx.firms)} firm, limit {ctx.request.get('limit')}."
    ),
    report_format=lambda: {"items": ["https://..."]},
    report_model=_FakeReport,
    ingest=_fake_ingest,
    request_model=_FakeRequest,
)


# ── rejestr ──────────────────────────────────────────────────────────────


def test_registry_kinds_are_known_to_the_database_check() -> None:
    assert set(bot_tasks.REGISTRY) <= set(schema.BOT_RUN_KINDS)
    assert {"signals", "briefing", "enrich", "question", "people"} <= set(bot_tasks.REGISTRY)
    assert bot_tasks.LEGACY_KINDS == set(schema.SIGNAL_RUN_KINDS)
    for task in bot_tasks.REGISTRY.values():
        if task.kind in bot_tasks.LEGACY_KINDS:
            # ``briefing`` przyjmuje nadzbiór (``hooks`` haczyka), raport v1 dalej przechodzi.
            assert issubclass(task.report_model, signals.RunReport)
        assert issubclass(task.report_model, BaseModel)
        assert task.task_text(signals.new_run(task.kind, [1], now=NOW)[0], _ctx())


def test_briefing_task_sends_ongoing_without_news_to_no_signal() -> None:
    run = signals.new_run("briefing", [1], now=NOW, modes={1: "ongoing"})[0]
    text = bot_tasks.REGISTRY["briefing"].task_text(run, _ctx())
    assert 'Gdy przy mode = "ongoing" nie ma nic nowego' in text
    assert "wpisz firmę do no_signal" in text


def test_new_kinds_and_modes_fit_their_columns() -> None:
    assert all(len(kind) <= 16 for kind in schema.BOT_RUN_KINDS)
    assert all(len(mode) <= 12 for mode in schema.BOT_BRIEFING_MODES)
    assert set(schema.SIGNAL_RUN_KINDS) < set(schema.BOT_RUN_KINDS)
    assert {"call_hook", "meeting_prep"} < set(schema.BOT_BRIEFING_MODES)
    swap_kind, swap_mode = schema.BOT_TASKS_DDL[:2]
    # Podmiana CHECK-u tylko raz: entrypoint biegnie przy każdym starcie.
    assert "LIKE '%people%'" in swap_kind and "'people'" in swap_kind
    assert "LIKE '%meeting_prep%'" in swap_mode and "'call_hook'" in swap_mode


def _ctx() -> bot_tasks.TaskContext:
    return bot_tasks.TaskContext(firms=({"ref": 1, "name": "Firma A"},), request={})


def test_unknown_kind_and_new_kinds_without_flag_do_not_start(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    monkeypatch.setitem(bot_tasks.REGISTRY, "enrich", FAKE)
    assert bot_tasks.allowed_to_start("signals")
    assert bot_tasks.allowed_to_start("briefing")
    assert not bot_tasks.allowed_to_start("enrich")
    assert not bot_tasks.allowed_to_start("unregistered")
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    assert bot_tasks.allowed_to_start("enrich")
    assert not bot_tasks.allowed_to_start("unregistered")


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [False, True])
async def test_start_run_refuses_before_touching_the_database(
    monkeypatch, flag
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", flag)
    # ``db=None``: odmowa musi zapaść przed pierwszym zapytaniem.
    assert await signals.start_run(None, "unregistered", [1], now=NOW) is None
    if not flag:
        monkeypatch.setitem(bot_tasks.REGISTRY, "enrich", FAKE)
        assert await signals.start_run(None, "enrich", [1], now=NOW) is None


def test_request_only_with_fields_the_kind_declares() -> None:
    legacy = bot_tasks.REGISTRY["signals"]
    assert legacy.validate_request(None) == {}
    assert legacy.validate_request({}) == {}
    with pytest.raises(ValueError):
        legacy.validate_request({"question": "kto tam pracuje"})
    assert FAKE.validate_request({"limit": 2}) == {"limit": 2}
    with pytest.raises(ValueError):
        FAKE.validate_request({"limit": 2, "email": "x@example.com"})


@pytest.mark.asyncio
async def test_start_run_refuses_request_fields_of_a_legacy_kind() -> None:
    with pytest.raises(ValueError):
        await signals.start_run(None, "signals", [1], now=NOW, request={"x": 1})


# ── treść webhooka v2 ────────────────────────────────────────────────────


V1_FIELDS = {
    "schema_version",
    "run_id",
    "kind",
    "callback_url",
    "token",
    "expires_at",
    "window_days",
    "max_signals",
    "max_points",
    "signal_types",
    "firms",
    "rejected",
    "seen_urls",
}


def test_webhook_body_v2_keeps_v1_fields_and_adds_task(monkeypatch) -> None:
    run, token = signals.new_run("signals", [1], now=NOW)
    run.id = 12
    company = SalesCompany(id=1, name="Firma A", domain="firma-a.pl", nip="123")
    body = signals.webhook_body(
        run, token, [company], {"rejected": [], "seen_urls": []}
    )
    assert V1_FIELDS <= set(body)
    assert body["request"] == {}
    assert "signal_types" in body["task"] or "sygnał" in body["task"]
    assert set(body["report_format"]) == {
        "checked_firms",
        "signals",
        "briefings",
        "no_signal",
    }
    assert "nip" not in str(body)

    monkeypatch.setitem(bot_tasks.REGISTRY, "enrich", FAKE)
    run, token = signals.new_run("enrich", [1], now=NOW, request={"limit": 3})
    run.id = 13
    body = signals.webhook_body(
        run, token, [company], {"rejected": [], "seen_urls": []}
    )
    assert body["kind"] == "enrich"
    assert body["task"] == "Sprawdź 1 firm, limit 3."
    assert body["report_format"] == {"items": ["https://..."]}
    assert body["request"] == {"limit": 3}


# ── przyjęcie raportu ────────────────────────────────────────────────────


def test_parse_report_validates_with_the_kind_model() -> None:
    report = intake.parse_report(b'{"items": ["e.com/a"]}', _FakeReport)
    assert report.items == ["https://e.com/a"]
    for raw in (
        b"{",
        b"",
        b'{"items": ["javascript:alert(1)"]}',
        b'{"items": [], "people": []}',
        b'{"items": ["https://e.com/1", "https://e.com/2", "https://e.com/3", "https://e.com/4"]}',
    ):
        with pytest.raises(RequestValidationError) as caught:
            intake.parse_report(raw, _FakeReport)
        assert caught.value.errors()[0]["loc"][0] == "body"


def _request(body: bytes, *, declared: int | None = None) -> Request:
    headers = [] if declared is None else [(b"content-length", str(declared).encode())]
    chunks = [body[i : i + 1000] for i in range(0, len(body), 1000)] or [b""]

    async def receive():
        chunk = chunks.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}

    scope = {"type": "http", "method": "POST", "headers": headers, "path": "/"}
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_body_over_the_limit_is_413_also_without_content_length() -> None:
    assert await intake.read_limited(_request(b"x" * 100), limit=100) == b"x" * 100
    with pytest.raises(HTTPException) as declared:
        await intake.read_limited(_request(b"{}", declared=101), limit=100)
    assert declared.value.status_code == 413
    with pytest.raises(HTTPException) as streamed:
        await intake.read_limited(_request(b"x" * 2500), limit=2000)
    assert streamed.value.status_code == 413
    assert intake.MAX_REPORT_BYTES == 512 * 1024


@pytest.mark.asyncio
async def test_fake_kind_round_trip_marks_run_received() -> None:
    run, token = signals.new_run("enrich", [1], now=NOW)
    run.id = 14
    report = intake.parse_report(b'{"items": ["https://e.com/a"]}', _FakeReport)
    summary = await bot_tasks.ingest(None, FAKE, run, report, now=NOW)
    assert summary == {"items": 1, "first": "https://e.com/a"}
    assert (run.status, run.token_hash, run.received_at) == ("received", None, NOW)
    assert not signals.token_matches(run, token, NOW)
    # Odpowiedź dla bota: same liczby, bez treści.
    assert FAKE.reply(summary) == {"items": 1}


def test_legacy_reply_keeps_the_v1_response_shape() -> None:
    summary = {
        "leads": 2,
        "leads_new": 1,
        "briefings": 1,
        "quiet": ["Firma B"],
        "dropped": {
            "outside_window": [{"company": "Firma A"}],
            "nexus_clients": [],
            "unknown_company": 3,
            "duplicates": 0,
        },
    }
    assert bot_tasks.REGISTRY["signals"].reply(summary) == {
        "leads": 2,
        "leads_new": 1,
        "briefings": 1,
        "dropped": {
            "outside_window": 1,
            "nexus_clients": 0,
            "unknown_company": 3,
            "duplicates": 0,
        },
    }


def test_numbers_only_drops_names_and_lists() -> None:
    assert bot_tasks.numbers_only(
        {"a": 1, "b": "Firma", "c": ["x"], "d": {"e": 2.5, "f": "y"}, "g": {"h": "z"}}
    ) == {"a": 1, "d": {"e": 2.5}}


def test_result_fingerprint_is_stable_and_fits_the_column() -> None:
    first = bot_tasks.result_fingerprint("enrich", 1, "HTTPS://E.com/a")
    assert first == bot_tasks.result_fingerprint("enrich", 1, "https://e.com/a")
    assert first.startswith("enrich|") and len(first) <= 200
    assert first != bot_tasks.result_fingerprint("winback", 1, "https://e.com/a")


@pytest.mark.asyncio
async def test_default_accept_is_refused_with_409_message() -> None:
    with pytest.raises(bot_tasks.AcceptRefused) as caught:
        await FAKE.accept(None, None, 1, NOW)
    assert str(caught.value) == "Ten rodzaj nie ma jeszcze akcji."
