"""Etap 3a słownika (07.11.2026): warianty nazw w tekście CV dla QC i strażnika.

Pomiar na kopii (704 pary): QC pytało o „Anti-Money Laundering” analityków
AML, bo warianty spoza technologii się nie liczyły; z kolei wariant „project”
przy „Microsoft Project” uznałby brak za trafienie.
"""

from __future__ import annotations

from app.services import dz_review as dz
from app.services.cv_generator_b2b.legacy_v7._helpers import strip_unsupported_terms
from app.services.skill_normalize import alias_counts_in_text, text_alias_forms
from tests.taxonomy_fixture import hydrated_taxonomy

SKILLS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Anti-Money Laundering": ("domain", ("aml",)),
    "Microsoft Project": ("tools", ("ms project", "project")),
    "Microsoft Excel": ("tools", ("excel", "ms excel")),
    "Kubernetes": ("devops", ("k8s",)),
    "QA": ("role_qa", ("quality assurance",)),
}


def _req(name: str) -> dz.Requirement:
    return dz.Requirement(label=name, alternatives=(name,))


def test_default_rule_for_aliases() -> None:
    assert alias_counts_in_text("k8s", "Kubernetes", "devops", None)
    assert alias_counts_in_text("aml", "Anti-Money Laundering", "domain", None)
    assert alias_counts_in_text("ms project", "Microsoft Project", "tools", None)
    # Jedno słowo z wielowyrazowej nazwy to zwykłe słowo w CV.
    assert not alias_counts_in_text("project", "Microsoft Project", "tools", None)
    assert not alias_counts_in_text("excel", "Microsoft Excel", "tools", None)
    # Technologia liczy się jak dotąd, nawet gdy wariant jest częścią nazwy.
    assert alias_counts_in_text("kafka", "Apache Kafka", "messaging", None)


def test_curator_flag_wins_except_for_roles() -> None:
    assert alias_counts_in_text("excel", "Microsoft Excel", "tools", True)
    assert not alias_counts_in_text("k8s", "Kubernetes", "devops", False)
    assert not alias_counts_in_text("quality assurance", "QA", "role_qa", True)


def test_text_forms_skip_roles_and_unknown_names() -> None:
    with hydrated_taxonomy(SKILLS):
        assert text_alias_forms("AML") == ["aml", "anti-money laundering"]
        assert "project" not in text_alias_forms("Microsoft Project")
        assert text_alias_forms("QA") == []
        assert text_alias_forms("Kafka Streams") == []


def test_qc_finds_aml_for_anti_money_laundering() -> None:
    text = "AML & Sanctions Processing Officer, Nordea, 2022–2024"
    assert dz.found_in(text, _req("Anti-Money Laundering")) is None
    with hydrated_taxonomy(SKILLS):
        assert dz.found_in(text, _req("Anti-Money Laundering")) is not None


def test_qc_does_not_take_project_for_microsoft_project() -> None:
    text = "Led the project team of five analysts"
    with hydrated_taxonomy(SKILLS):
        assert dz.found_in(text, _req("Microsoft Project")) is None
        assert dz.found_in("Plans in MS Project", _req("Microsoft Project")) is not None


def test_bold_patterns_stay_on_technologies() -> None:
    with hydrated_taxonomy(SKILLS):
        tech = [p.pattern for p in dz._tech_patterns("Anti-Money Laundering")]
        assert not any("aml" in p.lower() for p in tech)
        assert any("k8s" in p.pattern.lower() for p in dz._tech_patterns("Kubernetes"))


def _strip(cv_text: str) -> dict:
    data = {
        "experience": [],
        "skills": [
            {"label": "Domain:", "content": "Anti-Money Laundering, Kubernetes"}
        ],
    }
    strip_unsupported_terms(
        data,
        cv_text=cv_text,
        screening_notes_text="",
        requirements=["Anti-Money Laundering", "Kubernetes"],
        language="en",
    )
    return data


def test_guard_keeps_requirement_written_as_alias_in_cv() -> None:
    cv = "AML analyst with experience in transaction monitoring and K8s operations."
    assert "Anti-Money Laundering" not in _strip(cv)["skills"][0]["content"]
    with hydrated_taxonomy(SKILLS):
        content = _strip(cv)["skills"][0]["content"]
    assert "Anti-Money Laundering" in content
    assert "Kubernetes" in content
