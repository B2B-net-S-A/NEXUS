import hashlib
from types import SimpleNamespace

import pytest

from app.services import full_search_measurement as measure


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
    points = [
        SimpleNamespace(
            id=1,
            vector=[1, 0],
            payload={
                "content_hash": hashlib.sha256(content.encode()).hexdigest(),
                "embedding_model": "model",
            },
        ),
        SimpleNamespace(id=2, vector=[1, 0], payload={}),
    ]

    async def retrieve(_):
        return points

    monkeypatch.setattr(measure.embeddings, "_run_qdrant", retrieve)
    results = await measure.measure_candidates(
        [1, 0], [SimpleNamespace(id=i) for i in [1, 2, 3]]
    )
    assert results[1].score == 1 and results[1].status == "measured"
    assert results[2].score is None and results[2].status == "stale"
    assert results[3].score is None and results[3].status == "missing_index"


@pytest.mark.asyncio
async def test_provider_outage_is_unknown_not_zero(monkeypatch):
    async def fail(_):
        raise RuntimeError("down")

    monkeypatch.setattr(measure.embeddings, "_run_qdrant", fail)
    results = await measure.measure_candidates([1, 0], [SimpleNamespace(id=1)])
    assert results[1].score is None and results[1].status == "unavailable"
