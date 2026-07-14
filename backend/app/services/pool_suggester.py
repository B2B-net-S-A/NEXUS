"""Suggest talent pools for a candidate using semantic centroid similarity.

Flow:
1. Upewnij się, że kandydat ma embedding w Qdrant (`nexus_candidates`).
2. Dla każdej puli z `centroid_vector_id` — pobierz cosine similarity.
3. Bucketuj: ≥0.82 → auto-add (jeśli jeszcze nie członek), 0.65–0.82 → suggest,
   <0.65 → ignore.

Używane przez:
- `GET /api/candidates/{id}/suggested-pools` (UI sidebar)
- Background task `cc_centroid_sync` (auto-add wysokich confidence)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.talent_pool import TalentPool, TalentPoolMembership
from app.services.cc_centroid_service import POOL_CENTROIDS_COLLECTION
from app.services.embedding_service import candidate_collection_name

logger = logging.getLogger(__name__)

AUTO_THRESHOLD = 0.82
SUGGEST_THRESHOLD = 0.65


@dataclass(frozen=True)
class PoolSuggestion:
    pool_id: int
    pool_name: str
    score: float
    band: str  # "auto" | "suggest"
    already_member: bool

    def to_dict(self) -> dict:
        return {
            "pool_id": self.pool_id,
            "pool_name": self.pool_name,
            "score": self.score,
            "band": self.band,
            "already_member": self.already_member,
        }


def _fetch_candidate_vector_sync(candidate_id: int) -> Optional[list[float]]:
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        points = client.retrieve(
            collection_name=candidate_collection_name(),
            ids=[candidate_id],
            with_vectors=True,
        )
    except Exception as e:
        logger.debug("[PoolSuggest] retrieve candidate vector failed: %s", e)
        return None
    if not points:
        return None
    v = getattr(points[0], "vector", None)
    if isinstance(v, dict):
        v = next(iter(v.values()), None)
    return list(v) if v else None


def _search_pool_centroids_sync(
    vector: list[float], limit: int = 20
) -> dict[int, float]:
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        hits = client.search(
            collection_name=POOL_CENTROIDS_COLLECTION,
            query_vector=vector,
            limit=limit,
            with_payload=False,
        )
    except Exception as e:
        logger.debug("[PoolSuggest] centroid search failed: %s", e)
        return {}
    return {int(h.id): round(float(h.score), 4) for h in hits}


async def suggest_pools_for_candidate(
    db: AsyncSession,
    candidate_id: int,
    *,
    viewer_id: int | None = None,
    viewer_is_admin: bool = False,
) -> list[PoolSuggestion]:
    """Return pool suggestions for a candidate sorted by score descending.

    Empty list if the candidate has no embedding yet (not embedded or Qdrant
    unavailable). Membership info is attached so the UI can grey-out existing
    memberships while still showing confidence.

    Pule osobiste (migracja 0137) podpowiadamy WYŁĄCZNIE ich właścicielowi
    (``viewer_id``) lub adminowi (``viewer_is_admin``). Inaczej widget „Sugerowane
    pule" proponowałby „Dodaj" do cudzej puli osobistej, a POST /add zwróciłby
    403 (gate ``_assert_can_modify_pool``) — cichy, mylący błąd dla usera.
    """
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if not candidate:
        return []

    vector = await asyncio.to_thread(_fetch_candidate_vector_sync, candidate_id)
    if vector is None:
        return []

    scores = await asyncio.to_thread(_search_pool_centroids_sync, vector)
    if not scores:
        return []

    # Load pools + current memberships for the candidate
    pool_result = await db.execute(
        select(TalentPool).where(TalentPool.id.in_(list(scores.keys())))
    )
    pools = {p.id: p for p in pool_result.scalars().all()}

    mem_result = await db.execute(
        select(TalentPoolMembership.talent_pool_id).where(
            TalentPoolMembership.candidate_id == candidate_id
        )
    )
    existing_memberships = {row[0] for row in mem_result.all()}

    suggestions: list[PoolSuggestion] = []
    for pool_id, score in scores.items():
        if score < SUGGEST_THRESHOLD:
            continue
        pool = pools.get(pool_id)
        if not pool:
            continue
        # Skip cudze pule osobiste — usera nie wolno zachęcać do dodania
        # kandydata do puli, której i tak nie może modyfikować (→ 403).
        if pool.is_personal and not viewer_is_admin and pool.created_by != viewer_id:
            continue
        band = "auto" if score >= AUTO_THRESHOLD else "suggest"
        suggestions.append(
            PoolSuggestion(
                pool_id=pool.id,
                pool_name=pool.name,
                score=score,
                band=band,
                already_member=pool.id in existing_memberships,
            )
        )
    suggestions.sort(key=lambda s: s.score, reverse=True)
    return suggestions
