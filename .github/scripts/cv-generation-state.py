"""Fixed read-only runtime probe; exports IDs/timings, never CVs or credentials."""

import asyncio
import json

from sqlalchemy import text

from app.core.database import AsyncSessionLocal, engine
from app.services.cv_generator_b2b.provider import _model, _fallback_models


async def main():
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        await db.execute(text("SET LOCAL statement_timeout = '10s'"))
        rows = (await db.execute(text("""
            SELECT j.id, j.generated_id, j.kind, j.status,
                   j.created_at, j.lease_expires_at, j.finished_at,
                   d.status AS document_status,
                   CASE WHEN d.error_message LIKE '%przeciążona%' THEN 'provider_unavailable'
                        WHEN d.error_message LIKE '%pełnych danych źródłowych%' THEN 'source_rejected'
                        WHEN d.error_message IS NOT NULL THEN 'other' END AS error,
                   j.quota_snapshot->>'operation_id' AS operation_id
            FROM cv_generation_jobs j
            LEFT JOIN cv_generated_documents d ON d.id=j.generated_id
            ORDER BY j.id DESC LIMIT 10
        """))).mappings().all()
        result = []
        for row in rows:
            item = dict(row)
            operation_id = item.pop("operation_id")
            calls = (await db.execute(text("""
                SELECT model, outcome, latency_ms, input_tokens, output_tokens, created_at
                FROM ai_provider_calls WHERE operation_id=:operation_id
                ORDER BY created_at LIMIT 30
            """), {"operation_id": operation_id})).mappings().all()
            item["calls"] = [dict(c) for c in calls]
            result.append(item)
        await db.rollback()
    print("CV_GENERATION_STATE=" + json.dumps({"jobs": result, "model": _model(), "fallbacks": _fallback_models()}, default=str))
    await engine.dispose()


asyncio.run(main())
