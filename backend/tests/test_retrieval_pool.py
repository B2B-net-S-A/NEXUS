"""Fasada puli — jeden flip dla czterech powierzchni, skala semantyczna nietknięta.

Decyzja zamrożona tu testami: hybryda wybiera CZŁONKOSTWO puli, ale warstwa
semantyczna scoringu dalej dostaje KOSINUSY. Wyniki fuzji RRF (~1/60 na
pozycję) i rerankera żyją na innych skalach — wpuszczone do `similarity_map`
rozstroiłyby kalibrację (gamma, frakcja neutralna) i zatruły cache score'ów.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_flag_off_is_a_verbatim_passthrough(monkeypatch):
    """Wyłączona flaga = dosłownie dzisiejsza ścieżka, wywołanie za wywołanie."""

    from app.services import retrieval_pool as rp

    sentinel = [{"candidate_id": 1, "score": 0.9}]
    seen: dict = {}

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        seen.update(query=query, top_k=top_k, raise_on_error=raise_on_error)
        return sentinel

    async def exploding_hybrid(*a, **k):  # pragma: no cover - nie wolno
        raise AssertionError("hybryda nie może być wołana przy wyłączonej fladze")

    from app.services import embedding_service

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", exploding_hybrid)
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: False)

    out = await rp.retrieve_candidate_pool(
        object(), "Senior Python", top_k=200, raise_on_error=True
    )

    assert out is sentinel
    assert seen == {"query": "Senior Python", "top_k": 200, "raise_on_error": True}


@pytest.mark.asyncio
async def test_flag_on_membership_from_hybrid_scores_from_cosine(monkeypatch):
    """SEDNO: kto wchodzi — decyduje hybryda; ile podobieństwa — kosinus.

    Wynik RRF kandydata 7 (0.032) NIE może trafić do `score` — tam ma być jego
    kosinus (0.81), ta sama pasażo-świadoma miara co przy wyłączonej fladze.
    """

    from app.services import retrieval_pool as rp

    async def fake_hybrid(db, query, *, pool, final_top_k, use_rerank):
        return SimpleNamespace(
            pairs=[(7, 0.032), (9, 0.031), (4, 0.030)], degraded=False
        )

    async def fake_cosines(query, ids):
        assert ids == [7, 9, 4], "kosinusy liczone dokładnie dla wybranych"
        return {7: 0.81, 4: 0.55}  # 9 celowo bez wektora

    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", fake_hybrid)
    from app.services import embedding_service

    monkeypatch.setattr(embedding_service, "similarity_for_candidate_ids", fake_cosines)
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)

    out = await rp.retrieve_candidate_pool(object(), "Senior Python", top_k=3)

    assert [row["candidate_id"] for row in out] == [7, 9, 4], "kolejność z hybrydy"
    by_id = {row["candidate_id"]: row["score"] for row in out}
    assert by_id[7] == 0.81 and by_id[4] == 0.55, "score = kosinus, nie RRF"
    assert by_id[9] == 0.0, (
        "kandydat bez wektora zostaje w puli z zerowym sygnałem semantycznym — "
        "pozostałe warstwy scoringu wciąż mogą go wynieść"
    )


@pytest.mark.asyncio
async def test_hybrid_failure_falls_back_to_semantic_when_swallowing(monkeypatch):
    """`raise_on_error=False` obowiązuje też na gałęzi hybrydowej.

    Konsumenci (rekomendacje, Talent Radar) wołają z domyślnym `False` i liczą
    na łagodną degradację — flip flagi nie może zamienić awarii silnika w 500.
    Spadek idzie na ścieżkę semantyczną, nie w pustkę: awaria NOWEGO silnika
    nie może degradować puli poniżej stanu sprzed flagi.
    """

    from app.services import retrieval_pool as rp

    async def exploding_hybrid(*a, **k):
        raise RuntimeError("BM25 w awarii")

    sentinel = [{"candidate_id": 3, "score": 0.7}]
    seen: dict = {}

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        seen.update(raise_on_error=raise_on_error)
        return sentinel

    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", exploding_hybrid)
    from app.services import embedding_service

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)

    out = await rp.retrieve_candidate_pool(object(), "Senior Python", top_k=5)

    assert out is sentinel
    assert seen == {"raise_on_error": False}, (
        "fallback sam też musi połykać — inaczej pierwotny kontrakt wraca bokiem"
    )


@pytest.mark.asyncio
async def test_hybrid_failure_propagates_when_raising(monkeypatch):
    """`raise_on_error=True` (harness ewaluacyjny) ma widzieć awarię, nie maskę."""

    from app.services import retrieval_pool as rp

    async def exploding_hybrid(*a, **k):
        raise RuntimeError("BM25 w awarii")

    async def forbidden_semantic(*a, **k):  # pragma: no cover - nie wolno
        raise AssertionError("przy raise_on_error=True nie ma fallbacku")

    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", exploding_hybrid)
    from app.services import embedding_service

    monkeypatch.setattr(
        embedding_service, "search_candidates_semantic", forbidden_semantic
    )
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)

    with pytest.raises(RuntimeError, match="BM25 w awarii"):
        await rp.retrieve_candidate_pool(
            object(), "Senior Python", top_k=5, raise_on_error=True
        )


@pytest.mark.asyncio
async def test_cosine_failure_after_bm25_gives_zero_score_pool(monkeypatch):
    """Voyage pada PO udanym BM25 → pula BM25-only z score=0.0, nie wyjątek.

    To ta sama semantyka co „kandydat bez wektora", tylko dla wszystkich naraz —
    dokładne tokeny wciąż działają, a pusta pula byłaby gorsza od uboższej.
    """

    from app.services import retrieval_pool as rp

    async def fake_hybrid(db, query, *, pool, final_top_k, use_rerank):
        return SimpleNamespace(pairs=[(7, 0.032), (4, 0.030)], degraded=False)

    async def exploding_cosines(query, ids):
        raise RuntimeError("Voyage w awarii")

    import app.services.hybrid_search as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", fake_hybrid)
    from app.services import embedding_service

    monkeypatch.setattr(
        embedding_service, "similarity_for_candidate_ids", exploding_cosines
    )
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)

    out = await rp.retrieve_candidate_pool(object(), "Senior Python", top_k=2)

    assert [row["candidate_id"] for row in out] == [7, 4]
    assert all(row["score"] == 0.0 for row in out)

    with pytest.raises(RuntimeError, match="Voyage w awarii"):
        await rp.retrieve_candidate_pool(
            object(), "Senior Python", top_k=2, raise_on_error=True
        )


def test_hybrid_flag_is_deliberately_absent_from_scoring_cache_inputs():
    """Zamrożona decyzja, nie przeoczenie.

    Skala semantyczna przy włączonej hybrydzie NIE zmienia się (kosinusy są
    re-derywowane per kandydat), więc istniejące wiersze cache pozostają
    poprawne — inwalidacja całej tabeli byłaby czystym kosztem bez korekty.
    Jeśli kiedyś fasada zacznie wpuszczać do `score` coś innego niż kosinus,
    ten test trzeba ŚWIADOMIE usunąć i dopisać flagę do klucza.
    """

    from app.services.scoring_service import _SCORING_CACHE_INPUTS

    assert "HYBRID_POOL_ENABLED" not in _SCORING_CACHE_INPUTS


def test_all_four_pool_sites_go_through_the_facade():
    """Częściowy flip to jedyny naprawdę błędny stan — patrz pasaże.

    Każde z czterech miejsc puli (rekomendacje, Talent Radar, propozycje, eval)
    woła fasadę; żadne nie woła `search_candidates_semantic` bezpośrednio dla
    PULI. (Inne użycia — np. `similarity_for_candidate_ids` — zostają.)
    """

    sites = {
        "app/api/recommendations.py",
        "app/services/talent_radar_search.py",
        "app/tasks/compute_proposals.py",
        "scripts/eval_matching.py",
    }
    for rel in sites:
        source = (BACKEND / rel).read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "retrieve_candidate_pool" in calls, f"{rel}: pula poza fasadą"
        assert "search_candidates_semantic" not in calls, (
            f"{rel}: bezpośrednie wywołanie puli obok fasady — częściowy flip"
        )
        # Wariant atrybutowy (`embedding_service.search_candidates_semantic(...)`)
        # to inny węzeł AST (`ast.Attribute`, nie `ast.Name`) — bez tej gałęzi
        # strażnik przepuściłby refaktor na import modułu, chroniąc mniej, niż
        # obiecuje jego nazwa.
        attr_calls = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        assert "search_candidates_semantic" not in attr_calls, (
            f"{rel}: atrybutowe wywołanie puli obok fasady — częściowy flip"
        )


# ── multi-query (runda 2): unia wariantów, kosinusy z zapytania głównego ─────


@pytest.mark.asyncio
async def test_multi_query_union_membership_primary_similarity(monkeypatch):
    """Warianty dosypują CZŁONKOSTWO; podobieństwo dosypki liczy się względem
    zapytania GŁÓWNEGO (ta sama zasada co hybryda — jedna skala kosinusa)."""

    from app.services import embedding_service
    from app.services import retrieval_pool as rp

    calls: list[str] = []

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        calls.append(query)
        if query == "PRIMARY":
            return [
                {"candidate_id": 1, "score": 0.9},
                {"candidate_id": 2, "score": 0.8},
            ]
        return [
            {"candidate_id": 2, "score": 0.99},  # duplikat — zostaje primary 0.8
            {"candidate_id": 3, "score": 0.95},  # nowy — kosinus z primary
        ]

    async def fake_similarity(query, ids):
        assert query == "PRIMARY", "kosinusy dosypki MUSZĄ iść z tekstu głównego"
        assert ids == [3]
        return {3: 0.55}

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    monkeypatch.setattr(
        embedding_service, "similarity_for_candidate_ids", fake_similarity
    )
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: False)
    monkeypatch.setattr(rp, "multi_query_enabled", lambda: True)

    out = await rp.retrieve_candidate_pool(
        object(), "PRIMARY", top_k=10, query_variants=["wariant skillowy"]
    )

    assert calls == ["PRIMARY", "wariant skillowy"]
    assert out == [
        {"candidate_id": 1, "score": 0.9},
        {"candidate_id": 2, "score": 0.8},
        {"candidate_id": 3, "score": 0.55},
    ]


@pytest.mark.asyncio
async def test_multi_query_flag_off_single_call(monkeypatch):
    from app.services import embedding_service
    from app.services import retrieval_pool as rp

    calls: list[str] = []

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        calls.append(query)
        return []

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: False)
    monkeypatch.setattr(rp, "multi_query_enabled", lambda: False)

    await rp.retrieve_candidate_pool(
        object(), "PRIMARY", top_k=10, query_variants=["w1", "w2"]
    )
    assert calls == ["PRIMARY"], "flaga OFF ⇒ warianty ignorowane"


@pytest.mark.asyncio
async def test_multi_query_variant_failure_does_not_kill_pool(monkeypatch):
    from app.services import embedding_service
    from app.services import retrieval_pool as rp

    async def fake_semantic(query, *, top_k, raise_on_error=False):
        if query == "PRIMARY":
            return [{"candidate_id": 1, "score": 0.9}]
        raise RuntimeError("wariant padł")

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", fake_semantic)
    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: False)
    monkeypatch.setattr(rp, "multi_query_enabled", lambda: True)

    out = await rp.retrieve_candidate_pool(
        object(), "PRIMARY", top_k=10, query_variants=["zly"]
    )
    assert out == [{"candidate_id": 1, "score": 0.9}]


def test_multi_query_flag_is_deliberately_absent_from_scoring_cache_inputs():
    """Multi-query zmienia tylko CZŁONKOSTWO puli — kosinus per kandydat jest
    ten sam, więc cache score'ów pozostaje poprawny (jak przy hybrydzie)."""
    from app.services.scoring_service import _SCORING_CACHE_INPUTS

    assert "MULTI_QUERY_RETRIEVAL_ENABLED" not in _SCORING_CACHE_INPUTS
