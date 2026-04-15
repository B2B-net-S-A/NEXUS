"""
embed_all.py — Batch embed all candidates into Qdrant (nexus_candidates collection).

Usage:
    python embed_all.py [--host localhost] [--port 5432]

Reads all candidates from PostgreSQL, generates Voyage AI embeddings,
and upserts them into Qdrant. Safe to run multiple times (upsert is idempotent).
"""
import asyncio
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Load .env from project root
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
# Also try backend-local .env
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://nexus:nexus@localhost:5433/nexus",
)

# Override port if running locally (docker maps 5433→5432)
if "localhost:5432" in DATABASE_URL and os.environ.get("LOCAL_PORT"):
    DATABASE_URL = DATABASE_URL.replace("localhost:5432", f"localhost:{os.environ['LOCAL_PORT']}")


async def embed_all(concurrency: int = 5):
    from app.core.config import settings
    from app.models.candidate import Candidate
    from app.services.embedding_service import embed_candidate, init_qdrant_collection

    print(f"[embed_all] DATABASE_URL: {DATABASE_URL}")
    print(f"[embed_all] QDRANT: {settings.QDRANT_HOST}:{settings.QDRANT_PORT}")
    print(f"[embed_all] VOYAGE_API_KEY set: {bool(settings.VOYAGE_API_KEY)}")

    # Init Qdrant collection
    await asyncio.to_thread(init_qdrant_collection)

    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        result = await db.execute(select(Candidate))
        candidates = result.scalars().all()
        total = len(candidates)
        print(f"[embed_all] Found {total} candidates to embed.")

        success = 0
        failure = 0
        semaphore = asyncio.Semaphore(concurrency)

        async def _embed_one(c):
            nonlocal success, failure
            async with semaphore:
                # Re-use the same session — embed_candidate fetches by ID
                ok = await embed_candidate(c.id, db)
                if ok:
                    success += 1
                    print(f"  ✓ [{success}/{total}] Candidate {c.id}: {c.name} {c.lastname}")
                else:
                    failure += 1
                    print(f"  ✗ Failed: Candidate {c.id}: {c.name} {c.lastname}")

        tasks = [_embed_one(c) for c in candidates]
        await asyncio.gather(*tasks)

    await engine.dispose()
    print(f"\n[embed_all] Done. Success: {success}, Failed: {failure}, Total: {total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch embed all candidates into Qdrant")
    parser.add_argument("--concurrency", type=int, default=3, help="Parallel embedding workers (default: 3)")
    args = parser.parse_args()
    asyncio.run(embed_all(concurrency=args.concurrency))
