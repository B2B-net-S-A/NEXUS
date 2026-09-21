"""Moduł wspólnych predykatów wyszukiwania kandydatów — testy bez bazy.

Wyniki zapytań sprawdza ``test_search_engines_contract.py``. Tu pilnujemy:
parytetu parsera wyrażenia z frontendem (wspólny plik przypadków), mapowania
pól legacy na trzy kubełki, detekcji trybu tekstu oraz tego, że oba endpointy
nie trzymają już prywatnych kopii filtrów.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from app.services import candidate_search_predicates as p

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/lib/__fixtures__/skill-expression-cases.json"
)


def _cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_plik_przypadkow_istnieje_i_nie_jest_pusty() -> None:
    assert len(_cases()) > 20


@pytest.mark.parametrize("case", _cases(), ids=lambda c: repr(c["expr"]))
def test_parser_wyrazenia_zgodny_z_frontendem(case: dict) -> None:
    assert p.parse_skill_expression(case["expr"]).as_wire() == {
        "must": case["must"],
        "anyGroups": case["anyGroups"],
        "none": case["none"],
    }


# ── Kubełki: mapowanie pól legacy ───────────────────────────────────────────


def test_lista_pola_legacy_sa_twarde() -> None:
    b = p.skill_buckets_from_list(
        skills=["Python", "React"],
        skill_combine="and",
        skills_any=["java|kotlin", "aws|gcp"],
        skills_none=["php|perl", "cobol"],
    )
    assert b.required == ("python", "react")
    assert b.required_any_groups == (("java", "kotlin"), ("aws", "gcp"))
    assert b.excluded == ("php", "perl", "cobol")
    assert b.preferred == ()


def test_lista_skill_combine_or_to_jedna_grupa() -> None:
    b = p.skill_buckets_from_list(skills=["Java", "Go"], skill_combine="OR")
    assert b.required == ()
    assert b.required_any_groups == (("java", "go"),)


def test_wyszukiwarka_pola_legacy_sa_miekkie() -> None:
    class Req:
        skills_must = ["Python"]
        skills_any = ["Java"]
        skills_none = ["PHP"]
        skills_required: list[str] = []
        skills_required_any_groups: list[list[str]] = []
        skills_preferred = ["React"]
        skills_excluded = ["perl|cobol"]

    b = p.skill_buckets_from_search(Req())
    assert b.required == () and b.required_any_groups == ()
    assert b.preferred == (("python",), ("java",), ("react",))
    assert b.excluded == ("php", "perl", "cobol")


def test_pipe_znaczy_grupe_w_kazdym_polu_obu_silnikow() -> None:
    from_list = p.skill_buckets_from_list(
        skills_required=["java|go", "python"],
        skills_required_any_groups=["aws|gcp"],
        skills_preferred=["react|vue"],
        skills_excluded=["php|perl"],
    )

    class Req:
        skills_must: list[str] = []
        skills_any: list[str] = []
        skills_none: list[str] = []
        skills_required = ["java|go", "python"]
        skills_required_any_groups = [["aws", "gcp"]]
        skills_preferred = ["react|vue"]
        skills_excluded = ["php|perl"]

    assert from_list == p.skill_buckets_from_search(Req())
    assert from_list.required == ("python",)
    assert from_list.required_any_groups == (("java", "go"), ("aws", "gcp"))
    assert from_list.preferred == (("react", "vue"),)


def test_wyrazenie_bez_operatora_trafia_do_musi_miec() -> None:
    parsed = p.parse_skill_expression("Python")
    assert parsed.must == ("Python",) and not parsed.any_groups and not parsed.none


# ── Tryb tekstu ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "q,kind,mode",
    [
        ("Jan Kowalski", "name", "literal"),
        ("kowalski", "name", "literal"),
        ("Anna Nowak-Kowalska", "name", "literal"),
        ("Łukasz Grądzki", "name", "literal"),
        ("jan.kowalski@example.com", "email", "literal"),
        ("@b2bnetwork.pl", "email", "literal"),
        ("+48 600 700 800", "phone", "literal"),
        ("600-700-800", "phone", "literal"),
        ("senior java developer", "text", "semantic"),
        ("programista python fintech", "text", "semantic"),
        ("tester manualny", "text", "semantic"),
        ("c++ embedded", "text", "semantic"),
        ("python -junior", "text", "semantic"),
        ("analityk danych z doświadczeniem w bankowości", "text", "semantic"),
        ("12345", "text", "semantic"),  # za mało cyfr na telefon, nie nazwisko
        ("", "empty", "semantic"),
    ],
)
def test_detekcja_trybu_tekstu(q: str, kind: str, mode: str) -> None:
    found = p.detect_text_mode(q)
    assert (found.kind, found.mode) == (kind, mode)


def test_znana_umiejetnosc_nie_jest_nazwiskiem(monkeypatch) -> None:
    from app.services import scoring_service

    monkeypatch.setitem(scoring_service.ALIAS_MAP, "kotlin", "kotlin")
    found = p.detect_text_mode("kotlin")
    assert found.kind == "text" and found.skills == ("kotlin",)


def test_miasto_jest_opisywane_a_nie_brane_za_nazwisko() -> None:
    found = p.detect_text_mode("Kraków")
    assert found.kind == "text" and found.locations == ("Kraków",)


def test_jawny_tryb_wygrywa_z_detekcja() -> None:
    name = p.detect_text_mode("Jan Kowalski")
    assert p.resolve_text_mode("auto", name) == "literal"
    assert p.resolve_text_mode("semantic", name) == "semantic"
    assert p.resolve_text_mode("literal", p.detect_text_mode("java dev")) == "literal"


# ── Jeden parser grup q_* ───────────────────────────────────────────────────


def test_parser_grup_przyjmuje_oba_ksztalty_drutu() -> None:
    from_list = p.parse_q_groups(q_any=["a1", "b1"], q_any_groups=["react|vue"])
    from_search = p.parse_q_groups(q_any=["a1", "b1"], q_any_groups=[["react", "vue"]])
    assert from_list == from_search
    assert from_list.any_groups == (("a1", "b1"), ("react", "vue"))
    assert p.parse_q_groups().clause() is None


# ── Oba endpointy nie mają prywatnych kopii ─────────────────────────────────


def test_endpointy_czytaja_filtry_tylko_ze_wspolnego_modulu() -> None:
    from app.api import candidates as lista
    from app.api import search as wyszukiwarka
    from app.services import structured_candidate_search as strukturalne

    builder = inspect.getsource(lista._build_candidate_filtered_query)
    assert "candidate_search_predicates" in builder
    for forbidden in (
        "traffit_experience",  # własna reguła stażu
        ".ilike(",  # własne dopasowanie lokalizacji
        "expected_rate_hourly",  # własna reguła stawki
        "open_to_side_projects",  # własne „Otwarty na"
        "CandidateCompetenceCategory",  # własna reguła kategorii
        "build_advanced_filter",  # własny parser grup
        "single_phrase_filter",  # własne dopasowanie `q`
        "_skill_match",  # własne kubełki umiejętności
    ):
        assert forbidden not in builder, (
            f"lista znów ma prywatną kopię filtra ({forbidden}) — "
            "przenieś ją do candidate_search_predicates"
        )

    assert "build_advanced_filter" not in inspect.getsource(wyszukiwarka)
    groups = inspect.getsource(strukturalne.build_filter_groups)
    for forbidden in ("strpos", ".ilike(", "years_it_experience", "expected_rate"):
        assert forbidden not in groups, (
            f"wyszukiwarka znów ma prywatną kopię filtra ({forbidden})"
        )
