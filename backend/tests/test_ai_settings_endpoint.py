"""`GET /api/settings/ai` musi przeżyć osierocone wiersze `ai_features`.

Ta trasa nie miała ŻADNEGO testu — `tests/test_ai_settings_schemas.py` zapowiadał
go w swoim docstringu i nigdy nie powstał. Dlatego 500 na produkcji było
niewidoczne: `ai_features` trzyma na prodzie wiersze po funkcjach przemianowanych
i usuniętych (`embeddings`, `matching`, `reranking`, …), a `select(AIFeatureConfig)`
hydratuje kolumnę pythonowym enumem PRZY ODCZYCIE i na takim wierszu rzuca
`LookupError`. Efekt: jedyny panel, w którym da się ustawić miesięczny limit
wydatków AI i przełączyć główny kill-switch, był nieosiągalny, a front tłumaczył
adminowi 500 jako brak uprawnień — więc przestawał szukać.

Osierocony wiersz odtwarzamy na poziomie mapowania, nie przez `ALTER TYPE` na
współdzielonej bazie: DDL na typie enum jest globalny i nieodwracalny (Postgres
nie umie usunąć etykiety), a `resolve_feature_rows` jest jedynym miejscem, które
o tym decyduje.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.ai_settings import resolve_feature_rows
from app.models.ai_feature import AIFeatureKey


def test_orphan_feature_row_is_skipped_not_raised() -> None:
    known, stale = resolve_feature_rows(
        [
            ("scoring", True, 100),
            ("embeddings", True, 0),  # funkcja usunięta — wiersz został na prodzie
            ("cv_parser", False, 0),
            ("reranking", True, 5),
        ]
    )

    assert [k for k, _e, _l in known] == [AIFeatureKey.scoring, AIFeatureKey.cv_parser]
    assert sorted(stale) == ["embeddings", "reranking"]


def test_known_rows_keep_their_values() -> None:
    known, stale = resolve_feature_rows([("scoring", False, 250)])
    assert stale == []
    assert known == [(AIFeatureKey.scoring, False, 250)]


def test_null_monthly_limit_reads_as_unlimited() -> None:
    """0 = bez limitu; `None` z bazy nie może wywrócić walidacji `ge=0`."""
    known, _stale = resolve_feature_rows([("scoring", True, None)])
    assert known == [(AIFeatureKey.scoring, True, 0)]


def test_query_reads_the_feature_column_as_text() -> None:
    """Strażnik regresji: powrót do `select(AIFeatureConfig)` wraca do 500.

    Sam wynik nie jest widoczny w odpowiedzi (osierocone wiersze są pomijane),
    więc bez tej asercji ktoś „upraszcza" zapytanie z powrotem do encji ORM
    i defekt wraca niezauważony aż na produkcję.
    """
    import inspect

    from app.api import ai_settings

    src = inspect.getsource(ai_settings.get_ai_settings)
    assert "cast(AIFeatureConfig.feature, Text)" in src
    assert "select(AIFeatureConfig)" not in src


@pytest.mark.asyncio
async def test_ai_settings_panel_responds(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Panel w ogóle odpowiada — jedyna powierzchnia z limitami i kill-switchem."""
    resp = await app_client.get("/api/settings/ai", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["master_enabled"], bool)
    assert isinstance(body["features"], list)
    assert isinstance(body["usage"], list)


@pytest.mark.asyncio
async def test_panel_carries_model_and_token_usage(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """C13: każda funkcja niesie efektywny model z rejestru, a zużycie — tokeny.

    Model wprost z ``ai_models`` (jedno miejsce prawdy funkcja → model), więc
    panel nie może rozjechać się z tym, czego używa runtime. Tokeny są sumą
    z jednego GROUP BY — pola muszą być obecne, nawet gdy zerowe.
    """
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_models import model_for

    resp = await app_client.get("/api/settings/ai", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    for feat in body["features"]:
        key = AIFeatureKey(feat["feature"])
        assert feat["model"] == model_for(key), (
            f"{feat['feature']}: panel pokazuje inny model niż rejestr runtime"
        )
        assert feat["model"], f"{feat['feature']}: pusty model w panelu"

    for row in body["usage"]:
        assert "input_tokens" in row and "output_tokens" in row
        assert row["input_tokens"] >= 0 and row["output_tokens"] >= 0
