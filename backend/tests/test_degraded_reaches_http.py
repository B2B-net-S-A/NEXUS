"""Stan „nie wiem" musi wyjść z handlera, a nie zostać nadpisany na „pusto".

`fetch_similar_jobs` zwraca `"degraded"`, gdy wyszukiwanie podobnych ofert nie
odpowiedziało. Degradacja z DEFINICJI daje pustą listę refów, więc jedyną drogą,
którą ta informacja może opuścić handler, jest wczesny return na `if not
similar_refs:` — a ten nadpisywał `tier_used` na `"empty"` na sztywno. Skutek:
rekruter widział podczas awarii Qdranta komunikat o BRAKU historii, czyli fakt
o świecie zamiast informacji o awarii. Ta sama klasa co #408, odtworzona tuż
obok jej naprawy.

Drugi, uśpiony skutek: `TierUsed` nie zawierał `"degraded"`, więc samo
przepuszczenie wartości bez rozszerzenia Literala dałoby ValidationError na
`response_model`, czyli 500 zamiast odpowiedzi.
"""

import pytest


def test_tier_used_literal_admits_degraded():
    """Bez tego przepuszczenie wartości kończy się 500, a nie odpowiedzią."""
    from typing import get_args

    from app.schemas.similar_job_candidates import TierUsed

    assert "degraded" in get_args(TierUsed), (
        "response_model odrzuci `degraded` i handler zwróci 500 zamiast "
        "powiedzieć, że nie wie"
    )


def test_handler_does_not_hardcode_empty_on_the_early_return():
    """Czytamy ŹRÓDŁO: wczesny return musi rozgałęziać, a nie stawiać `empty`.

    Test strukturalny, bo ścieżka wymaga niedostępnego Qdranta — a atrapa
    Qdranta sprawdzałaby atrapę, nie ten `return`.
    """
    import ast
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[1] / "app/api/recommendations.py"
    ).read_text()
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and "candidates_from_similar" in n.name
    )
    # znajdź `if not similar_refs:` i jego return
    guard = next(
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.UnaryOp)
        and isinstance(n.test.op, ast.Not)
        and getattr(n.test.operand, "id", None) == "similar_refs"
    )
    dumped = ast.dump(guard)
    assert "IfExp" in dumped, (
        "wczesny return nie rozgałęzia — `degraded` jest nadpisywane na sztywno "
        "i nie ma ŻADNEJ drogi, którą mogłoby wyjść z handlera"
    )
    assert "similar_jobs_unavailable" in dumped, (
        "brak osobnego powodu dla awarii — front nie odróżni jej od pustki"
    )


def test_frontend_type_mirrors_the_backend_literal():
    """Rozjazd typów znaczy, że front nigdy nie zobaczy tego stanu."""
    import pathlib

    api = (
        pathlib.Path(__file__).resolve().parents[2] / "frontend/src/lib/api.ts"
    ).read_text()
    i = api.index("HistoricalTierUsed")
    assert '"degraded"' in api[i : i + 300], (
        "HistoricalTierUsed nie zna `degraded` — backend wysyła stan, którego "
        "typ po drugiej stronie nie dopuszcza"
    )


def test_section_renders_degraded_as_failure_not_as_empty():
    """Pusty stan podczas awarii czyta się jako „nie ma historii"."""
    import pathlib

    tsx = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend/src/components/HistoricalCandidatesSection.tsx"
    ).read_text()
    assert 'tierUsed === "degraded"' in tsx, "komponent nie rozpoznaje degradacji"
    i = tsx.index("degraded ? (")
    j = tsx.index('viewState === "empty"', i)
    branch = tsx[i:j]
    assert "Ponów" in branch, "brak ponowienia — użytkownik zostaje bez wyjścia"
    assert "nie wiadomo" in branch, (
        "komunikat nie mówi, że to niewiedza, a nie brak danych"
    )
