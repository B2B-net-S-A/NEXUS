"""Bramka must v9 (30.09.2026): ukrywają tylko umiejętności krytyczne,
budżet i dni w biurze to plakietki, kandydat bez żadnych danych ukryty zawsze."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import critical_skills
from app.services.dealbreaker_filters import (
    DealbreakerInputs,
    apply_dealbreakers,
    dealbreaker_inputs_for_job,
    office_fit_status,
    rate_fit_status,
)
from app.services.must_text_evidence import MustTextEvidence, evidence_for
from tests.taxonomy_fixture import hydrated_taxonomy

STATS = {
    "version": 1,
    "labels": {
        "java": {"rate": 0.956, "jobs": 187},
        "kafka": {"rate": 0.83, "jobs": 40},
    },
}


@pytest.fixture(autouse=True)
def _critical_mode(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MUST_GATE_MODE", "critical")
    with hydrated_taxonomy():
        critical_skills.set_payload(STATS)
        yield
        critical_skills.set_payload(None)


def _job(critical="absent", **kw):
    stack = {"must": [{"name": "Java"}, {"name": "Kafka"}]}
    if critical != "absent":
        stack["critical"] = critical
    base = dict(
        id=7,
        title="Java Developer",
        working_title=None,
        must_skills=["Java", "Kafka"],
        nice_skills=["Docker"],
        requirements_reviewed=True,
        matching_requirements=None,
        rate_budget_hourly=100,
        onsite_days_per_week=3,
        location="Warszawa",
        remote_policy=None,
        champion_profile={"stack": stack},
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _cand(cid, **kw):
    base = dict(
        id=cid,
        skills=None,
        verified_tech=None,
        tags=None,
        cv_extracted_data=None,
        raw_cv_text=None,
        expected_rate_hourly=None,
        expected_rate_currency=None,
        max_onsite_days_per_week=None,
        city=None,
        location=None,
        preferences=None,
        b2b_willingness=None,
        accepts_below_min_rate=None,
        accepts_more_office_days=None,
        work_time_preference=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _must(inputs):
    return [m.lower() for m in inputs.must_skills]


def test_undecided_job_gates_on_the_history_suggestion_only():
    inputs = dealbreaker_inputs_for_job(_job())
    assert _must(inputs) == ["java"]
    assert inputs.critical_source == "suggested"
    assert [m.lower() for m in inputs.must_skills_ignored] == ["kafka"]
    # Dowód z CV liczy się raz dla wszystkich technologii must i nice.
    assert {m.lower() for m in inputs.gate_evidence_labels} >= {
        "java",
        "kafka",
        "docker",
    }


def test_dl_choice_wins_over_the_suggestion():
    inputs = dealbreaker_inputs_for_job(_job(critical=["Kafka"]))
    assert _must(inputs) == ["kafka"] and inputs.critical_source == "dl"


def test_no_critical_means_no_must_gate():
    inputs = dealbreaker_inputs_for_job(_job(critical=[]))
    assert inputs.must_skills == () and inputs.critical_source == "none"
    kept = apply_dealbreakers([_cand(1, skills=["Python"])], inputs=inputs).kept
    assert [c.id for c in kept] == [1]


def test_budget_and_office_days_only_label_the_row():
    inputs = dealbreaker_inputs_for_job(_job(critical=[]))
    cand = _cand(
        1,
        skills=["Java"],
        expected_rate_hourly=180,
        expected_rate_currency="PLN",
        max_onsite_days_per_week=1,
    )
    result = apply_dealbreakers([cand], inputs=inputs)
    assert [c.id for c in result.kept] == [1]
    assert result.hidden_over_budget == 0 and result.hidden_office_days_exceeded == 0
    assert rate_fit_status(cand, inputs) == "over_budget"
    assert office_fit_status(cand, inputs) == "days_exceeded"


def test_candidate_without_any_data_is_hidden_even_without_a_must_gate():
    inputs = DealbreakerInputs()
    result = apply_dealbreakers(
        [_cand(1), _cand(2, raw_cv_text="Java dev")], inputs=inputs
    )
    assert [c.id for c in result.kept] == [2]
    assert result.exclusion_reasons == {1: "no_data"}


def test_a_note_from_a_call_is_data():
    cand = _cand(1)
    cand._must_text_evidence = MustTextEvidence(key=(), met=frozenset(), has_notes=True)
    assert apply_dealbreakers([cand], inputs=DealbreakerInputs()).kept == [cand]


def test_evidence_attached_for_a_superset_serves_the_critical_subset():
    cand = _cand(1)
    cand._must_text_evidence = MustTextEvidence(
        key=("java", "kafka", "docker"), met=frozenset({"java"}), has_notes=False
    )
    assert evidence_for(cand, ("java",)) is not None
    assert evidence_for(cand, ("python",)) is None


def test_missing_critical_hides_but_missing_other_must_does_not():
    inputs = dealbreaker_inputs_for_job(_job(critical=["Java"]))
    with_java = _cand(1, skills=["Java"])
    only_kafka = _cand(2, skills=["Kafka"])
    result = apply_dealbreakers([with_java, only_kafka], inputs=inputs)
    assert [c.id for c in result.kept] == [1]
    assert result.exclusion_reasons == {2: "missing_must"}


def test_all_mode_restores_v8(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MUST_GATE_MODE", "all")
    inputs = dealbreaker_inputs_for_job(_job(critical=[]))
    assert set(_must(inputs)) == {"java", "kafka"}
    cand = _cand(
        1,
        skills=["Java", "Kafka"],
        expected_rate_hourly=180,
        expected_rate_currency="PLN",
    )
    assert apply_dealbreakers([cand], inputs=inputs).hidden_over_budget == 1


def test_request_context_freezes_critical_and_changes_the_fingerprint():
    from app.services.request_matching_context import build_request_context
    from app.services.scoring_service import DEFAULT_PROFILE

    a = build_request_context(_job(critical=["Java"]), DEFAULT_PROFILE)
    b = build_request_context(_job(critical=["Kafka"]), DEFAULT_PROFILE)
    assert a.fingerprint != b.fingerprint
    frozen = a.as_job()
    assert critical_skills.effective_critical(frozen).labels == ("Java",) or [
        x.lower() for x in critical_skills.effective_critical(frozen).labels
    ] == ["java"]


def test_salary_is_neutral_and_says_so():
    from app.services.scoring_service import (
        UNKNOWN_NEUTRAL_FRACTION,
        _renormalizing,
        _score_salary,
    )

    job = _job(critical=[], salary_min=None, salary_max=None)
    in_budget = _cand(1, expected_rate_hourly=90, expected_rate_currency="PLN")
    over = _cand(2, expected_rate_hourly=150, expected_rate_currency="PLN")
    a, b = _score_salary(in_budget, job), _score_salary(over, job)
    assert a.points == b.points
    expected = 0.0 if _renormalizing() else a.max_points * UNKNOWN_NEUTRAL_FRACTION
    assert a.points == pytest.approx(expected)
    assert "ponad budżet o 50%" in b.reason and b.status == "info"


def test_skills_count_text_evidence_and_only_technologies():
    from app.services.scoring_service import _score_skills

    job = _job(
        critical=[],
        must_skills=["Java", "Kafka", "komunikatywność"],
        nice_skills=[],
    )
    cand = _cand(1, skills=["Java"])
    cand._must_text_evidence = MustTextEvidence(
        key=("java", "kafka"), met=frozenset({"kafka"}), has_notes=False
    )
    layer, matched, gaps, _, _ = _score_skills(cand, job)
    # Kafka z CV/notatek się liczy; „komunikatywność” nie rozcieńcza punktów.
    assert {m.lower() for m in matched} == {"java", "kafka"}
    assert "must 2/2" in layer.reason


def test_evidence_labels_cover_must_scored_from_the_description(monkeypatch):
    """Dowód z CV ma objąć każdą technologię, którą liczy ocena — także must
    wyciągnięte z opisu, nie tylko podane wprost (pomiar 30.09.2026)."""
    from app.services import scoring_service

    monkeypatch.setattr(
        scoring_service,
        "job_skill_requirements",
        lambda job: {"must": ["Java", "Kafka", "Spring"], "nice": ["Docker"]},
    )
    labels = dealbreaker_inputs_for_job(_job()).gate_evidence_labels
    assert {"Java", "Kafka", "Spring", "Docker"} <= set(labels)


# ── 09.10.2026: krytyczną z wyboru DL może być dowolna fraza ────────────────
def _phrase_job(rows=None, critical=("bankowość",)):
    stack = {
        "must": [{"name": "Java"}, {"name": "bankowość"}],
        "critical": list(critical),
    }
    if rows is not None:
        stack["rows"] = rows
    return _job(
        must_skills=["Java", "bankowość"],
        champion_profile={"stack": stack},
    )


def test_phrase_chosen_by_dl_hides_people_without_its_row_words():
    job = _phrase_job(
        rows=[
            {"words": ["Java"], "level": "must"},
            {"words": ["bankowość", "bankow*", "banking"], "level": "critical"},
        ]
    )
    inputs = dealbreaker_inputs_for_job(job)
    assert _must(inputs) == ["bankowość"] and inputs.critical_source == "dl"
    assert inputs.gate_options["bankowość"] == ("bankowość", "bankow*", "banking")
    candidates = [
        # Odmiana słowa z wiersza („bankowości”) w CV.
        _cand(1, skills=["Java"], raw_cv_text="5 lat w bankowości detalicznej."),
        # Angielski wariant z tego samego wiersza.
        _cand(2, skills=["Java"], raw_cv_text="Core banking systems, Java 17."),
        # Rdzeń z gwiazdką („bankow*”).
        _cand(3, skills=["Java"], raw_cv_text="Projekty dla sektora bankowego."),
        # Nic z wiersza — ukryty, choć zna Javę.
        _cand(4, skills=["Java"], raw_cv_text="E-commerce i logistyka."),
    ]
    result = apply_dealbreakers(candidates, inputs=inputs)
    assert [c.id for c in result.kept] == [1, 2, 3]
    assert result.exclusion_reasons[4] == "missing_must"


def test_phrase_without_rows_looks_for_itself():
    inputs = dealbreaker_inputs_for_job(_phrase_job())
    assert inputs.gate_options == {"bankowość": ("bankowość",)}
    kept = apply_dealbreakers(
        [
            _cand(1, raw_cv_text="Doświadczenie: bankowość korporacyjna."),
            _cand(2, raw_cv_text="Doświadczenie: telekomunikacja."),
        ],
        inputs=inputs,
    ).kept
    assert [c.id for c in kept] == [1]


def test_sentence_chosen_as_critical_gates_on_the_literal_words():
    sentence = "doświadczenie w migracji do chmury"
    job = _job(
        must_skills=["Java", sentence],
        champion_profile={
            "stack": {
                "must": [{"name": "Java"}, {"name": sentence}],
                "critical": [sentence],
            }
        },
    )
    inputs = dealbreaker_inputs_for_job(job)
    assert _must(inputs) == [sentence]
    kept = apply_dealbreakers(
        [
            _cand(1, raw_cv_text="Mam doświadczenie w migracji do chmury AWS."),
            _cand(2, raw_cv_text="Migrowałem systemy do chmury."),
        ],
        inputs=inputs,
    ).kept
    assert [c.id for c in kept] == [1]


def test_row_variants_count_for_a_technology_too():
    job = _job(
        critical=["Kafka"],
    )
    job.champion_profile["stack"]["rows"] = [
        {"words": ["Java"], "level": "must"},
        {"words": ["Kafka", "kolejki"], "level": "critical"},
    ]
    inputs = dealbreaker_inputs_for_job(job)
    assert {k.lower(): v for k, v in inputs.gate_options.items()} == {
        "kafka": ("kolejki",)
    }
    kept = apply_dealbreakers(
        [
            _cand(1, raw_cv_text="Systemy oparte o kolejki komunikatów."),
            _cand(2, raw_cv_text="REST API i bazy danych."),
        ],
        inputs=inputs,
    ).kept
    assert [c.id for c in kept] == [1]


def test_history_suggestion_never_gates_on_a_phrase():
    # Bez decyzji DL działa podpowiedź z historii — tylko technologie ze
    # słownika, bez słów wiersza.
    job = _job(must_skills=["Java", "bankowość"])
    job.champion_profile = {
        "stack": {"must": [{"name": "Java"}, {"name": "bankowość"}]}
    }
    inputs = dealbreaker_inputs_for_job(job)
    assert _must(inputs) == ["java"] and inputs.critical_source == "suggested"
    assert inputs.gate_options == {}


def test_sql_pool_is_not_narrowed_by_a_critical_searched_by_words():
    from app.services.hybrid_search import build_job_must_groups

    job = _phrase_job(critical=("Java", "bankowość"))
    groups = build_job_must_groups(job)
    flat = {name.lower() for group in groups for name in group}
    # Technologia zawęża pulę, fraza nie — pula ⊇ bramka.
    assert "java" in flat and not any("bankowo" in name for name in flat)
