"""Walidator `preferences` (0278) — trzecia rubryka po stronie kandydata.

Commit 1 tej fali: wyłącznie kontrakt na poziomie Pydantic (`CandidateCreate`
/ `CandidateUpdate`), bez sieci ani bazy — `_normalize_candidate_preferences`
w `app.schemas.candidate` jest czystą funkcją, więc nie potrzebuje jednego
ani drugiego. Commit 2: testy HTTP na płytkim merge w `PATCH
/api/candidates/{id}` (`update_candidate`, `app.api.candidates`) i na filtrze
listy `remote_policy` po naprawie literówki `on_site`→`onsite` (S1) — w TYM
SAMYM pliku, jak zaplanowano.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.schemas.candidate import CandidateCreate, CandidateUpdate

# Bez `pytestmark = pytest.mark.asyncio`: `pytest.ini` ma `asyncio_mode = auto`
# (każdy `async def test_...` jest wykrywany sam), a ten moduł miesza je z
# SYNCHRONICZNYMI testami walidatora wyżej — jawny marker na module dawałby
# im spurious `PytestWarning` (`marked with asyncio but not async`).


async def _create_candidate(
    app_client: AsyncClient, headers: dict, **overrides
) -> dict:
    payload = {
        "name": "Pytest",
        "lastname": f"OfficePresence-{uuid.uuid4().hex[:8]}",
        **overrides,
    }
    resp = await app_client.post("/api/candidates", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _error_type(model, payload: dict) -> str:
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(payload)
    return exc_info.value.errors()[0]["type"]


def _create_payload(**preferences_kwargs) -> dict:
    return {"name": "Jan", "lastname": "Kowalski", "preferences": preferences_kwargs}


def test_remote_modes_on_site_is_rejected_422():
    # Literówka historyczna (S1 naprawia dane; walidator odcina ją na wejściu
    # od teraz) — formularz nie ma już prawa wysłać `on_site`.
    assert (
        _error_type(
            CandidateUpdate, {"preferences": {"remote_modes": ["on_site"]}}
        )
        == "candidate_preferences_remote_mode_invalid"
    )
    assert (
        _error_type(CandidateCreate, _create_payload(remote_modes=["on_site"]))
        == "candidate_preferences_remote_mode_invalid"
    )
    # Nieznana wartość spoza `RemotePolicy` też odpada, nie tylko literówka.
    assert (
        _error_type(
            CandidateUpdate, {"preferences": {"remote_modes": ["fully_remote"]}}
        )
        == "candidate_preferences_remote_mode_invalid"
    )


def test_remote_modes_valid_values_pass_and_dedupe():
    result = CandidateUpdate.model_validate(
        {"preferences": {"remote_modes": ["onsite", "hybrid", "onsite", " remote "]}}
    )
    # Dedup + strip, kolejność pierwszego wystąpienia zachowana.
    assert result.preferences["remote_modes"] == ["onsite", "hybrid", "remote"]

    created = CandidateCreate.model_validate(_create_payload(remote_modes=["hybrid"]))
    assert created.preferences["remote_modes"] == ["hybrid"]


def test_office_cities_normalised():
    result = CandidateUpdate.model_validate(
        {
            "preferences": {
                "office_cities": [" Warszawa ", "Kraków", "warszawa", "", "   "]
            }
        }
    )
    # strip, puste odrzucone, dedup po casefold (pierwsze wystąpienie wygrywa).
    assert result.preferences["office_cities"] == ["Warszawa", "Kraków"]


def test_onsite_days_inside_preferences_rejected():
    # Kolumna, nie klucz JSONB — inaczej powstałoby drugie źródło prawdy
    # o tej samej rubryce.
    assert (
        _error_type(
            CandidateUpdate, {"preferences": {"max_onsite_days_per_week": 3}}
        )
        == "candidate_onsite_days_is_a_column"
    )
    assert (
        _error_type(CandidateCreate, _create_payload(max_onsite_days_per_week=3))
        == "candidate_onsite_days_is_a_column"
    )


def test_max_onsite_days_out_of_range_422():
    assert (
        _error_type(CandidateUpdate, {"max_onsite_days_per_week": 8})
        == "less_than_equal"
    )
    assert (
        _error_type(CandidateUpdate, {"max_onsite_days_per_week": -1})
        == "greater_than_equal"
    )
    assert (
        _error_type(
            CandidateCreate,
            {"name": "Jan", "lastname": "Kowalski", "max_onsite_days_per_week": 8},
        )
        == "less_than_equal"
    )


# ── HTTP: płytki merge w PATCH /api/candidates/{id} (commit 2) ──────────────


async def test_patch_preferences_keeps_unknown_keys(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Do 09.2026 PATCH podmieniał `preferences` w całości — edycja jednego
    klucza (tu: `remote_modes`) kasowała każdy inny, którego formularz nie
    modelował. Merge ma zostawić `industries`/`contract_types` nietknięte."""
    created = await _create_candidate(
        app_client,
        app_auth_headers,
        preferences={"industries": ["Fintech"], "contract_types": ["b2b"]},
    )
    resp = await app_client.patch(
        f"/api/candidates/{created['id']}",
        json={"preferences": {"remote_modes": ["remote"]}},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    prefs = resp.json()["preferences"]
    assert prefs["remote_modes"] == ["remote"]
    assert prefs["industries"] == ["Fintech"]
    assert prefs["contract_types"] == ["b2b"]


async def test_patch_preferences_null_deletes_key(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Jawny `null` przy kluczu w `preferences` jest markerem USUNIĘCIA tego
    klucza — konsumowany przez merge w `update_candidate`, wypuszczony przez
    walidator z `allow_null_values=True` na `CandidateUpdate`."""
    created = await _create_candidate(
        app_client,
        app_auth_headers,
        preferences={"industries": ["Fintech"], "remote_modes": ["remote"]},
    )
    resp = await app_client.patch(
        f"/api/candidates/{created['id']}",
        json={"preferences": {"industries": None}},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    prefs = resp.json()["preferences"]
    assert "industries" not in prefs
    assert prefs["remote_modes"] == ["remote"]


async def test_patch_preferences_top_level_null_clears(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`preferences: null` (nie zagnieżdżony klucz) czyści cały słownik —
    odróżnione od „nie wysłano pola w ogóle" (co zostawiłoby preferencje
    nietknięte, bo `exclude_unset=True`)."""
    created = await _create_candidate(
        app_client,
        app_auth_headers,
        preferences={"industries": ["Fintech"], "remote_modes": ["remote"]},
    )
    resp = await app_client.patch(
        f"/api/candidates/{created['id']}",
        json={"preferences": None},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["preferences"] == {}


async def test_patch_preferences_invalid_remote_mode_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    created = await _create_candidate(app_client, app_auth_headers)
    resp = await app_client.patch(
        f"/api/candidates/{created['id']}",
        json={"preferences": {"remote_modes": ["on_site"]}},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_patch_max_onsite_days_roundtrip(
    app_client: AsyncClient, app_auth_headers: dict
):
    created = await _create_candidate(app_client, app_auth_headers)
    assert created["max_onsite_days_per_week"] is None

    resp = await app_client.patch(
        f"/api/candidates/{created['id']}",
        json={"max_onsite_days_per_week": 2},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["max_onsite_days_per_week"] == 2

    cleared = await app_client.patch(
        f"/api/candidates/{created['id']}",
        json={"max_onsite_days_per_week": None},
        headers=app_auth_headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["max_onsite_days_per_week"] is None


async def test_list_filter_finds_onsite_after_fix(
    app_client: AsyncClient, app_auth_headers: dict
):
    """S1 (migracja 0278) naprawia literówkę `on_site`→`onsite` w danych;
    ten test pilnuje, że KOD dalej pisze/filtruje po naprawionej wartości —
    kandydat zapisany z `remote_modes=["onsite"]` musi wyjść z filtra
    `?remote_policy=onsite`. `id_after` zawęża wynik do tego jednego
    kandydata bez zależności od stanu reszty (współdzielonej) bazy testowej.
    """
    created = await _create_candidate(
        app_client,
        app_auth_headers,
        preferences={"remote_modes": ["onsite"]},
    )
    resp = await app_client.get(
        "/api/candidates",
        params={"remote_policy": "onsite", "id_after": created["id"] - 1},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert created["id"] in ids
