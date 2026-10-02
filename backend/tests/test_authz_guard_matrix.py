"""Kto przechodzi bramki której trasy — wzorzec zapisany w repo.

Ekran uprawnień obiecuje ludziom konkretne rzeczy, a o dostępie decydują
zależności tras. Ten test trzyma jedno z drugim razem: dla każdej trasy
i każdej persony porównuje werdykt bramek z plikami
``tests/data/authz_golden/<moduł>.json``.

Zmiana werdyktu = czerwony test z listą „persona: było→jest”. Jeśli zmiana
jest zamierzona, odśwież wzorzec i dołącz jego diff do PR-a — to lista zmian
dostępu do przeglądu:

    cd backend && AUTHZ_GOLDEN_WRITE=1 python -m pytest tests/test_authz_guard_matrix.py

Nowe trasy nie wywracają testu (wzorzec ich jeszcze nie zna); trafiają do
niego przy najbliższym odświeżeniu. Opis liter: ``tests/_authz_matrix.py``.
"""

from __future__ import annotations

import os
import warnings

import pytest

from tests._authz_matrix import (
    PERSONAS,
    collect_matrix,
    differences,
    load_golden,
    unpinned,
    write_golden,
)

_PERSONA_INDEX = {persona.key: index for index, persona in enumerate(PERSONAS)}


@pytest.fixture(scope="module")
async def matrix() -> dict[str, dict[str, str]]:
    from app.main import app

    monkeypatch = pytest.MonkeyPatch()
    try:
        return await collect_matrix(app, monkeypatch)
    finally:
        monkeypatch.undo()


def _letter(matrix: dict[str, dict[str, str]], route: str, persona: str) -> str:
    for routes in matrix.values():
        if route in routes:
            return routes[route][_PERSONA_INDEX[persona]]
    raise AssertionError(f"Trasy {route} nie ma w aplikacji")


def test_route_guards_match_the_recorded_matrix(matrix) -> None:
    if os.environ.get("AUTHZ_GOLDEN_WRITE") == "1":
        write_golden(matrix)
        return

    golden = load_golden()
    assert golden, (
        "Brak wzorca w tests/data/authz_golden — nagraj go: "
        "AUTHZ_GOLDEN_WRITE=1 python -m pytest tests/test_authz_guard_matrix.py"
    )
    changed = differences(golden, matrix)
    new_routes = unpinned(golden, matrix)
    if new_routes:
        warnings.warn(
            f"{len(new_routes)} tras nie ma jeszcze we wzorcu bramek "
            f"(np. {new_routes[0]}) — trafią do niego przy odświeżeniu.",
            stacklevel=1,
        )
    assert not changed, (
        f"Zmienił się werdykt bramek na {len(changed)} trasach:\n  "
        + "\n  ".join(changed[:80])
        + ("\n  …" if len(changed) > 80 else "")
        + "\n\nJeśli to zamierzona zmiana dostępu, odśwież wzorzec i dołącz "
        "jego diff do PR-a:\n  cd backend && AUTHZ_GOLDEN_WRITE=1 python -m "
        "pytest tests/test_authz_guard_matrix.py"
    )


def test_matrix_tells_the_roles_apart(matrix) -> None:
    """Siatka, która każdemu daje ten sam werdykt, niczego nie pilnuje."""

    create_contract = "POST /api/contracts"
    assert _letter(matrix, create_contract, "admin") == "P"
    assert _letter(matrix, create_contract, "delivery_lead") in {"P", "B"}
    assert _letter(matrix, create_contract, "finance") == "D"
    assert _letter(matrix, create_contract, "recruiter") == "D"
    assert _letter(matrix, create_contract, "trainee") == "D"

    permissions_panel = "GET /api/admin/section-permissions"
    assert _letter(matrix, permissions_panel, "admin") == "P"
    assert _letter(matrix, permissions_panel, "head_of_recruitment") == "D"

    # Profil jest poza bramką domenową — widzi go nawet praktykant.
    assert _letter(matrix, "GET /api/auth/me", "trainee") == "P"


async def test_middleware_does_not_change_the_verdict() -> None:
    """Macierz omija middleware'y; próbka tras potwierdza, że wolno."""

    from app.main import app

    sample = tuple(
        persona for persona in PERSONAS if persona.key in {"finance", "recruiter"}
    )
    verdicts = []
    for with_middleware in (False, True):
        monkeypatch = pytest.MonkeyPatch()
        try:
            verdicts.append(
                await collect_matrix(
                    app, monkeypatch, sample, with_middleware=with_middleware, every=9
                )
            )
        finally:
            monkeypatch.undo()
    assert verdicts[0] == verdicts[1]
