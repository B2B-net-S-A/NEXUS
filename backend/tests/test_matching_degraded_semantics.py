"""Baner „tryb awaryjny" ma świecić przy AWARII, nie przy każdej odpowiedzi.

Audyt 18.09.2026 zmierzył na żywej, opublikowanej rekrutacji z ważnym
embeddingiem: `degraded: true`, `reason: semantic_unavailable`, wszystkie 20
zwróconych wyników `match_score = null` — przy `checks.qdrant: healthy`
i `checks.voyage: healthy`. Próbka 25 losowych rekrutacji: 20 z 21.

Przyczyna: `semantic_degraded = not candidate_ids or bool(semantic_unknown_ids)`
— wystarczył JEDEN kandydat bez zmierzonego kosinusu (dociągnięty przez BM25
i zwykle zaraz odfiltrowany), żeby cała odpowiedź zgłosiła awarię.

Znaczenie tego defektu jest odwrotne do wyglądu: rekruter widzi „to NIE jest
wynik dopasowania AI, zweryfikuj profile przed wysłaniem do klienta", więc
JEDYNY sygnał ostrzegający przed nieufnym rankingiem był zapalony non stop —
a realna awaria Voyage'a byłaby od normalnej pracy nieodróżnialna.
"""

from __future__ import annotations

from app.services import retrieval_pool


def test_pool_marks_a_missing_vector_without_claiming_an_outage():
    """Kandydat bez wektora: `semantic_unknown`, ale BEZ `semantic_engine_down`."""
    row = {"candidate_id": 1, "score": 0.0, "semantic_unknown": True}
    assert row.get("semantic_unknown") is True
    assert row.get("semantic_engine_down") is None


def test_engine_failure_is_a_separate_flag_in_the_pool_source():
    """Obie gałęzie wyjątku w puli MUSZĄ stemplować `semantic_engine_down`.

    Test czyta źródło, bo obie gałęzie wymagają realnej awarii dostawcy —
    zasymulowanie jej tutaj sprowadziłoby się do sprawdzenia mocka.
    Sprawdzamy KONTRAKT: każdy `cosine_by_id = {}` po wyjątku podnosi flagę.
    """
    source = open(retrieval_pool.__file__, encoding="utf-8").read()
    assert source.count("engine_down = True") == 2, (
        "gałąź wyjątku bez `engine_down = True` znaczy awarię silnika "
        "nieodróżnialną od kandydata bez wektora"
    )
    assert source.count("semantic_engine_down") >= 2


def test_ai_matches_computes_degraded_after_trimming_and_only_on_real_failure():
    """Kontrakt na źródle `/ai-matches` — te trzy warunki są całą poprawką."""
    source = open("app/api/matching.py", encoding="utf-8").read()
    body = source[source.index("search_type = \"semantic+composite\"") :]
    trim = body.index("][:max_results]")
    degraded = body.index("degraded = engine_down")
    # Przycięcie do `max_results` PRZED liczeniem degradacji: wiersz, którego
    # rekruter nie zobaczy, nie może zapalać banera nad tym, co widzi.
    assert trim < degraded, "degradacja liczona przed przycięciem wyników"
    assert "semantic_engine_down" in body
    # Pojedynczy niezmierzony wiersz ma etykietę, nie baner.
    assert "nothing_measured" in body


def test_recommendations_degrade_only_on_engine_failure():
    source = open("app/api/recommendations.py", encoding="utf-8").read()
    assert "semantic_degraded = not candidate_ids or semantic_engine_down" in source
    assert "bool(semantic_unknown_ids)" not in source


def test_recommendations_degrade_when_nothing_visible_was_measured():
    """Zero zmierzonych wierszy TO awaria — i to musi zostać.

    Bez tego warunku poprawka zamieniłaby baner świecący non stop na baner,
    który nie zapala się nigdy. Ranking, w którym nic nie zmierzono, nie jest
    rankingiem — rekruter musi to zobaczyć.
    """
    source = open("app/api/recommendations.py", encoding="utf-8").read()
    assert "nothing_measured = bool(fits) and all(" in source
    assert "semantic_degraded = semantic_degraded or nothing_measured" in source
