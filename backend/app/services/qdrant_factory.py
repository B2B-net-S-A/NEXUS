"""Single Qdrant client factory and logical collection names.

All production consumers go through this module so URL/API-key handling and
collection routing cannot drift between services.  Physical collection
cutovers remain configuration-driven until the blue/green migration in PR 5.
"""

from __future__ import annotations

from app.core.config import settings

CANDIDATES_ALIAS = "nexus_candidates_active"
JOBS_ALIAS = "nexus_jobs_active"
CC_CENTROIDS_ALIAS = "nexus_cc_centroids_active"
POOL_CENTROIDS_ALIAS = "nexus_pool_centroids_active"


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
