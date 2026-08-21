"""Generator CV B2B musi być objęty kwotą AI — nie tylko kill-switchem.

Regresja tutaj jest CICHA i kosztuje pieniądze. Do 0240 ta powierzchnia nie
miała własnego ``AIFeatureKey``, więc nie zostawiała śladu ani w
``ai_usage_log``, ani w ``/api/health.checks.ai_features``, a jedynym, co ją
zatrzymywało, był główny wyłącznik. Teraz bramka robi trzy rzeczy naraz
(master toggle → przełącznik funkcji → miesięczny sufit), bo tak działa
``check_and_increment``; test pilnuje każdej z nich osobno, żeby zdjęcie
którejkolwiek nie przeszło niezauważone.

Oprócz zachowania samej bramki test sprawdza AST-em, że OBA endpointy generacji
faktycznie przez nią przechodzą — samo istnienie helpera niczego nie gwarantuje
(dokładnie tak ta luka powstała: helper od kwoty istniał w sąsiednim module).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import cv_generator_b2b
from app.models.ai_feature import AIFeatureKey

_GATE = "_charge_cv_generation_quota"
_GUARDED_ENDPOINTS = {"generate", "generate_from_upload"}


class _FakeSession:
    """Minimalna sesja: bramka woła tylko ``rollback()`` na ścieżce odmowy."""

    def __init__(self) -> None:
        self.rolled_back = False

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.asyncio
async def test_gate_raises_503_when_quota_refuses(monkeypatch):
    """Każdy powód odmowy (master off / funkcja off / sufit) leci tą samą drogą."""
    import app.services.ai_quota as ai_quota

    async def _refuse(_db, feature, user_id=None):
        raise ai_quota.AIQuotaExceeded(feature, "Miesięczny limit wyczerpany", 50, 50)

    monkeypatch.setattr(ai_quota, "check_and_increment", _refuse)
    db = _FakeSession()

    with pytest.raises(HTTPException) as exc:
        await cv_generator_b2b._charge_cv_generation_quota(db, 7)

    assert exc.value.status_code == 503
    # Powód odmowy MUSI dojechać do rekrutera — inaczej wyczerpany limit czyta
    # się jak awaria generatora i kończy zgłoszeniem do supportu.
    assert exc.value.detail["feature"] == AIFeatureKey.cv_generator.value
    assert exc.value.detail["limit"] == 50
    assert db.rolled_back, (
        "Bez rollbacku niedoszły licznik zostaje w sesji i commituje się razem "
        "z czymkolwiek, co handler zapisze po odmowie."
    )


@pytest.mark.asyncio
async def test_gate_charges_the_cv_generator_bucket(monkeypatch):
    """Obciążenie musi trafić we WŁASNY kubełek i nieść id użytkownika.

    Doklejenie generacji CV do cudzego klucza (np. ``cv_parser``) zamieniłoby
    najdroższą powierzchnię w produkcie w niewidoczny dodatek do cudzego sufitu.
    """
    import app.services.ai_quota as ai_quota

    seen: dict[str, object] = {}

    async def _accept(_db, feature, user_id=None):
        seen["feature"] = feature
        seen["user_id"] = user_id
        return None

    monkeypatch.setattr(ai_quota, "check_and_increment", _accept)

    assert (
        await cv_generator_b2b._charge_cv_generation_quota(_FakeSession(), 42) is None
    )
    assert seen == {"feature": AIFeatureKey.cv_generator, "user_id": 42}


def _awaited_names(fn: ast.AsyncFunctionDef) -> set[str]:
    """Nazwy funkcji, na które w ciele handlera czeka ``await``."""
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def test_both_generation_endpoints_pass_through_the_gate():
    source = Path(cv_generator_b2b.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    found = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in _GUARDED_ENDPOINTS
    }
    assert set(found) == _GUARDED_ENDPOINTS, (
        "Endpoint generacji zniknął albo zmienił nazwę — zaktualizuj listę "
        "razem z bramką, inaczej test przestaje czegokolwiek pilnować."
    )

    for name, fn in found.items():
        assert _GATE in _awaited_names(fn), (
            f"{name}() nie woła {_GATE}() — najdroższe wywołanie Claude'a "
            "w produkcie znowu stoi poza kwotą, kill-switchem i ai_usage_log."
        )
