"""Provider adapters. SDK imports are confined to this module."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from app.ai.types import AIError, AIRequest, FeatureRoute
from app.core.config import settings


@dataclass
class AdapterResponse:
    content: Any
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal | None = None


class ProviderAdapter(Protocol):
    async def call(
        self, request: AIRequest, route: FeatureRoute, *, model: str
    ) -> AdapterResponse: ...


def _provider_error(exc: Exception) -> AIError:
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    retryable = status == 429 or (isinstance(status, int) and status >= 500)
    if type(exc).__name__ in {"APIConnectionError", "APITimeoutError", "TimeoutError"}:
        retryable = True
    return AIError(
        "provider_error",
        f"Dostawca AI zwrócił błąd {type(exc).__name__}",
        retryable=retryable,
    )


class AnthropicAdapter:
    async def call(
        self, request: AIRequest, route: FeatureRoute, *, model: str
    ) -> AdapterResponse:
        if not settings.ANTHROPIC_API_KEY:
            raise AIError(
                "provider_unconfigured", "ANTHROPIC_API_KEY nie jest ustawiony"
            )
        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            system_parts = [
                str(item.get("content", ""))
                for item in request.messages
                if item.get("role") == "system"
            ]
            messages = [
                item
                for item in request.messages
                if item.get("role") in {"user", "assistant"}
            ]
            response = await client.messages.create(
                model=model,
                max_tokens=route.max_output_tokens,
                system="\n\n".join(system_parts),
                messages=messages,
            )
            content = "".join(
                block.text
                for block in response.content
                if getattr(block, "type", "") == "text"
            )
            usage = response.usage
            return AdapterResponse(
                content=content,
                input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                cache_read_tokens=int(
                    getattr(usage, "cache_read_input_tokens", 0) or 0
                ),
                cache_write_tokens=int(
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                ),
            )
        except AIError:
            raise
        except Exception as exc:
            raise _provider_error(exc) from exc


class VoyageAdapter:
    async def call(
        self, request: AIRequest, route: FeatureRoute, *, model: str
    ) -> AdapterResponse:
        import httpx

        if not settings.VOYAGE_API_KEY:
            raise AIError("provider_unconfigured", "VOYAGE_API_KEY nie jest ustawiony")
        payload = request.metadata
        if route.operation == "embed":
            url = "https://api.voyageai.com/v1/embeddings"
            body = {
                "model": model,
                "input": payload.get("input", []),
                "input_type": payload.get("input_type", "document"),
                "output_dimension": payload.get("output_dimension", 1024),
            }
        elif route.operation == "rerank":
            url = "https://api.voyageai.com/v1/rerank"
            body = {
                "model": model,
                "query": payload.get("query", ""),
                "documents": payload.get("documents", []),
                "top_k": payload.get("top_k"),
            }
        else:
            raise AIError("unsupported_operation", "Nieobsługiwana operacja Voyage")
        try:
            async with httpx.AsyncClient(timeout=route.timeout_seconds) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {settings.VOYAGE_API_KEY}"},
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
            usage = data.get("usage") or {}
            return AdapterResponse(
                content=data,
                input_tokens=int(usage.get("total_tokens", 0) or 0),
            )
        except Exception as exc:
            if isinstance(exc, AIError):
                raise
            raise _provider_error(exc) from exc


class InternalAdapter:
    async def call(
        self, request: AIRequest, route: FeatureRoute, *, model: str
    ) -> AdapterResponse:
        handler = request.metadata.get("handler")
        if not callable(handler):
            raise AIError(
                "internal_handler_missing",
                "Brak deterministycznego handlera dla funkcji AI",
                status_code=500,
            )
        result = handler()
        if asyncio.iscoroutine(result):
            result = await result
        return AdapterResponse(content=result, cost_usd=Decimal("0"))


ADAPTERS: dict[str, ProviderAdapter] = {
    "anthropic": AnthropicAdapter(),
    "voyage": VoyageAdapter(),
    "internal": InternalAdapter(),
}
