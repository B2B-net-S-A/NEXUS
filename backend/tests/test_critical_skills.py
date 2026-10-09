"""Umiejętności krytyczne: podpowiedź z historii i decyzja DL (30.09.2026)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import critical_skills
from tests.taxonomy_fixture import hydrated_taxonomy

STATS = {
    "version": 1,
    "labels": {
        "java": {"rate": 0.956, "jobs": 187},
        "angular": {"rate": 0.901, "jobs": 27},
        "docker": {"rate": 0.944, "jobs": 30},
        "typescript": {"rate": 0.933, "jobs": 20},
        "kubernetes": {"rate": 0.886, "jobs": 40},
        "pega": {"rate": 0.95, "jobs": 3},  # za mało rekrutacji
        "react.js": {"rate": 0.97, "jobs": 10},
        "react": {"rate": 0.95, "jobs": 30},
        "qa": {"rate": 0.99, "jobs": 50},  # rola — nigdy krytyczna
    },
}


@pytest.fixture(autouse=True)
def _stats():
    with hydrated_taxonomy():
        critical_skills.set_payload(STATS)
        yield
        critical_skills.set_payload(None)


def _job(must, *, title="", critical="absent"):
    stack = {"must": [{"name": m} for m in must]}
    if critical != "absent":
        stack["critical"] = critical
    return SimpleNamespace(
        id=1,
        title=title,
        working_title=None,
        must_skills=list(must),
        nice_skills=[],
        requirements_reviewed=True,
        matching_requirements=None,
        champion_profile={"stack": stack},
    )


def test_suggestion_takes_only_technologies_with_strong_history():
    got = critical_skills.suggest_from_must(
        ["Java", "Kubernetes", "Pega", "QA", "team player"]
    )
    assert got == ("Java",)


def test_title_technology_goes_first_then_rate():
    must = ["Docker", "TypeScript", "Angular"]
    assert critical_skills.suggest_from_must(must, "Frontend (Angular)") == (
        "Angular",
        "Docker",
    )
    assert critical_skills.suggest_from_must(must) == ("Docker", "TypeScript")


def test_aliases_share_one_canonical_statistic():
    # „react.js” i „react” to ta sama technologia — średnia ważona.
    stat = critical_skills.stat_for("React 18+")
    assert stat is not None and stat.jobs == 40
    assert stat.rate == pytest.approx((0.97 * 10 + 0.95 * 30) / 40, abs=1e-4)


def test_undecided_job_uses_the_suggestion():
    res = critical_skills.effective_critical(_job(["Java", "Kubernetes"]))
    assert res.labels == ("java",) or res.labels == ("Java",)
    assert res.source == "suggested" and res.decided is False


def test_explicit_empty_list_disables_the_gate():
    res = critical_skills.effective_critical(_job(["Java"], critical=[]))
    assert res.labels == () and res.source == "none" and res.decided is True
    assert res.suggested  # podpowiedź dalej widoczna na ekranie


def test_dl_choice_wins_and_matches_by_canonical_name():
    res = critical_skills.effective_critical(
        _job(["Java", "Kubernetes"], critical=["kubernetes"])
    )
    assert [label.lower() for label in res.labels] == ["kubernetes"]
    assert res.source == "dl"


def test_dl_may_choose_three_but_the_suggestion_stays_at_two():
    # 08.10.2026: Delivery Lead wybiera do trzech krytycznych; podpowiedź
    # z historii działa bez decyzji człowieka, więc nadal daje najwyżej dwie.
    must = ["Java", "Docker", "TypeScript", "Angular"]
    chosen = critical_skills.effective_critical(
        _job(must, critical=["Java", "Docker", "Angular"])
    )
    assert [label.lower() for label in chosen.labels] == ["java", "docker", "angular"]
    assert chosen.source == "dl"
    undecided = critical_skills.effective_critical(_job(must))
    assert len(undecided.labels) == 2 and undecided.source == "suggested"
    assert len(critical_skills.suggest_from_must(must)) == 2


def test_resolution_payload_carries_search_rows_with_variants():
    """W1/W4 (audyt 06.10.2026): ekran wyszukiwania bierze obowiązkowe wiersze
    z serwera — po jednym na krytyczną, z wariantami nazwy."""
    from app.services import keyword_suggest
    from app.services.champion_intake import critical_resolution_payload

    saved = keyword_suggest._catalog
    keyword_suggest.load_catalog([(1, "Kubernetes", "devops")], [(1, "k8s")])
    try:
        payload = critical_resolution_payload(
            _job(["Java", "Kubernetes"], critical=["kubernetes"])
        )
    finally:
        keyword_suggest._catalog = saved
    assert payload["source"] == "dl"
    assert [[w.lower() for w in row] for row in payload["search_rows"]] == [
        ["kubernetes", "k8s"]
    ]


def test_single_letter_critical_is_skipped_from_search_rows_with_a_note(monkeypatch):
    """Krytyczna „R” nie staje się słowem kluczowym (prawie cała baza) —
    payload mówi, że pominięta; bramka AI dalej czyta ją z profilu."""
    from app.services import champion_intake

    monkeypatch.setattr(
        critical_skills,
        "effective_critical",
        lambda job: critical_skills.CriticalResolution(
            labels=("R", "Kubernetes"), source="dl", decided=True, suggested=()
        ),
    )
    payload = champion_intake.critical_resolution_payload(_job(["R", "Kubernetes"]))
    assert [row[0] for row in payload["search_rows"]] == ["Kubernetes"]
    assert payload["search_rows_skipped"] == ["R"]


def test_dl_choice_outside_must_is_dropped_but_any_must_phrase_stays():
    # 09.10.2026: o tym, co jest krytyczne, decyduje Delivery Lead — rola „QA”
    # z listy must zostaje; „Python”, którego na liście must nie ma, odpada.
    res = critical_skills.effective_critical(
        _job(["Java", "QA"], critical=["QA", "Python"])
    )
    assert [label.lower() for label in res.labels] == ["qa"]
    assert res.decided is True and res.source == "dl"


def test_dl_may_choose_any_phrase_from_must():
    # Narzędzie spoza słownika (08.10.2026) i fraza, która nie jest technologią
    # (09.10.2026): wybór Delivery Leada działa dla obu.
    must = ["Java", "Temenos T24", "bankowość"]
    res = critical_skills.effective_critical(
        _job(must, critical=["Temenos T24", "bankowość"])
    )
    assert [label.lower() for label in res.labels] == ["temenos t24", "bankowość"]
    assert res.source == "dl"
    assert critical_skills.critical_errors(["Temenos T24", "bankowość"], must) == []
    # Podpowiedź z historii dalej bierze wyłącznie technologie ze słownika.
    assert "Temenos T24" not in critical_skills.suggest_from_must(must)


def test_gate_options_carry_the_row_words_of_dl_chosen_criticals():
    must = ["Java", "Kafka", "bankowość"]
    job = _job(must, critical=["Kafka", "bankowość"])
    job.champion_profile["stack"]["rows"] = [
        {"words": ["Java"], "level": "must"},
        {"words": ["Kafka", "kolejki"], "level": "critical"},
        {"words": ["bankowość", "bankow*", "banking"], "level": "critical"},
        {"words": ["Docker"], "level": "nice"},
    ]
    options = critical_skills.critical_gate_options(job)
    by_label = {label.lower(): words for label, words in options.items()}
    # Fraza: wszystkie słowa wiersza; technologia: tylko słowa spoza reguły.
    assert by_label["bankowość"] == ("bankowość", "bankow*", "banking")
    assert by_label["kafka"] == ("kolejki",)
    # Krytyczna-technologia bez wariantów nie potrzebuje wpisu.
    plain = _job(must, critical=["Java"])
    plain.champion_profile["stack"]["rows"] = [{"words": ["Java"], "level": "critical"}]
    assert critical_skills.critical_gate_options(plain) == {}


def test_starred_stem_is_always_a_gate_word():
    """Przegląd kodu 09.10.2026: wiersz z samego rdzenia („bankow*”) ma etykietę
    „bankow”, która wygląda na nazwę technologii. Po zdjęciu gwiazdki rdzeń
    uchodził za powtórkę etykiety i wypadał — bramka szukała całego słowa
    „bankow”, a „Szukaj ręcznie” początku słowa."""
    job = _job(["Java", "bankow"], critical=["bankow"])
    job.champion_profile["stack"]["rows"] = [
        {"words": ["Java"], "level": "must"},
        {"words": ["bankow*"], "level": "critical"},
    ]
    options = critical_skills.critical_gate_options(job)
    assert {k.lower(): v for k, v in options.items()} == {"bankow": ("bankow*",)}
    with hydrated_taxonomy():
        # Technologia ze słownika z rdzeniem obok: rdzeń zostaje, nazwa nie dubluje.
        tech = _job(["JavaScript"], critical=["JavaScript"])
        tech.champion_profile["stack"]["rows"] = [
            {"words": ["JavaScript", "javascript*"], "level": "critical"}
        ]
        tech_options = critical_skills.critical_gate_options(tech)
        assert {k.lower(): v for k, v in tech_options.items()} == {
            "javascript": ("javascript*",)
        }


def test_gate_options_fall_back_to_the_phrase_itself_and_skip_suggestions():
    # Profil bez wierszy: fraza szuka samej siebie.
    job = _job(["Java", "bankowość"], critical=["bankowość"])
    options = critical_skills.critical_gate_options(job)
    assert {k.lower(): v for k, v in options.items()} == {"bankowość": ("bankowość",)}
    # Podpowiedź z historii (nikt jej nie potwierdził) nie dostaje słów wiersza.
    undecided = _job(["Java", "bankowość"])
    assert critical_skills.effective_critical(undecided).source == "suggested"
    assert critical_skills.critical_gate_options(undecided) == {}


def test_frozen_request_carries_the_gate_options():
    frozen = SimpleNamespace(
        critical_effective={
            "labels": ["bankowość"],
            "source": "dl",
            "suggested": [],
            "decided": True,
            "options": {"bankowość": ["bankow*", "banking"]},
        }
    )
    assert critical_skills.critical_gate_options(frozen) == {
        "bankowość": ("bankow*", "banking")
    }
    frozen.critical_effective.pop("options")
    assert critical_skills.critical_gate_options(frozen) == {}


def test_gate_mode_defaults_to_critical(monkeypatch):
    assert critical_skills.gate_mode() == "critical"
    monkeypatch.setattr(critical_skills.settings, "MUST_GATE_MODE", "ALL")
    assert critical_skills.gate_mode() == "all"
    monkeypatch.setattr(critical_skills.settings, "MUST_GATE_MODE", "bogus")
    assert critical_skills.gate_mode() == "critical"


def test_seed_file_is_readable_and_has_only_numbers():
    critical_skills.set_payload(None)
    payload = critical_skills.current_payload()
    assert payload["labels"]["java"]["jobs"] > 100
    for entry in payload["labels"].values():
        assert set(entry) <= {"rate", "jobs", "pairs"}
