"""Exact, bounded vector measurement for every ID in a SQL population batch."""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from collections import OrderedDict
from dataclasses import dataclass

from app.services import embedding_service as embeddings


# Process-local and bounded: retain vectors, never plaintext requests or fit.
# Candidate/index/eligibility changes are still checked on every measurement.
_QUERY_CACHE_LIMIT = 128
_QUERY_CACHE_TTL = 300
_QUERY_VECTOR_VERSION = "chunk-8000-mean-v1"
_YIELD_EVERY = 32
# The only payload keys that decide whether a stored vector is a verified
# measurement of the CURRENT candidate text; nothing else is transferred.
_PROVENANCE_KEYS = ("content_hash", "embedding_model")
_query_cache: OrderedDict[tuple[str, str, str], tuple[float, tuple[float, ...]]] = (
    OrderedDict()
)


async def _cooperate() -> None:
    """Yield to the event loop between CPU-bound slices of a batch."""
    await asyncio.sleep(0)


class _ExactSearchRejected(Exception):
    """Qdrant refused the scoring request itself (4xx) — not an outage."""


@dataclass(frozen=True)
class VectorMeasurement:
    score: float | None
    status: str


def cosine(left, right) -> float | None:
    if (
        not isinstance(left, list)
        or not isinstance(right, list)
        or len(left) != len(right)
        or not left
    ):
        return None
    if not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
        for v in [*left, *right]
    ):
        return None
    left_norm, right_norm = math.hypot(*left), math.hypot(*right)
    if (
        not left_norm
        or not right_norm
        or not math.isfinite(left_norm)
        or not math.isfinite(right_norm)
    ):
        return None
    # Normalize before products so a malformed huge coordinate cannot overflow
    # a whole batch or be reported as a measured zero.
    return max(
        -1.0,
        min(
            1.0,
            math.fsum((a / left_norm) * (b / right_norm) for a, b in zip(left, right)),
        ),
    )


async def request_vector(text: str) -> list[float] | None:
    key = (
        _QUERY_VECTOR_VERSION,
        embeddings._voyage_model(),
        hashlib.sha256(text.encode()).hexdigest(),
    )
    cached = _query_cache.get(key)
    if cached is not None:
        expires, vector = cached
        if expires > time.monotonic():
            _query_cache.move_to_end(key)
            return list(vector)
        del _query_cache[key]
    # Every character is represented, including requirements after long prose.
    # Bounded chunks avoid the provider's implicit truncation of long requests.
    chunks = [text[i : i + 8000] for i in range(0, len(text), 8000)]
    if not chunks:
        return None
    vectors = []
    for start in range(0, len(chunks), 8):
        part = chunks[start : start + 8]
        measured = await embeddings._voyage_embed_batch(part, input_type="query")
        if not measured or len(measured) != len(part) or any(not v for v in measured):
            return None
        vectors.extend(measured)
    size = len(vectors[0])
    if any(len(v) != size for v in vectors):
        return None
    vector = [math.fsum(v[i] for v in vectors) / len(vectors) for i in range(size)]
    norm = math.sqrt(math.fsum(v * v for v in vector))
    if not norm or not math.isfinite(norm):
        return None
    result = [v / norm for v in vector]
    if cosine(result, result) is None:
        return None
    _query_cache[key] = (time.monotonic() + _QUERY_CACHE_TTL, tuple(result))
    _query_cache.move_to_end(key)
    while len(_query_cache) > _QUERY_CACHE_LIMIT:
        _query_cache.popitem(last=False)
    return result


def _similarity(score) -> float | None:
    """Qdrant's COSINE score on the scale of :func:`cosine`: finite, [-1, 1]."""
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
    ):
        return None
    return max(-1.0, min(1.0, float(score)))


def _exact_search(query_vector, ids):
    """Blocking: ONE id-filtered exact search; Qdrant computes every cosine.

    Replaces pulling 256 × 1024 floats per batch as JSON and multiplying them
    in pure Python (the dominant cost of a full-population scan). ``exact``
    turns off the ANN graph, so every filtered point is scored; quantization is
    ignored so the original vectors are used, as the retrieve path did. Only
    the provenance payload travels back — no vectors.
    """
    from qdrant_client.http.exceptions import UnexpectedResponse
    from qdrant_client.models import (
        Filter,
        HasIdCondition,
        QuantizationSearchParams,
        SearchParams,
    )

    client = embeddings._get_qdrant_client()
    if client is None:
        raise RuntimeError("Vector store unavailable")
    try:
        return client.search(
            collection_name=embeddings._collection(),
            query_vector=query_vector,
            query_filter=Filter(must=[HasIdCondition(has_id=ids)]),
            search_params=SearchParams(
                exact=True, quantization=QuantizationSearchParams(ignore=True)
            ),
            limit=len(ids),
            with_payload=list(_PROVENANCE_KEYS),
            with_vectors=False,
        )
    except UnexpectedResponse as exc:
        if exc.status_code is not None and 400 <= exc.status_code < 500:
            raise _ExactSearchRejected(exc.status_code) from exc
        raise
    finally:
        client.close()


async def measure_candidates(query_vector, candidates) -> dict[int, VectorMeasurement]:
    """Provenance-checked cosine for every candidate, scored inside Qdrant.

    Semantics are those of :func:`_measure_by_retrieval` (the reference path):
    absent point → ``missing_index``; payload hash/model not matching the
    current text → ``stale``; otherwise the cosine, ``unavailable`` when it
    cannot be computed. Two deliberate delegations keep that true where Qdrant
    alone cannot: a 4xx (e.g. a query of the wrong dimension) re-runs the batch
    on the reference path, and an exact 0.0 — which is also what a zero-norm
    stored vector scores — is re-checked on the vectors, so a malformed vector
    is never reported as a measured zero.
    """
    ids = [candidate.id for candidate in candidates]
    if not ids:
        return {}
    if query_vector is None:
        return {cid: VectorMeasurement(None, "unavailable") for cid in ids}
    try:
        hits = await embeddings._run_qdrant(lambda: _exact_search(query_vector, ids))
    except _ExactSearchRejected:
        return await _measure_by_retrieval(query_vector, candidates)
    except Exception:
        return {cid: VectorMeasurement(None, "unavailable") for cid in ids}
    by_id = {int(hit.id): hit for hit in hits}
    model = embeddings._voyage_model()
    results: dict[int, VectorMeasurement] = {}
    zero_scored = []
    for index, candidate in enumerate(candidates):
        # Text build + sha256 per candidate is pure CPU; hand the event loop
        # back regularly so HTTP requests in this process are not starved by a
        # full-population scan. Results are unaffected.
        if index and index % _YIELD_EVERY == 0:
            await _cooperate()
        hit = by_id.get(candidate.id)
        if hit is None:
            results[candidate.id] = VectorMeasurement(None, "missing_index")
            continue
        expected = hashlib.sha256(
            embeddings._build_candidate_text(candidate).encode()
        ).hexdigest()
        payload = hit.payload or {}
        # Unknown provenance is explicitly stale until reconciliation/reindex;
        # an old vector is never presented as a verified current measurement.
        if (
            payload.get("content_hash") != expected
            or payload.get("embedding_model") != model
        ):
            results[candidate.id] = VectorMeasurement(None, "stale")
            continue
        score = _similarity(hit.score)
        if score == 0.0:
            zero_scored.append(candidate)
            continue
        results[candidate.id] = VectorMeasurement(
            score, "measured" if score is not None else "unavailable"
        )
    if zero_scored:
        results.update(await _measure_by_retrieval(query_vector, zero_scored))
    return results


async def _measure_by_retrieval(
    query_vector, candidates
) -> dict[int, VectorMeasurement]:
    """Reference path: pull the stored vectors and compute the cosine here.

    Too slow for a whole population (it was the full scan's bottleneck); kept
    for the cases in which Qdrant's own score cannot stand in for it.
    """
    ids = [candidate.id for candidate in candidates]

    def retrieve():
        client = embeddings._get_qdrant_client()
        if client is None:
            raise RuntimeError("Vector store unavailable")
        try:
            return client.retrieve(
                collection_name=embeddings._collection(),
                ids=ids,
                with_vectors=True,
                with_payload=True,
            )
        finally:
            client.close()

    try:
        points = await embeddings._run_qdrant(retrieve)
    except Exception:
        return {cid: VectorMeasurement(None, "unavailable") for cid in ids}
    by_id = {int(point.id): point for point in points}
    results = {}
    for index, candidate in enumerate(candidates):
        # Text build + sha256 + cosine per candidate is pure CPU; hand the
        # event loop back regularly so HTTP requests in this process are not
        # starved by a full-population scan. Results are unaffected.
        if index and index % _YIELD_EVERY == 0:
            await _cooperate()
        point = by_id.get(candidate.id)
        if point is None:
            results[candidate.id] = VectorMeasurement(None, "missing_index")
            continue
        expected = hashlib.sha256(
            embeddings._build_candidate_text(candidate).encode()
        ).hexdigest()
        payload = point.payload or {}
        # Unknown provenance is explicitly stale until reconciliation/reindex;
        # an old vector is never presented as a verified current measurement.
        if (
            payload.get("content_hash") != expected
            or payload.get("embedding_model") != embeddings._voyage_model()
        ):
            results[candidate.id] = VectorMeasurement(None, "stale")
            continue
        score = cosine(query_vector, point.vector)
        results[candidate.id] = VectorMeasurement(
            score, "measured" if score is not None else "unavailable"
        )
    return results
