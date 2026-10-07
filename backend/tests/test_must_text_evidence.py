"""Must spełniony, gdy jest w profilu, CV albo notatkach (decyzja 27.09.2026)."""

from types import SimpleNamespace

from app.services.dealbreaker_filters import DealbreakerInputs, apply_dealbreakers
from app.services.must_gate_terms import gate_requirement
from app.services.must_text_evidence import (
    MustTextEvidence,
    mentions,
    text_met_labels,
)


def _cand(**kw):
    base = dict(
        id=1,
        skills=None,
        verified_tech=None,
        tags=None,
        cv_extracted_data=None,
        raw_cv_text=None,
        experience=None,
        expected_rate_hourly=None,
        max_onsite_days_per_week=None,
        location=None,
        city=None,
        preferences=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_whole_word_and_special_names():
    assert mentions(gate_requirement("Java"), "Java 17, Spring")
    assert not mentions(gate_requirement("Java"), "JavaScript i TypeScript")
    assert mentions(gate_requirement("C#"), "Backend w C# i .NET")
    assert mentions(gate_requirement("Node.js"), "API w Node.js")


def test_short_names_only_as_written():
    # „go” to też polskie słowo — liczy się tylko „Go”.
    assert not mentions(gate_requirement("Go"), "chcę go zatrudnić")
    assert mentions(gate_requirement("Go"), "Mikroserwisy w Go i Kubernetes")


def test_any_example_option_satisfies():
    label = "CI/CD tools like Bitbucket, Jenkins"
    cand = _cand(raw_cv_text="Pipeline'y w Jenkins, repozytoria GitLab")
    assert text_met_labels(cand, [label]) == frozenset({label})


def test_profile_fields_count():
    cand = _cand(
        experience=[{"role": "Developer", "description": "Kafka Streams, Oracle"}]
    )
    assert text_met_labels(cand, ["Kafka"]) == frozenset({"Kafka"})


def test_attached_note_evidence_satisfies_the_gate():
    """Technologia wyłącznie w notatce rekrutera — kandydat przechodzi."""
    cand = _cand(id=7, skills=[{"name": "Java"}])
    cand._must_text_evidence = MustTextEvidence(
        key=("Kafka",), met=frozenset({"Kafka"}), has_notes=True
    )
    res = apply_dealbreakers([cand], inputs=DealbreakerInputs(must_skills=("Kafka",)))
    assert res.kept == [cand]


def test_notes_alone_are_data_but_not_evidence():
    """Kandydat z samymi notatkami (bez must) to `missing_must`, nie `no_data`."""
    cand = _cand(id=8)
    cand._must_text_evidence = MustTextEvidence(
        key=("Kafka",), met=frozenset(), has_notes=True
    )
    res = apply_dealbreakers([cand], inputs=DealbreakerInputs(must_skills=("Kafka",)))
    assert res.exclusion_reasons == {8: "missing_must"}


def test_evidence_for_another_must_list_is_ignored():
    cand = _cand(id=9, skills=[{"name": "Java"}])
    cand._must_text_evidence = MustTextEvidence(
        key=("Python",), met=frozenset({"Kafka"}), has_notes=True
    )
    res = apply_dealbreakers([cand], inputs=DealbreakerInputs(must_skills=("Kafka",)))
    assert res.exclusion_reasons == {9: "missing_must"}


# ── Audyt 06.10.2026 (K7, K9, K12) ──────────────────────────────────────────


def test_phrase_with_brackets_and_commas_counts():
    """K7: „Spring (Boot, Data)” w CV spełnia must „Spring Boot”."""
    assert mentions(gate_requirement("Spring Boot"), "Java 17, Spring (Boot, Data)")


def test_inflected_names_of_four_or_more_letters_count():
    """K12: „z Kafką”, „w Javie” — odmiana nazwy ≥ 4 litery to wzmianka."""
    assert mentions(gate_requirement("Kafka"), "Integracje z Kafką i Oracle")
    assert mentions(gate_requirement("Java"), "Pisał mikroserwisy w Javie")
    assert mentions(gate_requirement("Docker"), "Wdrożenia z Dockerem")
    # Odmiana nie otwiera dowolnej końcówki: „Java” ≠ „JavaScript”.
    assert not mentions(gate_requirement("Java"), "Frontend w JavaScripcie")
    # Krótsze nazwy (≤ 3 litery) bez odmiany — „Go” to też polskie słowo.
    assert not mentions(gate_requirement("Go"), "chcę go zatrudnić")


def test_profile_text_alone_is_data():
    """K9: historia stanowisk bez CV i listy umiejętności to dane, nie `no_data`."""
    from app.services.must_text_evidence import has_any_data

    cand = _cand(
        id=10,
        experience=[{"role": "Java Developer", "company": "Acme", "description": "x"}],
    )
    assert has_any_data(cand, None)


def test_cv_file_waiting_for_text_is_not_no_data():
    """K9: plik CV bez odczytanego tekstu czeka na ponowny odczyt (nocna faza
    `candidates_cv_text`) — to nie „nic o nim nie wiemy”."""
    from app.services.must_text_evidence import cv_waiting_for_text, has_any_data

    cand = _cand(id=11, cv_storage_key="cv/11.pdf")
    assert cv_waiting_for_text(cand)
    assert has_any_data(cand, None)
    res = apply_dealbreakers([cand], inputs=DealbreakerInputs(must_skills=("Kafka",)))
    assert res.exclusion_reasons.get(11) != "no_data"
    # Plik, którego nie da się odczytać (znacznik końcowy), nie jest danymi.
    hopeless = _cand(
        id=12,
        cv_storage_key="cv/12.pdf",
        cv_extracted_data={
            "_cv_text_extraction": {
                "outcome": "junk",
                "storage_key": "cv/12.pdf",
                "sniffed": True,
            }
        },
    )
    assert not cv_waiting_for_text(hopeless)
    assert not has_any_data(hopeless, None)
