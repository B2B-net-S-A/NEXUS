"""Adapter zapisanych wyszukiwań — parytet z frontendem (wspólny plik przypadków).

Ten sam JSON czyta ``frontend/src/lib/__tests__/saved-search-unified.test.ts``.
Skaner alertów i UI muszą czytać stare zapisy identycznie — inaczej alert liczy
inny zbiór niż ten, który rekruter widzi po kliknięciu powiadomienia.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import saved_search_payload as p

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/lib/__fixtures__/saved-search-unified-cases.json"
)


def _cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_przypadki_obejmuja_oba_formaty_legacy() -> None:
    origins = {c["origin"] for c in _cases()}
    assert {"candidates_list", "search_request"} <= origins


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_adapter_zgodny_z_frontendem(case: dict) -> None:
    fmt, origin, request = p.read_saved_search(case["filters"])
    assert (fmt, origin, request) == (case["format"], case["origin"], case["request"])
    if request is None or origin is None:
        return
    assert p.unified_to_list_params(request) == case["list_params"]
    assert p.unified_to_search_body(request) == case["search_body"]
    assert p.list_engine_gaps(request) == case["list_engine_gaps"]
    payload = p.build_unified_payload(case["filters"], origin=origin, request=request)
    assert payload == case["payload"]
    assert p.read_saved_search(payload) == ("unified", origin, request)


def test_pola_legacy_listy_zostaja_twarde_a_wyszukiwarki_miekkie() -> None:
    from_list = p.list_api_to_unified({"skills": ["Python"], "skills_none": ["PHP"]})
    assert from_list["skills_required"] == ["Python"]
    assert "skills_preferred" not in from_list
    from_search = p.search_request_to_unified(
        {"skills_must": ["Python"], "skills_none": ["PHP"]}
    )
    assert from_search["skills_preferred"] == ["Python"]
    assert "skills_required" not in from_search
    assert from_list["skills_excluded"] == from_search["skills_excluded"] == ["PHP"]


def test_znacznik_semantyki_dopisuje_sie_raz() -> None:
    assert p.with_semantics_marker("q=python") == "q=python&sv=2"
    assert p.with_semantics_marker("q=python&sv=2") == "q=python&sv=2"


def test_skaner_odtwarza_v3_sciezka_wspolna_a_legacy_bez_zmian() -> None:
    from app.tasks.saved_search_alerts import alert_list_params

    legacy = {"version": 2, "qs": "q=x", "api": {"skills": ["Python"]}}
    assert alert_list_params(legacy) == {"skills": ["Python"]}  # v1, bez zmian

    _fmt, origin, request = p.read_saved_search(legacy)
    migrated = p.build_unified_payload(legacy, origin=origin, request=request)
    assert alert_list_params(migrated) == {
        "semantics_version": 2,
        "skills_required": ["Python"],
    }

    # zapis wyszukiwarki z filtrem, którego lista nie zna → nie do odtworzenia
    search = {"skills_must": ["Python"], "languages": [{"code": "EN"}]}
    _fmt, origin, request = p.read_saved_search(search)
    assert (
        alert_list_params(
            p.build_unified_payload(search, origin=origin, request=request)
        )
        is None
    )
    assert alert_list_params({"qs": "q=python"}) is None
    assert alert_list_params(None) is None
