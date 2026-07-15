"""Compliance, quota, budget, retry, validation, cache and ledger gateway."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select

from app.ai.adapters import ADAPTERS, AdapterResponse
from app.ai.circuit_breaker import circuit_breaker
from app.ai.registry import get_feature_route
from app.ai.types import AIError, AIRequest, AIResult, FeatureRoute
from app.core.database import AsyncSessionLocal
from app.models.ai_feature import AIFeatureConfig
from app.models.ai_platform import (
    AIBudgetReservation,
    AICallLedger,
    AIProviderCompliance,
    AIRoutingState,
)
from app.services.ai_quota import check_and_increment


def _canonical_hash(request: AIRequest) -> str:
    metadata = {
        key: value
        for key, value in request.metadata.items()
        if key != "handler"
        and isinstance(value, (str, int, float, bool, list, dict, type(None)))
    }
    raw = json.dumps(
        {"messages": request.messages, "metadata": metadata},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _output_hash(content: Any) -> str:
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cost(response: AdapterResponse, route: FeatureRoute) -> Decimal:
    if response.cost_usd is not None:
        return response.cost_usd
    if route.input_cost_per_million_usd or route.output_cost_per_million_usd:
        return (
            Decimal(response.input_tokens) * route.input_cost_per_million_usd
            + Decimal(response.output_tokens) * route.output_cost_per_million_usd
        ) / Decimal(1_000_000)
    # Providers do not return currency cost. Until pricing is configured in a
    # versioned route, reconcile to the conservative pre-call reservation.
    return route.reservation_cost_usd


class _MemoryCache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, AIResult]] = {}

    def get(self, key: str) -> AIResult | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, result = item
        if expires_at <= time.monotonic():
            self._items.pop(key, None)
            return None
        return replace(result, cached=True)

    def put(self, key: str, result: AIResult, ttl_seconds: int) -> None:
        if ttl_seconds > 0:
            self._items[key] = (time.monotonic() + ttl_seconds, result)


class AIGateway:
    def __init__(self) -> None:
        self.cache = _MemoryCache()

    async def active_registry_version(self) -> str:
        async with AsyncSessionLocal() as db:
            value = await db.scalar(
                select(AIRoutingState.registry_version).where(AIRoutingState.id == 1)
            )
        return value or "v1_current"

    async def _authorize_and_reserve(
        self, request: AIRequest, route: FeatureRoute, registry_version: str
    ) -> None:
        async with AsyncSessionLocal() as db:
            existing = await db.scalar(
                select(AIBudgetReservation)
                .where(AIBudgetReservation.request_id == request.request_id)
                .with_for_update()
            )
            if existing is not None:
                raise AIError(
                    "duplicate_request",
                    "To żądanie biznesowe zostało już policzone",
                    status_code=409,
                )
            cfg = await db.scalar(
                select(AIFeatureConfig)
                .where(AIFeatureConfig.feature == request.feature)
                .with_for_update()
            )
            if cfg is None:
                raise AIError(
                    "feature_unconfigured",
                    "Funkcja AI nie jest skonfigurowana",
                    status_code=503,
                )

            await check_and_increment(db, request.feature, request.user_id)

            if route.provider != "internal":
                compliance = await db.get(AIProviderCompliance, route.provider)
                if compliance is None or not compliance.production_allowed:
                    raise AIError(
                        "compliance_blocked",
                        "Dostawca nie przeszedł bramy zgodności dla produkcji",
                        status_code=503,
                    )
                if request.metadata.get("evaluation") and not (
                    compliance.dpa_approved
                    and compliance.zdr_approved
                    and compliance.subprocessors_reviewed
                    and compliance.transfer_basis
                ):
                    raise AIError(
                        "evaluation_compliance_blocked",
                        "Dostawca nie ma kompletu DPA/ZDR/subprocessors/transfer dla ewaluacji",
                        status_code=503,
                    )

            period = datetime.now(timezone.utc).date().replace(day=1)
            budget = Decimal(cfg.monthly_budget_usd or 0)
            if budget > 0:
                spend = await db.scalar(
                    select(
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        AIBudgetReservation.actual_cost_usd.is_not(
                                            None
                                        ),
                                        AIBudgetReservation.actual_cost_usd,
                                    ),
                                    else_=AIBudgetReservation.reserved_cost_usd,
                                )
                            ),
                            0,
                        )
                    ).where(
                        AIBudgetReservation.feature == request.feature.value,
                        AIBudgetReservation.period_start == period,
                        AIBudgetReservation.status.in_(
                            ("reserved", "reconciled", "failed")
                        ),
                    )
                )
                if Decimal(spend or 0) + route.reservation_cost_usd > budget:
                    raise AIError(
                        "budget_exceeded",
                        "Miesięczny budżet funkcji AI został wyczerpany",
                        status_code=503,
                    )

            db.add(
                AIBudgetReservation(
                    request_id=request.request_id,
                    feature=request.feature.value,
                    period_start=period,
                    reserved_cost_usd=route.reservation_cost_usd,
                    status="reserved",
                )
            )
            await db.commit()

    async def _reconcile(self, request_id: str, cost: Decimal, *, failed: bool) -> None:
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(AIBudgetReservation).where(
                    AIBudgetReservation.request_id == request_id
                )
            )
            if row is None:
                return
            row.actual_cost_usd = None if failed and cost == 0 else cost
            row.status = "failed" if failed else "reconciled"
            row.reconciled_at = datetime.now(timezone.utc)
            await db.commit()

    async def _ledger(
        self,
        request: AIRequest,
        *,
        route_version: str,
        provider: str,
        model: str,
        attempt: int,
        response: AdapterResponse | None,
        cost: Decimal,
        latency_ms: int,
        status: str,
        input_hash: str,
        error_code: str | None = None,
        retried: bool = False,
        escalated: bool = False,
    ) -> None:
        async with AsyncSessionLocal() as db:
            db.add(
                AICallLedger(
                    request_id=request.request_id,
                    attempt=attempt,
                    feature=request.feature.value,
                    user_id=request.user_id,
                    client_id=request.client_id,
                    subject_type=request.subject_type,
                    subject_id=request.subject_id,
                    provider=provider,
                    model=model,
                    route_version=route_version,
                    prompt_version=request.prompt_version,
                    schema_version=request.schema_version,
                    input_tokens=response.input_tokens if response else 0,
                    output_tokens=response.output_tokens if response else 0,
                    cache_read_tokens=response.cache_read_tokens if response else 0,
                    cache_write_tokens=response.cache_write_tokens if response else 0,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    retried=retried,
                    escalated=escalated,
                    pii=request.pii,
                    status=status,
                    error_code=error_code,
                    input_hash=input_hash,
                    output_hash=_output_hash(response.content) if response else None,
                )
            )
            await db.commit()

    @staticmethod
    def _validate(request: AIRequest, content: Any) -> Any:
        if request.structured_validator is None:
            return content
        parsed = json.loads(content) if isinstance(content, str) else content
        return request.structured_validator(parsed)

    async def call(self, request: AIRequest) -> AIResult:
        route_version = await self.active_registry_version()
        route = get_feature_route(route_version, request.feature, request.mode)
        if not route.enabled:
            raise AIError(
                "route_disabled", "Routing funkcji AI jest wyłączony", status_code=503
            )
        await self._authorize_and_reserve(request, route, route_version)

        input_hash = _canonical_hash(request)
        cache_key = ":".join(
            (
                route_version,
                request.feature.value,
                request.mode or "default",
                route.provider,
                route.model,
                request.prompt_version,
                request.schema_version,
                input_hash,
            )
        )
        cached = None if request.pii else self.cache.get(cache_key)
        if cached is not None:
            await self._ledger(
                request,
                route_version=route_version,
                provider=route.provider,
                model=route.model,
                attempt=0,
                response=None,
                cost=Decimal("0"),
                latency_ms=0,
                status="cached",
                input_hash=input_hash,
            )
            await self._reconcile(request.request_id, Decimal("0"), failed=False)
            return replace(cached, request_id=request.request_id, cached=True)

        adapter = ADAPTERS.get(route.provider)
        if adapter is None:
            await self._reconcile(request.request_id, Decimal("0"), failed=True)
            raise AIError(
                "adapter_missing", "Brak adaptera dostawcy AI", status_code=503
            )

        total_cost = Decimal("0")
        last_error: AIError | None = None
        models = (route.model, *route.escalation_models)
        attempt_number = 0
        for model_index, model in enumerate(models):
            breaker_key = f"{route.provider}:{model}"
            if not circuit_breaker.allow(breaker_key):
                last_error = AIError(
                    "circuit_open", "Obwód dostawcy AI jest otwarty", status_code=503
                )
                continue
            for retry_index in range(2):
                attempt_number += 1
                started = time.monotonic()
                response: AdapterResponse | None = None
                try:
                    response = await asyncio.wait_for(
                        adapter.call(request, route, model=model),
                        timeout=route.timeout_seconds,
                    )
                    validated = self._validate(request, response.content)
                    response.content = validated
                    latency_ms = int((time.monotonic() - started) * 1000)
                    call_cost = _cost(response, route)
                    total_cost += call_cost
                    circuit_breaker.success(breaker_key)
                    await self._ledger(
                        request,
                        route_version=route_version,
                        provider=route.provider,
                        model=model,
                        attempt=attempt_number,
                        response=response,
                        cost=call_cost,
                        latency_ms=latency_ms,
                        status="success",
                        input_hash=input_hash,
                        retried=retry_index > 0,
                        escalated=model_index > 0,
                    )
                    await self._reconcile(request.request_id, total_cost, failed=False)
                    result = AIResult(
                        request_id=request.request_id,
                        feature=request.feature,
                        provider=route.provider,
                        model=model,
                        route_version=route_version,
                        content=validated,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        cache_read_tokens=response.cache_read_tokens,
                        cache_write_tokens=response.cache_write_tokens,
                        cost_usd=total_cost,
                        latency_ms=latency_ms,
                        escalated=model_index > 0,
                    )
                    if not request.pii:
                        self.cache.put(cache_key, result, request.cache_ttl_seconds)
                    return result
                except json.JSONDecodeError:
                    error = AIError(
                        "schema_invalid", "Odpowiedź AI nie jest poprawnym JSON"
                    )
                except AIError as exc:
                    error = exc
                except asyncio.TimeoutError:
                    error = AIError(
                        "timeout", "Przekroczono limit czasu AI", retryable=True
                    )
                except Exception as exc:
                    error = AIError("validation_failed", type(exc).__name__)

                latency_ms = int((time.monotonic() - started) * 1000)
                circuit_breaker.failure(breaker_key)
                await self._ledger(
                    request,
                    route_version=route_version,
                    provider=route.provider,
                    model=model,
                    attempt=attempt_number,
                    response=response,
                    cost=Decimal("0"),
                    latency_ms=latency_ms,
                    status="error",
                    input_hash=input_hash,
                    error_code=error.code,
                    retried=retry_index > 0,
                    escalated=model_index > 0,
                )
                last_error = error
                if not error.retryable or retry_index == 1:
                    break

        await self._reconcile(request.request_id, total_cost, failed=True)
        raise last_error or AIError("provider_failed", "Wywołanie AI nie powiodło się")


ai_gateway = AIGateway()
