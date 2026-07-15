"""Single Qdrant client factory and logical collection names.

All production consumers go through this module so URL/API-key handling and
collection routing cannot drift between services.  Physical collection
cutovers remain configuration-driven until the blue/green migration in PR 5.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.core.config import settings

CANDIDATES_ALIAS = "nexus_candidates_active"
JOBS_ALIAS = "nexus_jobs_active"
CC_CENTROIDS_ALIAS = "nexus_cc_centroids_active"
POOL_CENTROIDS_ALIAS = "nexus_pool_centroids_active"


@dataclass(frozen=True)
class VectorSpace:
    provider: str
    model: str
    dimension: int
    text_schema: str

    def collection(self, entity: str) -> str:
        safe_entity = re.sub(r"[^a-z0-9]+", "_", entity.lower()).strip("_")
        safe_provider = re.sub(r"[^a-z0-9]+", "_", self.provider.lower()).strip("_")
        safe_model = re.sub(r"[^a-z0-9]+", "_", self.model.lower()).strip("_")
        safe_schema = re.sub(r"[^a-z0-9]+", "_", self.text_schema.lower()).strip("_")
        identity = (
            safe_model
            if safe_model.startswith(f"{safe_provider}_")
            else f"{safe_provider}_{safe_model}"
        )
        return f"nexus_{safe_entity}_{identity}_{self.dimension}_{safe_schema}"


VOYAGE4_TEXT_V2 = VectorSpace(
    provider="voyage",
    model="voyage-4-large",
    dimension=1024,
    text_schema="text_v2",
)

ACTIVE_ALIASES: dict[str, str] = {
    "candidates": CANDIDATES_ALIAS,
    "jobs": JOBS_ALIAS,
    "cc_centroids": CC_CENTROIDS_ALIAS,
    "pool_centroids": POOL_CENTROIDS_ALIAS,
}


def physical_collections(space: VectorSpace = VOYAGE4_TEXT_V2) -> dict[str, str]:
    return {entity: space.collection(entity) for entity in ACTIVE_ALIASES}


def get_qdrant_client(*, timeout: float = 10.0):
    """Build the configured synchronous Qdrant client.

    ``QDRANT_URL`` supports managed/HTTPS Qdrant.  Host+port remains the
    backwards-compatible path for the current Coolify service.
    """
    from qdrant_client import QdrantClient

    common = {
        "api_key": settings.QDRANT_API_KEY or None,
        "timeout": timeout,
    }
    if settings.QDRANT_URL:
        return QdrantClient(url=settings.QDRANT_URL, **common)
    return QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        **common,
    )


def cc_centroids_collection_name() -> str:
    return settings.QDRANT_CC_CENTROIDS_COLLECTION


def pool_centroids_collection_name() -> str:
    return settings.QDRANT_POOL_CENTROIDS_COLLECTION
