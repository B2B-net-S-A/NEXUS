"""Read-only operational cost/latency report for completed full searches.

python -m scripts.report_candidate_search_metrics --hours 24 --limit 1000
No candidate IDs, request text or user information is emitted.
"""

import argparse
import asyncio
import json
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate_search_run import CandidateSearchRun


def summarize_runs(rows):
    elapsed, priced = [], []
    result = {
        "runs": len(rows),
        "partial_runs": 0,
        "latency_unknown_runs": 0,
        "cost_unknown_runs": 0,
        "known_cost_subtotal_usd": 0.0,
    }
    for state, metrics in rows:
        metrics = metrics or {}
        result["partial_runs"] += int(state == "partial")
        duration = metrics.get("elapsed_ms")
        if (
            isinstance(duration, (int, float))
            and math.isfinite(duration)
            and duration >= 0
        ):
            elapsed.append(duration)
        else:
            result["latency_unknown_runs"] += 1
        cost = metrics.get("estimated_cost_usd")
        if (
            metrics.get("cost_complete")
            and isinstance(cost, (int, float))
            and math.isfinite(cost)
            and cost >= 0
        ):
            priced.append(cost)
        else:
            result["cost_unknown_runs"] += 1
        subtotal = metrics.get("known_cost_usd")
        if (
            isinstance(subtotal, (int, float))
            and math.isfinite(subtotal)
            and subtotal >= 0
        ):
            result["known_cost_subtotal_usd"] += subtotal
    elapsed.sort()
    result["elapsed_p95_ms"] = (
        elapsed[math.ceil(len(elapsed) * 0.95) - 1] if elapsed else None
    )
    result["latency_samples"] = len(elapsed)
    result["fully_priced_runs"] = len(priced)
    result["mean_estimated_cost_usd_for_priced_runs"] = (
        sum(priced) / len(priced) if priced else None
    )
    result["estimated_total_cost_usd"] = (
        sum(priced) if rows and len(priced) == len(rows) else None
    )
    result["p95_method"] = (
        "nearest-rank; elapsed includes queue and retries; complete and partial runs"
    )
    return result


async def report(hours: int, limit: int):
    if not 1 <= hours <= 24 * 90 or not 1 <= limit <= 10000:
        raise ValueError("Hours must be 1..2160 and limit 1..10000")
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(CandidateSearchRun.state, CandidateSearchRun.metrics)
                .where(
                    CandidateSearchRun.created_at >= since,
                    CandidateSearchRun.state.in_(["complete", "partial"]),
                )
                .order_by(CandidateSearchRun.created_at.desc(), CandidateSearchRun.id)
                .limit(limit + 1)
            )
        ).all()
    return {
        "since": since.isoformat(),
        "sample_limit": limit,
        "sample_truncated": len(rows) > limit,
        **summarize_runs(rows[:limit]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(report(args.hours, args.limit)), indent=2))
