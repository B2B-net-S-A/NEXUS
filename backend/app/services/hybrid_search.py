"""Hybrid retrieval: BM25 (Postgres FTS) + dense (Voyage/Qdrant) + RRF fusion.

Research benchmark (2026): hybrid hits 91% recall@10 vs dense-only 78% / BM25-only
65%. We fuse with Reciprocal Rank Fusion (k=60), the de-facto standard for
ensembling retrievers with mismatched score scales.

Pipeline (jobs → candidates):
    1. BM25 over `candidates.fts_doc` (top 100)
    2. Dense Qdrant over `nexus_candidates` (top 100)
    3. RRF fusion → ordered list of candidate ids
    4. Voyage Rerank 2.5 on top 100 → top K (when feature flag on)

Same orchestrator works for jobs (CV → matching jobs) — pass a different
table/collection pair via the helpers.

Critical files reused:
- backend/app/api/search.py — already has FTS query helpers for candidates
- backend/app/services/embedding_service.py — search_candidates_semantic /
  search_jobs_semantic
- backend/app/services/reranker_service.py — Voyage Rerank 2.5 wrapper (Item 3)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal, Optional, Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# RRF constant — k=60 from the original RRF paper, robust to outlier ranks.
RRF_K = 60


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]], *, k: int = RRF_K
) -> list[tuple[int, float]]:
    """RRF over multiple ranked lists of doc ids.

    Returns [(doc_id, fused_score), ...] sorted desc. Score is sum of
    1/(k + rank_i) across rankings; ids absent from a list contribute 0.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


async def bm25_candidates(
    db: AsyncSession, query: str, *, limit: int = 100
) -> list[int]:
    """Top-N candidate ids by Postgres ts_rank over `candidates.fts_doc`."""
    if not query or not query.strip():
        return []
    sql = text(
        """
        SELECT id
        FROM candidates
        WHERE fts_doc @@ websearch_to_tsquery('simple', :q)
        ORDER BY ts_rank(fts_doc, websearch_to_tsquery('simple', :q)) DESC,
                 updated_at DESC
        LIMIT :limit
        """
    ).bindparams(bindparam("q", value=query), bindparam("limit", value=limit))
    rows = (await db.execute(sql)).all()
    return [int(r[0]) for r in rows]


async def bm25_jobs(
    db: AsyncSession,
    query: str,
    *,
    limit: int = 100,
    status_filter: Literal["all", "open", "published"] = "all",
) -> list[int]:
    """Top-N job ids by Postgres ts_rank over `jobs.fts_doc`."""
    if not query or not query.strip():
        return []
    status_sql = ""
    if status_filter == "open":
        status_sql = "AND status IN ('draft', 'published')"
    elif status_filter == "published":
        status_sql = "AND status = 'published'"
    sql = text(
        f"""
        SELECT id
        FROM jobs
        WHERE fts_doc @@ websearch_to_tsquery('simple', :q)
          {status_sql}
        ORDER BY ts_rank(fts_doc, websearch_to_tsquery('simple', :q)) DESC,
                 updated_at DESC
        LIMIT :limit
        """
    ).bindparams(bindparam("q", value=query), bindparam("limit", value=limit))
    rows = (await db.execute(sql)).all()
    return [int(r[0]) for r in rows]


async def dense_candidates(query: str, *, limit: int = 100) -> list[int]:
    """Top-N candidate ids from Qdrant dense semantic search."""
    from app.services.embedding_service import search_candidates_semantic

    hits = await search_candidates_semantic(query, top_k=limit)
    return [int(h["candidate_id"]) for h in hits]


async def dense_jobs(query: str, *, limit: int = 100) -> list[int]:
    """Top-N job ids from Qdrant dense semantic search."""
    from app.services.embedding_service import search_jobs_semantic

    hits = await search_jobs_semantic(query, top_k=limit)
    return [int(h["job_id"]) for h in hits]


async def hybrid_candidates(
    db: AsyncSession,
    query: str,
    *,
    pool: int = 100,
    final_top_k: int = 20,
    use_rerank: Optional[bool] = None,
) -> list[tuple[int, Optional[float]]]:
    """Hybrid (BM25 + dense + RRF) candidate retrieval.

    Returns [(candidate_id, score), ...]. When `use_rerank` is True (or None
    and settings.RERANKER_ENABLED is True), the top `pool` after RRF is
    re-ordered by Voyage rerank-2.5 — `score` then becomes the rerank score.
    """
    from app.services.embedding_service import search_candidates_semantic

    bm25_ids, dense_hits = await asyncio.gather(
        bm25_candidates(db, query, limit=pool),
        search_candidates_semantic(query, top_k=pool),
    )
    dense_ids = [int(hit["candidate_id"]) for hit in dense_hits]
    dense_scores = {int(hit["candidate_id"]): float(hit["score"]) for hit in dense_hits}
    fused = reciprocal_rank_fusion([bm25_ids, dense_ids])
    if not fused:
        return []

    cand_ids = [doc_id for doc_id, _ in fused[:pool]]

    # Resolve flag (allow caller override for testing).
    if use_rerank is None:
        from app.core.config import settings  # noqa: PLC0415

        use_rerank = bool(getattr(settings, "RERANKER_ENABLED", False))

    if not use_rerank:
        return [(doc_id, dense_scores.get(doc_id)) for doc_id, _ in fused[:final_top_k]]

    # Rerank: load minimal candidate text, send to cross-encoder.
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.candidate import Candidate  # noqa: PLC0415
    from app.services.embedding_service import _build_candidate_text  # noqa: PLC0415
    from app.services.reranker_service import rerank  # noqa: PLC0415

    rows = (
        (await db.execute(select(Candidate).where(Candidate.id.in_(cand_ids))))
        .scalars()
        .all()
    )
    by_id = {c.id: c for c in rows}
    ordered = [by_id[cid] for cid in cand_ids if cid in by_id]
    docs = [_build_candidate_text(c)[:4000] for c in ordered]
    pairs = await rerank(query, docs, top_k=final_top_k)
    if pairs is None:
        return [
            (candidate.id, dense_scores.get(candidate.id))
            for candidate in ordered[:final_top_k]
        ]

    # Map rerank pairs back to candidate ids.
    return [(ordered[idx].id, float(score)) for idx, score in pairs]


async def hybrid_jobs(
    db: AsyncSession,
    query: str,
    *,
    pool: int = 100,
    final_top_k: int = 20,
    use_rerank: Optional[bool] = None,
) -> list[tuple[int, Optional[float]]]:
    """Hybrid retrieval for jobs (e.g. CV-upload-preview reverse matching)."""
    from app.services.embedding_service import search_jobs_semantic

    bm25_ids, dense_hits = await asyncio.gather(
        bm25_jobs(db, query, limit=pool),
        search_jobs_semantic(query, top_k=pool),
    )
    dense_ids = [int(hit["job_id"]) for hit in dense_hits]
    dense_scores = {int(hit["job_id"]): float(hit["score"]) for hit in dense_hits}
    fused = reciprocal_rank_fusion([bm25_ids, dense_ids])
    if not fused:
        return []

    job_ids = [doc_id for doc_id, _ in fused[:pool]]

    if use_rerank is None:
        from app.core.config import settings  # noqa: PLC0415

        use_rerank = bool(getattr(settings, "RERANKER_ENABLED", False))

    if not use_rerank:
        return [(doc_id, dense_scores.get(doc_id)) for doc_id, _ in fused[:final_top_k]]

    from sqlalchemy import select  # noqa: PLC0415

    from app.models.job import Job  # noqa: PLC0415
    from app.services.embedding_service import _build_job_text  # noqa: PLC0415
    from app.services.reranker_service import rerank  # noqa: PLC0415

    rows = (await db.execute(select(Job).where(Job.id.in_(job_ids)))).scalars().all()
    by_id = {j.id: j for j in rows}
    ordered = [by_id[jid] for jid in job_ids if jid in by_id]
    docs = [_build_job_text(j)[:4000] for j in ordered]
    pairs = await rerank(query, docs, top_k=final_top_k)
    if pairs is None:
        return [(job.id, dense_scores.get(job.id)) for job in ordered[:final_top_k]]
    return [(ordered[idx].id, float(score)) for idx, score in pairs]
