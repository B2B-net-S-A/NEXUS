"""Read-only runtime report and one fixed synthetic query-vector probe.

No candidate content, user IDs, request text, credentials or configuration
changes. The operation identity permits only one probe per scheduled run.
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate_search_run import CandidateSearchResult, CandidateSearchRun
from app.services.full_search_measurement import request_vector
from app.services.index_outbox_service import diagnostics
from app.services.search_telemetry import SearchTelemetry
from scripts.report_candidate_search_metrics import report as metrics_report

PREFIX = "NEXUS_SEARCH_DIAGNOSTICS_RESULT="


def metrics_projection(metrics):
    metrics = metrics or {}
    providers = list((metrics.get("providers") or {}).values())
    query = (metrics.get("stages") or {}).get("query_embedding") or {}
    return {
        "elapsed_ms": metrics.get("elapsed_ms"),
        "estimated_cost_usd": metrics.get("estimated_cost_usd"),
        "cost_complete": metrics.get("cost_complete"),
        "accounting_complete": metrics.get("accounting_complete"),
        "query_calls": query.get("calls"),
        "query_failed": query.get("failed"),
        "provider_calls": sum(p.get("calls", 0) for p in providers),
        "provider_failed": sum(p.get("failed", 0) for p in providers),
        "observed_tokens": sum(p.get("observed_tokens", 0) for p in providers),
        "unpriced_calls": sum(p.get("unpriced_calls", 0) for p in providers),
    }


async def query_probe():
    telemetry = SearchTelemetry()
    error_type = None
    vector = None
    try:
        with telemetry.activate():
            async with asyncio.timeout(65):
                vector = await request_vector("Synthetic candidate search diagnostic")
    except Exception as error:
        error_type = type(error).__name__
    return {
        "ok": vector is not None,
        "dimensions": len(vector) if vector is not None else None,
        "error_type": error_type,
        **metrics_projection(telemetry.snapshot()),
    }


async def collect_report():
    from app.services.embedding_service import _collection, _voyage_model

    model = _voyage_model()
    async with AsyncSessionLocal() as db:
        queue = await diagnostics(db)
        runs = (
            (
                await db.execute(
                    select(CandidateSearchRun)
                    .order_by(
                        CandidateSearchRun.created_at.desc(), CandidateSearchRun.id
                    )
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        recent = []
        for run in runs:
            counts = (
                await db.execute(
                    select(CandidateSearchResult.measurement, func.count())
                    .where(CandidateSearchResult.run_id == run.id)
                    .group_by(CandidateSearchResult.measurement)
                )
            ).all()
            recent.append(
                {
                    "run_id": run.id,
                    "state": run.state,
                    "population": run.population_size,
                    "query_characters": len(
                        run.request_context.get("query_text") or ""
                    ),
                    "measurement_counts": {
                        key or "pending": value for key, value in counts
                    },
                    **metrics_projection(run.metrics),
                }
            )
    return {
        "ok": True,
        "runtime": {
            "embedding_model": model,
            "collection": _collection(),
            "key_present": bool(settings.VOYAGE_API_KEY),
            "worker_enabled": settings.AI_INDEX_WORKER_ENABLED,
            "worker_batch": settings.AI_INDEX_WORKER_BATCH,
            "worker_interval_seconds": settings.AI_INDEX_WORKER_INTERVAL_SECONDS,
            "usd_per_million_tokens": settings.AI_SEARCH_EMBEDDING_PRICES.get(model),
        },
        "queue": queue,
        "recent_runs": recent,
        "metrics_24h": await metrics_report(24, 1000),
        "synthetic_query_probe": await query_probe(),
    }


async def run_once(identity, *, root=Path("/tmp")):
    if not re.fullmatch(r"[1-9][0-9]{0,19}-[1-9][0-9]{0,5}", identity):
        raise ValueError("Invalid run identity")
    directory = root / f"nexus-search-diagnostics-{identity}"
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        return None
    try:
        async with asyncio.timeout(180):
            return await collect_report()
    except Exception as error:
        return {"ok": False, "error_type": type(error).__name__}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-identity", required=True)
    args = parser.parse_args()
    result = asyncio.run(run_once(args.run_identity))
    if result is not None:
        print(PREFIX + json.dumps(result, separators=(",", ":")), flush=True)
        raise SystemExit(0 if result["ok"] else 1)
