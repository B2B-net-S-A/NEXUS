"""Anthropic Claude client with retry + model fallback — evolved from the
external CV-Generator port.

Policy:
  - Primary model: ``claude-sonnet-4-6`` (env-overridable via ``CV_B2B_MODEL``).
  - Fallback chain: ``claude-opus-4-8`` → ``claude-sonnet-5`` →
    ``claude-haiku-4-5`` (env-overridable via ``CV_B2B_FALLBACK_MODELS``,
    comma-separated). A 529 ``overloaded_error`` is per-model-pool, so when a
    pool is saturated we re-issue against a different model family rather than
    failing the whole generation. ``claude-sonnet-5`` is the pool the rest of
    NEXUS already runs on (match-scoring, champion drafts, AI writer), and
    ``claude-haiku-4-5`` is the high-availability last resort — so a capacity
    crunch on the two premium pools still yields a (recruiter-reviewed) CV
    instead of a hard "przeciążona" failure.
  - Max tokens: 8192 (env-overridable via ``CV_B2B_MAX_TOKENS``).
  - Per-request timeout: 120 s (env-overridable via ``CV_B2B_REQUEST_TIMEOUT``)
    so a hung attempt can't pin its FastAPI threadpool slot for the SDK's 600 s
    default.
  - Instructions go through the ``system`` param (with prompt caching);
    candidate data travels in the user message only.
  - Per model: manual retries on overloaded/rate-limit/5xx with exponential
    backoff + jitter (``CV_B2B_MAX_RETRIES``, default 3). SDK-internal retries
    are disabled so the two policies don't stack. Only *retryable* failures
    (overload / 429 / 5xx / connection) cascade to the next model — a 4xx
    request/config error (e.g. unknown model, bad key) surfaces immediately
    instead of being masked by a silent fallback.
  - ``stop_reason == "max_tokens"`` raises a dedicated error instead of
    surfacing later as a confusing "invalid JSON" failure. Truncation is a
    content-length issue (identical on any model) so it never triggers fallback.

Synchronous by design — callers run it via ``run_in_threadpool`` so the
FastAPI event loop never blocks on a 30-60 s Claude call.
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any

import anthropic

logger = logging.getLogger(__name__)


# Rewert #628 (sonnet-5): fala feedbacku od rekruterów — jakość CV wyraźnie
# spadła. Sonnet 5 z wymuszonym thinking=disabled (konieczne, bo jego adaptive
# thinking zjadał budżet max_tokens — #630/#632) generuje słabsze CV niż
# Sonnet 4.6 w swoim naturalnym trybie. Ewentualny powrót na Sonnet 5 wymaga
# CV_B2B_THINKING=adaptive + CV_B2B_MAX_TOKENS>=24576 i porównania jakości.
_DEFAULT_MODEL = "claude-sonnet-4-6"
# Fallback chain, tried in order when the model before it stays overloaded /
# rate-limited / timing-out across all its retries. A 529 overloaded_error is
# per-model-POOL, so cascading to a different model family is what stops a
# capacity crunch on one pool from failing the whole generation:
#   • claude-opus-4-8          — premium, current-gen peer of the primary.
#   • claude-sonnet-5          — the pool the REST of NEXUS already runs on
#     (match-scoring, champion drafts, AI writer). When those features work but
#     CV generation 529s, the sonnet-4-6/opus-4-8 pools are the saturated ones,
#     so routing here clears the outage with good quality. Runs with thinking
#     disabled like the rest of the chain — the #635 quality caveat is about
#     sonnet-5 as the PRIMARY; as an outage fallback a complete CV beats none.
#   • claude-haiku-4-5-20251001 — highest-availability last resort; only reached
#     when every model above is also down.
# Override the whole list without a redeploy via CV_B2B_FALLBACK_MODELS.
_DEFAULT_FALLBACK_MODELS = (
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
)
_DEFAULT_MAX_TOKENS = 8192
_DEFAULT_MAX_RETRIES = 3
# Per-request ceiling (seconds). The SDK default is 600 s — far too long for a
# call that runs synchronously inside a FastAPI threadpool slot; a hung attempt
# would pin that slot. A timed-out attempt surfaces as APITimeoutError (which
# ``_is_retryable`` treats as retryable) so backoff / fallback still apply.
_DEFAULT_REQUEST_TIMEOUT = 120.0

# Backoff (seconds): min(cap, base * 2**attempt) + uniform jitter.
_BACKOFF_BASE = 2.0
_BACKOFF_CAP = 8.0
_BACKOFF_JITTER = 1.0

PROMPT_NAME = "cv_b2b_extraction"
# v3 (2026-06-11): poufność notatek (stawki/red flagi), kwantyfikacja, zwięzłość
# starszych ról, tytuł pod ofertę, kanoniczna pisownia tech, kontekst projektu,
# higiena dat edukacji/luk.
# v4 (2026-06-11): limit 12 technologii per rola (priorytet must/nice klienta).
# v5 (2026-07-01): wierność obowiązków — zakaz rozdmuchiwania zakresu (klienci/
# domeny/usługi/integracje), Profil Championa i notatki tylko jako pozycjonowanie,
# nie źródło wymyślonych obowiązków (generator nie nagina prawdy).
# v6 (2026-07-13): Profil Championa (MUST/NICE) rozróżnia technologie od
# metodyk/kompetencji/ról/języków — model nie nazywa już wszystkich wymagań
# „technologiami" ani nie tworzy dla nich sztucznych kategorii technicznych
# (boldowanie i tak filtruje przez taksonomię, ale prompt nie ma mylić modelu).
PROMPT_VERSION = 6


def _model() -> str:
    return os.environ.get("CV_B2B_MODEL", _DEFAULT_MODEL)


def _fallback_models() -> list[str]:
    raw = os.environ.get("CV_B2B_FALLBACK_MODELS")
    if raw is None:
        return list(_DEFAULT_FALLBACK_MODELS)
    return [m.strip() for m in raw.split(",") if m.strip()]


def _models() -> list[str]:
    """Ordered, de-duplicated [primary, *fallbacks] model chain."""
    ordered = [_model(), *_fallback_models()]
    seen: set[str] = set()
    result: list[str] = []
    for m in ordered:
        if m and m not in seen:
            seen.add(m)
            result.append(m)
    return result


def _env_number(name: str, default: float, cast):
    """Parse a numeric env var, falling back to ``default`` on empty/garbage.

    An operator slip (e.g. ``CV_B2B_MAX_RETRIES=""`` in the Coolify vault) must
    not crash generation with a bare 500 — ``os.environ.get(name, str(default))``
    returns ``""`` when the key is *set but empty*, and ``int("")`` raises.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return cast(default)
    try:
        return cast(raw)
    except (TypeError, ValueError):
        logger.warning(
            "[cv_b2b] invalid %s=%r — falling back to default %s", name, raw, default
        )
        return cast(default)


def _max_tokens() -> int:
    return _env_number("CV_B2B_MAX_TOKENS", _DEFAULT_MAX_TOKENS, int)


def _max_retries() -> int:
    return _env_number("CV_B2B_MAX_RETRIES", _DEFAULT_MAX_RETRIES, int)


def _request_timeout() -> float:
    return _env_number("CV_B2B_REQUEST_TIMEOUT", _DEFAULT_REQUEST_TIMEOUT, float)


def _thinking_param() -> dict[str, str] | None:
    """Extended-thinking config for the extraction call.

    Dla ``claude-sonnet-4-6`` (obecny primary) ``disabled`` jest no-opem —
    thinking i tak jest tam domyślnie wyłączony. Pin ma znaczenie, gdy przez
    ``CV_B2B_MODEL`` wybrany zostanie model Claude 5:
    ``claude-sonnet-5`` runs adaptive thinking with ``effort=high`` BY DEFAULT,
    and thinking tokens are billed as output — they count toward ``max_tokens``
    and crowd out the CV JSON, tripping ``stop_reason=max_tokens`` (the
    "Odpowiedź Claude została ucięta" truncation). CV extraction is a structured
    transformation that gains little from extended reasoning, so thinking is
    disabled by default. Set ``CV_B2B_THINKING`` to ``adaptive``/``on`` to
    restore the model's default adaptive thinking (e.g. if extraction quality
    regresses) — that omits the param so the model decides.
    """
    mode = os.environ.get("CV_B2B_THINKING", "disabled").strip().lower()
    if mode in ("adaptive", "on", "true", "1", "enabled", "default"):
        return None  # omit → model default (adaptive)
    return {"type": "disabled"}


def _api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        from app.core.config import settings

        return settings.ANTHROPIC_API_KEY or None
    except Exception:  # noqa: BLE001 — config import must never break the client
        return None


class CVGeneratorAIError(RuntimeError):
    """Raised when Claude call fails after all retries."""


class CVGeneratorTruncatedError(CVGeneratorAIError):
    """Raised when the response was cut off by the max_tokens limit."""


class CVGeneratorOverloadedError(CVGeneratorAIError):
    """Raised when every model in the chain stayed overloaded/unavailable.

    Carries a clean, user-facing Polish message (retry-actionable) instead of
    a raw API error dict — the overload is transient and the operator just
    needs to try again in a moment.
    """


class _ModelExhausted(Exception):
    """Internal: a single model exhausted its retry budget.

    ``retryable`` reflects the *last* underlying error so the caller can decide
    whether to cascade to the next model (transient overload) or stop (a 4xx
    request/config error that every model would reject the same way).
    """

    def __init__(self, cause: BaseException | None, retryable: bool) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.retryable = retryable


def _is_retryable(err: BaseException) -> bool:
    """Overloaded / rate-limited / 5xx / connection problems are retryable."""
    status = getattr(err, "status_code", None)
    if status is None:
        response = getattr(err, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)

    err_type = ""
    body = getattr(err, "body", None)
    if isinstance(body, dict):
        err_obj = body.get("error") or {}
        if isinstance(err_obj, dict):
            err_type = err_obj.get("type", "")

    if not err_type:
        err_type = getattr(err, "type", "") or ""

    if status in (429, 529):
        return True
    if err_type in ("overloaded_error", "rate_limit_error"):
        return True
    if (
        isinstance(err, anthropic.APIStatusError)
        and status
        and 500 <= int(status) < 600
    ):
        return True
    if isinstance(err, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return True
    return False


def _call_model(
    client: anthropic.Anthropic,
    *,
    model: str,
    content: str,
    kwargs: dict[str, Any],
    max_tokens: int,
    max_retries: int,
    request_id: str,
    start: float,
) -> str:
    """Issue one model's call with the full retry budget.

    Returns the response text on success. Raises:
        CVGeneratorTruncatedError: response hit the max_tokens limit (no point
            retrying or falling back — identical on any model).
        _ModelExhausted: every attempt for this model failed; ``retryable``
            tells the caller whether to try the next model.
    """
    last_err: BaseException | None = None
    last_retryable = False

    for attempt in range(max_retries + 1):
        try:
            logger.info(
                "[cv_b2b][%s] Claude attempt %d/%d model=%s prompt=%s/v%d",
                request_id,
                attempt + 1,
                max_retries + 1,
                model,
                PROMPT_NAME,
                PROMPT_VERSION,
            )
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": content}],
                **kwargs,
            )
            if not message.content:
                raise CVGeneratorAIError("Empty response from Claude")
            # Claude 5 models can lead with a non-text block (e.g. a thinking
            # block), so content[0] is not guaranteed to hold the JSON text —
            # blindly reading content[0].text yielded an empty string here,
            # which surfaced downstream as a misleading "invalid JSON (char 0)"
            # failure. Concatenate every text block instead (mirrors the
            # defensive pattern already used in dynareporter_mindy.py).
            text = "".join(
                getattr(b, "text", "") or ""
                for b in message.content
                if hasattr(b, "text")
            )
            # Check truncation BEFORE logging success — otherwise a truncated
            # response logs "Claude success" immediately followed by the
            # truncation error, which is contradictory in Grafana/Loki.
            if getattr(message, "stop_reason", None) == "max_tokens":
                raise CVGeneratorTruncatedError(
                    f"Odpowiedź Claude została ucięta limitem {max_tokens} tokenów "
                    "(stop_reason=max_tokens). Zwiększ CV_B2B_MAX_TOKENS."
                )
            if not text.strip():
                # Content present but no usable text (e.g. only a thinking
                # block) — surface a clean error instead of returning "" that
                # later fails JSON parsing at "char 0".
                raise CVGeneratorAIError("Claude returned no text content")
            duration = int((time.time() - start) * 1000)
            usage = getattr(message, "usage", None)
            logger.info(
                "[cv_b2b][%s] Claude success in %dms (attempts=%d, model=%s, "
                "tokens_in=%s, tokens_out=%s, cache_read=%s)",
                request_id,
                duration,
                attempt + 1,
                model,
                getattr(usage, "input_tokens", "?"),
                getattr(usage, "output_tokens", "?"),
                getattr(usage, "cache_read_input_tokens", "?"),
            )
            return text or ""
        except CVGeneratorTruncatedError:
            raise
        except BaseException as err:  # noqa: BLE001 — broad on purpose, retry inspects type
            last_err = err
            last_retryable = _is_retryable(err)
            logger.warning(
                "[cv_b2b][%s] Claude attempt %d failed (model=%s): %s (retryable=%s)",
                request_id,
                attempt + 1,
                model,
                err,
                last_retryable,
            )
            if attempt == max_retries or not last_retryable:
                break
            delay = min(_BACKOFF_CAP, _BACKOFF_BASE * (2**attempt)) + random.uniform(
                0, _BACKOFF_JITTER
            )
            time.sleep(delay)

    raise _ModelExhausted(last_err, last_retryable)


def analyze_with_ai(content: str, request_id: str, system: str | None = None) -> str:
    """Call Claude (with model fallback) and return the text of the first block.

    Args:
        content: the user message (candidate data wrapped in delimiters).
        request_id: correlation id for logs.
        system: instruction prompt; sent via the ``system`` param with an
            ephemeral cache_control marker so the static instructions are
            prompt-cached between generations.

    Raises:
        CVGeneratorTruncatedError: when the response hit the max_tokens limit.
        CVGeneratorOverloadedError: when every model in the chain stayed
            overloaded / rate-limited / unavailable.
        CVGeneratorAIError: when the API key is missing or a non-retryable
            request/config error (4xx) is hit.
    """
    api_key = _api_key()
    if not api_key:
        raise CVGeneratorAIError("ANTHROPIC_API_KEY env var is not set")

    models = _models()
    if not models:
        raise CVGeneratorAIError(
            "Brak skonfigurowanego modelu Claude (CV_B2B_MODEL jest pusty)."
        )

    # max_retries=0 — manual backoff below governs; SDK retries would stack.
    # An explicit per-request timeout caps a hung attempt (see _request_timeout).
    client = anthropic.Anthropic(
        api_key=api_key, max_retries=0, timeout=_request_timeout()
    )
    max_tokens = _max_tokens()
    max_retries = _max_retries()

    kwargs: dict[str, Any] = {}
    if system:
        kwargs["system"] = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    # Disable Sonnet 5's default adaptive thinking — its thinking tokens count
    # toward max_tokens and were truncating the CV JSON (stop_reason=max_tokens).
    thinking = _thinking_param()
    if thinking is not None:
        kwargs["thinking"] = thinking

    start = time.time()
    last_err: BaseException | None = None
    # Track whether *any* model in the chain hit a transient/overload error.
    # If the primary was overloaded (retry-able) but a fallback then fails with
    # a non-retryable 4xx, the recoverable condition still holds — a later retry
    # could route back to the recovered primary — so the clean overload message
    # must win over the fallback's hard error.
    any_retryable = False

    for idx, model in enumerate(models):
        try:
            return _call_model(
                client,
                model=model,
                content=content,
                kwargs=kwargs,
                max_tokens=max_tokens,
                max_retries=max_retries,
                request_id=request_id,
                start=start,
            )
        except CVGeneratorTruncatedError:
            raise  # content-length issue — identical on any model
        except _ModelExhausted as exc:
            last_err = exc.cause
            any_retryable = any_retryable or exc.retryable
            # A non-retryable failure (4xx request/config error) would be
            # rejected the same way by every model — stop cascading rather than
            # masking a misconfiguration behind a silent, slower fallback.
            if not exc.retryable:
                break
            if idx + 1 < len(models):
                logger.warning(
                    "[cv_b2b][%s] model %s exhausted (overloaded/transient) — "
                    "falling back to %s",
                    request_id,
                    model,
                    models[idx + 1],
                )

    duration = int((time.time() - start) * 1000)
    logger.error(
        "[cv_b2b][%s] Claude exhausted all %d model(s) after %dms: %s",
        request_id,
        len(models),
        duration,
        last_err,
    )
    if any_retryable:
        # A model stayed overloaded/unavailable — transient, retry-able.
        raise CVGeneratorOverloadedError(
            "Usługa AI (Claude) jest chwilowo przeciążona. "
            "Spróbuj wygenerować CV ponownie za chwilę."
        ) from last_err
    raise CVGeneratorAIError(f"Claude call failed: {last_err}") from last_err
