"""Odczyt awaryjny (bez AI): powód zapisany na wpisie i ponowienie odczytu AI.

Zgłoszenie 09.2026 (PKO BP): mail odczytany w trakcie deployu dostał odczyt
awaryjny, a powód awarii AI trafił wyłącznie do logu kontenera, który zniknął
przy następnym deployu. Wpis czekał na człowieka, choć ponowny odczyt AI
kilka godzin później by się udał.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest

from app.services import order_mail_ingest as ingest
from app.services import order_pdf_parser as parser
from app.services.claude_client import ClaudeOverloaded
from app.services.order_mail_gate import evaluate
from app.services.order_pdf_parser import OrderExtraction, parse_order_document
from app.services.order_policies import policy_by_key
from tests.test_alior_order_policy import (
    _alior_with_a_pending_next_period,
    old_rule_extraction,
)
from tests.test_order_mail_gate_and_planner import _extraction, _gate_input, _row

# ── Parser: powód porażki AI ────────────────────────────────────────────────


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ClaudeOverloaded("x"), "dostawca AI przeciążony"),
        (
            anthropic.APITimeoutError(request=_request()),
            "przekroczony czas odpowiedzi AI",
        ),
        (
            anthropic.APIConnectionError(request=_request()),
            "brak połączenia z dostawcą AI",
        ),
        (
            anthropic.RateLimitError(
                "x", response=httpx.Response(429, request=_request()), body=None
            ),
            "limit zapytań u dostawcy AI (HTTP 429)",
        ),
        (
            anthropic.InternalServerError(
                "x", response=httpx.Response(500, request=_request()), body=None
            ),
            "błąd dostawcy AI (HTTP 500)",
        ),
        (ValueError("treść dokumentu"), "błąd wywołania AI (ValueError)"),
    ],
)
def test_ai_failure_is_described_without_provider_message(exc, expected):
    assert parser.describe_ai_failure(exc) == expected


async def test_fallback_records_why_the_model_call_failed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(parser.settings, "ORDER_EXTRACTION_ENABLED", True)

    def boom(**_kwargs):
        raise anthropic.APITimeoutError(request=_request())

    monkeypatch.setattr(parser, "call_claude", boom)
    result = await parse_order_document("Zamówienie nr 1/2031", all_rows=True)
    assert result.source == "regex"
    assert result.ai_failure == "przekroczony czas odpowiedzi AI"


async def test_fallback_records_disabled_extraction(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(parser.settings, "ORDER_EXTRACTION_ENABLED", False)
    result = await parse_order_document("Zamówienie nr 1/2031", all_rows=True)
    assert result.ai_failure == "odczyt AI wyłączony (ORDER_EXTRACTION_ENABLED)"


async def test_successful_read_after_a_failure_carries_no_stale_reason(monkeypatch):
    parser._AI_FAILURE.set("brak połączenia z dostawcą AI")
    monkeypatch.setattr(
        parser,
        "_extract_all_rows_with_claude",
        AsyncMock(return_value=OrderExtraction(source="claude")),
    )
    result = await parse_order_document("Zamówienie nr 1/2031", all_rows=True)
    assert result.source == "claude" and result.ai_failure is None


def test_failure_reason_survives_the_database_round_trip():
    ex = OrderExtraction(source="regex", ai_failure="dostawca AI przeciążony")
    restored = ingest.restore_extraction(ingest.extraction_to_json(ex))
    assert restored.ai_failure == "dostawca AI przeciążony"


# ── Bramka: powód widoczny w kolejce ────────────────────────────────────────


def test_gate_reason_names_the_ai_failure():
    ex = _extraction([_row("Jan Kowalski")], source="regex")
    ex.ai_failure = "przekroczony czas odpowiedzi AI"
    verdict = evaluate(_gate_input(extraction=ex))
    assert (
        "Odczyt awaryjny (AI: przekroczony czas odpowiedzi AI) — sprawdź zgodność pól z PDF"
        in verdict.reasons
    )


def test_gate_reason_without_known_failure_is_unchanged():
    verdict = evaluate(
        _gate_input(extraction=_extraction([_row("Jan Kowalski")], source="regex"))
    )
    assert "Odczyt awaryjny — sprawdź zgodność pól z PDF" in verdict.reasons


# ── Ponowienie odczytu AI w biegu skrzynki (baza) ───────────────────────────


def _fallback_extraction() -> dict:
    stored = ingest.restore_extraction(old_rule_extraction())
    stored.source = "regex"
    stored.ai_failure = "brak połączenia z dostawcą AI"
    stored.consultant_rows = []
    return ingest.extraction_to_json(stored)


async def _pending_fallback(db, monkeypatch, tmp_path, **meta):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ingest.settings, "ORDER_EXTRACTION_ENABLED", True)
    current = {"alior": policy_by_key("alior").rule_version}
    return await _alior_with_a_pending_next_period(
        db,
        monkeypatch,
        tmp_path,
        extraction=_fallback_extraction(),
        document_meta={"page_count": 2, "rule_versions": current, **meta},
        gate_reasons=["Odczyt awaryjny — sprawdź zgodność pól z PDF"],
    )


async def test_recovered_ai_read_is_planned_and_auto_applied(monkeypatch, tmp_path):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        first, doc = await _pending_fallback(db, monkeypatch, tmp_path)
        model = AsyncMock(return_value=ingest.restore_extraction(old_rule_extraction()))
        monkeypatch.setattr(ingest, "parse_order_document", model)
        stats = ingest.IngestStats()
        await ingest.retry_ai_fallback_documents(db, stats)
        assert (stats.ai_retried, stats.ai_recovered) == (1, 1), stats.errors
        assert stats.ai_recovered_auto_applied == 1
        await db.refresh(doc)
        assert doc.outcome == "auto_applied", doc.gate_reasons
        assert doc.extraction["source"] == "claude"
        assert doc.document_meta["ai_retry_attempts"] == 1
        assert doc.document_meta["ai_recovered_at"]
        assert doc.applied_order_id not in (None, first.id)

        again = ingest.IngestStats()
        await ingest.retry_ai_fallback_documents(db, again)
        assert again.ai_retried == 0
        assert model.await_count == 1


async def test_failed_retry_records_reason_and_stops_after_the_cap(
    monkeypatch, tmp_path
):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        _, doc = await _pending_fallback(db, monkeypatch, tmp_path)
        still_down = OrderExtraction(
            source="regex", ai_failure="dostawca AI przeciążony"
        )
        model = AsyncMock(return_value=still_down)
        monkeypatch.setattr(ingest, "parse_order_document", model)

        for attempt in range(1, ingest.MAX_AI_RETRY_ATTEMPTS + 1):
            stats = ingest.IngestStats()
            await ingest.retry_ai_fallback_documents(db, stats)
            assert (stats.ai_retried, stats.ai_recovered) == (1, 0), stats.errors
            await db.refresh(doc)
            assert doc.outcome == "needs_review"
            assert doc.document_meta["ai_retry_attempts"] == attempt
            assert (
                doc.document_meta["ai_retry_last_failure"] == "dostawca AI przeciążony"
            )
            assert (
                "Odczyt awaryjny (AI: dostawca AI przeciążony) — sprawdź zgodność pól z PDF"
                in doc.gate_reasons
            )

        assert any("nie powiódł się 3×" in r for r in doc.gate_reasons)
        stats = ingest.IngestStats()
        await ingest.retry_ai_fallback_documents(db, stats)
        assert stats.ai_retried == 0
        assert model.await_count == ingest.MAX_AI_RETRY_ATTEMPTS

        # „Przelicz plan" nie kasuje licznika prób.
        await ingest.refresh_review_plan(db, doc)
        assert doc.document_meta["ai_retry_attempts"] == ingest.MAX_AI_RETRY_ATTEMPTS
        await db.rollback()


async def test_no_retry_when_ai_extraction_is_off(monkeypatch, tmp_path):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        _, doc = await _pending_fallback(db, monkeypatch, tmp_path)
        monkeypatch.setattr(ingest.settings, "ORDER_EXTRACTION_ENABLED", False)
        model = AsyncMock(side_effect=AssertionError("AI wyłączone"))
        monkeypatch.setattr(ingest, "parse_order_document", model)
        stats = ingest.IngestStats()
        await ingest.retry_ai_fallback_documents(db, stats)
        assert stats.ai_retried == 0
        await db.refresh(doc)
        assert "ai_retry_attempts" not in doc.document_meta
