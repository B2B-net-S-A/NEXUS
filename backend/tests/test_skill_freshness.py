"""Umiejętność nieużywana od ponad 3 lat nie jest spełnionym „musi mieć” (27.10.2026).

Zgłoszenie Delivery Leada: tester z Angularem z lat 2019–2020 (testy
w Protractorze) dostawał „✓ angular” przy „Full Stack Developer (Java,
Angular)”. Taki wiersz ma być „?” z rokiem ostatniego użycia.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import skill_freshness
from app.services.requirement_contract import evaluate_requirements, explicit_contract

TODAY = date(2026, 10, 27)


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(skill_freshness, "business_today", lambda: TODAY)


def candidate(skills=None, timeline=None, **extra):
    extracted = {"skill_timeline": timeline} if timeline is not None else None
    return SimpleNamespace(skills=skills or [], cv_extracted_data=extracted, **extra)


def angular(**dates):
    return [{"name": "Java", "last_used": "present"}, {"name": "Angular", **dates}]


def evaluate(cand, must=("Java", "Angular")):
    contract = explicit_contract(list(must), [], reviewed=True)
    return {
        " lub ".join(row["any_of"]): row
        for row in evaluate_requirements(contract, cand)
    }


def test_skill_last_used_over_three_years_ago_is_unknown_with_year():
    rows = evaluate(candidate(angular(first_used="2019-10", last_used="2020-06")))
    assert rows["java"]["status"] == "met"
    assert rows["angular"]["status"] == "unknown"
    assert rows["angular"]["last_used_year"] == 2020
    assert rows["angular"]["evidence_basis"] == "stale_profile_signal"
    assert rows["angular"]["matched"] == []
    assert "last_used_year" not in rows["java"]


def test_skill_without_last_used_stays_met():
    rows = evaluate(candidate(angular(first_used="2019")))
    assert rows["angular"]["status"] == "met"
    assert "last_used_year" not in rows["angular"]


def test_present_stays_met():
    rows = evaluate(candidate(angular(first_used="2015", last_used="present")))
    assert rows["angular"]["status"] == "met"


@pytest.mark.parametrize(
    ("last_used", "status"),
    [
        # Sam rok = do końca tego roku: 2023 to najwyżej 34 miesiące temu.
        ("2023", "met"),
        ("2022", "unknown"),
        # Dokładnie 3 lata (36 miesięcy) jeszcze się liczy, 37 — już nie.
        ("2023-10", "met"),
        ("2023-09", "unknown"),
        ("2023-10-01", "met"),
    ],
)
def test_year_only_and_exactly_three_years(last_used, status):
    rows = evaluate(candidate(angular(last_used=last_used)))
    assert rows["angular"]["status"] == status


def test_unreadable_date_is_not_proof_of_old_skill():
    rows = evaluate(candidate(angular(last_used="kiedyś")))
    assert rows["angular"]["status"] == "met"


def test_latest_date_across_sources_wins():
    # Lista umiejętności mówi 2020-06, oś technologii z doświadczenia — 2024.
    cand = candidate(
        angular(last_used="2020-06"),
        timeline=[{"skill": "Angular", "last_used": "2024-03"}],
    )
    assert evaluate(cand)["angular"]["status"] == "met"


def test_year_shown_is_the_latest_known_use():
    cand = candidate(
        angular(last_used="2020-06"),
        timeline=[{"skill": "Angular", "last_used": "2021-07"}],
    )
    assert evaluate(cand)["angular"]["last_used_year"] == 2021


def test_fresh_alternative_in_group_is_met():
    skills = [
        {"name": "Angular", "last_used": "2020-06"},
        {"name": "React", "last_used": "present"},
    ]
    rows = evaluate(candidate(skills), must=["Angular lub React"])
    row = rows["angular lub react"]
    assert row["status"] == "met"
    assert row["matched"] == ["react"]


def test_text_mention_from_same_cv_does_not_override_old_date():
    cand = candidate(angular(last_used="2020-06"))
    cand._must_text_evidence = SimpleNamespace(met=frozenset({"angular"}))
    assert evaluate(cand)["angular"]["status"] == "unknown"


def test_curated_skills_ignore_dates_from_cv_reading():
    # Lista poprawiona ręcznie jest całą prawdą — stara oś z CV jej nie zmienia.
    cand = candidate(
        [{"name": "Angular"}],
        timeline=[{"skill": "Angular", "last_used": "2019"}],
        skills_manually_curated=True,
    )
    assert evaluate(cand)["angular"]["status"] == "met"


def test_proposal_evidence_keeps_the_year():
    from app.services.job_proposals import sanitize_evidence

    rows = evaluate(candidate(angular(last_used="2020-06")))
    clean = sanitize_evidence({"requirements": list(rows.values())})
    assert clean["requirements"][1] == {
        "level": "must",
        "status": "unknown",
        "last_used_year": 2020,
        "any_of": ["angular"],
    }


def test_recruiter_review_wins_over_old_date(monkeypatch):
    from app.services import requirement_verification

    monkeypatch.setattr(
        requirement_verification,
        "reviewed_group",
        lambda *a, **k: {"status": "met", "verified_at": "2026-10-20"},
    )
    rows = evaluate(candidate(angular(last_used="2020-06")))
    assert rows["angular"]["status"] == "met"
    assert rows["angular"]["evidence_basis"] == "reviewed"
    assert "last_used_year" not in rows["angular"]
