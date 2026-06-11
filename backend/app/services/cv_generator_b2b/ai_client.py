"""Anthropic Claude client with retry — evolved from the external CV-Generator port.

Policy:
  - Model: ``claude-sonnet-4-6`` (env-overridable via ``CV_B2B_MODEL``)
  - Max tokens: 8192 (env-overridable via ``CV_B2B_MAX_TOKENS``)
  - Instructions go through the ``system`` param (with prompt caching);
    candidate data travels in the user message only.
  - 4 manual retries on overloaded/rate-limit/5xx with exponential backoff;
    SDK-internal retries are disabled so the two policies don't stack.
  - ``stop_reason == "max_tokens"`` raises a dedicated error instead of
    surfacing later as a confusing "invalid JSON" failure.

Synchronous by design — callers run it via ``run_in_threadpool`` so the
FastAPI event loop never blocks on a 30-60 s Claude call.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import anthropic

logger = logging.getLogger(__name__)


_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_MAX_TOKENS = 8192

PROMPT_NAME = "cv_b2b_extraction"
# v3 (2026-06-11): poufność notatek (stawki/red flagi), kwantyfikacja, zwięzłość
# starszych ról, tytuł pod ofertę, kanoniczna pisownia tech, kontekst projektu,
# higiena dat edukacji/luk.
# v4 (2026-06-11): limit 12 technologii per rola (priorytet must/nice klienta).
PROMPT_VERSION = 4


def _model() -> str:
    return os.environ.get("CV_B2B_MODEL", _DEFAULT_MODEL)


def _max_tokens() -> int:
    return int(os.environ.get("CV_B2B_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS)))


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


def analyze_with_ai(content: str, request_id: str, system: str | None = None) -> str:
    """Call Claude and return the text of the first content block.

    Args:
        content: the user message (candidate data wrapped in delimiters).
        request_id: correlation id for logs.
        system: instruction prompt; sent via the ``system`` param with an
            ephemeral cache_control marker so the static instructions are
            prompt-cached between generations.

    Raises:
        CVGeneratorTruncatedError: when the response hit the max_tokens limit.
        CVGeneratorAIError: when all retries are exhausted or the API key
            is missing.
    """
    api_key = _api_key()
    if not api_key:
        raise CVGeneratorAIError("ANTHROPIC_API_KEY env var is not set")

    # max_retries=0 — manual backoff below governs; SDK retries would stack.
    client = anthropic.Anthropic(api_key=api_key, max_retries=0)
    model = _model()
    max_tokens = _max_tokens()
    max_retries = 4
    last_err: BaseException | None = None

    kwargs: dict[str, Any] = {}
    if system:
        kwargs["system"] = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    start = time.time()

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
            block: Any = message.content[0] if message.content else None
            if block is None:
                raise CVGeneratorAIError("Empty response from Claude")
            text = getattr(block, "text", "")
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
            if getattr(message, "stop_reason", None) == "max_tokens":
                raise CVGeneratorTruncatedError(
                    f"Odpowiedź Claude została ucięta limitem {max_tokens} tokenów "
                    "(stop_reason=max_tokens). Zwiększ CV_B2B_MAX_TOKENS."
                )
            return text or ""
        except CVGeneratorTruncatedError:
            raise
        except BaseException as err:  # noqa: BLE001 — broad on purpose, retry inspects type
            last_err = err
            retryable = _is_retryable(err)
            logger.warning(
                "[cv_b2b][%s] Claude attempt %d failed: %s (retryable=%s)",
                request_id,
                attempt + 1,
                err,
                retryable,
            )
            if attempt == max_retries or not retryable:
                break
            delay = 2 ** (attempt + 1)
            time.sleep(delay)

    duration = int((time.time() - start) * 1000)
    logger.error(
        "[cv_b2b][%s] Claude exhausted retries after %dms: %s",
        request_id,
        duration,
        last_err,
    )
    raise CVGeneratorAIError(f"Claude call failed: {last_err}") from last_err
