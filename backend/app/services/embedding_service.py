"""
Embedding Service — Voyage AI + Qdrant
Semantic search for Nexus ATS candidates.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings

logger = logging.getLogger(__name__)

VECTOR_SIZE = 1024
VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings"

JOBS_COLLECTION = "nexus_jobs"


def _collection() -> str:
    """Return configured Qdrant collection name (default: nexus_candidates)."""
    name = getattr(settings, "QDRANT_COLLECTION", "nexus_candidates")
    return name or "nexus_candidates"


def _jobs_collection() -> str:
    """Separate Qdrant collection for job embeddings (Phase 2)."""
    return getattr(settings, "QDRANT_JOBS_COLLECTION", None) or JOBS_COLLECTION


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------


def _get_qdrant_client():
    """Return a synchronous Qdrant client (used in background tasks)."""
    try:
        from qdrant_client import QdrantClient

        return QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    except Exception as e:
        logger.error(f"[Qdrant] Failed to create client: {e}")
        return None


def init_qdrant_collection() -> None:
    """
    Create Qdrant collections if missing:
      - nexus_candidates (Phase 1)
      - nexus_jobs       (Phase 2)

    Called at application startup (synchronous, runs in thread via asyncio.to_thread).
    """
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        existing = {c.name for c in client.get_collections().collections}

        for coll in (_collection(), _jobs_collection()):
            if coll not in existing:
                client.create_collection(
                    collection_name=coll,
                    vectors_config=VectorParams(
                        size=VECTOR_SIZE, distance=Distance.COSINE
                    ),
                )
                logger.info(
                    f"[Qdrant] Collection '{coll}' created (dim={VECTOR_SIZE}, cosine)."
                )
            else:
                logger.info(f"[Qdrant] Collection '{coll}' already exists.")
    except Exception as e:
        logger.warning(
            f"[Qdrant] init_qdrant_collection failed: {e} — semantic search will be unavailable."
        )


# ---------------------------------------------------------------------------
# Voyage AI — embedding generation
# ---------------------------------------------------------------------------


async def generate_embedding(text: str) -> Optional[list[float]]:
    """
    Generate a 1024-dim embedding for *text* using Voyage AI voyage-3.
    Returns None on error so callers can fall back to text search.
    """
    if not settings.VOYAGE_API_KEY:
        logger.warning("[Voyage] VOYAGE_API_KEY not set — cannot generate embeddings.")
        return None

    if not text or not text.strip():
        logger.warning("[Voyage] Empty text passed to generate_embedding.")
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                VOYAGE_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.VOYAGE_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "voyage-3",
                    "input": [text],
                    "input_type": "document",
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]
    except httpx.HTTPStatusError as e:
        logger.error(
            f"[Voyage] HTTP error: {e.response.status_code} — {e.response.text[:200]}"
        )
        return None
    except Exception as e:
        logger.error(f"[Voyage] Unexpected error: {e}")
        return None


# ---------------------------------------------------------------------------
# Candidate embedding — store in Qdrant
# ---------------------------------------------------------------------------


def _build_candidate_text(candidate) -> str:
    """Build a rich text blob from candidate fields for embedding."""
    parts: list[str] = []

    if candidate.name:
        parts.append(candidate.name)
    if candidate.lastname:
        parts.append(candidate.lastname)
    if candidate.competence_category:
        parts.append(candidate.competence_category)

    # Seniority hint from structured years_it_experience
    years = getattr(candidate, "years_it_experience", None)
    if years is not None:
        if years >= 7:
            parts.append("senior experienced engineer")
        elif years >= 3:
            parts.append("mid-level developer")
        else:
            parts.append("junior entry-level developer")

    # Skills
    if candidate.skills:
        skills = candidate.skills
        if isinstance(skills, list):
            for s in skills:
                if isinstance(s, dict):
                    parts.append(s.get("name", ""))
                elif isinstance(s, str):
                    parts.append(s)
        elif isinstance(skills, str):
            parts.append(skills)

    # Verified tech (Phase 1 — structured list of confirmed technologies)
    verified_tech = getattr(candidate, "verified_tech", None)
    if verified_tech:
        if isinstance(verified_tech, list):
            for t in verified_tech:
                if isinstance(t, dict):
                    parts.append(t.get("name", ""))
                elif isinstance(t, str):
                    parts.append(t)

    # Experience
    if candidate.experience:
        exp = candidate.experience
        if isinstance(exp, list):
            for e in exp:
                if isinstance(e, dict):
                    parts.append(e.get("role", ""))
                    parts.append(e.get("company", ""))
                    parts.append(e.get("desc", ""))
        elif isinstance(exp, str):
            parts.append(exp)

    # Tags
    if candidate.tags:
        tags = candidate.tags
        if isinstance(tags, list):
            parts.extend([str(t) for t in tags])
        elif isinstance(tags, str):
            parts.append(tags)

    # Preferences — industries help matching engine
    prefs = getattr(candidate, "preferences", None)
    if prefs and isinstance(prefs, dict):
        industries = prefs.get("industries") or []
        if isinstance(industries, list):
            parts.extend([str(i) for i in industries if i])

    # AI summary
    if candidate.ai_summary:
        parts.append(candidate.ai_summary)

    # Raw CV (truncated to avoid token blowup)
    if candidate.raw_cv_text:
        parts.append(candidate.raw_cv_text[:3000])

    return " ".join(p for p in parts if p and p.strip())


async def embed_candidate(candidate_id: int, db: AsyncSession) -> bool:
    """
    Generate an embedding for a candidate and upsert it into Qdrant.
    Returns True on success, False on failure.
    """
    from app.models.candidate import Candidate

    try:
        result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
        candidate = result.scalar_one_or_none()
        if not candidate:
            logger.warning(f"[Embed] Candidate {candidate_id} not found.")
            return False

        text = _build_candidate_text(candidate)
        if not text.strip():
            logger.warning(f"[Embed] Candidate {candidate_id} has no text to embed.")
            return False

        embedding = await generate_embedding(text)
        if embedding is None:
            return False

        # Upsert into Qdrant
        def _upsert():
            from qdrant_client import QdrantClient
            from qdrant_client.models import PointStruct

            client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
            client.upsert(
                collection_name=_collection(),
                points=[
                    PointStruct(
                        id=candidate_id,
                        vector=embedding,
                        payload={
                            "candidate_id": candidate_id,
                            "name": f"{candidate.name} {candidate.lastname}",
                            "competence_category": candidate.competence_category or "",
                        },
                    )
                ],
            )

        await asyncio.to_thread(_upsert)

        # Update embedding_id on the candidate record
        candidate.embedding_id = str(candidate_id)
        await db.commit()

        logger.info(f"[Embed] Candidate {candidate_id} embedded and stored in Qdrant.")
        return True

    except Exception as e:
        logger.error(f"[Embed] Failed to embed candidate {candidate_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------


async def search_candidates_semantic(
    query: str,
    top_k: int = 20,
) -> list[dict]:
    """
    Embed *query* and search the Qdrant collection for the closest candidates.
    Returns a list of dicts: [{candidate_id, score}].
    """
    embedding = await generate_embedding(query)
    if embedding is None:
        logger.warning(
            "[Search] Could not generate query embedding — returning empty results."
        )
        return []

    def _search():
        from qdrant_client import QdrantClient

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        hits = client.search(
            collection_name=_collection(),
            query_vector=embedding,
            limit=top_k,
            with_payload=True,
        )
        return [
            {
                "candidate_id": int(hit.id),
                "score": round(float(hit.score), 4),
                "payload": hit.payload or {},
            }
            for hit in hits
        ]

    try:
        return await asyncio.to_thread(_search)
    except Exception as e:
        logger.error(f"[Search] Qdrant search error: {e}")
        return []


# ---------------------------------------------------------------------------
# Phase 2: Job embedding (reverse matching)
# ---------------------------------------------------------------------------


def _build_job_text(job) -> str:
    """Build a rich text blob from job fields for embedding."""
    parts: list[str] = []

    if job.title:
        parts.append(job.title)
    if job.description:
        parts.append(job.description[:1200])
    if job.requirements:
        parts.append(job.requirements[:1200])

    # Structured fields (Phase 1)
    if getattr(job, "seniority", None):
        parts.append(f"{job.seniority.value} level")
    if getattr(job, "subcategory", None):
        parts.append(job.subcategory)
    if getattr(job, "industry", None):
        parts.append(f"branża {job.industry}")

    # Must / nice skills names
    for bucket_name, bucket in (("must", job.must_skills), ("nice", job.nice_skills)):
        if bucket and isinstance(bucket, list):
            for item in bucket:
                if isinstance(item, dict) and item.get("name"):
                    parts.append(item["name"])
                elif isinstance(item, str):
                    parts.append(item)

    return " ".join(p for p in parts if p and p.strip())


async def embed_job(job_id: int, db: AsyncSession) -> bool:
    """
    Generate a vector embedding for *job_id* and upsert it into the nexus_jobs
    collection. Sets jobs.embedding_id = str(job_id).
    Non-blocking: returns False on any failure, logs at WARNING.
    """
    from app.models.job import Job

    try:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            logger.warning(f"[Embed] Job {job_id} not found.")
            return False

        text = _build_job_text(job)
        if not text.strip():
            logger.warning(f"[Embed] Job {job_id} has no text to embed.")
            return False

        embedding = await generate_embedding(text)
        if embedding is None:
            return False

        def _upsert():
            from qdrant_client import QdrantClient
            from qdrant_client.models import PointStruct

            client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
            client.upsert(
                collection_name=_jobs_collection(),
                points=[
                    PointStruct(
                        id=job_id,
                        vector=embedding,
                        payload={
                            "job_id": job_id,
                            "title": job.title or "",
                            "client_id": job.client_id,
                            "industry": job.industry or "",
                        },
                    )
                ],
            )

        await asyncio.to_thread(_upsert)

        job.embedding_id = str(job_id)
        await db.commit()

        logger.info(f"[Embed] Job {job_id} embedded and stored in Qdrant.")
        return True

    except Exception as e:
        logger.error(f"[Embed] Failed to embed job {job_id}: {e}")
        return False


async def search_jobs_semantic(query: str, top_k: int = 20) -> list[dict]:
    """Embed *query* and return top-k closest job ids from nexus_jobs."""
    embedding = await generate_embedding(query)
    if embedding is None:
        return []

    def _search():
        from qdrant_client import QdrantClient

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        hits = client.search(
            collection_name=_jobs_collection(),
            query_vector=embedding,
            limit=top_k,
            with_payload=True,
        )
        return [
            {
                "job_id": int(hit.id),
                "score": round(float(hit.score), 4),
                "payload": hit.payload or {},
            }
            for hit in hits
        ]

    try:
        return await asyncio.to_thread(_search)
    except Exception as e:
        logger.error(f"[Search] Qdrant jobs search error: {e}")
        return []
