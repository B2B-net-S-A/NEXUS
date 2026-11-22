"""Odczyt CV z integracji wsadem (`cv_parse_batch`, decyzja Artura 22.11.2026).

Kontrakty bez bazy:

- wgranie z integracji idzie do kolejki i NIE woła modelu na żywo;
- wgranie przez człowieka i kolejka wyłączona czytają na żywo jak dotąd;
- paczka wysyła to samo żądanie co odczyt na żywo, z tą samą translacją
  `thinking` (Sonnet 5.5 odrzuca `disabled`);
- wynik inny niż `succeeded`, niepoprawny JSON i błąd zapisu dają odczyt na
  żywo (`fallback`), a udany wynik idzie ścieżką wgrania CV z kosztem −50%.

Pełny obrót pętli na Postgresie: `test_cv_parse_batch_db.py`.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import cv_parse_batch

_SHA = "a" * 64


# ── wgranie: kolejka zamiast modelu ────────────────────────────────────────


class _ModelCalled(Exception):
    """Zatrzymuje zadanie w miejscu płatnego wywołania."""


class _Session:
    """Kolejne `scalar` zadania: dokument, kandydat, (recenzja tożsamości)."""

    def __init__(self, *answers: Any) -> None:
        self._answers = list(answers)
        self.commits = 0

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def scalar(self, _stmt: Any) -> Any:
        return self._answers.pop(0) if self._answers else None

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(all=lambda: [])

    async def refresh(self, *_a: Any, **_kw: Any) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


@pytest.fixture
def upload_task(monkeypatch):
    """Zadanie odczytu po wgraniu na atrapie sesji.

    Zwraca (wywołania `parse_cv`, wywołania `enqueue`, sesja).
    """
    from app.api import candidates as candidates_api
    from app.services import cv_parser, cv_text_extractor

    parse_calls: list[str] = []
    enqueue_calls: list[dict] = []

    async def _parse_cv(text: str, **_kw: Any) -> dict:
        parse_calls.append(text)
        raise _ModelCalled

    monkeypatch.setattr(cv_parser, "parse_cv", _parse_cv)
    monkeypatch.setattr(
        cv_text_extractor, "extract_text", lambda *_a: "Jan Testowy\nJava"
    )

    async def _run(*, queue_open: bool = True, **task_kwargs: Any):
        async def _enqueue(db, **kwargs):
            enqueue_calls.append(kwargs)
            return queue_open

        monkeypatch.setattr(cv_parse_batch, "enqueue", _enqueue)
        document = SimpleNamespace(
            id=2,
            filename="cv.txt",
            content_sha256=_SHA,
            storage_key=None,
            file_content=b"Jan Testowy\nJava",
        )
        # Profil bez odczytu tego pliku: zwykle płatny odczyt.
        candidate = SimpleNamespace(id=1, raw_cv_text=None, cv_extracted_data={})
        session = _Session(document, candidate)
        monkeypatch.setattr("app.core.database.AsyncSessionLocal", lambda: session)
        await candidates_api._enrich_candidate_from_document_task(
            1, 2, _SHA, **task_kwargs
        )
        return parse_calls, enqueue_calls, session

    return _run


async def test_integration_upload_is_queued_without_a_live_read(upload_task):
    replaced = SimpleNamespace(document_id=9, cv_filename="stare.pdf")
    parse_calls, enqueue_calls, session = await upload_task(
        defer_to_batch=True, actor_user_id=44, replaced_primary=replaced
    )
    assert parse_calls == []
    assert len(enqueue_calls) == 1
    queued = enqueue_calls[0]
    assert queued["candidate_id"] == 1
    assert queued["document_id"] == 2
    assert queued["content_sha256"] == _SHA
    assert queued["raw_text"] == "Jan Testowy\nJava"
    assert queued["actor_user_id"] == 44
    assert queued["replaced_primary"] is replaced
    assert session.commits == 1


async def test_human_upload_reads_live_and_never_queues(upload_task):
    parse_calls, enqueue_calls, _ = await upload_task()
    assert parse_calls == ["Jan Testowy\nJava"]
    assert enqueue_calls == []


async def test_closed_queue_falls_back_to_the_live_read(upload_task):
    parse_calls, enqueue_calls, _ = await upload_task(
        defer_to_batch=True, queue_open=False
    )
    assert len(enqueue_calls) == 1
    assert parse_calls == ["Jan Testowy\nJava"]


def _add_task_keywords(func) -> dict[str, ast.expr]:
    tree = ast.parse(inspect.getsource(func).lstrip())
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_task"
    )
    return {kw.arg: kw.value for kw in call.keywords}


def test_only_the_integration_upload_route_defers_to_the_batch():
    """`POST /{id}/cv` pyta o token integracji; reszta wgrań zostaje na żywo."""
    from app.api import candidates as candidates_api

    kwargs = _add_task_keywords(candidates_api._after_cv_commit)
    assert ast.unparse(kwargs["defer_to_batch"]) == "defer_to_batch"

    upload = ast.parse(inspect.getsource(candidates_api.upload_cv))
    deferred = [
        kw
        for node in ast.walk(upload)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "_after_cv_commit"
        for kw in node.keywords
        if kw.arg == "defer_to_batch"
    ]
    assert [ast.unparse(kw.value) for kw in deferred] == [
        "candidate_claim.is_integration_request(request)"
    ]

    # Ręczne „Dodaj plik” w zakładce Pliki i „Ponów odczyt” bez wsadu.
    documents = ast.parse(inspect.getsource(candidates_api.upload_candidate_document))
    assert not any(
        kw.arg == "defer_to_batch"
        for node in ast.walk(documents)
        if isinstance(node, ast.Call)
        for kw in node.keywords
    )
    reparse = _add_task_keywords(candidates_api.reparse_primary_cv)
    assert "defer_to_batch" not in reparse


# ── treść paczki ───────────────────────────────────────────────────────────


def test_batch_request_translates_disabled_thinking_for_sonnet_5_5():
    from app.services.claude_client import batch_request_params
    from app.services.cv_parser import claude_cv_request_params

    live = claude_cv_request_params("Jan Testowy", model="claude-sonnet-5-5")
    params = batch_request_params(live)
    assert params["thinking"] == {"type": "between_tools"}
    assert params["messages"] == live["messages"]
    assert params["system"] == live["system"]
    assert params["max_tokens"] == live["max_tokens"]
    assert "extra_body" not in params

    haiku = batch_request_params(
        claude_cv_request_params("Jan Testowy", model="claude-haiku-5-5")
    )
    assert haiku["thinking"] == {"type": "disabled"}


def test_custom_id_round_trip_and_foreign_ids_are_ignored():
    assert cv_parse_batch.parse_custom_id(cv_parse_batch.custom_id(123)) == 123
    for other in ("cvr-1-abc", "cvp-", "cvp-x", "", "x-1"):
        assert cv_parse_batch.parse_custom_id(other) is None


def test_queue_closes_with_kill_switch_and_non_anthropic_model(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda _m: True
    )
    monkeypatch.setattr(cv_parse_batch, "batch_model", lambda: "claude-sonnet-5-5")
    monkeypatch.setattr(settings, "CV_PARSER_BATCH_ENABLED", True)
    monkeypatch.setattr(settings, "CV_ENRICHMENT_ENABLED", True)
    assert cv_parse_batch.enabled() is True

    monkeypatch.setattr(settings, "CV_PARSER_BATCH_ENABLED", False)
    assert cv_parse_batch.enabled() is False

    monkeypatch.setattr(settings, "CV_PARSER_BATCH_ENABLED", True)
    monkeypatch.setattr(settings, "CV_ENRICHMENT_ENABLED", False)
    assert cv_parse_batch.enabled() is False

    monkeypatch.setattr(settings, "CV_ENRICHMENT_ENABLED", True)
    monkeypatch.setattr(cv_parse_batch, "batch_model", lambda: "gpt-6-luna")
    assert cv_parse_batch.enabled() is False


def test_replaced_primary_survives_the_queue_row():
    from app.services.candidate_identity_quarantine import ReplacedPrimaryCv

    original = ReplacedPrimaryCv(document_id=5, cv_filename="stare.pdf")
    stored = cv_parse_batch._replaced_to_json(original)
    assert json.loads(json.dumps(stored)) == stored
    assert cv_parse_batch._replaced_from_json(stored) == original
    assert cv_parse_batch._replaced_to_json(None) is None
    assert cv_parse_batch._replaced_from_json(None) is None


# ── wynik paczki ───────────────────────────────────────────────────────────


def _item(**overrides: Any) -> SimpleNamespace:
    base = dict(
        id=11,
        candidate_id=1,
        document_id=2,
        content_sha256=_SHA,
        raw_text="Jan Testowy\njan.testowy@example.com\nJava Developer\nJava, Kafka",
        trigger="cv_upload",
        actor_user_id=44,
        replaced_primary={"document_id": 9, "cv_filename": "stare.pdf"},
        model="claude-sonnet-5-5",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _succeeded(text: str) -> SimpleNamespace:
    message = SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=2000, output_tokens=3000),
    )
    return SimpleNamespace(
        custom_id="cvp-11", result=SimpleNamespace(type="succeeded", message=message)
    )


@pytest.fixture
def apply_wired(monkeypatch):
    from app.api import candidates as candidates_api

    calls: dict[str, list] = {"apply": [], "meter": []}
    state = {"applied": True, "raise": None}

    async def _apply(**kwargs):
        calls["apply"].append(kwargs)
        if state["raise"] is not None:
            raise state["raise"]
        return state["applied"]

    async def _meter(message, *, model, user_id):
        calls["meter"].append((model, user_id))

    monkeypatch.setattr(candidates_api, "_apply_batch_document_read", _apply)
    monkeypatch.setattr(cv_parse_batch, "_meter", _meter)
    return calls, state


def _run_apply(item, entry):
    return asyncio.run(cv_parse_batch._apply_result(item, entry))


def test_succeeded_result_goes_through_the_upload_path(apply_wired):
    calls, _ = apply_wired
    payload = {"first_name": "Jan", "last_name": "Testowy", "skills": ["Java"]}
    status, reason = _run_apply(_item(), _succeeded(json.dumps(payload)))
    assert (status, reason) == ("done", None)
    assert calls["meter"] == [("claude-sonnet-5-5", 44)]
    [applied] = calls["apply"]
    assert applied["candidate_id"] == 1
    assert applied["document_id"] == 2
    assert applied["expected_hash"] == _SHA
    assert applied["trigger"] == "cv_upload"
    assert applied["replaced_primary"].document_id == 9
    parsed = applied["parsed"]
    # Ta sama obróbka co `parse_cv`: źródło promptu, a kontakt, którego model
    # nie podał, z regexu po tekście CV.
    assert parsed["_source"].startswith("claude:")
    assert parsed["first_name"] == "Jan"
    assert parsed["email"] == "jan.testowy@example.com"


@pytest.mark.parametrize("result_type", ["errored", "canceled", "expired"])
def test_failed_result_falls_back_to_a_live_read(apply_wired, result_type):
    calls, _ = apply_wired
    entry = SimpleNamespace(
        custom_id="cvp-11", result=SimpleNamespace(type=result_type)
    )
    assert _run_apply(_item(), entry) == ("fallback", f"result_{result_type}")
    assert calls["apply"] == []


def test_missing_result_falls_back_to_a_live_read(apply_wired):
    calls, _ = apply_wired
    assert _run_apply(_item(), None) == ("fallback", "result_missing")
    assert calls["apply"] == []


def test_invalid_json_falls_back_to_a_live_read(apply_wired):
    calls, _ = apply_wired
    assert _run_apply(_item(), _succeeded("to nie jest JSON")) == (
        "fallback",
        "invalid_json",
    )
    assert calls["apply"] == []


def test_write_error_falls_back_to_a_live_read(apply_wired):
    calls, state = apply_wired
    state["raise"] = RuntimeError("deadlock")
    status, reason = _run_apply(_item(), _succeeded(json.dumps({"first_name": "Jan"})))
    assert (status, reason) == ("fallback", "apply_failed:RuntimeError")


def test_superseded_file_closes_without_a_second_read(apply_wired):
    """Plik przestał być głównym CV: odczyt na żywo nic by nie zmienił."""
    _, state = apply_wired
    state["applied"] = False
    assert _run_apply(_item(), _succeeded(json.dumps({"first_name": "Jan"}))) == (
        "done",
        "not_applied",
    )


def test_meter_prices_the_batch_at_half(monkeypatch):
    """`record_batch_message_usage` = wycena Batch API (−50%) w `ai_metering`."""
    from app.services import claude_client

    source = inspect.getsource(cv_parse_batch._meter)
    assert "AIFeatureKey.cv_parser" in source
    assert "record_batch_message_usage" in source
    recorded = []
    monkeypatch.setattr(
        claude_client,
        "_record_tokens",
        lambda message, *, model, batch=False, **_kw: recorded.append(batch),
    )
    claude_client.record_batch_message_usage(SimpleNamespace(), model="m")
    assert recorded == [True]
