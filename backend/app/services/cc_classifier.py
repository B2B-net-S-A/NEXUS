"""Competence Category classifier — hybrid keyword + embedding scoring.

Architektura:
- Keywords są taniym, stabilnym sygnałem (ILIKE JSONB CompetenceCategory.keywords).
- Embedding cosine similarity (Qdrant `nexus_cc_centroids`) wychwytuje
  semantyczne podobieństwo gdy słownictwo nie pokrywa się 1:1.
- Final score = 0.4 * keyword_ratio + 0.6 * embedding_cosine.
- Tie detection: |score[0] - score[1]| < 0.10 → `tie=True` (UI nie pre-selectuje).

Progi confidence (dla UI badge):
- high:   ≥ 0.65
- medium: 0.40 – 0.65
- low:    < 0.40
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competence_category import CompetenceCategory

logger = logging.getLogger(__name__)

KEYWORD_WEIGHT = 0.4
EMBEDDING_WEIGHT = 0.6
TIE_THRESHOLD = 0.10
HIGH_THRESHOLD = 0.65
MEDIUM_THRESHOLD = 0.40

CC_CENTROIDS_COLLECTION = "nexus_cc_centroids"


@dataclass(frozen=True)
class CcScore:
    cc_id: int
    slug: str
    name_pl: str
    score: float
    keyword_ratio: float
    embedding_score: float
    keywords_matched: list[str]

    @property
    def confidence_band(self) -> str:
        if self.score >= HIGH_THRESHOLD:
            return "high"
        if self.score >= MEDIUM_THRESHOLD:
            return "medium"
        return "low"


def _build_job_corpus(job) -> str:
    """Concat text representation of a job for keyword matching."""
    parts: list[str] = []
    for attr in ("title", "description", "requirements", "subcategory", "industry"):
        val = getattr(job, attr, None)
        if val:
            parts.append(str(val))
    for bucket_name in ("must_skills", "nice_skills"):
        bucket = getattr(job, bucket_name, None) or []
        if isinstance(bucket, list):
            for item in bucket:
                if isinstance(item, dict) and item.get("name"):
                    parts.append(str(item["name"]))
                elif isinstance(item, str):
                    parts.append(item)
    return " ".join(parts).lower()


def _build_candidate_corpus(candidate) -> str:
    parts: list[str] = []
    for attr in ("competence_category", "ai_summary", "raw_cv_text"):
        val = getattr(candidate, attr, None)
        if val:
            parts.append(str(val)[:3000])
    for bucket_name in ("skills", "verified_tech", "tags"):
        bucket = getattr(candidate, bucket_name, None) or []
        if isinstance(bucket, list):
            for item in bucket:
                if isinstance(item, dict) and item.get("name"):
                    parts.append(str(item["name"]))
                elif isinstance(item, str):
                    parts.append(item)
    return " ".join(parts).lower()


def _keyword_score(corpus: str, keywords: list[str]) -> tuple[float, list[str]]:
    """Fraction of CC keywords appearing in `corpus` as whole tokens.

    Uses word-boundary matching so short acronyms like ``po``/``ba`` don't
    falsely match substrings of ``postgresql``/``backend``. Keywords with
    special chars (``ci/cd``, ``c#``, ``.net``, ``node.js``) fall back to
    substring matching because ``\\b`` doesn't work around non-word chars.
    """
    if not keywords or not corpus:
        return 0.0, []
    matched: list[str] = []
    for kw in keywords:
        if not kw:
            continue
        kw_lower = kw.lower().strip()
        # If keyword has non-word chars, word boundaries break — use substring.
        has_non_word = bool(re.search(r"[^\w\s]", kw_lower))
        if has_non_word:
            if kw_lower in corpus:
                matched.append(kw)
        else:
            pattern = r"\b" + re.escape(kw_lower) + r"\b"
            if re.search(pattern, corpus):
                matched.append(kw)
    ratio = len(matched) / len(keywords)
    # Boost: capping non-linear — 10+ matches already = full signal
    boosted = min(1.0, ratio * 2.5 if ratio < 0.4 else ratio + 0.3)
    return boosted, matched


async def _embedding_scores(
    entity_embedding: Optional[list[float]],
) -> dict[int, float]:
    """Return {cc_id: cosine_similarity} from Qdrant nexus_cc_centroids."""
    if entity_embedding is None:
        return {}
    try:
        import asyncio

        from qdrant_client import QdrantClient

        from app.core.config import settings

        def _search() -> dict[int, float]:
            client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
            try:
                hits = client.search(
                    collection_name=CC_CENTROIDS_COLLECTION,
                    query_vector=entity_embedding,
                    limit=10,
                    with_payload=False,
                )
            except Exception as e:
                logger.debug(
                    "[CC classifier] Qdrant search miss (collection may be empty): %s",
                    e,
                )
                return {}
            return {int(h.id): round(float(h.score), 4) for h in hits}

        return await asyncio.to_thread(_search)
    except Exception as e:
        logger.warning("[CC classifier] embedding scoring failed: %s", e)
        return {}


async def _fetch_job_embedding(job_id: int) -> Optional[list[float]]:
    """Read job embedding from Qdrant `nexus_jobs` collection."""
    try:
        import asyncio

        from qdrant_client import QdrantClient

        from app.core.config import settings

        def _retrieve() -> Optional[list[float]]:
            client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
            try:
                points = client.retrieve(
                    collection_name="nexus_jobs",
                    ids=[job_id],
                    with_vectors=True,
                )
            except Exception:
                return None
            if not points:
                return None
            vector = getattr(points[0], "vector", None)
            if isinstance(vector, dict):
                # Named vectors — take first
                vector = next(iter(vector.values()), None)
            return list(vector) if vector else None

        return await asyncio.to_thread(_retrieve)
    except Exception as e:
        logger.debug("[CC classifier] fetch_job_embedding failed: %s", e)
        return None


async def _fetch_candidate_embedding(candidate_id: int) -> Optional[list[float]]:
    try:
        import asyncio

        from qdrant_client import QdrantClient

        from app.core.config import settings

        def _retrieve() -> Optional[list[float]]:
            client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
            try:
                points = client.retrieve(
                    collection_name="nexus_candidates",
                    ids=[candidate_id],
                    with_vectors=True,
                )
            except Exception:
                return None
            if not points:
                return None
            vector = getattr(points[0], "vector", None)
            if isinstance(vector, dict):
                vector = next(iter(vector.values()), None)
            return list(vector) if vector else None

        return await asyncio.to_thread(_retrieve)
    except Exception as e:
        logger.debug("[CC classifier] fetch_candidate_embedding failed: %s", e)
        return None


async def _score_all_ccs(
    db: AsyncSession,
    corpus: str,
    entity_embedding: Optional[list[float]],
) -> list[CcScore]:
    """Hybrid scoring across all active CCs. Returns top-3 sorted desc by score."""
    result = await db.execute(
        select(CompetenceCategory).where(CompetenceCategory.is_active.is_(True))
    )
    ccs = list(result.scalars().all())
    if not ccs:
        return []

    embedding_scores = await _embedding_scores(entity_embedding)

    scored: list[CcScore] = []
    for cc in ccs:
        kw_ratio, matched = _keyword_score(corpus, cc.keywords or [])
        emb_score = embedding_scores.get(cc.id, 0.0)
        final = KEYWORD_WEIGHT * kw_ratio + EMBEDDING_WEIGHT * emb_score
        scored.append(
            CcScore(
                cc_id=cc.id,
                slug=cc.slug,
                name_pl=cc.name_pl,
                score=round(final, 4),
                keyword_ratio=round(kw_ratio, 4),
                embedding_score=round(emb_score, 4),
                keywords_matched=matched[:10],
            )
        )
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:3]


@dataclass(frozen=True)
class ClassifyResult:
    top: Optional[CcScore]
    alternatives: list[CcScore]
    tie: bool


async def classify_job_to_cc(job, db: AsyncSession) -> ClassifyResult:
    """Classify a job into the best-fitting CompetenceCategory.

    Returns top-3 with `tie=True` when the #1-#2 score gap is below the
    tie threshold. Callers should not pre-select in that case.
    """
    corpus = _build_job_corpus(job)
    embedding = await _fetch_job_embedding(job.id) if getattr(job, "id", None) else None
    scored = await _score_all_ccs(db, corpus, embedding)
    if not scored:
        return ClassifyResult(top=None, alternatives=[], tie=False)

    top = scored[0]
    alternatives = scored[1:]
    tie = False
    if len(scored) >= 2:
        tie = abs(scored[0].score - scored[1].score) < TIE_THRESHOLD
    return ClassifyResult(top=top, alternatives=alternatives, tie=tie)


async def classify_candidate_to_cc(candidate, db: AsyncSession) -> list[CcScore]:
    """Classify a candidate into up to 3 CCs (≥0.60 threshold).

    Returns scored list sorted desc. Caller decides which scores promote to
    `ai_auto` vs `ai_suggested` based on confidence thresholds (0.80 / 0.60).
    """
    corpus = _build_candidate_corpus(candidate)
    embedding = (
        await _fetch_candidate_embedding(candidate.id)
        if getattr(candidate, "id", None)
        else None
    )
    scored = await _score_all_ccs(db, corpus, embedding)
    return [s for s in scored if s.score >= 0.30]  # cut very weak signals
