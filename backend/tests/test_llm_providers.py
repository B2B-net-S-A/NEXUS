"""Dostawcy spoza Anthropic za granicą `call_claude` (decyzja z badania 16.09.2026).

Trzy obietnice tej warstwy: (1) ten sam kształt odpowiedzi co `Message` SDK,
więc wołający parsują bez zmian; (2) błędy jako WYJĄTKI SDK Anthropic, więc
klasyfikacja ponowień, fallback i mapowanie błędów u wołających działają bez
zmian; (3) brak klucza dostawcy jest głośny (401, bez kaskady na Claude).
"""

from __future__ import annotations

import anthropic
import httpx
import pytest

from app.services import claude_client, llm_providers
from app.services.claude_client import call_claude, is_retryable_anthropic_error, text_of
from app.services.llm_providers import (
    DEEPSEEK,
    OPENAI,
    ProviderMessage,
    build_request,
    parse_response,
    provider_of,
)

# ── provider_of / klucze ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-sonnet-5", "anthropic"),
        ("claude-haiku-4-5-20251001", "anthropic"),
        ("gpt-5.6-luna", OPENAI),
        ("GPT-5.6-terra", OPENAI),
        ("o3-mini", OPENAI),
        ("deepseek-v4-pro", DEEPSEEK),
        ("deepseek-flash", DEEPSEEK),
        ("", "anthropic"),
    ],
)
def test_provider_follows_the_model_name(model, expected):
    assert provider_of(model) == expected


def test_api_key_configured_asks_for_the_models_provider(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    assert llm_providers.api_key_configured("deepseek-v4-pro") is True
    assert llm_providers.api_key_configured("gpt-5.6-luna") is False
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    assert llm_providers.api_key_configured("gpt-5.6-luna") is False


# ── build_request ────────────────────────────────────────────────────────


def test_openai_request_mirrors_the_study_configuration():
    body = build_request(
        OPENAI,
        model="gpt-5.6-luna",
        messages=[{"role": "user", "content": "pytanie"}],
        max_tokens=400,
        kwargs={
            "system": "instrukcja",
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "timeout": 30,
        },
    )
    assert body["model"] == "gpt-5.6-luna"
    assert body["max_completion_tokens"] == 400
    assert body["reasoning_effort"] == "none"
    assert body["store"] is False
    assert "temperature" not in body, "modele rozumujące GPT odrzucają temperature"
    assert "thinking" not in body
    assert body["messages"] == [
        {"role": "system", "content": "instrukcja"},
        {"role": "user", "content": "pytanie"},
    ]


def test_deepseek_request_disables_thinking_and_keeps_temperature():
    body = build_request(
        DEEPSEEK,
        model="deepseek-v4-pro",
        messages=[{"role": "user", "content": "notatki"}],
        max_tokens=4000,
        kwargs={"temperature": 0, "thinking": {"type": "disabled"}},
    )
    assert body["max_tokens"] == 4000
    assert body["thinking"] == {"type": "disabled"}
    assert body["temperature"] == 0
    assert body["messages"] == [{"role": "user", "content": "notatki"}]


def test_cached_system_blocks_are_flattened_to_text():
    """`cache_system=True` zamienia system w listę bloków z `cache_control` —
    dostawca bez cache promptu dostaje sam tekst."""
    body = build_request(
        OPENAI,
        model="gpt-5.6-luna",
        messages=[{"role": "user", "content": [{"type": "text", "text": "a"}]}],
        max_tokens=10,
        kwargs={
            "system": [
                {"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}
            ]
        },
    )
    assert body["messages"][0] == {"role": "system", "content": "S"}
    assert body["messages"][1] == {"role": "user", "content": "a"}


def test_json_schema_output_config_maps_to_response_format():
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    kwargs = {"output_config": {"format": {"type": "json_schema", "schema": schema}}}
    openai_body = build_request(
        OPENAI, model="gpt-5.6-luna", messages=[], max_tokens=1, kwargs=dict(kwargs)
    )
    assert openai_body["response_format"]["type"] == "json_schema"
    assert openai_body["response_format"]["json_schema"]["schema"] == schema
    deepseek_body = build_request(
        DEEPSEEK, model="deepseek-v4-pro", messages=[], max_tokens=1, kwargs=dict(kwargs)
    )
    assert deepseek_body["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in deepseek_body["messages"][0]["content"]


@pytest.mark.parametrize(
    "kwargs,messages",
    [
        ({"tools": [{"name": "x"}]}, [{"role": "user", "content": "a"}]),
        (
            {},
            [
                {
                    "role": "user",
                    "content": [{"type": "document", "source": {"data": "..."}}],
                }
            ],
        ),
    ],
)
def test_unsupported_shapes_raise_a_non_retryable_error(kwargs, messages):
    """Narzędzia i bloki inne niż tekst nie mają odpowiednika — głośny błąd,
    nie ciche pominięcie części promptu."""
    with pytest.raises(ValueError):
        build_request(OPENAI, model="gpt-5.6-luna", messages=messages, max_tokens=1, kwargs=kwargs)
    assert is_retryable_anthropic_error(ValueError("x")) is False


# ── parse_response ───────────────────────────────────────────────────────


def _openai_payload(text="odp", finish="stop", prompt=120, cached=20, completion=7):
    return {
        "id": "chatcmpl-1",
        "model": "gpt-5.6-luna-2026-09-01",
        "choices": [{"message": {"content": text}, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "prompt_tokens_details": {"cached_tokens": cached},
        },
    }


def test_response_looks_like_an_anthropic_message():
    message = parse_response(OPENAI, "gpt-5.6-luna", _openai_payload())
    assert isinstance(message, ProviderMessage)
    assert text_of(message) == "odp"
    # idiomy wołających: `.text` + hasattr, oraz `getattr(b, "type") == "text"`
    assert "".join(b.text for b in message.content if hasattr(b, "text")) == "odp"
    assert [b.text for b in message.content if getattr(b, "type", "") == "text"] == ["odp"]
    assert message.stop_reason == "end_turn"
    assert message.provider == OPENAI
    assert message.model == "gpt-5.6-luna-2026-09-01"
    assert message.usage.input_tokens == 100  # prompt minus cache
    assert message.usage.cache_read_input_tokens == 20
    assert message.usage.output_tokens == 7
    assert message.usage.cache_creation_input_tokens == 0


def test_length_finish_becomes_max_tokens_stop_reason():
    message = parse_response(OPENAI, "gpt-5.6-luna", _openai_payload(finish="length"))
    assert message.stop_reason == "max_tokens"


def test_deepseek_cache_hits_are_subtracted_from_input():
    payload = {
        "id": "ds-1",
        "model": "deepseek-v4-pro",
        "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "prompt_cache_hit_tokens": 400,
        },
    }
    message = parse_response(DEEPSEEK, "deepseek-v4-pro", payload)
    assert message.usage.input_tokens == 600
    assert message.usage.cache_read_input_tokens == 400


# ── transport → wyjątki SDK ──────────────────────────────────────────────


def _fake_post(monkeypatch, responder):
    calls: list[dict] = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        result = responder(len(calls))
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(llm_providers.httpx, "post", post)
    monkeypatch.setattr(claude_client.time, "sleep", lambda *_a, **_k: None)
    return calls


def _http(status, payload, url="https://api.openai.com/v1/chat/completions"):
    return httpx.Response(status, json=payload, request=httpx.Request("POST", url))


@pytest.mark.parametrize(
    "status,payload,expected_cls,retryable",
    [
        (429, {"error": {"code": "rate_limit_exceeded"}}, anthropic.RateLimitError, True),
        (503, {"error": {"type": "server_error"}}, anthropic.InternalServerError, True),
        (400, {"error": {"code": "invalid_request"}}, anthropic.BadRequestError, False),
        (401, {"error": {"code": "invalid_api_key"}}, anthropic.AuthenticationError, False),
    ],
)
def test_http_errors_become_sdk_exceptions_with_the_same_retry_verdict(
    monkeypatch, status, payload, expected_cls, retryable
):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _fake_post(monkeypatch, lambda _n: _http(status, payload))
    with pytest.raises(expected_cls) as excinfo:
        llm_providers.chat_complete(
            OPENAI,
            model="gpt-5.6-luna",
            messages=[{"role": "user", "content": "x"}],
            max_tokens=5,
            timeout=5,
            kwargs={},
        )
    assert excinfo.value.status_code == status
    assert is_retryable_anthropic_error(excinfo.value) is retryable
    # Do wyjątku trafia kod HTTP i krótki kod dostawcy — nigdy treść żądania.
    assert "x" not in str(excinfo.value).split("HTTP")[0]


def test_timeout_and_connection_errors_map_to_retryable_sdk_types(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _fake_post(monkeypatch, lambda _n: httpx.ReadTimeout("slow"))
    with pytest.raises(anthropic.APITimeoutError) as timeout:
        llm_providers.chat_complete(
            OPENAI, model="gpt-5.6-luna", messages=[], max_tokens=1, timeout=1, kwargs={}
        )
    assert is_retryable_anthropic_error(timeout.value)
    _fake_post(monkeypatch, lambda _n: httpx.ConnectError("down"))
    with pytest.raises(anthropic.APIConnectionError) as conn:
        llm_providers.chat_complete(
            OPENAI, model="gpt-5.6-luna", messages=[], max_tokens=1, timeout=1, kwargs={}
        )
    assert is_retryable_anthropic_error(conn.value)


def test_missing_key_is_a_loud_non_retryable_401(monkeypatch):
    from app.core.config import settings

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")
    calls = _fake_post(monkeypatch, lambda _n: _http(200, {}))
    with pytest.raises(anthropic.AuthenticationError) as excinfo:
        llm_providers.chat_complete(
            DEEPSEEK, model="deepseek-v4-pro", messages=[], max_tokens=1, timeout=1, kwargs={}
        )
    assert "DEEPSEEK_API_KEY" in str(excinfo.value)
    assert is_retryable_anthropic_error(excinfo.value) is False
    assert calls == [], "bez klucza nie wychodzi żadne żądanie"


# ── call_claude: ta sama pętla, inny transport ───────────────────────────


class _NeverAnthropic:
    """Podstawka klienta SDK: każde użycie to błąd testu."""

    def __init__(self, *a, **k):
        self.messages = self

    def create(self, **kwargs):  # pragma: no cover — asercja
        raise AssertionError(f"SDK Anthropic zawołane dla modelu {kwargs.get('model')}")

    def stream(self, **kwargs):  # pragma: no cover — asercja
        raise AssertionError("stream Anthropic zawołany")


def test_call_claude_routes_gpt_models_past_the_anthropic_sdk(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(claude_client.anthropic, "Anthropic", _NeverAnthropic)
    calls = _fake_post(monkeypatch, lambda _n: _http(200, _openai_payload("z luny")))
    health: list[tuple] = []
    from app.services import ai_health

    monkeypatch.setattr(
        ai_health, "record_provider_call", lambda p, ms, failed: health.append((p, failed))
    )

    message = call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="gpt-5.6-luna",
        max_tokens=64,
        api_key="anthropic-key-ignored",
        system="S",
        max_retries=0,
    )
    assert text_of(message) == "z luny"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert calls[0]["json"]["model"] == "gpt-5.6-luna"
    assert calls[0]["json"]["messages"][0] == {"role": "system", "content": "S"}
    assert calls[0]["timeout"] == pytest.approx(
        claude_client.settings.ANTHROPIC_TIMEOUT_SECONDS
    )
    assert health == [("openai", False)]


def test_rate_limited_gpt_falls_back_to_sonnet_5(monkeypatch):
    """429 u OpenAI jest per-dostawca: po wyczerpaniu ponowień łańcuch
    schodzi na Claude, tak jak przy przeciążeniu jednej rodziny Claude."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _fake_post(
        monkeypatch, lambda _n: _http(429, {"error": {"code": "rate_limit_exceeded"}})
    )
    seen: list[str] = []

    class _Msg:
        content = [type("B", (), {"text": "z sonneta", "type": "text"})()]
        stop_reason = "end_turn"
        usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()
        model = "claude-sonnet-5"
        id = "msg_1"

    class _Client:
        def __init__(self, *a, **k):
            self.messages = self

        def create(self, **kwargs):
            seen.append(kwargs["model"])
            return _Msg()

    monkeypatch.setattr(claude_client.anthropic, "Anthropic", _Client)
    message = call_claude(
        messages=[{"role": "user", "content": "x"}],
        model="gpt-5.6-luna",
        max_tokens=8,
        api_key="k",
        max_retries=1,
        fallback_models=["claude-sonnet-5"],
    )
    assert text_of(message) == "z sonneta"
    assert seen == ["claude-sonnet-5"]


def test_missing_provider_key_does_not_cascade_to_claude(monkeypatch):
    """Błąd konfiguracji ma być widoczny, nie zamaskowany droższym fallbackiem."""
    from app.core.config import settings

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(claude_client.anthropic, "Anthropic", _NeverAnthropic)
    monkeypatch.setattr(claude_client.time, "sleep", lambda *_a, **_k: None)
    with pytest.raises(anthropic.AuthenticationError):
        call_claude(
            messages=[{"role": "user", "content": "x"}],
            model="gpt-5.6-luna",
            max_tokens=8,
            api_key="k",
            max_retries=1,
            fallback_models=["claude-sonnet-5"],
        )


def test_truncated_provider_answer_raises_when_asked(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(claude_client.anthropic, "Anthropic", _NeverAnthropic)
    _fake_post(monkeypatch, lambda _n: _http(200, _openai_payload(finish="length")))
    with pytest.raises(claude_client.ClaudeTruncated):
        call_claude(
            messages=[{"role": "user", "content": "x"}],
            model="gpt-5.6-luna",
            max_tokens=8,
            api_key="k",
            max_retries=0,
            raise_on_truncation=True,
        )


# ── wycena i telemetria ──────────────────────────────────────────────────


def test_metering_event_carries_the_provider_and_its_own_prices():
    from decimal import Decimal

    from app.services.ai_metering import response_event

    message = parse_response(
        OPENAI, "gpt-5.6-luna", _openai_payload(prompt=1500, cached=500, completion=100)
    )
    event = response_event("op-1", message, model="gpt-5.6-luna", latency_ms=12)
    assert event["provider"] == OPENAI
    assert event["event_key"] == "openai:chatcmpl-1"
    assert event["model"] == "gpt-5.6-luna-2026-09-01"
    assert event["input_tokens"] == 1000
    assert event["cache_read_tokens"] == 500
    assert event["cache_creation_tokens"] == 0
    # (0.20 × 1000 + 0.02 × 500 + 1.20 × 100) / 1e6
    assert event["estimated_cost_usd"] == Decimal("0.00033000")
    assert event["price_version"]


def test_deepseek_cache_read_is_priced_at_its_own_rate_not_a_tenth():
    from decimal import Decimal

    from app.services.ai_metering import response_event

    payload = {
        "id": "ds-9",
        "model": "deepseek-v4-pro",
        "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 2_000_000,
            "completion_tokens": 0,
            "prompt_cache_hit_tokens": 1_000_000,
        },
    }
    message = parse_response(DEEPSEEK, "deepseek-v4-pro", payload)
    event = response_event("op-2", message, model="deepseek-v4-pro", latency_ms=1)
    # 1M wejścia po 0.66 + 1M z cache po 0.022 (nie 0.066)
    assert event["estimated_cost_usd"] == Decimal("0.68200000")


def test_anthropic_events_keep_their_shape():
    from types import SimpleNamespace

    from app.services.ai_metering import response_event

    message = SimpleNamespace(
        id="msg_a",
        model="claude-sonnet-5",
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=10,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )
    event = response_event("op-3", message, model="claude-sonnet-5", latency_ms=1)
    assert event["provider"] == "anthropic"
    assert event["event_key"] == "anthropic:msg_a"
    assert event["estimated_cost_usd"] is not None
