"""Wagi scoringu MUSZĄ sumować się do 100 — także w payloadzie pięciowagowym.

Suma była pilnowana przez `@field_validator("champion_fit")`, a walidator POLA
w Pydantic v2 NIE odpala się, gdy pola nie ma w żądaniu i wchodzi wartość
domyślna (bez `validate_default=True`). `champion_fit` jest opcjonalne właśnie
po to, żeby stary payload dalej działał — więc suma nie była sprawdzana
DOKŁADNIE w przypadku, którego broni komentarz przy tym polu.

Odtworzone na żywym endpoincie: pięć wag sumujących się do 99 zwracało
201 Created i profil lądował w bazie z `{"...": 19, "champion_fit": 0}`.

Dlaczego to nie jest kosmetyka walidacji: `WeightProfile.from_record` bierze te
liczby WPROST jako budżety warstw scoringu, więc profil o sumie 99 liczy KAŻDY
match score względem innego maksimum niż 100 — a progi (`RECOMMENDATION_MIN_SCORE`,
`AI_MATCH_MIN_SCORE`) i procenty w UI zakładają setkę. Bramka API jest JEDYNYM
miejscem, które tego pilnuje: baza nie ma CHECK-a na sumę.

Plik jest osobny CELOWO. Ten sam przypadek pokrywa
`test_new_endpoints.py::test_scoring_weights_rejects_sum_not_100`, ale ten plik
jest w CI jawnie pominięty (`--ignore=tests/test_new_endpoints.py` w ci.yml) —
i dlatego regresja przeżyła. Test bez przebiegu nie jest testem.
"""

from __future__ import annotations

import uuid

import pytest

_FIVE_LAYERS = ("semantic", "skills", "salary", "location", "availability")


def _weights(**overrides) -> dict:
    base = {name: 20 for name in _FIVE_LAYERS}
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("weights", "why"),
    [
        (_weights(availability=19), "pięć wag, suma 99 — payload legacy"),
        (_weights(availability=21), "pięć wag, suma 101"),
        (_weights(champion_fit=10), "sześć wag, suma 110 — dawna luka champion"),
    ],
)
@pytest.mark.asyncio
async def test_profile_whose_layers_do_not_sum_to_100_is_rejected(
    app_client, app_auth_headers, weights, why
):
    resp = await app_client.post(
        "/api/scoring-weights",
        headers=app_auth_headers,
        json={"name": f"Suma-{uuid.uuid4().hex[:8]}", "weights": weights},
    )
    assert resp.status_code == 422, f"{why}: dostaliśmy {resp.status_code}"
    assert "sum to 100" in resp.text


@pytest.mark.asyncio
async def test_legacy_five_layer_profile_summing_to_100_still_works(
    app_client, app_auth_headers
):
    """Kontrola negatywna — bez niej „naprawa" mogłaby odrzucać wszystko.

    `champion_fit` zostaje opcjonalne: pięciowagowy klient ma nadal działać.
    """
    resp = await app_client.post(
        "/api/scoring-weights",
        headers=app_auth_headers,
        json={"name": f"Suma-ok-{uuid.uuid4().hex[:8]}", "weights": _weights()},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["weights"]["champion_fit"] == 0


@pytest.mark.asyncio
async def test_six_layer_profile_summing_to_100_still_works(
    app_client, app_auth_headers
):
    resp = await app_client.post(
        "/api/scoring-weights",
        headers=app_auth_headers,
        json={
            "name": f"Suma-6-{uuid.uuid4().hex[:8]}",
            "weights": _weights(availability=10, champion_fit=10),
        },
    )
    assert resp.status_code == 201, resp.text
