"""Główny kill-switch AI musi zatrzymywać generowanie CV B2B.

Regresja tutaj jest CICHA i kosztuje pieniądze: gdy ktoś usunie wywołanie
``_ensure_ai_master_enabled`` z handlera, admin dalej będzie widział w
Ustawieniach → AI komunikat „Wszystkie funkcje AI są wyłączone globalnie",
a ``POST /api/cv-generator/generate`` dalej będzie wołał Sonneta z fallbackiem
na Opusa (16 384 tokeny outputu, do 3 prób na model). Nic tego nie pokaże:
generator CV nie ma własnego ``AIFeatureKey``, więc nie zostawia śladu ani w
``ai_usage_log``, ani w ``/api/health.checks.ai_features``.

Dlatego oprócz zachowania samej bramki test pilnuje AST-em, że OBA endpointy
generacji faktycznie przez nią przechodzą — samo istnienie helpera niczego nie
gwarantuje.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import cv_generator_b2b

_GATE = "_ensure_ai_master_enabled"
_GUARDED_ENDPOINTS = {"generate", "generate_from_upload"}


@pytest.mark.asyncio
async def test_gate_raises_503_when_master_toggle_is_off(monkeypatch):
    import app.services.ai_quota as ai_quota

    async def _off(_db):
        return False

    monkeypatch.setattr(ai_quota, "get_master_enabled", _off)

    with pytest.raises(HTTPException) as exc:
        await cv_generator_b2b._ensure_ai_master_enabled(object())

    assert exc.value.status_code == 503
    assert "wyłączone globalnie" in exc.value.detail


@pytest.mark.asyncio
async def test_gate_lets_generation_through_when_master_toggle_is_on(monkeypatch):
    import app.services.ai_quota as ai_quota

    async def _on(_db):
        return True

    monkeypatch.setattr(ai_quota, "get_master_enabled", _on)

    # Brak wyjątku = ścieżka generacji idzie dalej.
    assert await cv_generator_b2b._ensure_ai_master_enabled(object()) is None


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
            f"{name}() nie woła {_GATE}() — główny kill-switch AI przestał "
            "zatrzymywać najdroższe wywołanie Claude'a w produkcie."
        )
