"""Anthropic Claude client with retry — 1:1 port from `lib/cv-shared.ts`.

Uses the model + retry policy from the external CV-Generator:
  - Model: ``claude-sonnet-4-20250514`` (env-overridable)
  - Max tokens: 4000
  - 4 retries on overloaded/rate-limit errors with exponential backoff
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import anthropic

logger = logging.getLogger(__name__)


CV_B2B_MODEL = os.environ.get("CV_B2B_MODEL", "claude-sonnet-4-20250514")
CV_B2B_MAX_TOKENS = int(os.environ.get("CV_B2B_MAX_TOKENS", "4000"))


class CVGeneratorAIError(RuntimeError):
    """Raised when Claude call fails after all retries."""


def _is_retryable(err: BaseException) -> bool:
    """Match the JS predicate (`isAnthropicRetryable`)."""
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

    if status == 529:
        return True
    if err_type == "overloaded_error":
        return True
    if isinstance(err, anthropic.APIStatusError) and status and 500 <= int(status) < 600:
        return True
    if isinstance(err, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return True
    return False


def analyze_with_ai(content: str, request_id: str) -> str:
    """Call Claude with the prompt and retry on transient failures.

    Returns the text content of the first message block.

    Raises:
        CVGeneratorAIError: when all retries are exhausted, or when
            ``ANTHROPIC_API_KEY`` is missing.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise CVGeneratorAIError("ANTHROPIC_API_KEY env var is not set")

    client = anthropic.Anthropic(api_key=api_key)
    max_retries = 4
    last_err: BaseException | None = None

    start = time.time()

    for attempt in range(max_retries + 1):
        try:
            logger.info(
                "[cv_b2b][%s] Claude attempt %d/%d model=%s",
                request_id,
                attempt + 1,
                max_retries + 1,
                CV_B2B_MODEL,
            )
            message = client.messages.create(
                model=CV_B2B_MODEL,
                max_tokens=CV_B2B_MAX_TOKENS,
                messages=[{"role": "user", "content": content}],
            )
            block: Any = message.content[0] if message.content else None
            if block is None:
                raise CVGeneratorAIError("Empty response from Claude")
            text = getattr(block, "text", "")
            duration = int((time.time() - start) * 1000)
            logger.info(
                "[cv_b2b][%s] Claude success in %dms (attempts=%d, tokens_out=%s)",
                request_id,
                duration,
                attempt + 1,
                getattr(message.usage, "output_tokens", "?"),
            )
            return text or ""
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
