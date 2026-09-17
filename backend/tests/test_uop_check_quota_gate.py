"""Sprawdzenie znamion umowy o pracę pod bramką kwot AI (0270).

Powód istnienia: ta trasa stała CAŁKOWICIE poza systemem kwot i było to
zmierzone na produkcji 02.09 — wywołanie trwało 15,4 s, a licznik
w Ustawieniach → AI nie drgnął. Od 17.09.2026 NEXUS nie ma limitów AI, więc
bramka już nie blokuje, ale licznik nadal musi rosnąć.

Druga rola tego pliku: klucz `uop_check` jest WARUNKIEM kasacji drugiego stosu
dostawcy. Po zdjęciu `ai_client.py` bramka `_assert_declared` zaczyna widzieć
tę trasę, a handler łapie tylko `CVGeneratorAIError` i `ValueError` — bez
naliczenia `AIQuotaUngated` przeszłoby oba i dało nieobsłużone 500. Test pilnuje,
żeby ta zależność nie została rozprute przy porządkach.
"""

from __future__ import annotations

import os

import pytest
from app.models.ai_feature import AIFeatureKey
from app.services import ai_quota

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="wymaga PostgreSQL (realne wiersze ai_features / ai_usage_log)",
)

_TEXT = (
    "Partner będzie wykonywał polecenia przełożonego w godzinach 9-17 "
    "w biurze Klienta i przysługuje mu 26 dni urlopu rocznie."
)


async def _usage() -> int:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        return await ai_quota.get_total_usage_for_period(
            session, AIFeatureKey.uop_check
        )


async def test_check_uop_charges_the_quota(app_client, app_auth_headers, monkeypatch):
    """Wywołanie ma zostawić ślad w liczniku — dokładnie to, czego zabrakło."""
    from app.services.b2b_contract_generator import uop_check as module

    monkeypatch.setattr(
        module,
        "analyze_with_ai",
        lambda *a, **k: '{"issues": [], "rewritten": "ok", "summary": "ok"}',
    )

    before = await _usage()
    response = await app_client.post(
        "/api/b2b-generator/check-uop",
        json={"text": _TEXT, "language": "pl"},
        headers=app_auth_headers,
    )
    assert response.status_code == 200, response.text
    assert await _usage() == before + 1


async def test_empty_text_short_circuits_without_charging(
    app_client, app_auth_headers, monkeypatch
):
    """Pusty zakres usług nie idzie do modelu, więc nie ma za co płacić —
    a licznik, który rośnie bez wywołania, kłamie w raporcie zużycia."""
    from app.services.b2b_contract_generator import uop_check as module

    def _must_not_run(*_a, **_k):
        raise AssertionError("model nie może być wołany dla pustego tekstu")

    monkeypatch.setattr(module, "analyze_with_ai", _must_not_run)

    before = await _usage()
    response = await app_client.post(
        "/api/b2b-generator/check-uop",
        json={"text": "   ", "language": "pl"},
        headers=app_auth_headers,
    )
    assert response.status_code == 200
    assert await _usage() == before
