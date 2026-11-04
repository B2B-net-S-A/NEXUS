"""Podobne rekrutacje po wektorze rekrutacji (decyzja Artura 30.09.2026).

Na historii (1620 rekrutacji docelowych) prawdziwe źródło przepięcia było
w top 5 dla 39,7% rekrutacji przy wzorze leksykalnym z progiem 55 i dla 60,6%
przy kosinusie wektorów rekrutacji z premią 0,08 za tego samego klienta.

Bez bazy i bez Qdranta: pula zbudowana z atrap wierszy, a kolekcja
``nexus_jobs`` to atrapa zwracająca zadane kosinusy — z tą samą regułą co
prawdziwe zapytanie (tylko pula wołającego, bez referencji i wykluczonych,
referencja bez wektora nie ma klucza, ``None`` = Qdrant nie odpowiedział).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import embedding_service
from app.services import full_search_measurement
from app.services import job_similarity as sim


def _row(jid, title, skills, *, client=1, cc=1, status="published"):
    return SimpleNamespace(
        id=jid,
        title=title,
        client_id=client,
        reference_number=f"ZOB-{jid}",
        status=status,
        competence_category_id=cc,
        must_skills=skills,
        champion_profile=None,
        created_at=None,
        opened_at=None,
    )


# 1 = rekrutacja, dla której szukamy. 2–6 mają osoby u klienta, 7 nie ma.
_ROWS = [
    _row(1, "Java Developer", ["Java", "Spring"], client=10),
    _row(2, "Senior Java Developer", ["Java", "Spring"], client=20),
    _row(3, "Backend Engineer", ["Kotlin"], client=10),
    _row(4, "Analityk systemowy", ["UML"], client=30, cc=2),
    _row(5, "Tester manualny", ["Selenium"], client=40, cc=3, status="closed"),
    _row(6, "Java Engineer", ["Java"], client=50),
    _row(7, "Java Developer", ["Java", "Spring"], client=10),
]
_SENT = frozenset({2, 3, 4, 5, 6})

# Kosinusy wektorów rekrutacji (symetryczne).
_COS = {
    (1, 2): 0.74,
    (1, 3): 0.70,  # ten sam klient co 1 → 0,78 z premią, wyżej niż 2
    (1, 4): 0.31,  # niski kosinus — wektor nie ma progu
    (1, 5): 0.52,
    (1, 6): 0.60,
    (1, 7): 0.99,  # bez osób u klienta — nie wolno go podpowiedzieć
}


def _cos(a: int, b: int) -> float:
    return _COS.get((a, b)) or _COS.get((b, a)) or 0.0


class _FakeJobsIndex:
    def __init__(self, *, with_vectors=frozenset({1, 2, 3, 4, 5, 6, 7}), down=False):
        self.with_vectors = set(with_vectors)
        self.down = down
        self.calls: list[dict] = []

    async def by_ids(self, refs, candidates, *, exclude=None, limit=60):
        self.calls.append(
            {"refs": list(refs), "candidates": set(candidates), "exclude": exclude}
        )
        if self.down:
            return None
        out = {}
        for ref in refs:
            if ref not in self.with_vectors:
                continue
            skip = {ref, *((exclude or {}).get(ref, ()))}
            hits = [
                (jid, _cos(ref, jid))
                for jid in candidates
                if jid not in skip and jid in self.with_vectors
            ]
            hits.sort(key=lambda h: -h[1])
            out[ref] = hits[:limit]
        return out


@pytest.fixture
def world(monkeypatch):
    sim.reset_pool_cache()
    pool = sim._build_pool(_ROWS)
    pool.sent_ids = _SENT

    async def _load_pool(_db):
        return pool

    monkeypatch.setattr(sim, "_load_pool", _load_pool)
    index = _FakeJobsIndex()
    monkeypatch.setattr(embedding_service, "nearest_jobs_for_job_ids", index.by_ids)
    yield SimpleNamespace(pool=pool, index=index, db=object())
    sim.reset_pool_cache()


def _job(jid: int):
    row = next(r for r in _ROWS if r.id == jid)
    return SimpleNamespace(**vars(row))


# ── Ranking jednej rekrutacji ─────────────────────────────────────────────


async def test_ranks_by_cosine_with_same_client_bonus_and_no_threshold(world):
    found = await sim.suggestions_for_job(world.db, _job(1))

    assert [s.job.id for s in found] == [3, 2, 6, 5, 4]
    assert {s.kind for s in found} == {sim.KIND_VECTOR}
    by_id = {s.job.id: s for s in found}
    # Ekran pokazuje sam kosinus; porządek liczy kosinus + premię klienta.
    assert by_id[3].similarity == 70
    assert by_id[3].score == pytest.approx(0.70 + sim.VECTOR_CLIENT_BONUS)
    assert by_id[2].similarity == 74
    assert by_id[2].score == pytest.approx(0.74)
    # Dawny próg 55 nie obowiązuje: 31 pkt nadal jest podpowiedzią.
    assert by_id[4].similarity == 31


async def test_pool_is_jobs_with_people_sent_to_client(world):
    found = await sim.suggestions_for_job(world.db, _job(1))

    assert 7 not in {s.job.id for s in found}
    call = world.index.calls[-1]
    assert call["candidates"] == set(_SENT)
    assert call["refs"] == [1]


async def test_excludes_self_and_linked_jobs(world):
    found = await sim.suggestions_for_job(world.db, _job(3), exclude=[2])

    ids = [s.job.id for s in found]
    assert 3 not in ids and 2 not in ids
    assert world.index.calls[-1]["exclude"] == {3: [2]}


async def test_limit_is_max_suggestions(world):
    world.pool.sent_ids = frozenset({2, 3, 4, 5, 6, 7})
    found = await sim.suggestions_for_job(world.db, _job(1))
    assert len(found) == sim.MAX_SUGGESTIONS
    assert found[0].job.id == 7


# ── Zapas leksykalny ──────────────────────────────────────────────────────


async def test_qdrant_down_falls_back_to_lexical_with_threshold(world):
    world.index.down = True
    found = await sim.suggestions_for_job(world.db, _job(1))

    expected = sim._rank(world.pool, sim._as_pool_job(_job(1)), set())
    assert [(s.job.id, s.similarity) for s in found] == expected[: sim.MAX_SUGGESTIONS]
    assert {s.kind for s in found} <= {sim.KIND_LEXICAL}
    assert all(s.similarity >= sim.MIN_SCORE for s in found)
    assert found, "leksykalnie 1 i 7 to ta sama rola"


async def test_job_without_vector_falls_back_to_lexical(world):
    world.index.with_vectors.discard(1)
    found = await sim.suggestions_for_job(world.db, _job(1))
    assert found and {s.kind for s in found} == {sim.KIND_LEXICAL}


async def test_timeout_falls_back_to_lexical(world, monkeypatch):
    import asyncio

    async def _slow(*_a, **_k):
        await asyncio.sleep(1)
        return {}

    monkeypatch.setattr(embedding_service, "nearest_jobs_for_job_ids", _slow)
    found = await sim._vector_neighbours(
        world.db, world.pool, [(sim._as_pool_job(_job(1)), frozenset())], timeout=0.01
    )
    assert found is None


# ── /jobs/new: szkic bez zapisanego wektora ───────────────────────────────


def _draft(title, skills, client_id=None):
    return SimpleNamespace(
        id=0,
        title=title,
        must_skills=skills,
        competence_category_id=None,
        client_id=client_id,
        reference_number=None,
        status=None,
        created_at=None,
    )


async def test_preview_embeds_the_draft_and_ranks_by_vector(world, monkeypatch):
    texts: list[str] = []

    async def _vector(text):
        texts.append(text)
        return [1.0, 0.0]

    calls: list[dict] = []

    async def _nearest(vector, candidates, *, exclude=(), limit=60):
        calls.append({"vector": vector, "candidates": set(candidates)})
        return [(2, 0.66), (3, 0.62), (4, 0.20)]

    monkeypatch.setattr(full_search_measurement, "request_vector", _vector)
    monkeypatch.setattr(embedding_service, "nearest_jobs_for_vector", _nearest)

    found = await sim.preview_suggestions(
        world.db, _draft("Java Developer", ["Java", "Spring"], client_id=10)
    )

    assert texts == ["Java Developer\nJava, Spring"]
    assert calls[0]["candidates"] == set(_SENT)
    # Klient ze szkicu daje premię: 3 (0,62 + 0,08) wyprzedza 2 (0,66).
    assert [s.job.id for s in found] == [3, 2, 4]
    assert {s.kind for s in found} == {sim.KIND_VECTOR}


async def test_preview_without_embedding_is_lexical(world, monkeypatch):
    async def _none(_text):
        return None

    monkeypatch.setattr(full_search_measurement, "request_vector", _none)
    found = await sim.preview_suggestions(
        world.db, _draft("Java Developer", ["Java", "Spring"])
    )
    assert found and {s.kind for s in found} == {sim.KIND_LEXICAL}


# ── Lista rekrutacji: plakietka „≈” ───────────────────────────────────────


@pytest.fixture
def sent_counts(monkeypatch):
    async def _sent(_db, ids):
        return {jid: 2 for jid in ids if jid in _SENT}

    monkeypatch.setattr(sim, "sent_counts", _sent)


async def test_badge_counts_only_vector_suggestions_above_threshold(
    world, sent_counts, monkeypatch
):
    monkeypatch.setattr(sim, "SIMILAR_JOBS_BADGE_MIN_COSINE", 0.72)
    out = await sim.suggestion_summaries(world.db, [_job(1)], {})

    # 3: 0,70 + 0,08 = 0,78 i 2: 0,74 — reszta poniżej progu plakietki.
    assert out[1]["count"] == 2
    assert out[1]["kind"] == sim.KIND_VECTOR
    assert out[1]["first"]["id"] == 3
    assert out[1]["sent_count"] == 4


async def test_no_badge_when_every_vector_suggestion_is_below_threshold(
    world, sent_counts, monkeypatch
):
    monkeypatch.setattr(sim, "SIMILAR_JOBS_BADGE_MIN_COSINE", 0.95)
    out = await sim.suggestion_summaries(world.db, [_job(1)], {})
    assert 1 not in out


async def test_list_asks_qdrant_once_and_keeps_the_ranking(world, sent_counts):
    jobs = [_job(1), _job(3), _job(6)]
    first = await sim.suggestion_summaries(world.db, jobs, {})
    assert len(world.index.calls) == 1
    assert world.index.calls[0]["refs"] == [1, 3, 6]

    second = await sim.suggestion_summaries(world.db, jobs, {})
    assert second == first
    assert len(world.index.calls) == 1, "druga strona z pamięci puli"


async def test_list_does_not_cache_a_qdrant_outage(world, sent_counts):
    world.index.down = True
    first = await sim.suggestion_summaries(world.db, [_job(1)], {})
    assert first.get(1, {}).get("kind") in (None, sim.KIND_LEXICAL)

    world.index.down = False
    second = await sim.suggestion_summaries(world.db, [_job(1)], {})
    assert len(world.index.calls) == 2
    assert second[1]["kind"] == sim.KIND_VECTOR


async def test_list_skips_closed_rows(world, sent_counts):
    out = await sim.suggestion_summaries(world.db, [_job(5)], {})
    assert out == {}
    assert world.index.calls == []


def test_rank_cache_key_carries_the_ranking_version():
    ref = sim._as_pool_job(_job(1))
    assert sim._rank_cache_key(ref, frozenset())[0] == "vector-v1"


# ── Prawdziwy klient Qdranta (tryb w pamięci) ─────────────────────────────


@pytest.fixture
def memory_qdrant(monkeypatch):
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    client = QdrantClient(":memory:")
    client.create_collection(
        embedding_service.JOBS_COLLECTION,
        vectors_config=VectorParams(size=3, distance=Distance.COSINE),
    )
    vectors = {
        1: [1.0, 0.0, 0.0],
        2: [1.0, 0.2, 0.0],
        3: [0.5, 0.5, 0.0],
        4: [0.0, 1.0, 0.0],
        5: [1.0, 0.05, 0.0],
    }
    client.upsert(
        embedding_service.JOBS_COLLECTION,
        [PointStruct(id=i, vector=v) for i, v in vectors.items()],
    )
    monkeypatch.setattr("qdrant_client.QdrantClient", lambda **_k: client)
    return client


class _ServerLike:
    """Klient „jak serwer”: tryb w pamięci nie zna zapytania po id punktu
    (``query=<id>``, serwer Qdranta od 1.10; prod ma 1.17), więc atrapa
    zapisuje żądanie i wykonuje je wektorem punktu — filtr i limit liczy
    prawdziwy silnik trybu w pamięci."""

    def __init__(self, memory):
        self.memory = memory
        self.requests = []

    def retrieve(self, **kwargs):
        return self.memory.retrieve(**kwargs)

    def query_batch_points(self, collection_name, requests):
        out = []
        for request in requests:
            self.requests.append(request)
            assert isinstance(request.query, int), "zapytanie po id, bez wektora"
            (point,) = self.memory.retrieve(
                collection_name=collection_name, ids=[request.query], with_vectors=True
            )
            out.append(
                self.memory.query_points(
                    collection_name=collection_name,
                    query=point.vector,
                    query_filter=request.filter,
                    limit=request.limit,
                    with_payload=False,
                )
            )
        return out


@pytest.fixture
def server_qdrant(memory_qdrant, monkeypatch):
    client = _ServerLike(memory_qdrant)
    monkeypatch.setattr("qdrant_client.QdrantClient", lambda **_k: client)
    return client


async def test_nearest_jobs_query_by_point_id_within_the_pool(server_qdrant):
    got = await embedding_service.nearest_jobs_for_job_ids(
        [1, 99, 4], [1, 2, 3, 4, 5], exclude={1: [5]}, limit=10
    )

    # 99 nie ma wektora — brak klucza (wołający liczy go leksykalnie) i nie
    # trafia do zapytania, bo nieznane id wywróciłoby całą paczkę.
    assert set(got) == {1, 4}
    assert [r.query for r in server_qdrant.requests] == [1, 4]
    assert [jid for jid, _ in got[1]] == [2, 3, 4]  # bez siebie i bez 5
    assert got[1][0][1] == pytest.approx(0.98, abs=0.01)
    assert 4 not in [jid for jid, _ in got[4]]


async def test_nearest_jobs_respect_the_candidate_pool(server_qdrant):
    got = await embedding_service.nearest_jobs_for_job_ids([1], [3, 4], limit=10)
    assert [jid for jid, _ in got[1]] == [3, 4]


async def test_nearest_jobs_for_vector(memory_qdrant):
    got = await embedding_service.nearest_jobs_for_vector(
        [1.0, 0.0, 0.0], [2, 3, 4], limit=2
    )
    assert [jid for jid, _ in got] == [2, 3]


async def test_nearest_jobs_report_an_outage_as_none(monkeypatch):
    def _broken(**_k):
        raise ConnectionError("qdrant down")

    monkeypatch.setattr("qdrant_client.QdrantClient", _broken)
    assert await embedding_service.nearest_jobs_for_job_ids([1], [2]) is None
    assert await embedding_service.nearest_jobs_for_vector([1.0], [2]) is None
