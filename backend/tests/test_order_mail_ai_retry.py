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
from app.core.scheduling import business_today
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
    # F7 = GPT-6 Luna (22.09.2026): sonda pyta o klucz DOSTAWCY modelu.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(parser.settings, "ORDER_EXTRACTION_ENABLED", True)

    def boom(**_kwargs):
        raise anthropic.APITimeoutError(request=_request())

    monkeypatch.setattr(parser, "call_claude", boom)
    result = await parse_order_document("Zamówienie nr 1/2031", all_rows=True)
    assert result.source == "regex"
    assert result.ai_failure == "przekroczony czas odpowiedzi AI"


async def test_fallback_records_disabled_extraction(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # F7 = GPT-6 Luna (22.09.2026): sonda pyta o klucz DOSTAWCY modelu.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
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
    # F7 = GPT-6 Luna (22.09.2026): sonda pyta o klucz DOSTAWCY modelu.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
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


# ── Odpowiedź modelu otoczona prozą (PKO BP, 15.09: ponowienie też „nie JSON") ──

_OBJECT = '{"title": "1/2031", "consultant_rows": [], "confidence": {}}'
_TRUNCATED = '{"title": "1/2031", "consultant_rows": ['


@pytest.mark.parametrize(
    "raw",
    [
        _OBJECT,
        f"```json\n{_OBJECT}\n```",
        f"Oto wynik odczytu:\n{_OBJECT}",
        f"```json\n{_OBJECT}\n```\nUwaga: stawka oznaczona gwiazdką jest negocjowana.",
        f'Przykład formatu {{"a": 1}} — właściwy wynik:\n{_OBJECT}\nKoniec.',
    ],
)
def test_model_json_is_found_inside_prose_and_fences(raw):
    assert parser.parse_model_json(raw)["title"] == "1/2031"


@pytest.mark.parametrize(
    "raw",
    ["", "Nie mogę odczytać dokumentu.", '{"title": "1/2031", "consultant_rows": ['],
)
def test_unreadable_or_truncated_answer_is_not_repaired(raw):
    assert parser.parse_model_json(raw) is None


def test_unparsed_shape_describes_without_content():
    truncated_raw = '{"title": "1893/2031", "consultant_rows": ['
    shape = parser.describe_unparsed_response(truncated_raw, "max_tokens")
    assert shape == (
        f"zaczyna się od {{, {len(truncated_raw)} znaków, ucięta limitem tokenów"
    )
    assert "1893" not in shape
    assert (
        parser.describe_unparsed_response("Tekst", "end_turn")
        == "zaczyna się od tekstu, 5 znaków, stop=end_turn"
    )


def _message(text: str, stop_reason: str = "end_turn"):
    from types import SimpleNamespace

    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason
    )


async def test_answer_with_prose_is_read_by_ai_not_fallback(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # F7 = GPT-6 Luna (22.09.2026): sonda pyta o klucz DOSTAWCY modelu.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(parser.settings, "ORDER_EXTRACTION_ENABLED", True)
    monkeypatch.setattr(
        parser, "call_claude", lambda **_k: _message(f"Wynik:\n{_OBJECT}\nGotowe.")
    )
    result = await parse_order_document("Zamówienie nr 1/2031", all_rows=True)
    assert result.source == "claude" and result.ai_failure is None
    assert result.title == "1/2031"


async def test_truncated_answer_falls_back_with_shape(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # F7 = GPT-6 Luna (22.09.2026): sonda pyta o klucz DOSTAWCY modelu.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(parser.settings, "ORDER_EXTRACTION_ENABLED", True)
    monkeypatch.setattr(
        parser,
        "call_claude",
        lambda **_k: _message(_TRUNCATED, "max_tokens"),
    )
    result = await parse_order_document("Zamówienie nr 1/2031", all_rows=True)
    assert result.source == "regex"
    assert result.ai_failure == (
        "nieczytelna odpowiedź AI (nie JSON; zaczyna się od {, "
        f"{len(_TRUNCATED)} znaków, ucięta limitem tokenów)"
    )


# ── Kwota `order_parser` w ścieżce poczty (09.2026) ─────────────────────────
#
# Do 09.2026 poczta wołała model poza `ai_feature`: wywołania nie trafiały do
# telemetrii AI ani pod wyłącznik funkcji. `AI_QUOTA_STRICT` w CI tego nie
# łapał, bo parser zamówień zamienia KAŻDY wyjątek wywołania (także
# `AIQuotaUngated`) na odczyt awaryjny, a testy podmieniały `call_claude`
# na poziomie parsera albo cały `parse_order_document`.


def _ai_available(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # F7 = GPT-6 Luna (22.09.2026): sonda pyta o klucz DOSTAWCY modelu.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(ingest.settings, "ORDER_EXTRACTION_ENABLED", True)


def _refusing_gate(reason: str):
    from contextlib import asynccontextmanager

    from app.services.ai_quota import AIQuotaExceeded

    @asynccontextmanager
    async def gate(_db, feature, **_kwargs):
        raise AIQuotaExceeded(feature, reason)
        yield  # pragma: no cover — generator kontekstu

    return gate


def _declared_admission(monkeypatch, admitted: list):
    """`check_and_increment` bez bazy — `ai_feature` ustawia prawdziwy kontekst."""

    from app.services import ai_quota

    async def admit(_db, feature, user_id=None, *, units=1, commit_with_caller=False):
        admitted.append((feature, user_id))
        return ai_quota.QuotaState(
            used=1, limit=0, period_start=business_today(), operation_id="op-test"
        )

    monkeypatch.setattr(ai_quota, "check_and_increment", admit)


async def test_mail_read_runs_inside_the_order_parser_declaration(monkeypatch):
    from app.models.ai_feature import AIFeatureKey
    from app.services import ai_quota

    _ai_available(monkeypatch)
    admitted: list = []
    seen: list = []
    _declared_admission(monkeypatch, admitted)

    async def model(_text, **kwargs):
        call = ai_quota.current_ai_call()
        seen.append((call.feature if call else None, kwargs))
        return OrderExtraction(source="claude")

    monkeypatch.setattr(ingest, "parse_order_document", model)

    result = await ingest.read_order_with_model(
        AsyncMock(), "Zamówienie nr 1/2031", fallback_when_blocked=True
    )

    assert result.source == "claude"
    assert admitted == [(AIFeatureKey.order_parser, None)]
    assert seen == [(AIFeatureKey.order_parser, {"all_rows": True})]


async def test_quota_refusal_gives_the_mail_a_fallback_read_with_a_reason(
    monkeypatch,
):
    _ai_available(monkeypatch)
    monkeypatch.setattr(
        ingest, "ai_feature", _refusing_gate("Funkcja AI wyłączona w ustawieniach")
    )

    def must_not_call(**_kwargs):
        raise AssertionError("model wywołany mimo odmowy kwoty")

    monkeypatch.setattr(parser, "call_claude", must_not_call)

    result = await ingest.read_order_with_model(
        AsyncMock(), "Zamówienie nr 1/2031", fallback_when_blocked=True
    )

    assert result.source == "regex"
    assert result.ai_failure == (
        "odczyt AI zablokowany w ustawieniach AI (Funkcja AI wyłączona w ustawieniach)"
    )


async def test_quota_refusal_reaches_the_retry_loop(monkeypatch):
    from app.services.ai_quota import AIQuotaExceeded

    _ai_available(monkeypatch)
    monkeypatch.setattr(
        ingest, "ai_feature", _refusing_gate("Miesięczny limit wyczerpany")
    )
    monkeypatch.setattr(
        ingest, "parse_order_document", AsyncMock(side_effect=AssertionError("odczyt"))
    )

    with pytest.raises(AIQuotaExceeded):
        await ingest.read_order_with_model(
            AsyncMock(), "Zamówienie nr 1/2031", fallback_when_blocked=False
        )


async def test_no_quota_operation_when_the_model_cannot_run(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(ingest.settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(ingest.settings, "OPENAI_API_KEY", None)
    monkeypatch.setattr(ingest, "ai_feature", _refusing_gate("bramka nie może ruszyć"))
    model = AsyncMock(
        return_value=OrderExtraction(source="regex", ai_failure="brak klucza API AI")
    )
    monkeypatch.setattr(ingest, "parse_order_document", model)

    result = await ingest.read_order_with_model(
        AsyncMock(), "Zamówienie nr 1/2031", fallback_when_blocked=False
    )

    assert result.ai_failure == "brak klucza API AI"
    model.assert_awaited_once()


async def test_quota_refusal_does_not_spend_a_retry_attempt(monkeypatch, tmp_path):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        _, doc = await _pending_fallback(db, monkeypatch, tmp_path)
        monkeypatch.setattr(
            ingest, "ai_feature", _refusing_gate("Miesięczny limit wyczerpany")
        )
        model = AsyncMock(side_effect=AssertionError("odczyt mimo odmowy kwoty"))
        monkeypatch.setattr(ingest, "parse_order_document", model)

        stats = ingest.IngestStats()
        await ingest.retry_ai_fallback_documents(db, stats)

        assert stats.ai_retried == 0
        await db.refresh(doc)
        assert "ai_retry_attempts" not in (doc.document_meta or {})
        model.assert_not_awaited()
        await db.rollback()


async def test_new_mail_document_is_read_under_the_order_parser_declaration(
    monkeypatch,
):
    from types import SimpleNamespace

    from app.models.ai_feature import AIFeatureKey
    from app.services import ai_quota
    from app.services.order_document_text import OrderDocumentText

    _ai_available(monkeypatch)
    admitted: list = []
    declared: list = []
    _declared_admission(monkeypatch, admitted)

    async def model(_text, **_kwargs):
        call = ai_quota.current_ai_call()
        declared.append(call.feature if call else None)
        return OrderExtraction(source="claude")

    monkeypatch.setattr(ingest, "parse_order_document", model)
    monkeypatch.setattr(
        ingest,
        "extract_order_text",
        lambda *_a: OrderDocumentText(
            text="Zamówienie nr 7/2031",
            page_count=1,
            ocr_used=False,
            ocr_capped=False,
            reextracted_with=None,
            letter_spacing_ratio=0,
        ),
    )
    monkeypatch.setattr(
        ingest,
        "identify_client",
        lambda *_a, **_kw: SimpleNamespace(method="none", reason="", client_key=None),
    )
    monkeypatch.setattr(
        ingest, "resolve_order_client_id", AsyncMock(return_value=(None, None))
    )
    row = SimpleNamespace(
        attachment_name="7-2031.pdf", sender_email="o@example.com", gate_verdict=None
    )

    await ingest.process_pdf_bytes(AsyncMock(), row, b"synthetic", registry=None)

    assert admitted == [(AIFeatureKey.order_parser, None)]
    assert declared == [AIFeatureKey.order_parser]


async def test_retry_read_runs_under_the_order_parser_declaration(
    monkeypatch, tmp_path
):
    from app.core.database import AsyncSessionLocal
    from app.models.ai_feature import AIFeatureKey
    from app.services import ai_quota

    async with AsyncSessionLocal() as db:
        _, doc = await _pending_fallback(db, monkeypatch, tmp_path)
        admitted: list = []
        declared: list = []
        _declared_admission(monkeypatch, admitted)
        still_down = OrderExtraction(
            source="regex", ai_failure="dostawca AI przeciążony"
        )

        async def model(_text, **_kwargs):
            call = ai_quota.current_ai_call()
            declared.append(call.feature if call else None)
            return still_down

        monkeypatch.setattr(ingest, "parse_order_document", model)
        stats = ingest.IngestStats()
        await ingest.retry_ai_fallback_documents(db, stats)

        assert admitted == [(AIFeatureKey.order_parser, None)]
        assert declared == [AIFeatureKey.order_parser]
        assert stats.ai_retried == 1
        await db.rollback()
