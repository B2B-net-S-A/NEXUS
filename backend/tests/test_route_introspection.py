"""Helper wyliczający trasy musi widzieć CAŁĄ aplikację, nie jej fragment.

Pięć testów autoryzacji opiera swoje asercje na tym, co zwróci
``iter_api_routes``. Jeśli helper zacznie gubić trasy — po zmianie w FastAPI,
po dodaniu zagnieżdżonego routera, po refaktorze — te testy nie zrobią się
czerwone. Zrobią się **puste**: przelecą po zbiorze mniejszym, niż myślą, i
zameldują sukces. Dokładnie tak wyglądała awaria, która ten helper wywołała
(FastAPI 0.139: pętla po ``app.routes`` widziała 4 trasy zamiast 789, a kontrakt
autoryzacji zażądał skasowania 148 wpisów baseline'u).

Te testy są więc asercją przeciw samemu narzędziu, nie przeciw aplikacji.
"""

from __future__ import annotations

import pytest

from tests._route_introspection import api_route_methods, iter_api_routes


# Zmierzone 2026-07-27 na FastAPI 0.115.6 ORAZ 0.139.0 — oba kształty dały ten
# sam zbiór. Próg, nie dokładna liczba: trasy przybywają, więc twarda równość
# psułaby się przy każdej nowej funkcji. Ale spadek poniżej progu znaczy, że
# helper przestał widzieć całość, i to musi być czerwone.
_MINIMUM_API_ROUTES = 700


def _app():
    from app.main import app

    return app


def test_helper_sees_the_whole_application() -> None:
    routes = api_route_methods(_app())
    assert len(routes) >= _MINIMUM_API_ROUTES, (
        f"iter_api_routes widzi tylko {len(routes)} tras /api/** (próg "
        f"{_MINIMUM_API_ROUTES}). Na FastAPI 0.139+ gołe `app.routes` daje 4 — "
        "jeśli ta liczba jest bliska zeru, helper przestał rozwijać "
        "_IncludedRouter i pięć testów autoryzacji właśnie przestało cokolwiek "
        "sprawdzać."
    )


def test_every_path_is_absolute_and_prefixed() -> None:
    """Prefiks z ``include_router`` musi trafić do ścieżki.

    Bez tego helper zwróciłby ``/login`` zamiast ``/api/auth/login`` — filtr
    ``startswith("/api/")`` odrzuciłby wszystko i kontrakt autoryzacji zrobiłby
    się pusty, zamiast czerwony.
    """
    paths = [p for p, _ in iter_api_routes(_app())]
    assert paths, "helper nie zwrócił żadnej trasy"
    relative = [p for p in paths if not p.startswith("/")]
    assert not relative, f"ścieżki bez wiodącego ukośnika: {relative[:5]}"

    api = [p for p in paths if p.startswith("/api/")]
    assert len(api) >= _MINIMUM_API_ROUTES, (
        f"tylko {len(api)} ścieżek zaczyna się od /api/ — prefiksy routerów "
        "prawdopodobnie nie są doklejane"
    )


@pytest.mark.parametrize(
    "expected",
    [
        ("POST", "/api/auth/login"),
        ("GET", "/api/candidates"),
        ("GET", "/api/jobs"),
    ],
)
def test_known_routes_are_found(expected: tuple[str, str]) -> None:
    """Kotwice na trasach, które istnieją od dawna i nie znikną po cichu."""
    assert expected in api_route_methods(_app()), (
        f"{expected[0]} {expected[1]} nie znaleziona przez helper — "
        "albo trasa zniknęła, albo helper gubi jej router"
    )
