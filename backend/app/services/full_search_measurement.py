"""Exact, bounded vector measurement for every ID in a SQL population batch."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from app.services import embedding_service as embeddings


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
    return [v / norm for v in vector] if norm and math.isfinite(norm) else None


async def measure_candidates(query_vector, candidates) -> dict[int, VectorMeasurement]:
    ids = [candidate.id for candidate in candidates]
    if not ids:
        return {}
    if query_vector is None:
        return {cid: VectorMeasurement(None, "unavailable") for cid in ids}

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
    for candidate in candidates:
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
