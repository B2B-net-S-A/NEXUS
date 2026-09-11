import hashlib
import math
import random
import struct
from types import SimpleNamespace

import httpx
import pytest
from qdrant_client.http.exceptions import UnexpectedResponse

from app.services import full_search_measurement as measure


@pytest.fixture(autouse=True)
def clear_query_cache():
    measure._query_cache.clear()
    yield
    measure._query_cache.clear()


def test_exact_cosine_and_invalid_dimensions():
    assert measure.cosine([1, 0], [1, 0]) == 1
    assert measure.cosine([1, 0], [0, 1]) == 0
    assert measure.cosine([1, 0], [1]) is None
    assert measure.cosine([1, 0], [0, 0]) is None
    assert measure.cosine([1, 0], ["bad", 0]) is None
    assert measure.cosine([1, 0], [True, 0]) is None
    assert measure.cosine([1e308, 0], [1e308, 0]) == 1


@pytest.mark.asyncio
async def test_every_request_chunk_including_tail_is_embedded(monkeypatch):
    seen = []

    async def embed(texts, **kwargs):
        seen.extend(texts)
        return [[1, 0] for _ in texts]

    monkeypatch.setattr(measure.embeddings, "_voyage_embed_batch", embed)
    text = "x" * 17000 + "Required: Django"
    assert await measure.request_vector(text) == [1, 0]
    assert "".join(seen) == text
    assert all(len(chunk) <= 8000 for chunk in seen)


@pytest.mark.asyncio
async def test_exact_retrieval_distinguishes_fresh_stale_and_missing(monkeypatch):
    content = "Python"
    monkeypatch.setattr(measure.embeddings, "_build_candidate_text", lambda _: content)
    monkeypatch.setattr(measure.embeddings, "_voyage_model", lambda: "model")
    # Scored points from Qdrant's exact search: a score and provenance, no vector.
    points = [
        SimpleNamespace(
            id=1,
            score=1.0,
            payload={
                "content_hash": hashlib.sha256(content.encode()).hexdigest(),
                "embedding_model": "model",
            },
        ),
        SimpleNamespace(id=2, score=1.0, payload={}),
    ]

    async def search(_):
        return points

    monkeypatch.setattr(measure.embeddings, "_run_qdrant", search)
    results = await measure.measure_candidates(
        [1, 0], [SimpleNamespace(id=i) for i in [1, 2, 3]]
    )
    assert results[1].score == 1 and results[1].status == "measured"
    assert results[2].score is None and results[2].status == "stale"
    assert results[3].score is None and results[3].status == "missing_index"


@pytest.mark.asyncio
async def test_long_batch_hands_back_the_event_loop_without_changing_results(
    monkeypatch,
):
    """Per-candidate hashing is CPU; a full scan must not starve HTTP."""
    content = "Python"
    monkeypatch.setattr(measure.embeddings, "_build_candidate_text", lambda _: content)
    monkeypatch.setattr(measure.embeddings, "_voyage_model", lambda: "model")
    digest = hashlib.sha256(content.encode()).hexdigest()

    async def retrieve(_):
        return [
            SimpleNamespace(
                id=i,
                score=1.0,
                payload={"content_hash": digest, "embedding_model": "model"},
            )
            for i in range(1, 71)
        ]

    yields = []
    real_cooperate = measure._cooperate

    async def counting_cooperate():
        yields.append(True)
        await real_cooperate()

    monkeypatch.setattr(measure.embeddings, "_run_qdrant", retrieve)
    monkeypatch.setattr(measure, "_cooperate", counting_cooperate)
    candidates = [SimpleNamespace(id=i) for i in range(1, 71)]
    results = await measure.measure_candidates([1, 0], candidates)
    assert len(yields) == 2  # after 32 and 64 candidates
    assert len(results) == 70
    assert {r.status for r in results.values()} == {"measured"}
    assert {r.score for r in results.values()} == {1}


@pytest.mark.asyncio
async def test_provider_outage_is_unknown_not_zero(monkeypatch):
    async def fail(_):
        raise RuntimeError("down")

    monkeypatch.setattr(measure.embeddings, "_run_qdrant", fail)
    results = await measure.measure_candidates([1, 0], [SimpleNamespace(id=1)])
    assert results[1].score is None and results[1].status == "unavailable"


@pytest.mark.asyncio
async def test_request_cache_reuses_only_same_full_text_model_and_live_ttl(monkeypatch):
    from unittest.mock import AsyncMock

    embed = AsyncMock(return_value=[[1, 0]])
    monkeypatch.setattr(measure.embeddings, "_voyage_embed_batch", embed)
    monkeypatch.setattr(measure.embeddings, "_voyage_model", lambda: "model-A")
    clock = [100.0]
    monkeypatch.setattr(measure.time, "monotonic", lambda: clock[0])
    first = await measure.request_vector("Python")
    first[0] = 999
    assert await measure.request_vector("Python") == [1, 0]
    assert embed.await_count == 1
    await measure.request_vector("Python Django")
    assert embed.await_count == 2
    monkeypatch.setattr(measure.embeddings, "_voyage_model", lambda: "model-B")
    await measure.request_vector("Python")
    assert embed.await_count == 3
    clock[0] += 301
    await measure.request_vector("Python")
    assert embed.await_count == 4
    assert all("Python" not in str(key) for key in measure._query_cache)


@pytest.mark.asyncio
async def test_request_cache_does_not_keep_failures_and_evicts_oldest(monkeypatch):
    from unittest.mock import AsyncMock

    embed = AsyncMock(side_effect=[None, [[1, 0]], [[1, 0]], [[1, 0]], [[1, 0]]])
    monkeypatch.setattr(measure.embeddings, "_voyage_embed_batch", embed)
    monkeypatch.setattr(measure, "_QUERY_CACHE_LIMIT", 2)
    assert await measure.request_vector("one") is None
    assert await measure.request_vector("one") == [1, 0]
    await measure.request_vector("two")
    await measure.request_vector("three")
    assert len(measure._query_cache) == 2
    await measure.request_vector("one")
    assert embed.await_count == 5


# ── Qdrant-side exact similarity vs the retrieve + Python cosine it replaces ──


def _f32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


def _as_stored(vector: list[float]) -> list[float]:
    """What a COSINE collection keeps: normalized on write, as float32.

    A zero vector is left untouched by Qdrant's normalization, so it scores
    exactly 0.0 against any query — the case the old path called unavailable.
    """
    norm = math.sqrt(math.fsum(v * v for v in vector))
    return [_f32(v / norm if norm else v) for v in vector]


class _FakeQdrant:
    """One collection with exactly the read semantics both paths rely on."""

    def __init__(self, points: dict[int, tuple[list[float], dict]]):
        self.points = {
            pid: (_as_stored(vector), payload)
            for pid, (vector, payload) in points.items()
        }
        self.calls: list[tuple] = []

    def retrieve(self, *, collection_name, ids, with_vectors, with_payload):
        self.calls.append(("retrieve", tuple(ids), with_vectors))
        return [
            SimpleNamespace(
                id=pid,
                vector=list(self.points[pid][0]) if with_vectors else None,
                payload=dict(self.points[pid][1]) if with_payload else None,
            )
            for pid in ids
            if pid in self.points
        ]

    def search(
        self,
        *,
        collection_name,
        query_vector,
        query_filter,
        search_params,
        limit,
        with_payload,
        with_vectors,
    ):
        (condition,) = query_filter.must
        self.calls.append(("search", tuple(condition.has_id), search_params, limit))
        self.search_kwargs = {
            "exact": search_params.exact,
            "ignore_quantization": search_params.quantization.ignore,
            "limit": limit,
            "with_payload": list(with_payload),
            "with_vectors": with_vectors,
        }
        query = _as_stored(list(query_vector))
        hits = []
        for pid in condition.has_id:
            if pid not in self.points:
                continue
            stored, payload = self.points[pid]
            if len(stored) != len(query):
                raise UnexpectedResponse(
                    status_code=400,
                    reason_phrase="Bad Request",
                    content=b'{"status":{"error":"Wrong input: Vector dimension error"}}',
                    headers=httpx.Headers(),
                )
            hits.append(
                SimpleNamespace(
                    id=pid,
                    score=_f32(math.fsum(q * s for q, s in zip(query, stored))),
                    payload={k: payload[k] for k in with_payload if k in payload},
                    vector=None,
                )
            )
        hits.sort(key=lambda hit: -hit.score)
        return hits[:limit]

    def close(self):
        pass


async def _legacy_measure(query_vector, candidates):
    """The pre-change algorithm, verbatim: retrieve vectors, cosine in Python."""
    client = measure.embeddings._get_qdrant_client()
    points = client.retrieve(
        collection_name="c",
        ids=[c.id for c in candidates],
        with_vectors=True,
        with_payload=True,
    )
    by_id = {int(point.id): point for point in points}
    results = {}
    for candidate in candidates:
        point = by_id.get(candidate.id)
        if point is None:
            results[candidate.id] = measure.VectorMeasurement(None, "missing_index")
            continue
        expected = hashlib.sha256(
            measure.embeddings._build_candidate_text(candidate).encode()
        ).hexdigest()
        payload = point.payload or {}
        if (
            payload.get("content_hash") != expected
            or payload.get("embedding_model") != measure.embeddings._voyage_model()
        ):
            results[candidate.id] = measure.VectorMeasurement(None, "stale")
            continue
        score = measure.cosine(query_vector, point.vector)
        results[candidate.id] = measure.VectorMeasurement(
            score, "measured" if score is not None else "unavailable"
        )
    return results


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(math.fsum(v * v for v in vector))
    return [v / norm for v in vector]


def _synthetic_index(dims: int, seed: int = 1409):
    """70 candidates (crosses the yield boundary twice) with every state."""
    rng = random.Random(seed)
    query = _unit([rng.gauss(0, 1) for _ in range(dims)])

    def text(candidate_id: int) -> str:
        return f"candidate-{candidate_id}"

    def fresh(candidate_id: int) -> dict:
        return {
            "content_hash": hashlib.sha256(text(candidate_id).encode()).hexdigest(),
            "embedding_model": "model",
            "competence_category": "unused",
        }

    points: dict[int, tuple[list[float], dict]] = {}
    for candidate_id in range(1, 71):
        vector = [rng.gauss(0, 1) for _ in range(dims)]
        if candidate_id == 3:
            vector = [-v for v in query]  # cosine -1
        elif candidate_id == 4:
            vector = [2.5 * v for v in query]  # cosine 1, unnormalized input
        elif candidate_id == 5:
            vector = [0.0] * dims  # zero norm → unavailable, never measured 0
        if candidate_id in (10, 11):
            payload = {**fresh(candidate_id), "content_hash": "old"}
        elif candidate_id == 12:
            payload = {**fresh(candidate_id), "embedding_model": "other-model"}
        elif candidate_id == 13:
            payload = {}
        else:
            payload = fresh(candidate_id)
        if candidate_id in (20, 21):
            continue  # never indexed
        points[candidate_id] = (vector, payload)
    candidates = [SimpleNamespace(id=i) for i in range(1, 71)]
    return query, candidates, points, text


def _install(monkeypatch, fake, text):
    async def run_inline(fn):
        return fn()

    monkeypatch.setattr(measure.embeddings, "_get_qdrant_client", lambda: fake)
    monkeypatch.setattr(measure.embeddings, "_run_qdrant", run_inline)
    monkeypatch.setattr(measure.embeddings, "_collection", lambda: "c")
    monkeypatch.setattr(measure.embeddings, "_voyage_model", lambda: "model")
    monkeypatch.setattr(
        measure.embeddings, "_build_candidate_text", lambda c: text(c.id)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("dims", [8, 1024])
async def test_exact_search_matches_the_python_cosine_it_replaces(monkeypatch, dims):
    """PARITY: same statuses for every candidate, same scores within 1e-6.

    Stored vectors are float32 and normalized, as in a COSINE collection, so
    the only difference left is float32 rounding of the score (~1e-7).
    """
    query, candidates, points, text = _synthetic_index(dims)
    fake = _FakeQdrant(points)
    _install(monkeypatch, fake, text)

    old = await _legacy_measure(query, candidates)
    fake.calls.clear()
    new = await measure.measure_candidates(query, candidates)

    assert set(new) == set(old) == {c.id for c in candidates}
    assert {cid: m.status for cid, m in new.items()} == {
        cid: m.status for cid, m in old.items()
    }
    measured = [cid for cid, m in old.items() if m.status == "measured"]
    assert len(measured) == 70 - 2 - 4 - 1  # missing, stale, zero-norm
    for cid in measured:
        assert new[cid].score == pytest.approx(old[cid].score, abs=1e-6)
    assert new[3].score == pytest.approx(-1.0, abs=1e-6)
    assert new[4].score == pytest.approx(1.0, abs=1e-6)
    assert new[5] == measure.VectorMeasurement(None, "unavailable")
    assert {new[i].status for i in (10, 11, 12, 13)} == {"stale"}
    assert {new[i].status for i in (20, 21)} == {"missing_index"}
    # One vector-free search for the batch; vectors only for the zero score.
    assert [call[0] for call in fake.calls] == ["search", "retrieve"]
    assert fake.calls[0][1] == tuple(c.id for c in candidates)
    assert fake.calls[1] == ("retrieve", (5,), True)
    assert fake.search_kwargs == {
        "exact": True,
        "ignore_quantization": True,
        "limit": 70,
        "with_payload": ["content_hash", "embedding_model"],
        "with_vectors": False,
    }


@pytest.mark.asyncio
async def test_orthogonal_vector_is_a_measured_zero_after_the_vector_recheck(
    monkeypatch,
):
    """An exact 0.0 is only re-checked, not assumed broken: a real vector at a
    right angle to the request is still a measured (and scored) zero."""
    digest = hashlib.sha256(b"7").hexdigest()
    fake = _FakeQdrant(
        {7: ([0.0, 1.0], {"content_hash": digest, "embedding_model": "model"})}
    )
    _install(monkeypatch, fake, str)
    result = await measure.measure_candidates([1.0, 0.0], [SimpleNamespace(id=7)])
    assert result[7] == measure.VectorMeasurement(0.0, "measured")
    assert [call[0] for call in fake.calls] == ["search", "retrieve"]


@pytest.mark.asyncio
async def test_rejected_search_falls_back_to_the_reference_path(monkeypatch):
    """A request Qdrant refuses (wrong query dimension) keeps the old states.

    The old path still told stale and missing apart from unmeasurable; a 4xx
    must not collapse the whole batch into ``unavailable``.
    """
    query, candidates, points, text = _synthetic_index(8)
    fake = _FakeQdrant(points)
    _install(monkeypatch, fake, text)
    wrong_dimension = query + [0.0]

    old = await _legacy_measure(wrong_dimension, candidates)
    new = await measure.measure_candidates(wrong_dimension, candidates)

    assert new == old
    assert {m.status for m in new.values()} == {
        "unavailable",
        "stale",
        "missing_index",
    }


@pytest.mark.asyncio
async def test_search_server_error_is_unknown_not_a_fallback(monkeypatch):
    """5xx / connection trouble is an outage: no second, slower round trip."""
    fake = _FakeQdrant({1: ([1.0, 0.0], {})})

    def broken_search(**_kwargs):
        raise UnexpectedResponse(
            status_code=503,
            reason_phrase="Service Unavailable",
            content=b"",
            headers=httpx.Headers(),
        )

    fake.search = broken_search
    _install(monkeypatch, fake, str)
    result = await measure.measure_candidates([1.0, 0.0], [SimpleNamespace(id=1)])
    assert result == {1: measure.VectorMeasurement(None, "unavailable")}
    assert fake.calls == []
