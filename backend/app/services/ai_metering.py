"""Durable per-response usage, independent of the business transaction.

The provider is synchronous and runs in a worker thread. Persist immediately
there using a small separate sync pool; a paid response survives a subsequent
parser error, rollback or process exit. Failed writes remain in the operation's
buffer and are retried idempotently on exit. No monthly-row UPDATE or lock can
fan out over NULL actors, nor wait on a caller's uncommitted monthly upsert.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from functools import lru_cache
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url

from app.models.ai_metering import AIOperation, AIProviderCall

logger = logging.getLogger(__name__)
PRICE_VERSION = "anthropic-standard-2026-09-08"
# USD / million tokens, official source (verified 2026-09-08):
# https://platform.claude.com/docs/en/about-claude/pricing
_PRICES = {
    "claude-sonnet-5": (2, 10),
    "claude-sonnet-4-6": (3, 15),
    "claude-sonnet-4-5": (3, 15),
    "claude-opus-4-8": (5, 25),
    "claude-opus-4-7": (5, 25),
    "claude-opus-4-6": (5, 25),
    "claude-opus-4-5": (5, 25),
    "claude-opus-5": (5, 25),
    "claude-haiku-4-5": (1, 5),
}


def token_count(value):
    return value if type(value) is int and value >= 0 else None


def response_event(
    operation_id: str,
    message,
    *,
    model: str,
    latency_ms: int,
    inference_geo: str = "global",
    standard_pricing: bool = True,
) -> dict:
    usage = getattr(message, "usage", None)
    actual_model = getattr(message, "model", None) or model
    message_id = getattr(message, "id", None)
    creation = getattr(usage, "cache_creation", None)
    event = {
        "event_key": f"anthropic:{message_id or uuid4()}",
        "operation_id": operation_id,
        "provider": "anthropic",
        "model": actual_model,
        "request_id": getattr(message, "_request_id", None),
        "outcome": "truncated"
        if getattr(message, "stop_reason", None) == "max_tokens"
        else "response",
        "latency_ms": max(0, latency_ms),
        "input_tokens": token_count(getattr(usage, "input_tokens", None)),
        "output_tokens": token_count(getattr(usage, "output_tokens", None)),
        "cache_read_tokens": token_count(getattr(usage, "cache_read_input_tokens", 0))
        if usage
        else None,
        "cache_creation_tokens": token_count(
            getattr(usage, "cache_creation_input_tokens", 0)
        )
        if usage
        else None,
        "cache_creation_1h_tokens": token_count(
            getattr(creation, "ephemeral_1h_input_tokens", 0)
        )
        if usage
        else None,
        "estimated_cost_usd": None,
        "price_version": None,
    }
    prices = next(
        (
            p
            for prefix, p in _PRICES.items()
            if actual_model == prefix or actual_model.startswith(prefix + "-")
        ),
        None,
    )
    counts = [
        event[k]
        for k in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
            "cache_creation_1h_tokens",
        )
    ]
    if (
        prices
        and standard_pricing
        and all(n is not None for n in counts)
        and counts[4] <= counts[3]
    ):
        tin, tout, read, write, hour = map(Decimal, counts)
        base, output = map(Decimal, prices)
        cost = (
            base * (tin + read / 10 + (write - hour) * Decimal("1.25") + hour * 2)
            + output * tout
        ) / 1_000_000
        if inference_geo == "us":
            cost *= Decimal("1.1")
        event["estimated_cost_usd"] = cost.quantize(Decimal("0.00000001"))
        event["price_version"] = PRICE_VERSION
    return event


@lru_cache(maxsize=1)
def _sync_engine():
    from app.core.config import settings

    url = make_url(settings.DATABASE_URL).set(drivername="postgresql+psycopg2")
    return create_engine(
        url,
        pool_size=2,
        max_overflow=2,
        pool_timeout=5,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
    )


def persist_response(event: dict) -> bool:
    try:
        with _sync_engine().begin() as connection:
            connection.execute(
                insert(AIProviderCall).values(**event).on_conflict_do_nothing()
            )
        return True
    except Exception:
        logger.error(
            "ai-metering: response persistence failed event=%s; queued for retry",
            event["event_key"],
            exc_info=True,
        )
        return False


async def measured_usage(db, period: date) -> dict[str, dict]:
    """Measured responses only; incomplete/legacy coverage is explicit."""
    result = await db.execute(
        select(
            AIOperation.feature,
            func.count(AIProviderCall.event_key),
            func.sum(AIProviderCall.input_tokens),
            func.sum(AIProviderCall.output_tokens),
            func.sum(AIProviderCall.cache_read_tokens),
            func.sum(AIProviderCall.cache_creation_tokens),
            func.sum(AIProviderCall.estimated_cost_usd),
            func.count().filter(AIProviderCall.estimated_cost_usd.is_(None)),
        )
        .join(AIProviderCall, AIProviderCall.operation_id == AIOperation.id)
        .where(AIOperation.period_start == period)
        .group_by(AIOperation.feature)
    )
    return {
        feature: dict(
            provider_calls=count,
            input_tokens=tin,
            output_tokens=tout,
            cache_read_tokens=read,
            cache_creation_tokens=write,
            estimated_cost_usd=cost,
            unpriced_calls=unpriced,
        )
        for feature, count, tin, tout, read, write, cost, unpriced in result.all()
    }
