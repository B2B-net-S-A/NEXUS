"""Awaria kosinusów oddaje pulę z `score=0.0`, a wołający czyta ją jako zdrową.

`retrieve_candidate_pool` w trybie hybrydowym (i wielo-zapytaniowym) ma
udokumentowaną, świadomą degradację: gdy dosypka kosinusów padnie PO udanym
BM25, kandydaci wchodzą do puli z `score=0.0` („brak sygnału semantycznego",
nie wykluczenie). Sama pula jest wtedy nadal użyteczna.

Problem jest u WOŁAJĄCEGO. `api/recommendations.py` rozpoznaje degradację
wyłącznie po PUSTCE:

    semantic_degraded = not candidate_ids
    ...
    allow_cache_write=not semantic_degraded

Pula pełna zer jest niepusta, więc `semantic_degraded` zostaje `False`,
`allow_cache_write` zostaje `True` i warstwa semantyczna licząca 0/60 punktów
ląduje w `candidate_job_match_scores` jako wynik ŚWIEŻY — dokładnie klasa
M3-CACHE-01, przed którą ta gałąź miała bronić. Wiersz przeżywa powrót dostawcy
(nic go nie unieważnia: klucz cache'u nie zna zdrowia providera), a `meta`
mówi `mode="dense"`, czyli „wynik zdrowy".

Ten plik zamraża kontrakt, którego dziś nie ma: pula MUSI umieć powiedzieć, że
jej wyniki semantyczne są nieznane, a nie tylko puste.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_pool_reports_missing_cosines_instead_of_passing_zeros_off_as_scores(
    monkeypatch,
):
    """Pula z zerami po awarii kosinusów musi być ODRÓŻNIALNA od zdrowej.

    Bez tego sygnału jedynym testem degradacji, jaki ma wołający, jest pustka —
    a ta gałąź z definicji zwraca listę NIEPUSTĄ.
    """
    from app.services import embedding_service, retrieval_pool as rp
    from app.services import hybrid_search as hybrid_module
    from app.services.hybrid_search import HybridResult

    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)

    async def fake_hybrid(db, query, **kwargs):
        # Noga BM25 zadziałała — pula ma trzech ludzi.
        return HybridResult(pairs=[(11, 0.9), (22, 0.8), (33, 0.7)])

    async def exploding_cosines(query, ids):
        raise RuntimeError("Voyage 503")

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", fake_hybrid)
    monkeypatch.setattr(
        embedding_service, "similarity_for_candidate_ids", exploding_cosines
    )

    pool = await rp.retrieve_candidate_pool(object(), "Senior Python", top_k=50)

    assert [row["candidate_id"] for row in pool] == [11, 22, 33], (
        "pula BM25 zostaje — awaria kosinusów nie może jej zamienić w pustkę"
    )
    assert all(row["score"] == 0.0 for row in pool), (
        "warunek wstępny: to jest właśnie ta udokumentowana degradacja"
    )
    assert all(row.get("semantic_unknown") for row in pool), (
        "zero z awarii MUSI być odróżnialne od zmierzonego zera — inaczej "
        "wołający zapisze warstwę semantyczną 0/60 do cache'u jako wynik świeży"
    )


@pytest.mark.asyncio
async def test_healthy_pool_does_not_claim_unknown_semantics(monkeypatch):
    """Kontrola negatywna: zdrowa pula nie może podnosić tej flagi.

    Bez tego testu „napraw" polegająca na oznaczaniu wszystkiego jako nieznane
    przechodziłaby na zielono i wyłączyłaby zapis cache'u na stałe.
    """
    from app.services import embedding_service, retrieval_pool as rp
    from app.services import hybrid_search as hybrid_module
    from app.services.hybrid_search import HybridResult

    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)

    async def fake_hybrid(db, query, **kwargs):
        return HybridResult(pairs=[(11, 0.9), (22, 0.8)])

    async def real_cosines(query, ids):
        return {11: 0.61, 22: 0.44}

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", fake_hybrid)
    monkeypatch.setattr(embedding_service, "similarity_for_candidate_ids", real_cosines)

    pool = await rp.retrieve_candidate_pool(object(), "Senior Python", top_k=50)

    assert [row["score"] for row in pool] == [0.61, 0.44]
    assert not any(row.get("semantic_unknown") for row in pool)


@pytest.mark.asyncio
async def test_candidate_without_a_vector_is_unknown_not_a_measured_zero(
    monkeypatch,
):
    """Kandydat z BM25 bez wektora w indeksie też nie ma ZMIERZONEGO zera.

    Ta gałąź jest w kodzie opisana jako „przyszłościowa" (pokrycie indeksu
    100%), ale niesie tę samą pomyłkę co awaria: 0.0 wpisane w miejsce
    „nie wiem" jedzie do scoringu jako pełna kara w warstwie wartej 60 pkt.
    """
    from app.services import embedding_service, retrieval_pool as rp
    from app.services import hybrid_search as hybrid_module
    from app.services.hybrid_search import HybridResult

    monkeypatch.setattr(rp, "hybrid_pool_enabled", lambda: True)

    async def fake_hybrid(db, query, **kwargs):
        return HybridResult(pairs=[(11, 0.9), (99, 0.8)])

    async def partial_cosines(query, ids):
        return {11: 0.61}  # 99 nie ma wektora

    monkeypatch.setattr(hybrid_module, "hybrid_candidates", fake_hybrid)
    monkeypatch.setattr(
        embedding_service, "similarity_for_candidate_ids", partial_cosines
    )

    pool = {
        row["candidate_id"]: row
        for row in await rp.retrieve_candidate_pool(object(), "Senior Python", top_k=50)
    }

    assert not pool[11].get("semantic_unknown")
    assert pool[99].get("semantic_unknown"), (
        "brak wektora to brak pomiaru, nie pomiar równy zeru"
    )


def test_recommendations_treats_unknown_semantics_as_degraded():
    """`/recommendations` musi rozpoznawać pulę bez zmierzonych kosinusów.

    Test czyta ŹRÓDŁO, bo defekt jest w tym, czego kod NIE robi, a przejście
    całej ścieżki wymaga Qdranta, Voyage i zaseedowanej oferty — czyli
    testowałoby wszystko poza tą jedną linijką.

    **Zmiana z 18.09.2026: rozpoznawać ≠ alarmować przy każdym wierszu.**
    Pierwotnie warunek brzmiał „ktokolwiek bez pomiaru", a ponieważ w puli
    prawie zawsze jest ktoś bez wektora, baner „tryb awaryjny" świecił non
    stop: zmierzone 20 z 21 losowych rekrutacji przy `checks.qdrant`
    i `checks.voyage` = healthy. Jedyny sygnał ostrzegający przed nieufnym
    rankingiem przestał więc cokolwiek znaczyć, a REALNA awaria była od
    normalnej pracy nieodróżnialna. Teraz: awaria SILNIKA
    (`semantic_engine_down`) albo brak pomiaru dla WSZYSTKIEGO, co widać.

    Ochrona cache'u, o którą chodziło pierwotnie, jest dziś niepotrzebna na
    tej ścieżce z innego powodu: `/recommendations` nie pisze już legacy
    composites (pilnuje tego asercja niżej).
    """
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "app" / "api" / "recommendations.py"
    ).read_text(encoding="utf-8")

    assert "semantic_engine_down" in src, (
        "pula musi odróżniać awarię silnika od kandydata bez wektora"
    )
    assert "semantic_degraded = not candidate_ids or semantic_engine_down" in src, (
        "sama pustka nie wystarcza, ale pojedynczy brak wektora to nie awaria"
    )
    assert "nothing_measured" in src, (
        "brak pomiaru dla WSZYSTKIEGO, co widać, nadal musi zapalać baner"
    )
    assert "any(fit.fit_score is None for fit in fits)" not in src, (
        "„ktokolwiek bez pomiaru” to powrót do banera świecącego non stop"
    )
    from tests._ast_calls import calls_in

    calls = calls_in("app/api/recommendations.py", "_recommend_candidates_core")
    assert "score_candidates" in calls
    assert "bulk_get_or_compute" not in calls, (
        "canonical recommendations must not write/read legacy composites"
    )


def test_canonical_consumers_cannot_return_to_legacy_cache():
    """Migrated consumers must remeasure fit and never reuse legacy composites."""
    import ast
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    for rel in (
        "app/api/recommendations.py",
        "app/api/matching.py",
        "app/tasks/compute_proposals.py",
        "app/tasks/match_digest.py",
        # Manual search score column (09.2026): read the legacy cache until
        # then, which nothing on the current ranker writes — an empty column.
        "app/api/search.py",
    ):
        tree = ast.parse((backend / rel).read_text(encoding="utf-8"))
        calls = {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        assert "score_candidates" in calls, f"{rel} must use canonical measurement"
        assert not calls.intersection({"bulk_get_or_compute", "get_or_compute"}), (
            f"{rel} must not read/write legacy fit composites"
        )


def test_search_score_column_reads_no_legacy_cache():
    """The job-context search badge must measure canonical fit, not read cache.

    `fresh_score_conditions` is the ONE definition of "a fresh legacy cache
    row". Reading it here is what left the column empty on production: since
    #1428 no current-ranker path writes those rows. The display surfaces now
    measure on demand (bounded to the visible rows), like every C2 screen.
    """
    from tests._ast_calls import calls_in

    calls = calls_in("app/api/search.py", "candidate_match_scores")
    assert "score_candidates" in calls
    assert not calls.intersection(
        {
            "fresh_score_conditions",
            "bulk_get_or_compute",
            "get_or_compute",
            "get_cached_or_compute",
        }
    ), "the score column must not read or write legacy fit composites"


def test_dopasowanie_tab_displays_the_canonical_number():
    """The tab's ring must show the number C2 shows for the pair.

    The prose may still be generated from the legacy breakdown (its cache key
    is unchanged on purpose), but the displayed score comes from
    `score_candidates` under the viewer's profile.
    """
    from tests._ast_calls import calls_in

    calls = calls_in("app/services/match_justification_service.py", "display_fit")
    assert "score_candidates" in calls
    assert "resolve_active_profile" in calls
    assert not calls.intersection(
        {"get_cached_or_compute", "bulk_get_or_compute", "get_or_compute"}
    )
