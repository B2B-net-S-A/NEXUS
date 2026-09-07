"""Walidator `preferences` (0278) — trzecia rubryka po stronie kandydata.

Commit 1 tej fali: wyłącznie kontrakt na poziomie Pydantic (`CandidateCreate`
/ `CandidateUpdate`), bez sieci ani bazy — `_normalize_candidate_preferences`
w `app.schemas.candidate` jest czystą funkcją, więc nie potrzebuje jednego
ani drugiego. Testy HTTP (płytki merge w `PATCH /api/candidates/{id}`,
filtr listy) dochodzą w commicie 2, do TEGO SAMEGO pliku — patrz plan.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.candidate import CandidateCreate, CandidateUpdate


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
