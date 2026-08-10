"""Shared, resilient Claude (Anthropic) call helper.

Centralises the timeout + transient-retry policy that previously lived only in
``cv_generator_b2b/ai_client.py`` (the CV-B2B generator). The other request-path
Claude callers — ``match_justification_service``, ``champion_draft_service`` and
``dynareporter_mindy`` — used to construct ``anthropic.Anthropic(api_key)`` with
the SDK's **600 s default timeout** and **no retry**, so a hung provider pinned a
threadpool slot for ten minutes and a single transient 429/529 turned into a hard
502 with no degraded mode.

Design — deliberately ADDITIVE and behaviour-preserving:

* ``call_claude()`` returns the *same* ``anthropic.types.Message`` that
  ``client.messages.create()`` returns, so each caller's existing response
  parsing (concatenating text blocks, ``stop_reason`` checks, ``usage`` logging)
  is unchanged.
* On the success path it does exactly one ``messages.create`` — identical to the
  old code, only with an explicit per-request timeout.
* It re-raises the underlying error once the retry budget is exhausted, so each
  caller's existing ``except`` / fallback / error-status mapping still fires.

The function is synchronous (it uses ``time.sleep`` for backoff) and MUST be run
off the event loop — callers invoke it via ``starlette.concurrency.run_in_threadpool``,
so the blocking sleep occupies a worker thread, never the single-worker loop.
"""

from __future__ import annotations

import logging
import random
import time
import traceback
from typing import Any

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)

# Backoff schedule for transient failures: min(cap, base * 2**attempt) + jitter.
# Mirrors the proven cv_generator_b2b/ai_client.py policy.
_BACKOFF_BASE = 1.0
_BACKOFF_CAP = 8.0
_BACKOFF_JITTER = 0.5


def is_retryable_anthropic_error(err: BaseException) -> bool:
    """Return True for overloaded / rate-limited / 5xx / connection / timeout errors.

    A 4xx request/config error (bad key, malformed request) is NOT retryable —
    every attempt would fail identically — so it surfaces immediately.
    """
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


def _record_health(started: float, *, failed: bool) -> None:
    """Feed the call outcome into the Claude circuit breaker (never raises)."""
    try:
        from app.services.ai_health import record_provider_call

        record_provider_call("claude", int((time.monotonic() - started) * 1000), failed)
    except Exception:  # noqa: BLE001 — health telemetry must not break a call
        pass


def _assert_declared(model: str) -> None:
    """Refuse (or at least log) an LLM call nobody charged a quota for.

    The gate cannot live on the route: `fireflies_sync` is a background loop,
    CV enrichment is a BackgroundTask and `enrich_from_call` is a webhook —
    none of them is a request handler, and all three reached Claude without a
    quota check while every *handler* looked correctly wrapped. Standing here,
    at the provider boundary, is the only position that sees all of them.
    """
    try:
        from app.core.config import settings
        from app.services.ai_quota import AIQuotaUngated, current_ai_call

        if current_ai_call() is not None:
            return
        if getattr(settings, "AI_QUOTA_STRICT", False):
            raise AIQuotaUngated(
                f"LLM call (model={model}) outside `async with ai_feature(...)` — "
                "it would spend money the quota system cannot see"
            )
        logger.error(
            "[ai-quota] UNGATED LLM call model=%s — not wrapped in "
            "`async with ai_feature(...)`; invisible to the master toggle, the "
            "monthly limit and ai_usage_log. Stack: %s",
            model,
            "".join(traceback.format_stack(limit=8)),
        )
    except ImportError:  # pragma: no cover — keeps the client importable alone
        return


def call_claude(
    *,
    messages: list[dict[str, Any]],
    model: str,
    max_tokens: int,
    api_key: str | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
    **kwargs: Any,
) -> anthropic.types.Message:
    """Call ``messages.create`` with an explicit timeout and transient-retry backoff.

    Returns the raw Anthropic ``Message`` (identical to ``client.messages.create``)
    so callers parse it exactly as before. Re-raises the last error once the retry
    budget is exhausted, preserving each caller's existing error handling.

    Args:
        messages: the Anthropic ``messages`` list (passed through unchanged).
        model: model id.
        max_tokens: max_tokens (passed through unchanged).
        api_key: overrides ``settings.ANTHROPIC_API_KEY`` when a caller resolves
            the key itself (e.g. also honouring a legacy ``CLAUDE_API_KEY``).
        timeout: per-request timeout in seconds; defaults to
            ``settings.ANTHROPIC_TIMEOUT_SECONDS``.
        max_retries: extra attempts after the first on transient errors; defaults
            to ``settings.ANTHROPIC_MAX_RETRIES``.
        **kwargs: forwarded verbatim to ``messages.create`` (``system``,
            ``thinking``, etc.).
    """
    _assert_declared(model)

    key = api_key if api_key is not None else settings.ANTHROPIC_API_KEY
    request_timeout = (
        timeout if timeout is not None else settings.ANTHROPIC_TIMEOUT_SECONDS
    )
    retries = max_retries if max_retries is not None else settings.ANTHROPIC_MAX_RETRIES

    # max_retries=0 — the SDK's own retry policy is disabled so it does not stack
    # on top of the manual backoff below; the explicit timeout caps a hung attempt.
    client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=request_timeout)

    started = time.monotonic()
    last_err: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                **kwargs,
            )
            _record_health(started, failed=False)
            return message
        except BaseException as err:  # noqa: BLE001 — classify then re-raise
            last_err = err
            retryable = is_retryable_anthropic_error(err)
            logger.warning(
                "[claude_client] attempt %d/%d model=%s failed: %s (retryable=%s)",
                attempt + 1,
                retries + 1,
                model,
                err,
                retryable,
            )
            if attempt >= retries or not retryable:
                _record_health(started, failed=True)
                raise
            delay = min(_BACKOFF_CAP, _BACKOFF_BASE * (2**attempt)) + random.uniform(
                0, _BACKOFF_JITTER
            )
            time.sleep(delay)

    # Unreachable (the loop either returns or raises), but satisfies type-checkers.
    _record_health(started, failed=True)
    raise last_err if last_err is not None else RuntimeError("call_claude failed")
