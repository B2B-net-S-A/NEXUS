"""RODO w oknie side-by-side: delete kandydata czyści KAŻDĄ kolekcję kandydacką.

Runda 2 wprowadza kolekcje side-by-side (stara + nowy schemat tekstu,
przełączane QDRANT_COLLECTION). Kasowanie wyłącznie z aktywnej zostawiałoby
wektor osoby w tej drugiej — dokładnie klasa przecieku, którą pasaże domknęły
wcześniej. Ten test zamraża kontrakt: delete idzie po WSZYSTKICH kolekcjach
o prefiksie nexus_candidates.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FakeClient:
    deleted: list[tuple[str, object]] = []

    def __init__(self, *a, **k):
        pass

    def get_collections(self):
        cols = [
            SimpleNamespace(name="nexus_candidates"),
            SimpleNamespace(name="nexus_candidates__voyage_3_large__d1024__tv3__e1"),
            SimpleNamespace(name="nexus_jobs"),
            SimpleNamespace(name="nexus_cv_passages"),
        ]
        return SimpleNamespace(collections=cols)

    def delete(self, collection_name, points_selector):
        _FakeClient.deleted.append((collection_name, points_selector))


@pytest.mark.asyncio
async def test_delete_covers_every_candidate_collection(monkeypatch):
    import qdrant_client

    from app.services import embedding_service as emb
    from app.services import passage_index

    _FakeClient.deleted = []
    monkeypatch.setattr(qdrant_client, "QdrantClient", _FakeClient)
    monkeypatch.setattr(
        passage_index, "delete_candidate_passages", lambda client, cid: True
    )

    ok = await emb.delete_candidate_embedding(4242)
    assert ok is True

    hit = {name for name, _sel in _FakeClient.deleted}
    assert "nexus_candidates" in hit
    assert "nexus_candidates__voyage_3_large__d1024__tv3__e1" in hit, (
        "kolekcja side-by-side NIE została wyczyszczona — przeciek RODO"
    )
    assert "nexus_jobs" not in hit
    assert "nexus_cv_passages" not in hit, "pasaże kasuje delete_candidate_passages"


@pytest.mark.asyncio
async def test_delete_survives_listing_failure(monkeypatch):
    """Awaria listingu kolekcji nie może zablokować kasowania z aktywnej."""
    import qdrant_client

    from app.services import embedding_service as emb
    from app.services import passage_index

    class _NoListing(_FakeClient):
        def get_collections(self):
            raise RuntimeError("qdrant chwilowo nie odpowiada na listing")

    _FakeClient.deleted = []
    monkeypatch.setattr(qdrant_client, "QdrantClient", _NoListing)
    monkeypatch.setattr(
        passage_index, "delete_candidate_passages", lambda client, cid: True
    )

    ok = await emb.delete_candidate_embedding(7)
    assert ok is True
    assert [n for n, _s in _FakeClient.deleted] == ["nexus_candidates"]
