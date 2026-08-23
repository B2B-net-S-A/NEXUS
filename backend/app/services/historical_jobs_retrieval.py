"""Retrieval of similar historical jobs for Champion Profile pre-fill (Phase 15).

Flow
----
1. Embed ad-hoc `title + raw_description` via Voyage (no Qdrant upsert, no DB
   write) so we can serve both saved and unsaved jobs from the same path.
2. Query Qdrant collection `nexus_jobs` with an optional `client_id` filter
   (same-client preferred by default).
3. Re-check in Postgres that each hit is `status=closed` AND has a populated
   `champion_profile` — Qdrant payload only carries {job_id, title, client_id,
   industry}, so status/profile checks must come from the source of truth.
4. Compute per-skill frequency across the filtered matches; DL sees which
   skills "consistently" show up (default threshold ≥0.6).

The service is intentionally decoupled from the draft service: it returns
plain dataclasses so callers can either render a preview panel (no LLM) or
feed the matches into a prompt template.

Design
------
- Pure functions, no class state.
- Qdrant calls wrapped in `asyncio.to_thread` (qdrant_client is sync).
- Cosine-similarity score flows through untouched (0..1 in nexus_jobs cosine).
- `cross_client=True` drops the client filter entirely — intended for an
  opt-in toggle in the UI.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.services.embedding_service import (
    VECTOR_SIZE,
    _jobs_collection,
    generate_embedding,
)

logger = logging.getLogger(__name__)


# ── Tunables ─────────────────────────────────────────────────────────────────

MIN_MATCHES_FOR_GENERATION: int = 2
CONSISTENT_SKILL_THRESHOLD: float = 0.6
QDRANT_OVERSAMPLE_FACTOR: int = 4  # fetch top_k*4 then SQL-filter


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HistoricalJobMatch:
    """One historical closed job with enough context to pre-fill a profile."""

    job_id: int
    title: str
    similarity: float
    closed_at: Optional[datetime]
    client_id: Optional[int]
    client_name: Optional[str]
    champion_profile: dict
    must_skills: list[dict]
    nice_skills: list[dict]
    seniority: Optional[str] = None
    # Phase 15 / Phase D: programme tag of the historical job. Used to mark
    # `same_train` relative to the current role's train_name.
    train_name: Optional[str] = None
    same_train: bool = False


# ── Public API ───────────────────────────────────────────────────────────────


async def find_similar_historical_jobs(
    db: AsyncSession,
    *,
    client_id: Optional[int],
    title: str,
    raw_description: Optional[str] = None,
    train_name: Optional[str] = None,
    top_k: int = 5,
    cross_client: bool = False,
    exclude_job_id: Optional[int] = None,
) -> Optional[list[HistoricalJobMatch]]:
    """Find closed jobs with populated champion_profile most similar to the
    given title + description.

    Args:
        db: Async DB session.
        client_id: When set and `cross_client=False`, Qdrant filters results
            to only this client. Ignored when `cross_client=True`.
        title: Role title — cheap but high-signal embedding input.
        raw_description: Optional JD text. Concatenated to title for the
            embedding query.
        top_k: Max number of matches to return after SQL post-filter.
        cross_client: When True, drops the client filter and returns matches
            from any client.
        exclude_job_id: Job id to exclude (e.g. when called for a saved job
            that is NOT yet closed — we don't want it matching itself).

    Returns:
        Lista HistoricalJobMatch (0..top_k, malejąco po podobieństwie) albo
        ``None``.

        ``None`` znaczy „NIE WIEM" — padł provider embeddingów albo Qdrant.
        ``[]`` znaczy „WIEM, ŻE NIE MA" — wyszukiwanie odpowiedziało, a u tego
        klienta nie ma domkniętych, podobnych rekrutacji z Championem.

        Do sierpnia 2026 obie sytuacje zwracały pustą listę i wołający nie miał
        jak ich odróżnić. Skutek był trwały: `generate_from_historical_jobs`
        kasował gotową propozycję `pending` i zapisywał do bazy komunikat
        „znaleziono 0, wymagane co najmniej 2" — pewne siebie twierdzenie
        o danych klienta, podczas gdy leżała infrastruktura. Delivery Lead
        czytał to jako fakt i przestawał próbować.

        Wołający MUSI rozróżniać `is None` od pustej listy; samo `if not
        matches:` skleja oba stany z powrotem.
    """
    query_text = _build_query_text(title=title, raw_description=raw_description)
    if not query_text:
        return []

    embedding = await generate_embedding(query_text)
    if embedding is None or len(embedding) != VECTOR_SIZE:
        logger.warning(
            "[historical] embedding unavailable (text_len=%d)", len(query_text)
        )
        return None

    qdrant_limit = max(top_k * QDRANT_OVERSAMPLE_FACTOR, top_k)
    filter_client_id = None if cross_client else client_id
    hits = await asyncio.to_thread(
        _qdrant_search, embedding, filter_client_id, qdrant_limit
    )
    if hits is None:
        return None
    if not hits:
        return []

    # Drop self before SQL round-trip
    if exclude_job_id is not None:
        hits = [h for h in hits if h["job_id"] != exclude_job_id]
    if not hits:
        return []

    ordered_ids = [h["job_id"] for h in hits]
    similarity_by_id = {h["job_id"]: h["score"] for h in hits}

    stmt = (
        select(Job, Client.name)
        .join(Client, Job.client_id == Client.id, isouter=True)
        .where(
            Job.id.in_(ordered_ids),
            Job.status == JobStatus.closed,
            Job.champion_profile.isnot(None),
            Job.champion_profile != {},
        )
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    target_train = train_name.strip().lower() if train_name else None

    matches: list[HistoricalJobMatch] = []
    for job, client_name in rows:
        similarity = similarity_by_id.get(job.id, 0.0)
        job_train = getattr(job, "train_name", None)
        same_train = bool(
            target_train and job_train and job_train.strip().lower() == target_train
        )
        matches.append(
            HistoricalJobMatch(
                job_id=job.id,
                title=job.title or f"Job {job.id}",
                similarity=similarity,
                closed_at=job.closed_at,
                client_id=job.client_id,
                client_name=client_name,
                champion_profile=dict(job.champion_profile or {}),
                must_skills=list(job.must_skills or []),
                nice_skills=list(job.nice_skills or []),
                seniority=(job.seniority.value if job.seniority else None),
                train_name=job_train,
                same_train=same_train,
            )
        )

    # Primary sort: similarity. Same-train hits get a small deterministic
    # boost so they float above near-ties but don't override hard-better
    # semantic matches.
    matches.sort(
        key=lambda m: (
            m.similarity + (0.05 if m.same_train else 0.0),
            1 if m.same_train else 0,
        ),
        reverse=True,
    )
    return matches[:top_k]


def skill_frequency(
    matches: list[HistoricalJobMatch],
    *,
    threshold: float = CONSISTENT_SKILL_THRESHOLD,
) -> dict[str, Any]:
    """Compute how often each skill appears across a set of matches.

    Returns:
        {
          "n": <int>,                    # sample size
          "must": [{"name","fraction","count"}],
          "nice": [{"name","fraction","count"}],
          "consistent_must": [<name>, ...],  # fraction >= threshold
          "consistent_nice": [<name>, ...],
          "threshold": <float>,
        }

    Names are canonicalised by `.strip().lower()` — anything finer-grained
    (synonyms, aliases) is intentionally deferred; the existing skill taxonomy
    in Job.must_skills/nice_skills is treated as source-of-truth.
    """
    n = len(matches)
    if n == 0:
        return {
            "n": 0,
            "must": [],
            "nice": [],
            "consistent_must": [],
            "consistent_nice": [],
            "threshold": threshold,
        }

    def _aggregate(bucket_name: str) -> list[dict[str, Any]]:
        counts: Counter[str] = Counter()
        display_by_key: dict[str, str] = {}
        for match in matches:
            seen_in_match: set[str] = set()
            bucket = getattr(match, bucket_name) or []
            for item in bucket:
                name = _extract_skill_name(item)
                if not name:
                    continue
                key = name.strip().lower()
                if not key or key in seen_in_match:
                    continue
                seen_in_match.add(key)
                counts[key] += 1
                display_by_key.setdefault(key, name.strip())

        aggregated: list[dict[str, Any]] = []
        for key, count in counts.most_common():
            aggregated.append(
                {
                    "name": display_by_key.get(key, key),
                    "count": count,
                    "fraction": round(count / n, 3),
                }
            )
        return aggregated

    must_agg = _aggregate("must_skills")
    nice_agg = _aggregate("nice_skills")

    return {
        "n": n,
        "must": must_agg,
        "nice": nice_agg,
        "consistent_must": [
            entry["name"] for entry in must_agg if entry["fraction"] >= threshold
        ],
        "consistent_nice": [
            entry["name"] for entry in nice_agg if entry["fraction"] >= threshold
        ],
        "threshold": threshold,
    }


# ── Internals ────────────────────────────────────────────────────────────────


def _build_query_text(*, title: str, raw_description: Optional[str]) -> str:
    """Build the text blob we embed for semantic search.

    Mirrors `_build_job_text` in embedding_service.py at a minimum — title
    carries the biggest signal for role similarity, description fills in the
    technical context. Kept short (~1200 char cap on description) to match
    what was used when the historical jobs were indexed.
    """
    parts: list[str] = []
    if title:
        parts.append(title.strip())
    if raw_description:
        parts.append(raw_description.strip()[:1200])
    return " ".join(p for p in parts if p).strip()


def _extract_skill_name(item: Any) -> Optional[str]:
    """Pull a name out of whatever shape `must_skills`/`nice_skills` holds.

    The schema is nominally `list[{"name", "level", "years", "category"}]`
    but legacy rows and the `default=list` in the JSONB column mean we may
    also see plain strings or dicts without 'name'. Be forgiving.
    """
    if isinstance(item, dict):
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            return name
        return None
    if isinstance(item, str) and item.strip():
        return item
    return None


def _qdrant_search(
    embedding: list[float], client_id: Optional[int], limit: int
) -> Optional[list[dict[str, Any]]]:
    """Synchronous Qdrant search with optional client_id filter.

    Runs inside `asyncio.to_thread` from the async caller.

    ``list`` — Qdrant odpowiedział; `{job_id, score, payload}` malejąco po
    podobieństwie (pusta lista = odpowiedział i nic nie ma).
    ``None`` — Qdrant NIE odpowiedział.

    Do sierpnia 2026 awaria też zwracała `[]` („Swallows all Qdrant errors")
    i wołający nie miał jak jej odróżnić od uczciwego zera. Skutek opisany
    w `find_similar_historical_jobs`: kasowanie gotowej propozycji i zapis do
    bazy twierdzenia o danych klienta w trakcie awarii infrastruktury.
    """
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        query_filter: Optional[Filter] = None
        if client_id is not None:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="client_id", match=MatchValue(value=int(client_id))
                    )
                ]
            )

        hits = client.search(
            collection_name=_jobs_collection(),
            query_vector=embedding,
            query_filter=query_filter,
            limit=limit,
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
    except Exception as exc:  # noqa: BLE001
        # `None`, nie `[]`. Pusta lista znaczy „Qdrant odpowiedział i nic nie
        # ma"; awaria to zupełnie inna informacja i sklejenie ich sprawiało, że
        # wołający zapisywał do bazy twierdzenie o DANYCH KLIENTA w sytuacji,
        # gdy przyczyną była infrastruktura.
        logger.warning("[historical] Qdrant search failed: %s", exc)
        return None
