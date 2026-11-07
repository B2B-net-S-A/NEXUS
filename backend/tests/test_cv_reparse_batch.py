"""Ponowny odczyt CV starej bazy przez Batch API (`cv_reparse_batch`, 07.11.2026).

Kontrakty:

- paczka wysyła dokładnie to samo żądanie co ścieżka rekrutera;
- wynik idzie przez `finish_cv_ingest` z FILL_EMPTY i BEZ auto-dopasowania;
- CV zmienione po wysłaniu, nieudana odpowiedź i sprzeczna nazwa nic nie
  zapisują; nieudana odpowiedź wraca do zakresu najwyżej raz;
- koszt paczki jest liczony za pół ceny;
- znaczniki biegów (`_cv_*`) nie giną przy kolejnym odczycie CV;
- faza nocna czyta pełnym promptem.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import cv_reparse_batch as reparse
from app.services.ai_metering import response_event
from app.services.llm_prompts import CV_ENRICHMENT

CV = "Jan Kowalski\nJava Developer\nBank X 2020-01 – obecnie: Java, Kafka"


class _Nested:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _FakeDb:
    def __init__(self, candidate):
        self.candidate = candidate

    async def get(self, _model, _id):
        return self.candidate

    async def flush(self):
        return None

    def begin_nested(self):
        return _Nested()


def _candidate(**overrides):
    base = dict(id=7, raw_cv_text=CV, cv_extracted_data={})
    base.update(overrides)
    return SimpleNamespace(**base)


def _message(payload: dict):
    return SimpleNamespace(
        content=[SimpleNamespace(text=json.dumps(payload))],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=2000, output_tokens=3000),
    )


@pytest.fixture
def wired(monkeypatch):
    """Podstawione zależności zapisu: bramka, ingest, telemetria, kwota."""
    calls: dict = {"ingest": [], "usage": []}

    class _Feature:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    async def fake_ingest(db, **kwargs):
        calls["ingest"].append(kwargs)
        kwargs["candidate"].cv_extracted_data = {
            **kwargs["candidate"].cv_extracted_data,
            "skill_timeline": [{"skill": "Java", "months": 70}],
        }

    async def no_mismatch(db, candidate, parsed):
        return calls.get("held", False)

    import app.services.claude_client as cc
    import app.services.cv_field_backfill as cfb
    import app.services.cv_ingest_service as ingest

    monkeypatch.setattr(reparse, "ai_feature", _Feature)
    monkeypatch.setattr(ingest, "finish_cv_ingest", fake_ingest)
    monkeypatch.setattr(cfb, "_read_names_another_person", no_mismatch)
    monkeypatch.setattr(
        cc,
        "record_batch_message_usage",
        lambda m, *, model: calls["usage"].append(model),
    )
    return calls


def _apply(candidate, result, digest=None):
    """Skrót tak jak w paczce: z `custom_id`, czyli tylko jego początek."""
    if digest is None:
        _, digest = reparse.parse_custom_id(
            reparse.custom_id(candidate.id, reparse.text_digest(candidate.raw_cv_text))
        )
    stats = reparse.ReparseStats()
    asyncio.run(
        reparse.apply_result(
            _FakeDb(candidate),
            candidate_id=candidate.id,
            digest=digest,
            result=result,
            model="claude-haiku-5-5",
            stats=stats,
        )
    )
    return stats


def _ok(payload=None):
    return SimpleNamespace(
        type="succeeded",
        message=_message(payload or {"first_name": "Jan", "experience": []}),
    )


def test_custom_id_round_trip_and_foreign_ids_are_ignored():
    cid = reparse.custom_id(123, "abcdef0123456789ffff")
    assert len(cid) <= 64
    assert reparse.parse_custom_id(cid) == (123, "abcdef0123456789")
    for other in ("x-1-2", "cvr-abc-1", "cvr-1", ""):
        assert reparse.parse_custom_id(other) is None


def test_batch_request_is_the_recruiter_request():
    request = reparse.build_requests([(5, CV)], model="claude-haiku-5-5")[0]
    params = request["params"]
    assert params["model"] == "claude-haiku-5-5"
    assert params["system"] == CV_ENRICHMENT.system_prompt
    assert params["max_tokens"] == 8000
    assert params["thinking"] == {"type": "disabled"}
    assert CV in params["messages"][0]["content"][1]["text"]


def test_success_goes_through_ingest_without_auto_match(wired):
    candidate = _candidate()
    stats = _apply(candidate, _ok())
    (call,) = wired["ingest"]
    assert call["enqueue_auto_match"] is False
    assert call["policy"].name == "FILL_EMPTY"
    assert call["parsed"]["_source"] == f"claude:cv_enrichment:v{CV_ENRICHMENT.version}"
    assert wired["usage"] == ["claude-haiku-5-5"]
    assert (stats.applied, stats.with_axis) == (1, 1)
    marker = candidate.cv_extracted_data["_cv_reparse"]
    assert marker["outcome"] == "ok"
    assert marker["md5"] == reparse.text_digest(CV), (
        "znacznik ma pełny skrót jak w zakresie SQL"
    )


def test_collecting_a_batch_again_skips_rows_already_written(wired):
    """Wdrożenie zabija bieg w połowie paczki; po restarcie zbieramy ją jeszcze raz.

    Wiersz już zapisany z tego samego tekstu nie przechodzi drugi raz przez
    ingest (wektor, oś, zapis), a próby nieudane dalej wracają do zakresu.
    """
    candidate = _candidate()
    _apply(candidate, _ok())
    stats = _apply(candidate, _ok())
    assert len(wired["ingest"]) == 1
    assert (stats.applied, stats.already) == (0, 1)
    assert candidate.cv_extracted_data["_cv_reparse"]["attempts"] == 1

    failed = _candidate(id=8)
    _apply(failed, SimpleNamespace(type="errored"))
    stats = _apply(failed, _ok())
    assert stats.applied == 1 and stats.already == 0


def test_cv_changed_after_submit_writes_nothing(wired):
    candidate = _candidate()
    stats = _apply(candidate, _ok(), digest="0" * 32)
    assert stats.stale == 1 and not wired["ingest"]
    assert "_cv_reparse" not in candidate.cv_extracted_data


def test_failed_response_returns_to_scope_once(wired):
    candidate = _candidate()
    bad = SimpleNamespace(type="errored")
    _apply(candidate, bad)
    assert candidate.cv_extracted_data["_cv_reparse"]["attempts"] == 1
    _apply(candidate, bad)
    marker = candidate.cv_extracted_data["_cv_reparse"]
    assert (marker["outcome"], marker["attempts"]) == ("failed", reparse.MAX_ATTEMPTS)
    assert not wired["ingest"]


def test_invalid_json_is_a_failure_not_a_crash(wired):
    candidate = _candidate()
    broken = SimpleNamespace(
        type="succeeded",
        message=SimpleNamespace(
            content=[SimpleNamespace(text='{"first_name" "Jan"}')],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        ),
    )
    stats = _apply(candidate, broken)
    assert stats.failed == 1 and not wired["ingest"]
    assert wired["usage"], "zapłacona odpowiedź i tak trafia do licznika"


def test_identity_mismatch_holds_the_profile(wired):
    wired["held"] = True
    candidate = _candidate()
    stats = _apply(candidate, _ok())
    assert stats.identity_held == 1 and not wired["ingest"]
    assert candidate.cv_extracted_data["_cv_reparse"]["outcome"] == "identity_held"


def test_scope_sql_skips_current_prompt_and_read_markers():
    sql = reparse._scope(include_with_axis=False)
    assert ":current_source" in sql and "_cv_reparse" in sql and "skill_timeline" in sql
    assert "skill_timeline" not in reparse._scope(include_with_axis=True)


def test_batch_cost_is_half_price():
    message = SimpleNamespace(
        id="m1",
        model="claude-haiku-5-5",
        usage=SimpleNamespace(
            input_tokens=2000,
            output_tokens=3000,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=0),
        ),
    )
    full = response_event("op", message, model="claude-haiku-5-5", latency_ms=1)
    half = response_event(
        "op", message, model="claude-haiku-5-5", latency_ms=1, batch=True
    )
    assert full["estimated_cost_usd"] == Decimal("0.00170000")
    assert half["estimated_cost_usd"] == Decimal("0.00085000")


def test_run_markers_survive_a_later_cv_read(monkeypatch):
    from app.services import cv_enrichment as ce

    monkeypatch.setattr(
        ce, "apply_candidate_location_from_source", lambda *a, **k: None
    )
    markers = {
        "_cv_text_extraction": {"outcome": "extracted"},
        "_cv_fields_read_md5": "abc",
        "_cv_reparse": {"md5": "x", "outcome": "ok", "attempts": 1},
    }
    candidate = SimpleNamespace(
        cv_extracted_data=dict(markers),
        experience=[],
        skills=[],
        education=[],
        years_it_experience=None,
        ai_summary=None,
        linkedin=None,
        name="?",
        lastname=None,
        email=None,
        phone=None,
        city=None,
        country=None,
        location=None,
        cv_parsed_at=None,
    )
    ce._apply_cv_enrichment(candidate, {"_source": "claude:cv_enrichment:v9"})
    for key, value in markers.items():
        assert candidate.cv_extracted_data[key] == value


def test_nightly_phase_reads_with_the_full_prompt():
    import inspect

    from app.services import cv_field_backfill

    source = inspect.getsource(cv_field_backfill.backfill_cv_fields)
    assert "template=CV_ENRICHMENT," in source
    assert "replace_skill_usage" in source
    assert "CV_ENRICHMENT_BULK" not in source


@pytest.mark.parametrize("flag,expected", [(True, 1), (False, 0)])
def test_ingest_skips_auto_match_only_when_asked(monkeypatch, flag, expected):
    from app.core.config import settings
    from app.services import cv_ingest_service as ingest
    import app.services.auto_match_outbox as amo
    import app.services.index_outbox_service as ios
    import app.services.match_score_cache as msc
    import app.services.profile_projection as pp

    queued: list[int] = []

    async def fake_enqueue(db, *, candidate_id, trigger, profile_revision):
        queued.append(candidate_id)

    async def zero(*a, **k):
        return 0

    async def none(*a, **k):
        return None

    async def same(db, candidate, parsed):
        return parsed

    monkeypatch.setattr(settings, "AUTO_MATCH_ENABLED", True)
    monkeypatch.setattr(amo, "enqueue_candidate", fake_enqueue)
    monkeypatch.setattr(amo, "candidate_revision", lambda c: "rev")
    monkeypatch.setattr(ios, "schedule_or_embed_candidate", zero)
    monkeypatch.setattr(msc, "mark_stale_for_candidate", none)
    monkeypatch.setattr(pp, "replace_skill_usage", zero)
    monkeypatch.setattr(ingest, "_apply_cv_enrichment", lambda *a, **k: 0)
    monkeypatch.setattr(ingest, "_without_taken_email", same)
    monkeypatch.setattr(ingest, "assign_primary_cc_if_empty", none)

    candidate = SimpleNamespace(id=9, email=None, competence_category_id=None)
    outcome = asyncio.run(
        ingest.finish_cv_ingest(
            _FakeDb(candidate),
            candidate=candidate,
            parsed={},
            source_document_id=None,
            source_hash=None,
            policy=None,
            trigger="t",
            enqueue_auto_match=flag,
        )
    )
    assert len(queued) == expected
    assert outcome.auto_match_queued is bool(expected)


class _CommittingDb(_FakeDb):
    def __init__(self, candidate):
        super().__init__(candidate)
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _entry(candidate, result):
    return SimpleNamespace(
        custom_id=reparse.custom_id(
            candidate.id, reparse.text_digest(candidate.raw_cv_text)
        ),
        result=result,
    )


def test_write_error_marks_the_cv_so_the_next_run_does_not_pay_again(
    wired, monkeypatch
):
    import app.services.cv_ingest_service as ingest

    async def broken_ingest(db, **kwargs):
        raise ValueError("np. constraint")

    monkeypatch.setattr(ingest, "finish_cv_ingest", broken_ingest)
    candidate = _candidate()
    stats = reparse.ReparseStats()
    asyncio.run(
        reparse.apply_batch_results(
            _CommittingDb(candidate),
            [_entry(candidate, _ok())],
            model="claude-haiku-5-5",
            stats=stats,
        )
    )
    assert stats.errors == 1
    marker = candidate.cv_extracted_data["_cv_reparse"]
    assert (marker["outcome"], marker["attempts"]) == ("failed", 1)


def test_broken_result_stream_still_commits_written_rows(wired):
    candidate = _candidate()
    db = _CommittingDb(candidate)

    def stream():
        yield _entry(candidate, _ok())
        raise ConnectionError("strumień wyników zerwany")

    with pytest.raises(ConnectionError):
        asyncio.run(
            reparse.apply_batch_results(
                db, stream(), model="claude-haiku-5-5", stats=reparse.ReparseStats()
            )
        )
    assert db.commits == 1, (
        "wiersze zapisane przed zerwaniem muszą zostać zacommitowane"
    )
