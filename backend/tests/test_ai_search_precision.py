"""Trafność wyszukiwania AI po audycie 06–07.10.2026.

Fałszywy dowód z notatek (braki i przeczące odpowiedzi), „tylko zdalnie”
jako plakietka przy hybrydzie, węższa podpowiedź krytycznych i dopasowanie
nazw (C#, rodzina SQL, PlantUML, „rest of the team”).
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from app.services import critical_skills
from app.services.dealbreaker_filters import (
    DealbreakerInputs,
    apply_dealbreakers,
    dealbreaker_inputs_for_job,
    remote_fit_status,
)
from app.services.must_gate_terms import gate_requirement
from app.services.must_text_evidence import (
    evidence_note_text,
    is_negative_answer,
    mentions,
    profile_text,
    text_met_labels,
)
from app.services.scoring_service import is_technology_mention, skill_present
from tests.taxonomy_fixture import hydrated_taxonomy


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


# ── Dowód z faktów odczytanych z notatek ─────────────────────────────────────


def test_skill_gaps_from_notes_are_not_evidence():
    cand = _cand(
        cv_extracted_data={
            "_notes_insights": {
                "skills_gaps_observed": [{"name": "Kafka", "evidence": "nie zna"}],
                "client_vetoes": [{"client": "Kafka Bank"}],
            }
        }
    )
    assert "kafka" not in profile_text(cand).lower()
    assert text_met_labels(cand, ["Kafka"]) == frozenset()


def test_skills_confirmed_in_conversation_stay_evidence():
    cand = _cand(
        cv_extracted_data={
            "_notes_insights": {
                "skills_evidenced": [{"name": "Kafka", "evidence": "3 lata"}],
                "certifications": [{"name": "CKA"}],
            }
        }
    )
    assert text_met_labels(cand, ["Kafka"]) == frozenset({"Kafka"})


# ── Karta rekomendacji: przeczące odpowiedzi ─────────────────────────────────

_CARD = (
    "<p>Stawka: 140 zł/h</p>"
    "<p>P1: Jak wygląda Twoje doświadczenie z Kubernetes?</p>"
    "<p>Odpowiedź: zna tylko teoretycznie</p>"
    "<p>P2: Czy pracowałeś z Java i Spring?</p>"
    "<p>Odpowiedź: tak, 5 lat w bankowości</p>"
)


def test_question_answered_negatively_is_not_evidence():
    text = evidence_note_text("card", _CARD)
    assert not mentions(gate_requirement("Kubernetes"), text)
    # Pytanie z odpowiedzią twierdzącą zostaje dowodem — „tak” bez nazwy.
    assert mentions(gate_requirement("Java"), text)
    assert "Stawka" in text


def test_card_without_negative_answers_is_unchanged():
    content = "<p>P1: Czy znasz Kafkę?</p><p>Odpowiedź: tak</p>"
    assert evidence_note_text("card", content) == content


def test_same_card_is_parsed_once_not_on_every_board_refresh(monkeypatch):
    """Tablica (`/pipeline-scores`) przy każdym odświeżeniu parsowała od nowa
    karty wszystkich osób rekrutacji: 467 kart = 0,5 s CPU bez oddania pętli
    zdarzeń (pomiar na stagingu 27.10.2026). Karta się nie zmienia."""
    from app.services import recommendation_card_parser as rcp

    calls = []
    real = rcp.parse_card
    monkeypatch.setattr(rcp, "parse_card", lambda c: calls.append(c) or real(c))
    content = _CARD + "<p>Notatka: jedna karta dla testu pamięci podręcznej</p>"
    first = evidence_note_text("card", content)
    assert evidence_note_text("card", content) == first
    assert not mentions(gate_requirement("Kubernetes"), first)
    assert len(calls) == 1


def test_heading_list_counts_only_what_the_body_names():
    """Zgłoszenie DL-a 28.10.2026: fakty ze screeningu z nagłówkiem
    „Frontend (React / Angular)” i treścią tylko o Reakcie dawały „✓ angular”
    osobie, która Angulara nie zna."""
    content = (
        "<p><strong>Frontend (React / Angular)</strong><br>Ma jedynie podstawowe "
        "doświadczenie – głównie w zakresie bug fixing w React. Brak aktywnego "
        "rozwoju większych modułów.</p>"
        "<p><strong>Backend (Java / Spring Boot)</strong><br>8 lat komercyjnie, "
        "mikroserwisy.</p>"
    )
    text = evidence_note_text("screening_facts", content)
    assert not mentions(gate_requirement("Angular"), text)
    assert mentions(gate_requirement("React"), text)
    # Treść nie wymienia żadnej pozycji nagłówka — cały nagłówek zostaje.
    assert mentions(gate_requirement("Java"), text)
    assert mentions(gate_requirement("Spring Boot"), text)


def test_wrapped_list_line_is_not_a_heading():
    content = (
        "<p>Key technologies: Python (advanced level),<br>Robot Framework, "
        "CI/CD with Jenkins, SQL, Selenium, and AI solutions<br>Automated "
        "regression with Robot Framework and Jenkins for two years.</p>"
    )
    text = evidence_note_text("card", content)
    assert mentions(gate_requirement("Selenium"), text)
    assert mentions(gate_requirement("SQL"), text)


def test_negation_in_one_part_of_a_sentence_keeps_the_other_part():
    content = (
        "<p>Narzędzia: QTest nie używał, ale za to Jira, Confluence jest.</p>"
        "<p>Nie pracuje na co dzień z bazami danych, natomiast zna SQL.</p>"
        "<p>Pracował nie tylko z Kafką, ale i z RabbitMQ.</p>"
    )
    notes = [evidence_note_text("screening_facts", content)]
    assert text_met_labels(
        _cand(), ["QTest", "Jira", "SQL", "Kafka", "RabbitMQ"], notes
    ) == frozenset({"Jira", "SQL", "Kafka", "RabbitMQ"})


def test_wish_to_learn_is_not_evidence():
    content = (
        "<p>Podsumowanie: backend w Java i Spring Boot, Kafka, Docker. Open to "
        "expanding skills in frontend technologies (React.js, Angular.js) and "
        "Big Data tools.</p><p>Uwagi: Chce się nauczyć Kubernetes.</p>"
    )
    cand = _cand()
    notes = [evidence_note_text("card", content)]
    assert text_met_labels(
        cand, ["Java", "Kafka", "Angular", "React", "Kubernetes"], notes
    ) == frozenset({"Java", "Kafka"})


def test_other_note_kinds_pass_through():
    content = "<p>P1: Kubernetes?</p><p>Odpowiedź: nie</p>"
    assert evidence_note_text("human", content) == content
    assert evidence_note_text(None, content) == content


@pytest.mark.parametrize(
    ("answer", "negative"),
    [
        ("nie", True),
        ("Nie miał styczności", True),
        ("zna tylko teoretycznie", True),
        ("brak doświadczenia komercyjnego", True),
        ("nie pracował z tym", True),
        ("no", True),
        ("tak, 3 lata", False),
        ("zna podstawy", False),
        ("słabo, ale używał", False),
        ("", False),
        (None, False),
        ("Pracował z Kafką, nie tylko z RabbitMQ", False),
        ("chętnie się nauczy", True),
        ("Open to learning Angular", True),
        ("willing to learn", True),
        ("chciałby poznać Reacta", True),
        ("Chce rozwijać się w kierunku chmury, zna AWS", False),
        ("Posiada ISTQB, przygotowanie teoretyczne i praktyczne", False),
        ("W CV nie miał wpisanej Jiry - wszystko zna i używał", False),
        ("Nie miał dotychczas styczności z SOA", True),
        ("PowerShell największe, Bash słabe, Python nie miał", True),
        ("Ma tylko teoretyczne, na studiach", True),
    ],
)
def test_negative_answer_dictionary(answer, negative):
    assert is_negative_answer(answer) is negative


# ── Dopasowanie nazw ─────────────────────────────────────────────────────────


def test_csharp_label_matches_regardless_of_case():
    req = gate_requirement("c#")
    assert req is not None
    assert mentions(req, "Backend w C# i .NET")
    assert mentions(gate_requirement("C#"), "projekty w c# (asp.net)")
    # Zwykłe słowo dalej tylko w pisowni technologii.
    assert not mentions(gate_requirement("Go"), "chcę go zatrudnić")


def test_sql_family_satisfies_sql_but_not_the_other_way_round():
    cand = _cand(raw_cv_text="Bazy: PostgreSQL & MySQL, AWS RDS")
    assert text_met_labels(cand, ["SQL"]) == frozenset({"SQL"})
    assert skill_present("SQL", {"postgresql"})
    assert skill_present("sql", {"MS SQL"})
    assert not skill_present("PostgreSQL", {"sql"})


def test_plantuml_satisfies_uml():
    cand = _cand(skills=[{"name": "PlantUML"}])
    assert text_met_labels(cand, ["UML"]) == frozenset({"UML"})
    assert skill_present("UML", {"plantuml"})


def test_rest_as_a_plain_word_is_not_rest_api():
    skills = {"REST API": ("backend", ("rest", "restful"))}
    with hydrated_taxonomy(skills):
        req = gate_requirement("REST API")
        assert req is not None
        assert not mentions(req, "coordinated the rest of the team")
        assert not mentions(req, "encryption of data at rest")
        assert mentions(req, "REST/SOAP web services")
        assert mentions(req, "Built REST APIs in Spring")


def test_rest_mention_filter_for_raw_cv_scan():
    pattern = re.compile(r"\b(rest)\b", re.I)
    text = "the rest of the team; REST endpoints"
    hits = [m for m in pattern.finditer(text) if is_technology_mention(text, m)]
    assert [m.start() for m in hits] == [text.index("REST endpoints")]


# ── „Tylko zdalnie” z notatek ────────────────────────────────────────────────


def _remote_only():
    return _cand(
        id=5,
        skills=[{"name": "Java"}],
        cv_extracted_data={"_notes_insights": {"preferences": {"remote_only": True}}},
    )


def _job(policy, days=None, exclude=False):
    return SimpleNamespace(
        rate_budget_hourly=None,
        must_skills=None,
        onsite_days_per_week=days,
        location="Warszawa",
        remote_policy=SimpleNamespace(value=policy) if policy else None,
        champion_profile=None,
        exclude_remote_only=exclude,
    )


def test_hybrid_job_keeps_remote_only_candidate_with_badge():
    inputs = dealbreaker_inputs_for_job(_job("hybrid", days=2))
    assert inputs.wants_office and not inputs.remote_only_hides
    cand = _remote_only()
    res = apply_dealbreakers([cand], inputs=inputs)
    assert res.kept == [cand]
    assert remote_fit_status(cand, inputs) == "prefers_remote"


@pytest.mark.parametrize(
    "job",
    [_job("onsite"), _job("hybrid", days=4), _job("hybrid", days=1, exclude=True)],
)
def test_onsite_four_days_or_explicit_exclusion_still_hide(job):
    inputs = dealbreaker_inputs_for_job(job)
    assert inputs.remote_only_hides
    res = apply_dealbreakers([_remote_only()], inputs=inputs)
    assert res.kept == [] and res.hidden_remote_only == 1
    assert res.exclusion_reasons == {5: "remote_only"}


def test_remote_job_has_no_badge():
    inputs = dealbreaker_inputs_for_job(_job("remote"))
    assert remote_fit_status(_remote_only(), inputs) == "not_required"


def test_callers_without_inputs_keep_hiding_on_explicit_flag():
    res = apply_dealbreakers(
        [_remote_only()], inputs=DealbreakerInputs(), exclude_remote_only=True
    )
    assert res.hidden_remote_only == 1


# ── Podpowiedź krytycznych ───────────────────────────────────────────────────

_STATS = {
    "version": 1,
    "labels": {
        "java": {"rate": 0.956, "jobs": 187},
        "angular": {"rate": 0.901, "jobs": 27},
        "c#": {"rate": 0.931, "jobs": 86},
        "docker": {"rate": 0.944, "jobs": 30},
    },
}


@pytest.fixture
def _stats():
    with hydrated_taxonomy():
        critical_skills.set_payload(_STATS)
        yield
        critical_skills.set_payload(None)


@pytest.mark.usefixtures("_stats")
def test_far_position_of_a_long_list_is_not_suggested():
    must = [f"Umiejętność {i}" for i in range(6)] + ["C#", "Docker", "Java", "x"]
    assert critical_skills.suggest_from_must(must, "Java/Angular Developer") == (
        "Java",
    )
    assert critical_skills.suggest_from_must(must, "Developer") == ()


@pytest.mark.usefixtures("_stats")
def test_first_positions_of_a_short_list_are_suggested():
    must = ["Docker", "C#", "Angular", "Java"]
    assert critical_skills.suggest_from_must(must) == ("Docker", "C#")
