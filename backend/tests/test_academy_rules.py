"""Akademia — reguły sortowania zgłoszeń (czyste funkcje, bez bazy i modelu).

Kształty profilu (``education``/``experience``/``languages``) są wzięte
z produkcji (23.09.2026): większość pozycji edukacji z Traffita nie ma
``level``, a daty pracy to „RRRR-MM” albo „present”.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services import academy_rules as rules

TODAY = date(2026, 9, 24)


def _evaluate(**kwargs):
    base = dict(
        education=[],
        experience=[],
        languages=[],
        model_parsed=None,
        cv_text="CV",
        max_experience_years=6,
        require_polish=True,
        today=TODAY,
    )
    base.update(kwargs)
    return rules.evaluate(**base)


POLISH_NATIVE = [{"code": "PL", "lang": "polski", "level": "native"}]


# ── edukacja ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "entry,expected",
    [
        ({"level": "master", "school": "UW", "year": 2020}, True),
        ({"degree": "Licencjat", "school": "UJ", "year": 2021}, True),
        ({"degree": "Computer Science Studies", "school": "Cracow University of Economics", "level": "other", "end_year": 2018}, True),
        ({"school": "Politechnika Warszawska", "field": "Informatyka", "year": 2019}, True),
        ({"degree": "Kurs / Szkoła IT", "school": "Mate Academy", "level": "other", "start_year": 2023}, False),
        ({"degree": "Studia podyplomowe", "school": "SGH", "level": "other"}, False),
        ({"degree": "Liceum", "school": "II Liceum", "level": "secondary", "year": 2020}, False),
        ({"degree": "Manual Tester Course", "school": "Coders Lab - IT School"}, False),
        ({"degree": "MBA", "school": "Akademia Leona Koźmińskiego", "year": 2024}, False),
    ],
)
def test_is_higher_education(entry, expected):
    assert rules.is_higher_education(entry) is expected


def test_studies_end_is_the_latest_completed_degree_not_postgraduate():
    facts = rules.studies_from_profile(
        [
            {"level": "bachelor", "school": "UW", "year": 2013},
            {"level": "master", "school": "UW", "year": 2015},
            {"degree": "Studia podyplomowe", "school": "SGH", "year": 2024},
        ],
        TODAY,
    )
    assert facts.end_year == 2015
    assert facts.still_studying is False


def test_future_end_year_means_still_studying():
    facts = rules.studies_from_profile(
        [{"degree": "Studia magisterskie", "school": "SGH", "end_year": 2027}], TODAY
    )
    assert facts.end_year is None
    assert facts.still_studying is True


# ── doświadczenie liczone od końca studiów ─────────────────────────────────


def test_work_before_graduation_does_not_count():
    result = _evaluate(
        education=[{"level": "master", "school": "UW", "year": 2022}],
        experience=[
            {"start": "2016-01", "end": "2022-06", "role": "Kelner"},
            {"start": "2022-07", "end": "present", "role": "Asystent HR"},
        ],
        languages=POLISH_NATIVE,
    )
    # lipiec 2022 – wrzesień 2026 = 51 miesięcy.
    assert result.experience_years == pytest.approx(4.2, abs=0.05)
    assert result.verdict == rules.VERDICT_CALL
    assert result.facts["experience_basis"] == "after_studies"


def test_over_limit_after_studies_is_skipped_with_reason():
    result = _evaluate(
        education=[{"level": "bachelor", "school": "UW", "year": 2012}],
        experience=[{"start": "2012-09", "end": "present"}],
        languages=POLISH_NATIVE,
    )
    assert result.verdict == rules.VERDICT_SKIP
    over = [r for r in result.reasons if r["code"] == "experience_over"]
    assert over and "limit 6 lat" in over[0]["text"]


def test_without_studies_all_work_counts():
    result = _evaluate(
        education=[{"degree": "Liceum", "level": "secondary", "year": 2015}],
        experience=[
            {"start": "2016-01", "end": "2019-12"},
            {"start": "2020-01", "end": "2023-12"},
        ],
        languages=POLISH_NATIVE,
    )
    assert result.experience_years == pytest.approx(8.0)
    assert result.verdict == rules.VERDICT_SKIP
    assert result.facts["experience_basis"] == "all_work"


def test_overlapping_jobs_are_not_double_counted():
    months = rules.work_months_after(
        [
            rules.WorkPeriod(start=(2024, 1), end=(2024, 12)),
            rules.WorkPeriod(start=(2024, 6), end=(2025, 5)),
        ],
        None,
    )
    assert months == 17


def test_student_with_short_job_is_called():
    result = _evaluate(
        education=[{"degree": "Studia licencjackie", "school": "UW", "end_year": 2027}],
        experience=[{"start": "2025-10", "end": "present"}],
        languages=POLISH_NATIVE,
    )
    assert result.verdict == rules.VERDICT_CALL
    assert "studiuje" in result.reasons[0]["text"]


def test_undated_experience_goes_to_review_not_skip():
    result = _evaluate(
        education=[],
        experience=[{"role": "Sprzedawca"}, {"role": "Rekruter", "start": "", "end": ""}],
        languages=POLISH_NATIVE,
    )
    assert result.experience_years is None
    assert result.verdict == rules.VERDICT_REVIEW


def test_garbage_end_date_is_undated_not_ongoing():
    work = rules.work_from_profile([{"start": "2010-01", "end": "?"}], TODAY)
    assert work.periods == ()
    assert work.undated == 1


# ── język polski ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "languages,level",
    [
        ([{"code": "PL", "lang": "polski", "level": "native"}], rules.POLISH_NATIVE),
        ([{"code": "PL", "lang": "Polish", "level": "C2"}], rules.POLISH_NATIVE),
        ([{"code": "PL", "lang": "polski", "level": "C1"}], rules.POLISH_FLUENT),
        ([{"code": "PL", "lang": "polski", "level": "B1"}], rules.POLISH_BASIC),
        ([{"code": "PL", "lang": "Polski", "level": "unknown"}], rules.POLISH_UNKNOWN),
        ([{"code": "EN", "lang": "angielski", "level": "C1"}], rules.POLISH_UNKNOWN),
        ([], rules.POLISH_UNKNOWN),
    ],
)
def test_polish_level_from_profile(languages, level):
    assert rules.polish_from_profile(languages).level == level


def test_basic_polish_is_skipped():
    result = _evaluate(
        education=[{"level": "master", "school": "UW", "year": 2024}],
        experience=[],
        languages=[{"code": "PL", "lang": "polski", "level": "A2"}],
    )
    assert result.verdict == rules.VERDICT_SKIP
    assert any(r["code"] == "polish_basic" for r in result.reasons)


def test_unknown_polish_goes_to_review():
    result = _evaluate(
        education=[{"level": "master", "school": "UW", "year": 2024}],
        experience=[],
        languages=[],
    )
    assert result.verdict == rules.VERDICT_REVIEW


def test_polish_not_required_ignores_language():
    result = _evaluate(
        education=[{"level": "master", "school": "UW", "year": 2024}],
        experience=[],
        languages=[],
        require_polish=False,
    )
    assert result.verdict == rules.VERDICT_CALL


# ── fakty z modelu ─────────────────────────────────────────────────────────

CV = (
    "Anna Nowak. Języki: polski — ojczysty, angielski B2. "
    "Uniwersytet Warszawski, psychologia, magister 2023. "
    "Asystentka HR, 2023-09 – obecnie."
)


def test_model_fills_gaps_only_with_quotes_present_in_cv():
    parsed = {
        "polish": {"level": "native", "quote": "polski — ojczysty"},
        "education": [
            {"kind": "higher", "completed": True, "end_year": 2023, "quote": "magister 2023"}
        ],
        "work": [{"start": "2023-09", "end": "present", "quote": "Asystentka HR, 2023-09"}],
    }
    result = _evaluate(model_parsed=parsed, cv_text=CV)
    assert result.verdict == rules.VERDICT_CALL
    assert result.facts["sources"] == {"studies": "luna", "work": "luna", "polish": "luna"}
    assert result.facts["studies_end_year"] == 2023


def test_model_fact_without_matching_quote_is_dropped():
    parsed = {
        "polish": {"level": "native", "quote": "native speaker of Polish"},
        "education": [
            {"kind": "higher", "completed": True, "end_year": 2010, "quote": "SGH 2010"}
        ],
        "work": [{"start": "2010-01", "end": "present", "quote": "Dyrektor od 2010"}],
    }
    studies, work, polish = rules.facts_from_model(parsed, CV, TODAY)
    assert polish is not None and polish.level == rules.POLISH_UNKNOWN
    assert studies is not None and studies.end_year is None
    assert work is not None and work.periods == ()


def test_profile_wins_over_model():
    parsed = {
        "polish": {"level": "basic", "quote": "angielski B2"},
        "education": [],
        "work": [],
    }
    result = _evaluate(
        education=[{"level": "master", "school": "UW", "year": 2024}],
        languages=POLISH_NATIVE,
        model_parsed=parsed,
        cv_text=CV,
    )
    assert result.facts["polish"] == rules.POLISH_NATIVE
    assert result.facts["sources"]["polish"] == "profile"


def test_model_failure_forces_review_even_when_profile_is_clean():
    result = _evaluate(
        education=[{"level": "master", "school": "UW", "year": 2024}],
        languages=POLISH_NATIVE,
        model_error="APITimeoutError",
    )
    assert result.verdict == rules.VERDICT_REVIEW
    assert any(r["code"] == "luna_unavailable" for r in result.reasons)


def test_no_facts_about_name_or_age_are_ever_produced():
    """Sortowanie nie ma pól o imieniu, narodowości ani wieku (decyzja 24.09)."""
    result = _evaluate(
        education=[{"level": "master", "school": "UW", "year": 2024}],
        languages=POLISH_NATIVE,
    )
    forbidden = {"age", "birth_year", "nationality", "name", "surname"}
    assert not forbidden & set(result.facts)


@pytest.mark.parametrize(
    "years,label",
    [(1.0, "1 rok"), (3.0, "3 lata"), (5.0, "5 lat"), (12.0, "12 lat"), (22.0, "22 lata"), (2.5, "2,5 roku")],
)
def test_years_label(years, label):
    assert rules.years_label(years) == label


# ── audyt 24.09.2026: cytat musi DOWODZIĆ faktu ────────────────────────────


def test_work_dates_not_in_quote_are_not_proven():
    """„Specjalista” występuje w CV, ale nie dowodzi pracy od 2010 — bez tego
    model dopisywał datę do dowolnego fragmentu, a 14 lat = „skip”."""
    parsed = {"work": [{"start": "2010-01", "end": "present", "quote": "Spe"}]}
    result = _evaluate(
        model_parsed=parsed,
        cv_text="Specjalista ds. HR",
        languages=POLISH_NATIVE,
    )
    assert result.verdict != rules.VERDICT_SKIP
    assert result.facts["experience_years"] is None

    parsed = {
        "work": [{"start": "2019-03", "end": "2021-06", "quote": "Specjalista 2019"}]
    }
    _studies, work, _polish = rules.facts_from_model(
        parsed, "Specjalista 2019 – 2021", TODAY
    )
    assert work is not None and work.periods == ()  # brak roku końca w cytacie

    parsed = {
        "work": [
            {"start": "2019-03", "end": "2021-06", "quote": "Specjalista 2019 – 2021"}
        ]
    }
    _studies, work, _polish = rules.facts_from_model(
        parsed, "Specjalista 2019 – 2021", TODAY
    )
    assert work is not None and len(work.periods) == 1


def test_graduation_year_must_be_in_quote():
    parsed = {
        "education": [
            {"kind": "higher", "completed": True, "end_year": 2012, "quote": "magister"}
        ]
    }
    studies, _work, _polish = rules.facts_from_model(
        parsed, "Uniwersytet Warszawski, magister 2023", TODAY
    )
    assert studies is not None and studies.end_year is None


def test_polish_level_needs_a_quote_about_polish():
    cv = "Języki: angielski B2, polski podstawowy. Sprzedawca."
    parsed = {"polish": {"level": "native", "quote": "Sprzedawca"}}
    _s, _w, polish = rules.facts_from_model(parsed, cv, TODAY)
    assert polish is not None and polish.level == rules.POLISH_UNKNOWN

    # „podstawowy” (który daje „skip”) musi mieć w cytacie także poziom.
    parsed = {"polish": {"level": "basic", "quote": "polski"}}
    _s, _w, polish = rules.facts_from_model(parsed, cv, TODAY)
    assert polish is not None and polish.level == rules.POLISH_UNKNOWN

    parsed = {"polish": {"level": "basic", "quote": "polski podstawowy"}}
    _s, _w, polish = rules.facts_from_model(parsed, cv, TODAY)
    assert polish is not None and polish.level == rules.POLISH_BASIC


def test_position_without_end_date_further_down_is_past_not_until_today():
    """Reguła ``experience_end``: pusty koniec dalej niż na pierwszej pozycji to
    praca przeszła. Staż 2012 bez daty końca nie może dawać 14 lat."""
    work = rules.work_from_profile(
        [
            {"start": "2022-01", "end": "present", "role": "Asystent HR"},
            {"start": "2012-06", "role": "Stażysta"},
        ],
        TODAY,
    )
    assert len(work.periods) == 1
    assert work.undated == 1
    result = _evaluate(
        experience=[
            {"start": "2022-01", "end": "present", "role": "Asystent HR"},
            {"start": "2012-06", "role": "Stażysta"},
        ],
        languages=POLISH_NATIVE,
    )
    assert result.verdict == rules.VERDICT_REVIEW
    assert result.experience_years is not None and result.experience_years < 6

    # Pierwsza pozycja bez daty końca to nadal praca trwająca.
    current = rules.work_from_profile([{"start": "2025-01", "role": "Rekruter"}], TODAY)
    assert current.periods[0].end == (TODAY.year, TODAY.month)
