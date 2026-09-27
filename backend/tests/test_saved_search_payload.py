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
    search = {"skills_must": ["Python"], "has_cv": True}
    _fmt, origin, request = p.read_saved_search(search)
    assert (
        alert_list_params(
            p.build_unified_payload(search, origin=origin, request=request)
        )
        is None
    )
    assert alert_list_params({"qs": "q=python"}) is None
    assert alert_list_params(None) is None


def test_neutralizacja_zapisu_z_listy() -> None:
    request = p.list_api_to_unified({"min_rate": 100, "location": "Gdansk"})
    neutral, applied = p.neutralise_list_request(request)
    assert applied == ["hide_unknown", "location_scope"]
    assert neutral["hide_unknown"] is True
    assert neutral["location_scope"] == "location_only"
    # bez filtrów, których dotyczy „brak danych", nic nie dopisujemy
    plain, applied = p.neutralise_list_request(
        p.list_api_to_unified({"skills": ["Go"]})
    )
    assert applied == [] and "hide_unknown" not in plain


def test_kody_regul_bez_danych_osobowych() -> None:
    assert p.possible_difference_rules(
        "candidates_list", {"location_cities": ["A_B"]}
    ) == ["location_wildcards"]
    assert (
        p.possible_difference_rules("candidates_list", {"location_cities": ["Gdansk"]})
        == []
    )
    assert p.possible_difference_rules(
        "search_request",
        {
            "tags": ["java"],
            "competence_category_ids": [1],
            "open_to": ["side_projects", "sales_support"],
            "experience_years_min": 3,
        },
    ) == [
        "tags_whole_match",
        "category_secondary",
        "open_to_any",
        "experience_traffit_fallback",
    ]


def test_zostaw_po_staremu_przypina_oryginal() -> None:
    legacy = {"version": 2, "qs": "q=x", "api": {"q": "xy"}}
    _fmt, origin, request = p.read_saved_search(legacy)
    migrated = p.build_unified_payload(legacy, origin=origin, request=request)
    restored = p.restore_legacy_payload(migrated)
    assert restored == {**legacy, "keep_legacy_semantics": True}
    assert p.is_pinned_to_legacy(restored) and not p.is_pinned_to_legacy(legacy)
    assert p.restore_legacy_payload({"version": 3, "request": {}}) is None


def test_zapis_listy_w_v2_nie_jest_neutralizowany() -> None:
    """Lista zapisuje od 21.09.2026 `api.semantics_version = 2` — migracja nie
    może takiemu zapisowi dokładać flag dawnego zachowania listy."""
    v2 = {
        "version": 2,
        "qs": "loc=Gda%C5%84sk",
        "api": {"location": "Gdańsk", "semantics_version": 2},
    }
    v1 = {"version": 2, "qs": "loc=Gda%C5%84sk", "api": {"location": "Gdańsk"}}
    assert p.list_payload_is_unified(v2) is True
    assert p.list_payload_is_unified(v1) is False
    assert p.list_payload_is_unified({"qs": "q=x"}) is False
    assert p.list_payload_is_unified(None) is False


def test_jezyki_sa_wspolne_i_odtwarzalne_przez_liste() -> None:
    """22.09.2026: lista zna `?languages=` — zapis wyszukiwarki z językami
    przestaje być „luką listy", a alert odtwarza go parametrem listy."""
    from app.tasks.saved_search_alerts import alert_list_params

    search = {"skills_must": ["Python"], "languages": [{"code": "EN"}]}
    _fmt, origin, request = p.read_saved_search(search)
    assert request["languages"] == [{"code": "EN"}]
    assert p.list_engine_gaps(request) == []
    migrated = p.build_unified_payload(search, origin=origin, request=request)
    assert alert_list_params(migrated) == {
        "semantics_version": 2,
        "skills_preferred": ["Python"],
        "languages": ["EN"],
    }
    assert p.unified_to_search_body(request)["languages"] == [{"code": "EN"}]


def test_skaner_czyta_tekst_doslownie() -> None:
    """Retrieval semantyczny listy nie może trafić do alertów: pula z całej
    bazy przecięta ze znakiem wodnym gubiłaby nowych kandydatów."""
    from app.tasks.saved_search_alerts import alert_list_params

    search = {"q": "python fintech", "text_mode": "auto"}
    _fmt, origin, request = p.read_saved_search(search)
    migrated = p.build_unified_payload(search, origin=origin, request=request)
    assert alert_list_params(migrated)["text_mode"] == "literal"
    legacy = {"version": 2, "qs": "", "api": {"q": "x", "text_mode": "semantic"}}
    assert alert_list_params(legacy) == {"q": "x", "text_mode": "literal"}
    assert p.with_literal_text({"q": "x"}) == {"q": "x"}


def test_flagi_zadania_trafiaja_do_querystringu_listy() -> None:
    """CAND-06: `hu=1` / `ls=location_only` w qs, tylko brakujące, raz."""
    req = {"hide_unknown": True, "location_scope": "location_only"}
    assert p.with_request_flags("loc=gdansk", req) == "loc=gdansk&hu=1&ls=location_only"
    assert (
        p.with_request_flags("loc=gdansk&hu=1", req)
        == "loc=gdansk&hu=1&ls=location_only"
    )
    assert p.with_request_flags("q=python", {}) == "q=python"


def test_zawezajace_przelaczniki_wyszukiwarki_sa_luka_listy() -> None:
    """Runda 8 (R8-N10-6): `exclude_blacklisted`/`exclude_in_job_id` zawężają
    wynik — zapis z nimi nie może być alertem odtwarzanym przez listę, bo
    alarmowałby o osobach z czarnej listy i osobach już w rekrutacji."""
    from app.tasks.saved_search_alerts import alert_list_params

    base = {"semantics_version": 2, "skills_preferred": ["Python"]}
    blacklist = {**base, "search_only": {"exclude_blacklisted": True}}
    in_job = {**base, "search_only": {"exclude_in_job_id": 7}}
    assert p.list_engine_gaps(blacklist) == ["exclude_blacklisted"]
    assert p.list_engine_gaps(in_job) == ["exclude_in_job_id"]
    for request in (blacklist, in_job):
        payload = p.build_unified_payload({}, origin="search_request", request=request)
        assert alert_list_params(payload) is None

    # Nic nie zawężają: wyłączone albo status i tak bez czarnej listy.
    off = {**base, "search_only": {"exclude_blacklisted": False}}
    assert p.list_engine_gaps(off) == []
    by_status = {
        **base,
        "status": ["active"],
        "search_only": {"exclude_blacklisted": True},
    }
    assert p.list_engine_gaps(by_status) == []
    assert (
        p.list_engine_gaps({**base, "search_only": {"exclude_in_job_id": None}}) == []
    )
