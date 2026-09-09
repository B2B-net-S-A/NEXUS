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
    """Wołający, który PISZE do cache'u, musi czytać `semantic_unknown`.

    Test czyta ŹRÓDŁO, bo defekt jest w tym, czego kod NIE robi, a przejście
    całej ścieżki `/recommendations` wymaga Qdranta, Voyage i zaseedowanej
    oferty — czyli testowałoby wszystko poza tą jedną linijką.

    Trzy warunki naraz, bo każdy z osobna daje się spełnić pozornie:
    sam odczyt klucza bez wpięcia w `semantic_degraded` niczego nie blokuje,
    a `semantic_degraded` nadal wisi na `allow_cache_write`.
    """
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "app" / "api" / "recommendations.py"
    ).read_text(encoding="utf-8")

    assert "semantic_unknown" in src, (
        "`/recommendations` pisze do candidate_job_match_scores i musi "
        "rozpoznawać pulę bez zmierzonych kosinusów"
    )
    assert "semantic_degraded = not candidate_ids or" in src, (
        "sama pustka nie wystarcza: pula pełna zer z awarii JEST niepusta"
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
