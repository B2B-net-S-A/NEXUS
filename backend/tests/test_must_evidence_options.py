"""Warianty wierszy i chipy Championa w ocenie „musi mieć” (02.11.2026)."""

from types import SimpleNamespace

from app.services.dealbreaker_filters import dealbreaker_inputs_for_job
from app.services.must_text_evidence import MustTextEvidence, text_met_labels
from app.services.requirement_contract import (
    evaluate_requirements,
    requirements_for_job,
)
from app.services.scoring_service import job_skill_requirements


def _job(**extra):
    values = dict(
        id=1,
        title="Analityk",
        must_skills=[],
        nice_skills=[],
        requirements_reviewed=False,
        matching_requirements=None,
        champion_profile=None,
    )
    values.update(extra)
    return SimpleNamespace(**values)


def _rows(*rows, critical=None):
    stack = {"rows": [{"level": "must", "words": list(words)} for words in rows]}
    if critical is not None:
        stack["critical"] = critical
    return {"stack": stack}


def _person(cv):
    return SimpleNamespace(
        id=7,
        skills=[],
        raw_cv_text=cv,
        cv_extracted_data=None,
        experience=None,
        name="A",
        lastname="B",
        current_position=None,
    )


def _status(job, person):
    inputs = dealbreaker_inputs_for_job(job)
    person._must_text_evidence = MustTextEvidence(
        key=inputs.gate_evidence_labels,
        met=text_met_labels(
            person, inputs.gate_evidence_labels, (), options=inputs.gate_options
        ),
        has_notes=False,
    )
    return {
        row["any_of"][0]: row["status"]
        for row in evaluate_requirements(requirements_for_job(job), person)
        if row["level"] == "must"
    }


def test_any_word_of_a_non_critical_row_meets_the_requirement():
    job = _job(
        must_skills=[{"name": "płatniczych"}],
        champion_profile=_rows(("płatniczych", "payment*", "płatności")),
    )
    assert _status(job, _person("Systemy płatności w banku")) == {"płatniczych": "met"}
    assert _status(job, _person("Payments gateway")) == {"płatniczych": "met"}
    assert _status(job, _person("Hurtownia danych")) == {"płatniczych": "unknown"}


def test_requirement_outside_the_dictionary_searches_for_itself():
    job = _job(must_skills=[{"name": "Change management"}])
    assert _status(job, _person("Prowadził change management w PKO")) == {
        "change management": "met"
    }
    assert _status(job, _person("Programista Java")) == {"change management": "unknown"}


def test_the_gate_keeps_its_own_words_only():
    # Podpowiedź z historii nie dostaje słów wiersza: krytyczna z `must` nie może
    # zmięknąć przez opcje oceny.
    job = _job(
        must_skills=[{"name": "Java"}, {"name": "Agile"}],
        champion_profile=_rows(("Java", "Kotlin"), ("Agile",)),
    )
    inputs = dealbreaker_inputs_for_job(job)
    assert not set(inputs.must_skills) & set(inputs.gate_options)
    assert "agile" in {label.lower() for label in inputs.gate_evidence_labels}


def test_chips_replace_a_column_of_sentences():
    job = _job(
        must_skills=[
            {"name": "bardzo dobra znajomość SQL w praktyce"},
            {"name": "Git"},
        ],
        champion_profile={"stack": {"must": [{"name": "SQL"}, {"name": "Git"}]}},
    )
    assert job_skill_requirements(job)["must"] == ["sql", "git"]


def test_short_column_stays_when_chips_differ():
    job = _job(
        must_skills=[{"name": "Java"}],
        champion_profile={"stack": {"must": [{"name": "Python"}]}},
    )
    assert job_skill_requirements(job)["must"] == ["java"]


def test_reviewed_requirements_ignore_the_chips():
    job = _job(
        must_skills=[{"name": "bardzo dobra znajomość SQL w praktyce"}],
        requirements_reviewed=True,
        champion_profile={"stack": {"must": [{"name": "SQL"}]}},
    )
    assert job_skill_requirements(job)["must"] != ["sql"]
