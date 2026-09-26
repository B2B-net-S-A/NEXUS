"""Kolejność „Dopasowanie” listy kandydatów (``sort=match``) i górne pole.

Decyzje Artura (25.09.2026): „Szukaj ręcznie” i lista z wierszami wymagań
domyślnie według dopasowania; „Mile widziane” najpierw, osoby z brakami danych
za osobami z danymi; awaria wektorów = „najnowsi” z informacją w odpowiedzi.
Qdrant i Voyage są tu atrapami — liczy się kolejność, pamięć i awaria.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.services import candidate_match_order as cmo

NONCE = "zm" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_IDS: dict[str, int] = {}


# ── Czyste reguły ────────────────────────────────────────────────────────────


def test_order_rows_puts_preferred_then_known_then_similarity_then_newest():
    rows = [
        # (id, mile_widziane, braki, dodano)
        (1, 0, 0, 100.0),
        (2, 1, 0, 50.0),  # „Mile widziane” wygrywa z podobieństwem
        (3, 0, 1, 300.0),  # braki danych idą za osobami z danymi
        (4, 0, 0, 200.0),  # bez wektora — za osobami z wektorem
        (5, 0, 0, 10.0),
    ]
    scores = {1: 0.5, 2: 0.1, 3: 0.99, 5: 0.9}
    assert cmo.order_rows(rows, scores) == [2, 5, 1, 4, 3]


def test_rerank_within_groups_keeps_groups_and_sorts_by_fit_inside():
    # Kolejność wektorowa: grupa A (1, 2, 3), grupa B (4, 5), poza „top” (6).
    order = [1, 2, 3, 4, 5, 6]
    groups = {1: "A", 2: "A", 3: "A", 4: "B", 5: "B", 6: "B"}
    fits = {1: 10.0, 2: None, 3: 80.0, 4: 30.0, 5: 30.0, 6: 99.0}
    assert cmo.rerank_within_groups(order, groups, fits, top=5) == [3, 1, 2, 4, 5, 6]


def test_rerank_within_groups_top_cuts_a_group_and_zero_is_a_noop():
    order = [1, 2, 3, 4]
    groups = {cid: "A" for cid in order}
    fits = {1: 1.0, 2: 2.0, 3: 3.0, 4: 99.0}
    # Osoba za „top” nie wchodzi do przestawiania, nawet z najwyższą oceną.
    assert cmo.rerank_within_groups(order, groups, fits, top=3) == [3, 2, 1, 4]
    assert cmo.rerank_within_groups(order, groups, fits, top=0) == order
    # Brak oceny w słowniku = bez pomiaru → koniec grupy.
    assert cmo.rerank_within_groups(order, groups, {2: 5.0}, top=4) == [2, 1, 3, 4]


def test_cache_key_depends_on_the_context_fingerprint():
    class F:
        recruitment_id = None
        recruitment_match = None

        @staticmethod
        def model_dump(**_kwargs):
            return {"q": "java"}

    class U:
        id = 7

    async def keys():
        a = await cmo._cache_key(None, F, "job:1:x", U, "fp-a", 200)
        b = await cmo._cache_key(None, F, "job:1:x", U, "fp-b", 200)
        c = await cmo._cache_key(None, F, "job:1:x", U, "fp-a", 0)
        return a, b, c

    import asyncio

    a, b, c = asyncio.run(keys())
    assert a != b and a != c


def test_order_cache_is_bounded_and_drops_expired(monkeypatch):
    cmo.clear_cache()
    for n in range(cmo.CACHE_MAX_ENTRIES + 10):
        cmo._cache_set(f"k{n}", (n,))
    assert len(cmo._order_cache) == cmo.CACHE_MAX_ENTRIES
    assert cmo._cache_get("k0") is None
    last = f"k{cmo.CACHE_MAX_ENTRIES + 9}"
    assert cmo._cache_get(last) == (cmo.CACHE_MAX_ENTRIES + 9,)

    now = cmo.time.monotonic()
    monkeypatch.setattr(cmo.time, "monotonic", lambda: now + cmo.CACHE_TTL_SECONDS + 1)
    assert cmo._cache_get(last) is None
    cmo._cache_set("fresh", (1,))
    assert list(cmo._order_cache) == ["fresh"]
    cmo.clear_cache()


def test_job_scope_needs_exactly_one_recruitment_and_not_assigned():
    class F:
        recruitment_id = [7]
        recruitment_match = "not_assigned"

    assert cmo.job_scope(F) == 7
    F.recruitment_match = "assigned"
    assert cmo.job_scope(F) is None
    F.recruitment_match = "not_assigned"
    F.recruitment_id = [7, 8]
    assert cmo.job_scope(F) is None


def test_requirement_words_join_rows_and_drop_stars():
    class F:
        q_all = ["spring boot"]
        q_any = None

    assert cmo.requirement_words(F, [["java", "kotlin"], ["java*"]]) == (
        "java kotlin spring boot"
    )


@pytest.mark.asyncio
async def test_concurrent_requests_compute_the_order_once_off_the_loop(monkeypatch):
    """Runda 7 (R7-N10-4): „Dopasowanie” na ~60 tys. wierszy — konwersja
    i sortowanie w wątku, a dwa równoległe żądania tego samego klucza liczą
    kolejność raz (drugie bierze wynik z pamięci)."""
    import asyncio
    import threading

    from app.services import embedding_service

    cmo.clear_cache()
    executes = 0
    sort_threads: list[bool] = []

    class Rows:
        def all(self):
            return [(3, 0, 0, 30.0), (1, 0, 0, 10.0), (2, 0, 0, 20.0)]

    class FakeDb:
        async def execute(self, _query):
            nonlocal executes
            executes += 1
            await asyncio.sleep(0.05)
            return Rows()

    class FakeQuery:
        def with_only_columns(self, *_cols):
            return self

    async def fake_resolve(db, user, filters, groups):
        return cmo.MatchVector(vector=[0.1], key="rows:x", kind="rows")

    async def fake_key(db, filters, vector_key, user, fingerprint=None, top=0):
        return "candidate-match-order:test-single-flight"

    async def fake_run(fn):
        return fn()

    real_order_rows = cmo.order_rows

    def recording_order_rows(rows, scores):
        sort_threads.append(threading.current_thread() is not threading.main_thread())
        return real_order_rows(rows, scores)

    monkeypatch.setattr(cmo, "resolve_vector", fake_resolve)
    monkeypatch.setattr(cmo, "_cache_key", fake_key)
    monkeypatch.setattr(cmo, "_qdrant_scores", lambda v, ids: {2: 0.9, 1: 0.5})
    monkeypatch.setattr(embedding_service, "_run_qdrant", fake_run)
    monkeypatch.setattr(cmo, "order_rows", recording_order_rows)

    class F:
        recruitment_id = None
        recruitment_match = None

    db = FakeDb()
    try:
        first, second = await asyncio.gather(
            cmo.ordered_ids(db, None, F, FakeQuery(), [], (None, None)),
            cmo.ordered_ids(db, None, F, FakeQuery(), [], (None, None)),
        )
    finally:
        cmo.clear_cache()
    assert first == second == [2, 1, 3]
    assert executes == 1, "drugie żądanie czeka na pierwsze zamiast liczyć"
    assert sort_threads == [True], "sortowanie poza pętlą zdarzeń"


@pytest.mark.asyncio
async def test_hanging_embedding_provider_falls_back_instead_of_blocking(monkeypatch):
    """Runda 6 audytu: wiszący Voyage (klient HTTP 60 s) nie może zatrzymać
    listy — po limicie kolejność wraca do „najnowsi” (None)."""
    import asyncio

    from app.services import full_search_measurement

    async def hanging(_text):
        await asyncio.sleep(10)
        return [0.1]

    monkeypatch.setattr(full_search_measurement, "request_vector", hanging)
    monkeypatch.setattr(cmo, "QUERY_VECTOR_TIMEOUT_SECONDS", 0.05)

    class F:
        q_all = None
        q_any = None
        recruitment_id = None
        recruitment_match = None

    assert await cmo.resolve_vector(None, None, F, [["java"]]) is None


def test_classify_skills_needs_every_word_to_be_a_skill():
    from app.services import keyword_suggest

    previous = keyword_suggest.catalog()
    try:
        keyword_suggest.load_catalog(
            [(1, "Java", "lang"), (2, "Spring Boot", "fw"), (3, "Go", "lang")],
            [(3, "golang")],
        )
        both = keyword_suggest.classify_skills("Java, spring boot")
        assert both.all_skills and both.skills == ("Java", "Spring Boot")
        assert keyword_suggest.classify_skills("golang").skills == ("Go",)
        sentence = keyword_suggest.classify_skills("senior java z bankowością")
        assert not sentence.all_skills
    finally:
        keyword_suggest._catalog = previous


def test_classify_rows_keep_the_typed_alias_as_a_variant():
    """Runda 6 audytu: „kafka” nie może stać się frazą „Apache Kafka”
    (4569 → 1704 osób), a „postgres” nie może zgubić ludzi, którzy tak piszą."""
    from app.services import keyword_suggest

    previous = keyword_suggest.catalog()
    try:
        keyword_suggest.load_catalog(
            [(1, "Apache Kafka", "tool"), (2, "PostgreSQL", "db"), (3, "Java", "lang")],
            [(1, "kafka"), (2, "postgres")],
        )
        result = keyword_suggest.classify_skills("kafka postgres java")
        assert result.all_skills
        assert result.rows == (("Kafka",), ("postgres", "PostgreSQL"), ("Java",))
    finally:
        keyword_suggest._catalog = previous


# ── Przez endpoint ───────────────────────────────────────────────────────────


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    people = {
        "oldest_best": ([{"name": "Java"}], "Java."),
        "middle": ([{"name": "Java"}, {"name": "Kotlin"}], "Java, Kotlin."),
        "newest_weak": ([{"name": "Java"}], "Java."),
    }
    async with AsyncSessionLocal() as db:
        for key, (skills, cv) in people.items():
            row = Candidate(
                name=key.replace("_", ""),
                lastname="Dopasowany",
                email=f"{key}-{uuid.uuid4().hex[:10]}@example.com",
                status=CandidateStatus.active,
                linkedin_current_company=NONCE,
                raw_cv_text=cv,
                skills=skills,
            )
            db.add(row)
            await db.flush()
            _IDS[key] = row.id
        await db.commit()
    return _IDS


async def _ids(client, headers, **params: Any) -> tuple[list[str], dict]:
    await _seed()
    query: list[tuple[str, Any]] = [
        ("q", NONCE),
        ("text_mode", "literal"),
        ("semantics_version", 2),
        ("q_any_group", "java"),
    ]
    for key, value in params.items():
        query.append((key, value))
    resp = await client.get("/api/candidates", params=query, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_id = {v: k for k, v in _IDS.items()}
    return [by_id[i["id"]] for i in body["items"] if i["id"] in by_id], body


@pytest.fixture
def fake_vectors(monkeypatch):
    ids = {}

    async def fake_resolve(db, user, filters, groups):
        return cmo.MatchVector(
            vector=[1.0], key=f"test:{uuid.uuid4().hex}", kind="rows"
        )

    def fake_scores(vector, candidate_ids):
        return {
            ids["oldest_best"]: 0.9,
            ids["middle"]: 0.5,
            ids["newest_weak"]: 0.1,
        }

    monkeypatch.setattr(cmo, "resolve_vector", fake_resolve)
    monkeypatch.setattr(cmo, "_qdrant_scores", fake_scores)
    cmo.clear_cache()
    return ids


@pytest.mark.asyncio
async def test_match_sort_orders_by_similarity(
    app_client, app_auth_headers, fake_vectors
):
    fake_vectors.update(await _seed())
    order, body = await _ids(app_client, app_auth_headers, sort="match")
    assert order == ["oldest_best", "middle", "newest_weak"]
    assert body["sort_applied"] == "match"
    assert body["total"] >= 3


@pytest.mark.asyncio
async def test_preferred_skill_leads_the_match_order(
    app_client, app_auth_headers, fake_vectors
):
    fake_vectors.update(await _seed())
    order, _ = await _ids(
        app_client, app_auth_headers, sort="match", skills_preferred="kotlin"
    )
    assert order[0] == "middle"


@pytest.mark.asyncio
async def test_without_a_vector_the_list_says_it_fell_back_to_newest(
    app_client, app_auth_headers, monkeypatch
):
    async def no_vector(*args, **kwargs):
        return None

    monkeypatch.setattr(cmo, "resolve_vector", no_vector)
    order, body = await _ids(app_client, app_auth_headers, sort="match")
    assert body["sort_applied"] == "newest"
    assert order == ["newest_weak", "middle", "oldest_best"]


@pytest.mark.asyncio
async def test_qdrant_failure_falls_back_to_newest(
    app_client, app_auth_headers, fake_vectors, monkeypatch
):
    fake_vectors.update(await _seed())

    def broken(vector, ids):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(cmo, "_qdrant_scores", broken)
    order, body = await _ids(app_client, app_auth_headers, sort="match")
    assert body["sort_applied"] == "newest"
    assert order == ["newest_weak", "middle", "oldest_best"]


@pytest.mark.asyncio
async def test_switch_off_means_newest(app_client, app_auth_headers, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CANDIDATE_MATCH_SORT", False)
    _, body = await _ids(app_client, app_auth_headers, sort="match")
    assert body["sort_applied"] == "newest"


@pytest.mark.asyncio
async def test_classify_endpoint(app_client, app_auth_headers):
    resp = await app_client.get(
        "/api/candidates/keywords/classify",
        params={"q": "senior java z bankowością"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["as_requirements"] is False


# ── „Szukaj ręcznie”: ułożenie początku listy oceną „Dop.” ─────────────────


class _Fit:
    def __init__(self, cid: int, score):
        self.breakdown = type("B", (), {"candidate_id": cid})()
        self.fit_score = score


@pytest.fixture
def job_vectors(monkeypatch):
    """Ścieżka rekrutacji: wektor jak w ``fake_vectors``, ocena z atrapy.

    ``state["fits"]`` — ocena per klucz osoby (albo wyjątek), ``state["fp"]`` —
    odcisk kontekstu, ``state["calls"]`` — liczba wywołań oceny.
    """
    from types import SimpleNamespace

    from app.services import canonical_fit

    state: dict[str, Any] = {"fits": {}, "fp": "fp-1", "calls": 0, "ids": {}}

    async def fake_resolve(db, user, filters, groups):
        return cmo.MatchVector(
            vector=[1.0],
            key="test-job:fixed",
            kind="job",
            context=SimpleNamespace(fingerprint=state["fp"]),
        )

    def fake_scores(vector, candidate_ids):
        ids = state["ids"]
        return {ids["oldest_best"]: 0.9, ids["middle"]: 0.5, ids["newest_weak"]: 0.1}

    async def fake_score_candidates(db, context, candidates):
        state["calls"] += 1
        fits = state["fits"]
        if isinstance(fits, Exception):
            raise fits
        by_id = {v: k for k, v in state["ids"].items()}
        return [
            _Fit(c.id, fits.get(by_id[c.id]))
            for c in candidates
            if c.id in by_id and by_id[c.id] in fits
        ]

    monkeypatch.setattr(cmo, "resolve_vector", fake_resolve)
    monkeypatch.setattr(cmo, "_qdrant_scores", fake_scores)
    monkeypatch.setattr(canonical_fit, "score_candidates", fake_score_candidates)
    cmo.clear_cache()
    yield state
    cmo.clear_cache()


@pytest.mark.asyncio
async def test_job_order_follows_fit_score(app_client, app_auth_headers, job_vectors):
    job_vectors["ids"].update(await _seed())
    job_vectors["fits"] = {"oldest_best": 10.0, "middle": 50.0, "newest_weak": 90.0}
    order, body = await _ids(app_client, app_auth_headers, sort="match")
    assert order == ["newest_weak", "middle", "oldest_best"]
    assert body["sort_applied"] == "match"


@pytest.mark.asyncio
async def test_job_preferred_with_low_fit_stays_first(
    app_client, app_auth_headers, job_vectors
):
    job_vectors["ids"].update(await _seed())
    job_vectors["fits"] = {"oldest_best": 60.0, "middle": 5.0, "newest_weak": 90.0}
    order, _ = await _ids(
        app_client, app_auth_headers, sort="match", skills_preferred="kotlin"
    )
    assert order == ["middle", "newest_weak", "oldest_best"]


@pytest.mark.asyncio
async def test_job_unmeasured_go_last_in_their_group(
    app_client, app_auth_headers, job_vectors
):
    job_vectors["ids"].update(await _seed())
    job_vectors["fits"] = {"oldest_best": None, "middle": 30.0, "newest_weak": 20.0}
    order, _ = await _ids(app_client, app_auth_headers, sort="match")
    assert order == ["middle", "newest_weak", "oldest_best"]


@pytest.mark.asyncio
async def test_job_scoring_failure_keeps_vector_order(
    app_client, app_auth_headers, job_vectors
):
    job_vectors["ids"].update(await _seed())
    job_vectors["fits"] = RuntimeError("scoring down")
    order, body = await _ids(app_client, app_auth_headers, sort="match")
    assert order == ["oldest_best", "middle", "newest_weak"]
    assert body["sort_applied"] == "match"


@pytest.mark.asyncio
async def test_job_rerank_switch_off_keeps_vector_order(
    app_client, app_auth_headers, job_vectors, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CANDIDATE_MATCH_RERANK_TOP", 0)
    job_vectors["ids"].update(await _seed())
    job_vectors["fits"] = {"oldest_best": 10.0, "middle": 50.0, "newest_weak": 90.0}
    order, _ = await _ids(app_client, app_auth_headers, sort="match")
    assert order == ["oldest_best", "middle", "newest_weak"]
    assert job_vectors["calls"] == 0


@pytest.mark.asyncio
async def test_job_order_cache_follows_the_fingerprint(
    app_client, app_auth_headers, job_vectors
):
    job_vectors["ids"].update(await _seed())
    job_vectors["fits"] = {"oldest_best": 10.0, "middle": 50.0, "newest_weak": 90.0}
    first, _ = await _ids(app_client, app_auth_headers, sort="match")
    assert first == ["newest_weak", "middle", "oldest_best"]

    # Ten sam odcisk — kolejność z pamięci, bez ponownej oceny.
    job_vectors["fits"] = {"oldest_best": 90.0, "middle": 50.0, "newest_weak": 10.0}
    cached, _ = await _ids(app_client, app_auth_headers, sort="match")
    assert cached == first
    assert job_vectors["calls"] == 1

    # Inny profil wag (odcisk) — nowa kolejność.
    job_vectors["fp"] = "fp-2"
    fresh, _ = await _ids(app_client, app_auth_headers, sort="match")
    assert fresh == ["oldest_best", "middle", "newest_weak"]
    assert job_vectors["calls"] == 2
