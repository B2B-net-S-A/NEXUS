"""Narzędzie badania modeli (``scripts/model_eval``): bezpieczniki i miary.

Bez sieci i bez bazy — sprawdzamy to, co decyduje o uczciwości wyników:
blokadę modeli i danych, limit budżetu, tłumaczenie błędów dostawcy na
wyjątki SDK (od tego zależy polityka ponowień NEXUS) i porównania pól.
"""

from datetime import datetime, timezone
from decimal import Decimal

import anthropic
import pytest

from app.services.claude_client import is_retryable_anthropic_error, text_of
from scripts.model_eval import catalog, providers, scoring
from scripts.model_eval.ledger import BudgetExceeded, Ledger
from scripts.model_eval.shim import CURRENT, EvalAnthropic, _as_sdk_error, _message
from scripts.model_eval.tasks.orders import _rate_outcome, _title_outcome


def test_models_priced_like_opus_are_refused():
    for key in ("claude-opus-5", "claude-opus-4-8", "claude-fable-5-1"):
        with pytest.raises(catalog.ModelNotAllowed):
            catalog.spec_for(key)


def test_production_data_only_reaches_allowed_providers(monkeypatch):
    """Bez jawnego potwierdzenia dane produkcyjne idą wyłącznie do Anthropic."""
    monkeypatch.delenv("EVAL_OPENAI_PRODUCTION_CONFIRMED", raising=False)
    monkeypatch.delenv("EVAL_DEEPSEEK_PRODUCTION_CONFIRMED", raising=False)
    catalog.assert_data_allowed(
        catalog.spec_for("claude-haiku-4-5-20251001"), catalog.PRODUCTION
    )
    for key in (
        "deepseek-flash",
        "deepseek-v4-pro",
        "gemini-3.5-flash-lite",
        "gpt-5.6-luna",
    ):
        with pytest.raises(catalog.ModelNotAllowed):
            catalog.assert_data_allowed(catalog.spec_for(key), catalog.PRODUCTION)
    catalog.assert_data_allowed(catalog.spec_for("deepseek-flash"), catalog.SYNTHETIC)

    # Potwierdzenie jednego dostawcy nie otwiera drugiego.
    monkeypatch.setenv("EVAL_OPENAI_PRODUCTION_CONFIRMED", "1")
    catalog.assert_data_allowed(catalog.spec_for("gpt-5.6-luna"), catalog.PRODUCTION)
    with pytest.raises(catalog.ModelNotAllowed):
        catalog.assert_data_allowed(
            catalog.spec_for("deepseek-flash"), catalog.PRODUCTION
        )

    monkeypatch.setenv("EVAL_DEEPSEEK_PRODUCTION_CONFIRMED", "1")
    catalog.assert_data_allowed(catalog.spec_for("deepseek-flash"), catalog.PRODUCTION)
    # Gemini zostaje na syntetykach niezależnie od potwierdzeń (brak decyzji).
    with pytest.raises(catalog.ModelNotAllowed):
        catalog.assert_data_allowed(
            catalog.spec_for("gemini-3.5-flash-lite"), catalog.PRODUCTION
        )


def test_deepseek_peak_hours_double_the_price():
    spec = catalog.spec_for("deepseek-flash")
    peak = datetime(2026, 9, 15, 7, 0, tzinfo=timezone.utc)
    off_peak = datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc)
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    assert catalog.cost_usd(spec, at=peak, **usage) == pytest.approx(0.30)
    assert catalog.cost_usd(spec, at=off_peak, **usage) == pytest.approx(0.15)


def test_ledger_refuses_reservation_over_budget(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl", budget_usd=1.0)
    ledger.reserve(0.6)
    ledger.settle(0.6, {"cost_usd": 0.5})
    with pytest.raises(BudgetExceeded):
        ledger.reserve(0.6)
    assert Ledger(tmp_path / "ledger.jsonl", budget_usd=1.0).spent_usd == pytest.approx(
        0.5
    )


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (429, "rate_limit", True),
        (503, "", True),
        (500, "", True),
        (400, "response_format", False),
        (None, "timeout", True),
        (None, "connection", True),
    ],
)
def test_provider_errors_keep_nexus_retry_policy(status, code, retryable):
    error = _as_sdk_error(providers.ProviderError("openai", status, code))
    assert isinstance(error, anthropic.APIError)
    assert is_retryable_anthropic_error(error) is retryable


def test_translated_message_reads_like_anthropic():
    response = providers.LLMResponse(
        text='{"ok": true}', finish="length", input_tokens=10, output_tokens=5
    )
    message = _message("gpt-5.6-luna", response)
    assert text_of(message) == '{"ok": true}'
    assert message.stop_reason == "max_tokens"
    assert message.usage.output_tokens == 5


def test_model_call_outside_a_case_is_an_error():
    assert CURRENT.get() is None
    with pytest.raises(RuntimeError):
        EvalAnthropic(api_key="x")


def test_polish_inflection_counts_as_grounded():
    notes = "Nie chce wracać do projektów w Banku Przykładowym."
    assert scoring.grounded("Bank Przykładowy", notes)
    assert not scoring.grounded("Bank Inny", notes)


def test_reworded_technology_is_not_an_invention():
    cv = "Raporty w PowerBI, analizy w MS Excel, API z JWT."
    assert scoring.technology_grounding("Power BI", cv) == (True, True)
    assert scoring.technology_grounding("Microsoft Excel", cv)[0] is True
    assert scoring.technology_grounding("Kubernetes", cv) == (False, False)


def test_order_rate_compares_money_per_hour():
    assert _rate_outcome(900, "day", Decimal("112.50"), "hourly") == "correct"
    assert _rate_outcome(140, "month", 140, "hourly") == "wrong"
    assert _rate_outcome(None, None, 140, "hourly") == "missing"


def test_order_number_with_prefix_is_the_same_order():
    assert _title_outcome("OIT/0189/2026", "Zamówienie nr OIT/0189/2026") == "correct"
    assert _title_outcome("2026", "Zamówienie nr OIT/0189/2026") == "wrong"
    assert _title_outcome("OIT/0190/2026", "OIT/0189/2026") == "wrong"
