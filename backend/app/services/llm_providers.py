"""Dostawcy spoza Anthropic za TĄ SAMĄ granicą co Claude (`claude_client.call_claude`).

Badanie modeli na danych produkcyjnych (16.09.2026,
``outputs/model-matrix-2026-09-15/RAPORT-KONCOWY.md``) zakończyło się decyzją
Artura: cztery funkcje idą na GPT Luna (OpenAI — umowa powierzenia), dwie na
DeepSeek V4 Pro (dane produkcyjne za jawną zgodą z 16.09). Kod produkcyjny
znał do tej pory wyłącznie SDK Anthropic: kilkanaście miejsc wywołania parsuje
``anthropic.types.Message`` (bloki tekstowe, ``stop_reason``, ``usage``)
i mapuje WYJĄTKI SDK na własne kody błędów (timeout → 504, 429 → ponowienie…).

Zamiast przepisywać każde z nich, ta warstwa robi trzy rzeczy:

* rozpoznaje dostawcę po nazwie modelu (`provider_of`) — rejestr ``ai_models``
  nadal mówi tylko „funkcja → model", a dostawca wynika z nazwy;
* woła chat completions przez ``httpx`` w konfiguracji „bez rozumowania"
  z badania (OpenAI ``reasoning_effort=none``, DeepSeek ``thinking=disabled``)
  i oddaje odpowiedź w kształcie ``Message`` (`ProviderMessage`);
* błędy zgłasza WYJĄTKAMI SDK ANTHROPIC (`RateLimitError`, `APITimeoutError`,
  `AuthenticationError`…) z prawdziwym ``httpx.Response``/``Request`` w środku.
  Na tych typach stoi klasyfikacja ponowień (`is_retryable_anthropic_error`),
  łańcuch fallbacków i obsługa błędów wołających — reużycie taksonomii SDK
  jest tańsze i bezpieczniejsze niż druga, równoległa hierarchia wyjątków.
  SDK 1.x sam jeździ na ``httpx2`` (fork httpx o tym samym API), ale jego
  wyjątki nie sprawdzają typu ``response``/``request`` — obiekty z ``httpx``
  mają te same atrybuty (``status_code``, ``json()``), więc ta warstwa
  zostaje przy ``httpx``, którym woła OpenAI/DeepSeek. Nie mieszaj tu
  ``isinstance(err.response, httpx.Response)``: błąd z prawdziwego SDK
  niesie ``httpx2.Response``.

Klucze wyłącznie z env/settings. Do logów i wyjątków trafia kod HTTP i krótki
kod błędu dostawcy — nigdy treść żądania ani klucz. Streaming, narzędzia
(``tools``) i bloki inne niż tekst (obraz, dokument) NIE są obsługiwane: taki
kwarg kończy się ``ValueError`` (błąd nieponawialny), a nie cichym pominięciem.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import anthropic
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC = "anthropic"
OPENAI = "openai"
DEEPSEEK = "deepseek"

_ENDPOINTS = {
    OPENAI: "https://api.openai.com/v1/chat/completions",
    DEEPSEEK: "https://api.deepseek.com/chat/completions",
}
_KEY_ENV = {
    ANTHROPIC: "ANTHROPIC_API_KEY",
    OPENAI: "OPENAI_API_KEY",
    DEEPSEEK: "DEEPSEEK_API_KEY",
}
# Etykiety w circuit breakerze `ai_health`: Claude od zawsze raportuje jako
# "claude" (czyta to `/api/health`), więc nowe etykiety idą obok, nie zamiast.
HEALTH_LABEL = {ANTHROPIC: "claude", OPENAI: "openai", DEEPSEEK: "deepseek"}

# kwargi Anthropic bez odpowiednika u innych dostawców — pomijane świadomie.
_IGNORED_KWARGS = frozenset({"thinking", "inference_geo", "speed", "metadata", "top_k"})
_UNSUPPORTED_KWARGS = frozenset({"tools", "tool_choice", "mcp_servers", "container"})
_SAFE_CODE = re.compile(r"^[A-Za-z0-9_.\-]{1,60}$")
_OPENAI_MODEL = re.compile(r"^(gpt-|chatgpt-|o\d)")


def provider_of(model: str) -> str:
    """Dostawca wynika z NAZWY modelu: ``deepseek*`` → DeepSeek, ``gpt-*`` → OpenAI,
    reszta → Anthropic (dotychczasowe zachowanie dla każdej nazwy ``claude-*``)."""
    name = (model or "").strip().lower()
    if name.startswith("deepseek"):
        return DEEPSEEK
    if _OPENAI_MODEL.match(name):
        return OPENAI
    return ANTHROPIC


def api_key_for(provider: str) -> str:
    """Klucz dostawcy: env wygrywa z ``settings`` (jak w reszcie repo);
    Anthropic honoruje też starsze ``CLAUDE_API_KEY``."""
    env_name = _KEY_ENV[provider]
    raw = os.environ.get(env_name) or getattr(settings, env_name, "") or ""
    if provider == ANTHROPIC and not raw.strip():
        raw = os.environ.get("CLAUDE_API_KEY") or ""
    return raw.strip()


def api_key_configured(model: str) -> bool:
    """Czy jest klucz dla DOSTAWCY tego modelu — sondy „brak klucza" przed
    wywołaniem nie mogą pytać o klucz Anthropic dla funkcji na GPT/DeepSeek."""
    return bool(api_key_for(provider_of(model)))


# ── Odpowiedź w kształcie anthropic.types.Message ──────────────────────────


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_creation: Any = None


@dataclass
class ProviderMessage:
    """Tyle ``Message``, ile czytają wołający i telemetria: bloki tekstowe
    (``.text``/``.type``), ``stop_reason`` (``end_turn`` | ``max_tokens``),
    ``usage`` w polach Anthropic, ``id``/``model``; do tego ``provider`` dla
    ``ai_metering.response_event``."""

    id: str
    model: str
    provider: str
    content: list[TextBlock]
    stop_reason: str
    usage: Usage
    role: str = "assistant"
    type: str = "message"
    finish_reason: str | None = field(default=None, repr=False)


# ── Tłumaczenie żądania ────────────────────────────────────────────────────


def _flatten_text(content: Any, *, what: str) -> str:
    """Treść wiadomości/promptu systemowego jako jeden string.

    Anthropic przyjmuje string ALBO listę bloków (``cache_system`` zamienia
    system w listę z ``cache_control``). Blok inny niż tekst (obraz, dokument
    PDF) nie ma tu odpowiednika — to błąd wołającego, nie coś do pominięcia.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                btype, text = block.get("type"), block.get("text")
            else:
                btype, text = getattr(block, "type", None), getattr(block, "text", None)
            if btype in (None, "text") and isinstance(text, str):
                parts.append(text)
                continue
            raise ValueError(
                f"{what}: blok typu {btype!r} nie jest obsługiwany przez dostawcę "
                "spoza Anthropic (tylko tekst)"
            )
        return "".join(parts)
    raise ValueError(f"{what}: nieobsługiwany kształt treści {type(content).__name__}")


def _schema_instruction(schema: dict[str, Any]) -> str:
    return (
        "\n\nReturn only one JSON object that validates against this JSON Schema:\n"
        + json.dumps(schema, ensure_ascii=False)
    )


def build_request(
    provider: str,
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Ciało chat completions z kwargów w kształcie ``messages.create`` Anthropic."""
    unsupported = _UNSUPPORTED_KWARGS & set(kwargs)
    if unsupported:
        raise ValueError(
            f"{provider}: parametry {sorted(unsupported)} nie są obsługiwane "
            "przez dostawcę spoza Anthropic"
        )
    system = _flatten_text(kwargs.get("system"), what="system")
    schema: dict[str, Any] | None = None
    output_config = kwargs.get("output_config")
    if isinstance(output_config, dict):
        fmt = output_config.get("format") or {}
        if isinstance(fmt, dict) and fmt.get("type") == "json_schema":
            schema = fmt.get("schema")

    chat: list[dict[str, str]] = []
    for msg in messages:
        chat.append(
            {
                "role": str(msg.get("role") or "user"),
                "content": _flatten_text(msg.get("content"), what="messages"),
            }
        )

    body: dict[str, Any] = {"model": model}
    if provider == OPENAI:
        body["max_completion_tokens"] = max_tokens
        # Konfiguracja z badania: bez rozumowania, bez retencji po stronie OpenAI.
        body["reasoning_effort"] = "none"
        body["store"] = False
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "nexus_output",
                    "schema": schema,
                    "strict": False,
                },
            }
        # `temperature` świadomie pomijane: modele rozumujące GPT odrzucają
        # parametr (400), a harness badania też szedł bez niego.
    elif provider == DEEPSEEK:
        body["max_tokens"] = max_tokens
        body["thinking"] = {"type": "disabled"}
        if kwargs.get("temperature") is not None:
            body["temperature"] = kwargs["temperature"]
        if schema is not None:
            body["response_format"] = {"type": "json_object"}
            system = (system + _schema_instruction(schema)).strip()
    else:  # pragma: no cover — Anthropic idzie przez SDK, nie tędy
        raise ValueError(f"nieobsługiwany dostawca: {provider}")

    stop = kwargs.get("stop_sequences")
    if stop:
        body["stop"] = list(stop)
    for name in kwargs:
        if name not in _IGNORED_KWARGS and name not in (
            "system",
            "temperature",
            "output_config",
            "stop_sequences",
            "timeout",
        ):
            logger.warning(
                "[llm_providers] %s: pomijam parametr %s bez odpowiednika",
                provider,
                name,
            )

    if system:
        chat.insert(0, {"role": "system", "content": system})
    body["messages"] = chat
    return body


# ── Transport i mapowanie błędów na wyjątki SDK ─────────────────────────────


def _safe_code(payload: Any) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return ""
    for name in ("code", "type", "param"):
        value = error.get(name)
        if isinstance(value, str) and _SAFE_CODE.match(value):
            return value
        if isinstance(value, int):
            return str(value)
    return ""


_STATUS_ERRORS: dict[int, type[anthropic.APIStatusError]] = {
    400: anthropic.BadRequestError,
    401: anthropic.AuthenticationError,
    403: anthropic.PermissionDeniedError,
    404: anthropic.NotFoundError,
    429: anthropic.RateLimitError,
}


def _status_error(provider: str, response: httpx.Response) -> anthropic.APIStatusError:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    code = _safe_code(payload)
    status = response.status_code
    cls = _STATUS_ERRORS.get(status)
    if cls is None:
        cls = (
            anthropic.InternalServerError if status >= 500 else anthropic.APIStatusError
        )
    body = {"error": {"type": code or "http_error", "provider": provider}}
    return cls(
        f"{provider}: HTTP {status} {code or ''}".strip(), response=response, body=body
    )


def missing_key_error(provider: str) -> anthropic.AuthenticationError:
    """Brak klucza = 401 NIEPONAWIALNE: nie kaskaduje na fallback, żeby
    błąd konfiguracji nie chował się za wolniejszym modelem."""
    request = httpx.Request("POST", _ENDPOINTS.get(provider, "https://invalid/"))
    response = httpx.Response(401, request=request)
    return anthropic.AuthenticationError(
        f"{provider}: brak klucza {_KEY_ENV[provider]}",
        response=response,
        body={"error": {"type": "missing_api_key", "provider": provider}},
    )


def _post(provider: str, body: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    url = _ENDPOINTS[provider]
    key = api_key_for(provider)
    if not key:
        raise missing_key_error(provider)
    headers = {"Authorization": f"Bearer {key}"}
    request = httpx.Request("POST", url)
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise anthropic.APITimeoutError(request=request) from exc
    except httpx.HTTPError as exc:
        raise anthropic.APIConnectionError(request=request) from exc
    if response.status_code >= 400:
        raise _status_error(provider, response)
    try:
        return response.json()
    except ValueError as exc:
        raise anthropic.APIConnectionError(
            message=f"{provider}: odpowiedź nie jest JSON-em", request=request
        ) from exc


def parse_response(provider: str, model: str, data: dict[str, Any]) -> ProviderMessage:
    """Chat completions → ``ProviderMessage``. Tokeny z cache są ODEJMOWANE od
    wejścia (jak w harnessie badania), żeby wycena liczyła je po stawce cache."""
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise anthropic.APIConnectionError(
            message=f"{provider}: odpowiedź bez choices",
            request=httpx.Request("POST", _ENDPOINTS[provider]),
        ) from exc
    usage = data.get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    if provider == DEEPSEEK:
        cached = int(usage.get("prompt_cache_hit_tokens") or 0)
    else:
        cached = int(
            (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        )
    finish = choice.get("finish_reason")
    text = (choice.get("message") or {}).get("content") or ""
    return ProviderMessage(
        id=str(data.get("id") or uuid4()),
        model=str(data.get("model") or model),
        provider=provider,
        content=[TextBlock(text=text)],
        stop_reason="max_tokens" if finish == "length" else "end_turn",
        usage=Usage(
            input_tokens=max(prompt - cached, 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            cache_read_input_tokens=cached,
        ),
        finish_reason=str(finish) if finish is not None else None,
    )


def chat_complete(
    provider: str,
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    timeout: float,
    kwargs: dict[str, Any],
) -> ProviderMessage:
    """Jedno wywołanie dostawcy spoza Anthropic. Ponowienia, fallback
    i telemetria zostają w ``call_claude`` — tak jak dla Claude."""
    body = build_request(
        provider, model=model, messages=messages, max_tokens=max_tokens, kwargs=kwargs
    )
    data = _post(provider, body, timeout=timeout)
    return parse_response(provider, model, data)
