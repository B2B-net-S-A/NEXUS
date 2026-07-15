"""Voyage Rerank 2.5 — cross-encoder re-ranking on top of Qdrant retrieval.

Industry research consensus (2026): a re-ranker on top of dense retrieval gives
+5-10pp nDCG@10. Voyage Rerank 2.5 is the best balance of accuracy and latency
(~595ms p95 for ~50 documents).

Pipeline:
    1. Qdrant returns top-50 candidates by cosine similarity
    2. Re-ranker scores (query, candidate_text) pairs with a cross-encoder
    3. We return top-K by re-rank score

Feature flag: settings.RERANKER_ENABLED. When false, callers should fall back
to the original Qdrant order — `rerank()` itself is short-circuited via the
flag in callers (this module does not gate; it always tries when called).
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

import httpx

from app.core.config import settings
from app.services.ai_health import AiCallTimer

logger = logging.getLogger(__name__)

VOYAGE_RERANK_URL = "https://api.voyageai.com/v1/rerank"
DEFAULT_TIMEOUT_S = 30.0


def _rerank_model() -> str:
    return getattr(settings, "VOYAGE_RERANK_MODEL", None) or "rerank-2.5"


async def rerank(
    query: str,
    documents: Sequence[str],
    *,
    top_k: Optional[int] = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> Optional[list[tuple[int, float]]]:
    """Re-rank documents against a query using Voyage Rerank 2.5.

    Returns a list of `(orig_index, relevance_score)` tuples sorted by score
    descending, capped at `top_k` if provided. Indices refer to positions in
    the input `documents` sequence.

    Returns None on failure (caller should fall back to the input order). Empty
    input returns an empty list (not an error).
    """
    if not query or not query.strip():
        return []
    if not documents:
        return []
    if not settings.VOYAGE_API_KEY:
        logger.debug("[rerank] VOYAGE_API_KEY missing — skipping")
        return None

    docs = [d if d and d.strip() else " " for d in documents]
    payload: dict = {
        "query": query,
        "documents": list(docs),
        "model": _rerank_model(),
        "truncation": True,
    }
    if top_k is not None:
        payload["top_k"] = int(top_k)

    with AiCallTimer() as timer:
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(
                    VOYAGE_RERANK_URL,
                    headers={
                        "Authorization": f"Bearer {settings.VOYAGE_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json().get("data") or []
        except httpx.HTTPStatusError as e:
            timer.failed = True
            logger.warning(
                "[rerank] HTTP %s — %s",
                e.response.status_code,
                e.response.text[:200],
            )
            return None
        except Exception as e:  # noqa: BLE001 — surface any error, keep retrieval working
            timer.failed = True
            logger.warning("[rerank] error: %s", e)
            return None

    # Voyage returns: [{"index": <int>, "relevance_score": <float>, ...}, ...]
    # already sorted desc by relevance_score.
    pairs: list[tuple[int, float]] = []
    for item in data:
        try:
            idx = int(item["index"])
            score = float(item["relevance_score"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= idx < len(docs):
            pairs.append((idx, score))
    return pairs


async def rerank_or_passthrough(
    query: str,
    documents: Sequence[str],
    *,
    top_k: Optional[int] = None,
) -> list[tuple[int, float]]:
    """Convenience wrapper: returns reranked pairs if RERANKER_ENABLED and the
    API call succeeds, otherwise the original order with score=1.0.

    Always returns a non-None list so callers don't need to special-case.
    """
    if not getattr(settings, "RERANKER_ENABLED", False):
        return [(i, 1.0) for i in range(len(documents))][: top_k or len(documents)]

    pairs = await rerank(query, documents, top_k=top_k)
    if pairs is None:
        # API call failed — passthrough preserves Qdrant order
        return [(i, 1.0) for i in range(len(documents))][: top_k or len(documents)]
    return pairs
