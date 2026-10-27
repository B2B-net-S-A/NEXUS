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


# ── Przegląd Delivery Leada (`dl_review.evaluate_requirements`) ──────────────
#
# Tabela wymagań przeglądu DL szuka wzmianek w profilu, CV, notatkach
# i rozmowie. Trafienie wyłącznie w profilu i CV przy dacie sprzed ponad 3 lat
# to „?” z rokiem; notatka i rozmowa (styczność z kandydatem) zostają dowodem.


def dl_candidate(skills, timeline=None, raw_cv_text="", **extra):
    base = dict(
        skills=skills,
        verified_tech=None,
        tags=None,
        experience=None,
        cv_extracted_data={"skill_timeline": timeline} if timeline else {},
        raw_cv_text=raw_cv_text,
        current_position=None,
        headline=None,
        title=None,
    )
    base.update(extra)
    return SimpleNamespace(**base)


def dl_rows(cand, labels=("Java", "Angular"), notes=(), conversation=()):
    from app.services import dl_review

    items = [
        dl_review.RequirementInput(f"must:{i}", label, "must")
        for i, label in enumerate(labels)
    ]
    rows = dl_review.evaluate_requirements(
        cand, items, note_texts=notes, conversation_texts=conversation
    )
    return {row["label"]: row for row in rows}, dl_review.requirements_score(rows)


def candidate_14525():
    # Staging 22.10.2026: Angular w liście 2020-06, na osi z doświadczenia 2021-07.
    return dl_candidate(
        angular(last_used="2020-06"),
        timeline=[{"skill": "Angular", "last_used": "2021-07"}],
        raw_cv_text="2019–2021: testy automatyczne aplikacji w Angularze (Protractor).",
    )


def test_dl_review_old_skill_from_profile_and_cv_is_unknown_with_year():
    rows, score = dl_rows(candidate_14525())
    assert rows["Angular"]["status"] == "unknown"
    assert rows["Angular"]["last_used_year"] == 2021
    assert rows["Angular"]["sources"] == ["profil", "CV"]
    assert rows["Java"]["status"] == "met"
    assert "last_used_year" not in rows["Java"]
    # „?” nie liczy się w X/Y.
    assert score == (1, 1)


@pytest.mark.parametrize(
    ("notes", "conversation", "source"),
    [
        (["Rozmowa 10.2026: dziś pisze w Angularze 17"], [], "notatka"),
        ([], ["Angular — obecny projekt, 2 lata"], "rozmowa"),
    ],
)
def test_dl_review_note_or_conversation_keeps_old_skill_met(
    notes, conversation, source
):
    rows, score = dl_rows(candidate_14525(), notes=notes, conversation=conversation)
    assert rows["Angular"]["status"] == "met"
    assert source in rows["Angular"]["sources"]
    assert "last_used_year" not in rows["Angular"]
    assert score == (2, 2)


@pytest.mark.parametrize(
    ("last_used", "status"),
    [
        (None, "met"),
        ("present", "met"),
        ("kiedyś", "met"),
        ("2023", "met"),
        ("2022", "unknown"),
        ("2023-10", "met"),
        ("2023-09", "unknown"),
    ],
)
def test_dl_review_date_edges(last_used, status):
    dates = {"last_used": last_used} if last_used else {}
    rows, _ = dl_rows(dl_candidate(angular(**dates)))
    assert rows["Angular"]["status"] == status


def test_dl_review_curated_skills_ignore_dates_from_cv_reading():
    cand = dl_candidate(
        [{"name": "Angular"}],
        timeline=[{"skill": "Angular", "last_used": "2019"}],
        skills_manually_curated=True,
    )
    rows, _ = dl_rows(cand, labels=["Angular"])
    assert rows["Angular"]["status"] == "met"


def test_dl_review_fresh_alternative_in_group_is_met():
    skills = [
        {"name": "Angular", "last_used": "2020-06"},
        {"name": "React", "last_used": "present"},
    ]
    rows, _ = dl_rows(dl_candidate(skills), labels=["Angular lub React"])
    assert rows["Angular lub React"]["status"] == "met"


def test_dl_review_missing_stays_missing():
    rows, score = dl_rows(dl_candidate(angular(last_used="2020-06")), labels=["Kafka"])
    assert rows["Kafka"]["status"] == "missing"
    assert score == (0, 1)
