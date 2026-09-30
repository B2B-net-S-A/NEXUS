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
