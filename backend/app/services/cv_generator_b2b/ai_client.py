"""CV B2B model access through the central AI gateway.

The production baseline stays pinned to Claude Sonnet 4.6 in the code-owned
route registry. Sonnet 5/OpenAI may be evaluated only as blind challengers;
there is no automatic Opus or cross-provider fallback here.
"""

from __future__ import annotations

from typing import Optional

from app.ai import AIError, AIRequest, ai_gateway
from app.models.ai_feature import AIFeatureKey

PROMPT_NAME = "cv_b2b_extraction"
PROMPT_VERSION = 6


class CVGeneratorAIError(RuntimeError):
    """Raised when the routed provider call fails."""


class CVGeneratorTruncatedError(CVGeneratorAIError):
    """Raised when the response reaches the configured output-token ceiling."""


class CVGeneratorOverloadedError(CVGeneratorAIError):
    """Raised after the gateway exhausts its single transient retry."""


async def analyze_with_ai(
    content: str,
    request_id: str,
    system: str | None = None,
    *,
    user_id: Optional[int] = None,
    client_id: Optional[int] = None,
    candidate_id: Optional[int] = None,
) -> str:
    """Run the CV transformation on the versioned Sonnet 4.6 route."""
    try:
        result = await ai_gateway.call(
            AIRequest(
                feature=AIFeatureKey.cv_b2b,
                request_id=request_id,
                user_id=user_id,
                client_id=client_id,
                subject_type="candidate" if candidate_id is not None else "cv_upload",
                subject_id=candidate_id,
                messages=[
                    {"role": "system", "content": system or ""},
                    {"role": "user", "content": content},
                ],
                prompt_version=f"{PROMPT_NAME}_v{PROMPT_VERSION}",
                schema_version="cv_b2b_json_v6",
                pii=True,
            )
        )
        text = str(result.content or "").strip()
        if not text:
            raise CVGeneratorAIError("Claude returned no text content")
        return text
    except AIError as exc:
        if exc.code == "max_tokens":
            raise CVGeneratorTruncatedError(
                "Odpowiedź Claude została ucięta limitem tokenów."
            ) from exc
        if exc.retryable or exc.code in {"timeout", "circuit_open"}:
            raise CVGeneratorOverloadedError(
                "Usługa AI (Claude) jest chwilowo przeciążona. "
                "Spróbuj wygenerować CV ponownie za chwilę."
            ) from exc
        raise CVGeneratorAIError(f"Claude call failed (code={exc.code})") from exc


__all__ = [
    "CVGeneratorAIError",
    "CVGeneratorOverloadedError",
    "CVGeneratorTruncatedError",
    "PROMPT_NAME",
    "PROMPT_VERSION",
    "analyze_with_ai",
]
