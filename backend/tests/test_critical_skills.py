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


def test_dl_choice_outside_must_or_not_technology_is_dropped():
    res = critical_skills.effective_critical(
        _job(["Java", "QA"], critical=["QA", "Python"])
    )
    assert res.labels == () and res.decided is True


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
