"""Bounded, task-local search accounting; never stores prompts or identities.

Costs are estimates from observed provider tokens and explicit model pricing.
Unknown usage/pricing and interrupted attempts are never reported as zero cost.
Histogram p95 is an upper bound, not an exact percentile or an end-to-end SLA.
"""

from __future__ import annotations

import copy
import math
import time
from contextlib import contextmanager
from contextvars import ContextVar

_active: ContextVar[SearchTelemetry | None] = ContextVar(
    "search_telemetry", default=None
)
_stage: ContextVar[str | None] = ContextVar("search_stage", default=None)
BOUNDS_MS = (
    1,
    5,
    10,
    25,
    50,
    100,
    250,
    500,
    1000,
    2500,
    5000,
    10000,
    30000,
    60000,
    180000,
)
STAGES = (
    "query_embedding",
    "sql_load",
    "eligibility",
    "retrieval",
    "scoring",
    "batch",
    "rerank",
    "generation",
)


def _empty_stage():
    return {
        "calls": 0,
        "failed": 0,
        "total_ms": 0.0,
        "max_ms": 0.0,
        "histogram": [0] * (len(BOUNDS_MS) + 1),
    }


class SearchTelemetry:
    def __init__(self, previous: dict | None = None):
        self.data = (
            copy.deepcopy(previous)
            if previous
            else {
                "schema": "search-telemetry-v1",
                "attempts": 0,
                "accounting_complete": True,
                "providers": {},
                "stages": {stage: _empty_stage() for stage in STAGES},
            }
        )

    def begin_attempt(self):
        self.data["attempts"] += 1
        # A replaced worker may have called a provider after its last durable
        # checkpoint. We cannot reconstruct or claim complete billing for it.
        if self.data["attempts"] > 1:
            self.data["accounting_complete"] = False

    @contextmanager
    def activate(self):
        token = _active.set(self)
        try:
            yield self
        finally:
            _active.reset(token)

    def duration(self, name: str, ms: float, failed: bool):
        value = self.data["stages"][name]
        value["calls"] += 1
        value["failed"] += int(failed)
        value["total_ms"] += ms
        value["max_ms"] = max(value["max_ms"], ms)
        bucket = next(
            (i for i, bound in enumerate(BOUNDS_MS) if ms <= bound), len(BOUNDS_MS)
        )
        value["histogram"][bucket] += 1

    def snapshot(self):
        result = copy.deepcopy(self.data)
        for value in result["stages"].values():
            target, accumulated = math.ceil(value["calls"] * 0.95), 0
            value["p95_upper_bound_ms"] = None
            if target:
                for i, count in enumerate(value["histogram"]):
                    accumulated += count
                    if accumulated >= target:
                        value["p95_upper_bound_ms"] = (
                            BOUNDS_MS[i] if i < len(BOUNDS_MS) else value["max_ms"]
                        )
                        break
        providers = result["providers"].values()
        result["known_cost_usd"] = sum(p["known_cost_usd"] for p in providers)
        result["cost_complete"] = result["accounting_complete"] and all(
            p["unpriced_calls"] == 0 for p in providers
        )
        result["estimated_cost_usd"] = (
            result["known_cost_usd"] if result["cost_complete"] else None
        )
        return result


@contextmanager
def stage(name: str):
    if name not in STAGES:
        raise ValueError("Unknown search stage")
    telemetry = _active.get()
    token = _stage.set(name)
    started = time.monotonic()
    outcome = {"failed": False}
    try:
        yield outcome
    except BaseException:
        outcome["failed"] = True
        raise
    finally:
        _stage.reset(token)
        if telemetry:
            telemetry.duration(
                name, max(0.0, (time.monotonic() - started) * 1000), outcome["failed"]
            )


def record_embedding_attempt(*, model: str, tokens, failed: bool, elapsed_ms: float):
    telemetry = _active.get()
    if telemetry is None:
        return
    from app.core.config import settings

    price = settings.AI_SEARCH_EMBEDDING_PRICES.get(model)
    valid_tokens = (
        isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0
    )
    valid_price = (
        isinstance(price, (int, float))
        and not isinstance(price, bool)
        and math.isfinite(price)
        and price >= 0
    )
    key = f"voyage:{model}:{_stage.get() or 'unspecified'}:{price if valid_price else 'unpriced'}"
    value = telemetry.data["providers"].setdefault(
        key,
        {
            "provider": "voyage",
            "model": model,
            "stage": _stage.get(),
            "calls": 0,
            "failed": 0,
            "elapsed_ms": 0.0,
            "observed_tokens": 0,
            "usage_unknown_calls": 0,
            "unpriced_calls": 0,
            "known_cost_usd": 0.0,
            "usd_per_million_tokens": price if valid_price else None,
        },
    )
    value["calls"] += 1
    value["failed"] += int(failed)
    value["elapsed_ms"] += elapsed_ms
    value["observed_tokens"] += tokens if valid_tokens else 0
    value["usage_unknown_calls"] += int(not valid_tokens)
    value["unpriced_calls"] += int(not (valid_tokens and valid_price))
    if valid_tokens and valid_price:
        value["known_cost_usd"] += tokens * price / 1_000_000
