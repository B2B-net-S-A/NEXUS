"""Centroid computation for CompetenceCategory and TalentPool.

Centroid = średnia embeddingów kandydatów przypisanych do danej CC / puli.
Używany przez `cc_classifier` i `pool_suggester` jako porównanie semantyczne.

Strategia odświeżania:
- CC centroid: 1× przy starcie serwisu (bootstrap) + ręcznie po dużych
  zmianach taxonomii (rzadkie). Re-compute raz na 7 dni via cron (idle).
- Pool centroid: lazy — invalidujemy (`centroid_updated_at = NULL`) na
  każde dodanie/usunięcie członka w `pool_suggester`; kolejne wywołanie
  recomputes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.competence_category import (
    CandidateCompetenceCategory,
    CompetenceCategory,
)
from app.models.talent_pool import TalentPool, TalentPoolMembership
from app.services.cc_classifier import CC_CENTROIDS_COLLECTION
from app.services.embedding_service import candidate_collection_name

logger = logging.getLogger(__name__)

POOL_CENTROIDS_COLLECTION = "nexus_pool_centroids"
VECTOR_SIZE = 1024


def _ensure_centroid_collections() -> None:
    """Create CC/pool centroid Qdrant collections if missing."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        existing = {c.name for c in client.get_collections().collections}
        for coll in (CC_CENTROIDS_COLLECTION, POOL_CENTROIDS_COLLECTION):
            if coll not in existing:
                client.create_collection(
                    collection_name=coll,
                    vectors_config=VectorParams(
                        size=VECTOR_SIZE, distance=Distance.COSINE
                    ),
                )
                logger.info("[Centroid] collection '%s' created.", coll)
    except Exception as e:
        logger.warning("[Centroid] ensure collections failed: %s", e)


def _retrieve_vectors_sync(collection: str, ids: list[int]) -> list[list[float]]:
    """Retrieve embedding vectors from Qdrant in batch. Missing ids are skipped."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        points = client.retrieve(collection_name=collection, ids=ids, with_vectors=True)
    except Exception as e:
        logger.warning("[Centroid] retrieve failed (%s): %s", collection, e)
        return []
    vectors: list[list[float]] = []
    for p in points:
        v = getattr(p, "vector", None)
        if isinstance(v, dict):
            v = next(iter(v.values()), None)
        if v and len(v) == VECTOR_SIZE:
            vectors.append(list(v))
    return vectors


def _mean_vector(vectors: list[list[float]]) -> Optional[list[float]]:
    """Compute element-wise average (vectors expected same dim)."""
    if not vectors:
        return None
    dim = len(vectors[0])
    out = [0.0] * dim
    for v in vectors:
        for i, x in enumerate(v):
            out[i] += x
    return [x / len(vectors) for x in out]


def _upsert_centroid_sync(collection: str, point_id: int, vector: list[float]) -> None:
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct

    client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    client.upsert(
        collection_name=collection,
        points=[PointStruct(id=point_id, vector=vector, payload={})],
    )


async def _bootstrap_cc_from_keywords(cc: CompetenceCategory) -> Optional[list[float]]:
    """Fallback: embed CC name + description + keywords when no members yet."""
    from app.services.embedding_service import generate_embedding

    text_parts = [cc.name_pl, cc.name_en, cc.description or ""]
    text_parts.extend(cc.keywords or [])
    text = " ".join(p for p in text_parts if p)
    return await generate_embedding(text, input_type="document")


async def compute_cc_centroid(db: AsyncSession, cc_id: int) -> bool:
    """Recompute and upsert CC centroid. Returns True on success."""
    cc = await db.scalar(
        select(CompetenceCategory).where(CompetenceCategory.id == cc_id)
    )
    if not cc:
        return False

    # Collect primary-CC candidate ids
    result = await db.execute(
        select(CandidateCompetenceCategory.candidate_id).where(
            CandidateCompetenceCategory.competence_category_id == cc_id,
            CandidateCompetenceCategory.is_primary.is_(True),
        )
    )
    candidate_ids = [row[0] for row in result.all()]

    vector: Optional[list[float]] = None
    if candidate_ids:
        vectors = await asyncio.to_thread(
            _retrieve_vectors_sync, candidate_collection_name(), candidate_ids
        )
        vector = _mean_vector(vectors)

    if vector is None:
        # Fallback: embed name + description + keywords
        vector = await _bootstrap_cc_from_keywords(cc)

    if vector is None:
        logger.warning(
            "[Centroid] CC %s: no vector to upsert (bootstrap failed)", cc.slug
        )
        return False

    await asyncio.to_thread(
        _upsert_centroid_sync, CC_CENTROIDS_COLLECTION, cc.id, vector
    )

    # Mark CC as having embedding (id of point equals cc.id)
    cc.embedding_id = str(cc.id)
    await db.commit()
    logger.info("[Centroid] CC %s (%s) upserted.", cc.id, cc.slug)
    return True


async def compute_pool_centroid(db: AsyncSession, pool_id: int) -> bool:
    """Recompute and upsert pool centroid from member embeddings."""
    pool = await db.scalar(select(TalentPool).where(TalentPool.id == pool_id))
    if not pool:
        return False

    result = await db.execute(
        select(TalentPoolMembership.candidate_id).where(
            TalentPoolMembership.talent_pool_id == pool_id
        )
    )
    candidate_ids = [row[0] for row in result.all()]
    if not candidate_ids:
        logger.info("[Centroid] pool %s has no members — skipping centroid.", pool_id)
        pool.centroid_vector_id = None
        pool.centroid_updated_at = datetime.now(timezone.utc)
        await db.commit()
        return False

    vectors = await asyncio.to_thread(
        _retrieve_vectors_sync, candidate_collection_name(), candidate_ids
    )
    vector = _mean_vector(vectors)
    if vector is None:
        logger.warning(
            "[Centroid] pool %s: no embeddings among %d members",
            pool_id,
            len(candidate_ids),
        )
        return False

    await asyncio.to_thread(
        _upsert_centroid_sync, POOL_CENTROIDS_COLLECTION, pool_id, vector
    )
    pool.centroid_vector_id = str(pool_id)
    pool.centroid_updated_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info(
        "[Centroid] pool %s upserted (%d members).", pool_id, len(candidate_ids)
    )
    return True


async def invalidate_pool_centroid(db: AsyncSession, pool_id: int) -> None:
    """Lazy invalidation: next `compute_pool_centroid` call will refresh it."""
    await db.execute(
        update(TalentPool)
        .where(TalentPool.id == pool_id)
        .values(centroid_updated_at=None)
    )
    await db.commit()


async def refresh_stale_centroids(db: AsyncSession, stale_days: int = 7) -> dict:
    """Refresh all pools+CCs whose centroid is NULL or older than `stale_days`."""
    from datetime import timedelta

    threshold = datetime.now(timezone.utc) - timedelta(days=stale_days)
    stats = {"cc_refreshed": 0, "pools_refreshed": 0}

    # Refresh every CC (5 seed CCs, cheap)
    cc_ids = [row[0] for row in (await db.execute(select(CompetenceCategory.id))).all()]
    for cc_id in cc_ids:
        ok = await compute_cc_centroid(db, cc_id)
        if ok:
            stats["cc_refreshed"] += 1

    # Refresh stale pools
    result = await db.execute(
        select(TalentPool.id).where(
            (TalentPool.centroid_updated_at.is_(None))
            | (TalentPool.centroid_updated_at < threshold)
        )
    )
    pool_ids = [row[0] for row in result.all()]
    for pool_id in pool_ids:
        ok = await compute_pool_centroid(db, pool_id)
        if ok:
            stats["pools_refreshed"] += 1

    return stats
