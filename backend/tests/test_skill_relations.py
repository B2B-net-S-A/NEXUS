"""Mapa wiedzy IT (0660, 07.11.2026): powiązania haseł słownika.

Decyzje Artura z 07.11.2026: „wynika z” i „część” spełniają wymaganie wszędzie,
generator nie dopisuje technologii (tylko nie usuwa), zamiennik zostawia osobę
widoczną z pytaniem, a nocny bieg zatwierdza powiązania sam.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Iterator

from app.services import dz_review as dz
from app.services import skill_normalize as sn
from app.services import skill_relations as rel
from app.services.care.skills import SkillDictionary
from app.services.cv_generator_b2b.legacy_v7._helpers import strip_unsupported_terms
from app.services.cv_qc import related_detail, related_hint
from app.services.dealbreaker_filters import alternative_hits
from tests.taxonomy_fixture import hydrated_taxonomy

SKILLS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Java": ("language", ()),
    "Spring Boot": ("backend", ("springboot",)),
    "Git": ("tools", ()),
    "GitHub": ("tools", ()),
    "Python": ("language", ()),
    "FastAPI": ("backend", ()),
    "Flask": ("backend", ()),
    "Maven": ("tools", ()),
    "QA": ("role_qa", ()),
}


@contextmanager
def relations() -> Iterator[None]:
    with hydrated_taxonomy(SKILLS):
        sn.set_relations(
            implied_by={"java": {"spring boot"}, "git": {"github"}},
            alternatives={"fastapi": {"flask"}, "flask": {"fastapi"}},
            typical_by={"maven": {"java"}},
        )
        try:
            yield
        finally:
            sn.set_relations()


def _req(name: str) -> dz.Requirement:
    return dz.Requirement(label=name, alternatives=(name,))


def _dictionary() -> SkillDictionary:
    names = {
        1: "Java",
        2: "Spring Boot",
        3: "QA",
        4: "Jest",
        5: "TypeScript",
        6: "UAT",
        7: "UAT (User Acceptance Testing)",
    }
    categories = {
        1: "language",
        2: "backend",
        3: "role_qa",
        4: "qa",
        5: "language",
        6: "qa",
        7: "qa",
    }
    return SkillDictionary(
        by_key={n.lower(): i for i, n in names.items()},
        names=names,
        categories=categories,
    )


# ── Bezpieczniki nocnego biegu ──────────────────────────────────────────────


def test_hard_kind_needs_a_second_witness() -> None:
    d = _dictionary()
    strong = rel.Pair(from_id=2, to_id=1, support=3943, share=0.977)
    weak = rel.Pair(from_id=4, to_id=5, support=1799, share=0.6)
    glossary = rel.Pair(from_id=4, to_id=5, source="glossary")
    assert rel.apply_guards(strong, "implies", d) == "implies"
    assert rel.apply_guards(weak, "implies", d) == "typical"
    assert rel.apply_guards(glossary, "implies", d) == "implies"


def test_roles_none_and_same_thing_are_dropped() -> None:
    d = _dictionary()
    assert (
        rel.apply_guards(rel.Pair(from_id=3, to_id=1, share=0.99), "implies", d) is None
    )
    assert rel.apply_guards(rel.Pair(from_id=2, to_id=1, share=0.99), "none", d) is None
    assert (
        rel.apply_guards(rel.Pair(from_id=6, to_id=7, share=0.9), "alternative", d)
        is None
    )


def test_typical_from_glossary_needs_data() -> None:
    d = _dictionary()
    assert (
        rel.apply_guards(rel.Pair(from_id=1, to_id=2, source="glossary"), "typical", d)
        is None
    )
    assert (
        rel.apply_guards(rel.Pair(from_id=1, to_id=2, share=0.6), "typical", d)
        == "typical"
    )


def test_model_only_pair_never_becomes_hard() -> None:
    d = _dictionary()
    assert (
        rel.apply_guards(rel.Pair(from_id=2, to_id=1, source="model"), "implies", d)
        == "typical"
    )


def test_glossary_hints_split_into_names() -> None:
    assert rel.hint_names("Spring / Spring Boot") == ["Spring", "Spring Boot"]
    assert rel.hint_names("Maven lub Gradle") == ["Maven", "Gradle"]
    assert rel.hint_names("Java 8/11/17/21") == ["Java"]


def test_parse_kinds_ignores_unknown() -> None:
    raw = '{"items": [{"id": 0, "kind": "implies", "reason": "framework Javy"}, {"id": 1, "kind": "maybe"}]}'
    assert rel.parse_kinds(raw) == {0: ("implies", "framework Javy")}


# ── Jedna semantyka: wyszukiwanie, QC, strażnik ─────────────────────────────


def test_implied_forms_include_relations_with_aliases() -> None:
    with relations():
        forms = sn.implied_forms("Java")
        assert "spring boot" in forms and "springboot" in forms
        assert sn.implied_forms("Spring Boot") == ()  # jedna strona
        assert sn.implied_forms("SQL")  # stała rodzina zostaje


def test_qc_takes_github_as_git_and_spring_boot_as_java() -> None:
    assert dz.found_in("Repozytoria na GitHub", _req("Git")) is None
    with relations():
        assert dz.found_in("Repozytoria na GitHub", _req("Git")) is not None
        assert dz.found_in("Backend w Spring Boot 3", _req("Java")) is not None
        assert dz.found_in("Backend w Flask", _req("FastAPI")) is None


def test_qc_hint_names_alternative_and_typical() -> None:
    with relations():
        alt = related_hint("FastAPI", "Projekty w Flask i Sanic")
        assert alt == {"kind": "alternative", "names": ["Flask"]}
        assert "zamienniki: Flask" in related_detail("FastAPI", alt)
        typical = related_hint("Maven", "Programista Java, 5 lat")
        assert typical == {"kind": "typical", "names": ["Java"]}
        assert related_hint("Kafka", "Programista Java") is None


def test_guard_keeps_java_when_source_has_spring_boot() -> None:
    def strip() -> str:
        data = {
            "experience": [],
            "skills": [{"label": "Backend:", "content": "Java, Spring Boot"}],
        }
        strip_unsupported_terms(
            data,
            cv_text="Developer building services in Spring Boot and Kafka.",
            screening_notes_text="",
            requirements=["Java", "Spring Boot"],
            language="en",
        )
        return data["skills"][0]["content"]

    assert "Java" not in strip()
    with relations():
        assert "Java" in strip()


# ── Bramka krytycznych: zamiennik zostawia osobę ────────────────────────────


def test_alternative_hits_from_skill_list() -> None:
    candidate = SimpleNamespace(
        id=1, skills=[{"name": "Flask"}, {"name": "Python"}], raw_cv_text="", cv_text=""
    )
    with relations():
        assert alternative_hits(candidate, ["FastAPI"]) == {"FastAPI": ["flask"]}
        assert alternative_hits(candidate, ["Kafka"]) == {}
