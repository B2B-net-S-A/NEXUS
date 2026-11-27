"""Karta dojazdu przy odrzuceniu „Lokalizacja lub tryb pracy” (27.11.2026, wariant D).

Okno pyta najpierw „Co nie pasuje?”: za daleko do biura (miasto, biura, do
których dojedzie, inne miasto okazjonalnie, przeprowadzka) albo za dużo dni
w biurze (dni + zgoda na więcej przy wyjątkowym projekcie). Na kopii produkcji
141 z 224 takich osób dostało fałszywe „Tylko zdalnie”, a 36 z 53 notatek
podawało miasto, które nigdzie nie trafiało.

Kontrakty bez bazy: kształt pól ruchu, reguły „które pole przy czym” (422),
linia opisu w historii procesu, zapis miasta i preferencji dojazdu na profilu
oraz tokeny biura z ręcznej przeprowadzki. Ścieżka przez API —
``test_work_mode_rejection_move.py`` (Postgres w CI).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import app.services.candidate_commute as commute_mod
from app.schemas.pipeline import StageMove
from app.services import candidate_audit, candidate_commute, residence
from app.services.candidate_monthly_rate_retirement import (
    sanitize_candidate_preferences,
)
from app.services.location_utils import candidate_office_tokens


@pytest.fixture(autouse=True)
def _no_orm_instrumentation(monkeypatch):
    monkeypatch.setattr(commute_mod, "flag_modified", lambda *a, **k: None)


def _move(**extra) -> StageMove:
    return StageMove(candidate_id=1, job_id=2, stage="rejected", **extra)


# ── Kształt pól ─────────────────────────────────────────────────────────────


def test_five_office_days_are_allowed_six_are_not():
    assert _move(work_mode_max_onsite_days=5).work_mode_max_onsite_days == 5
    with pytest.raises(ValidationError):
        _move(work_mode_max_onsite_days=6)


def test_place_lists_are_stripped_and_deduplicated():
    move = _move(
        work_mode_issue="distance",
        residence_city="  Kraków ",
        commute_office_cities=[" Kraków", "katowice", "KRAKÓW", "Katowice "],
        relocation_willing=True,
        relocation_targets=["Wrocław ", "wrocław"],
    )
    assert move.residence_city == "Kraków"
    assert move.commute_office_cities == ["Kraków", "katowice"]
    assert move.relocation_targets == ["Wrocław"]


@pytest.mark.parametrize(
    "extra",
    [
        {"residence_city": "   "},
        {"residence_city": "x" * 121},
        {"commute_office_cities": ["Kraków", " "]},
        {"commute_office_cities": ["x" * 121]},
        {"commute_office_cities": [f"Miasto {i}" for i in range(11)]},
        {"relocation_willing": True, "relocation_targets": [f"M{i}" for i in range(6)]},
        {"work_mode_issue": "commute"},
    ],
)
def test_bad_place_values_are_refused(extra):
    with pytest.raises(ValidationError):
        _move(**extra)


# ── Które pole przy czym (422) ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "extra",
    [
        {"work_mode_issue": "distance"},
        {"work_mode_issue": "office_days"},
        {"residence_city": "Kraków"},
        {"commute_office_cities": ["Kraków"]},
        {"occasional_commute": False},
        {"relocation_willing": False},
        {"relocation_willing": True, "relocation_targets": ["Wrocław"]},
        {"accepts_more_office_days": True},
    ],
)
def test_every_field_is_refused_with_another_reason(extra):
    error = candidate_commute.rejection_fields_error(
        _move(**extra), work_mode_rejection=False
    )
    assert error is not None and "Lokalizacja lub tryb pracy" in error


def test_days_with_another_reason_keep_the_old_message():
    error = candidate_commute.rejection_fields_error(
        _move(work_mode_max_onsite_days=0), work_mode_rejection=False
    )
    assert error == (
        "Liczbę dni w biurze podaje się tylko przy powodzie "
        "„Nie akceptuje trybu pracy”."
    )


def test_another_reason_without_fields_passes():
    assert (
        candidate_commute.rejection_fields_error(_move(), work_mode_rejection=False)
        is None
    )


@pytest.mark.parametrize("issue", [None, "office_days"])
def test_days_stay_required_for_old_calls_and_office_days(issue):
    error = candidate_commute.rejection_fields_error(
        _move(work_mode_issue=issue), work_mode_rejection=True
    )
    assert error == "Podaj, ile dni w biurze kandydat akceptuje."


def test_distance_does_not_need_days():
    move = _move(work_mode_issue="distance", residence_city="Kraków")
    assert (
        candidate_commute.rejection_fields_error(move, work_mode_rejection=True) is None
    )


@pytest.mark.parametrize("issue", [None, "office_days"])
@pytest.mark.parametrize(
    "extra",
    [
        {"residence_city": "Kraków"},
        {"commute_office_cities": ["Kraków"]},
        {"occasional_commute": True},
        {"relocation_willing": False},
    ],
)
def test_distance_fields_need_distance(issue, extra):
    move = _move(work_mode_issue=issue, work_mode_max_onsite_days=2, **extra)
    error = candidate_commute.rejection_fields_error(move, work_mode_rejection=True)
    assert error is not None and "Za daleko do biura" in error


@pytest.mark.parametrize("issue", [None, "distance"])
def test_more_office_days_consent_needs_office_days(issue):
    move = _move(
        work_mode_issue=issue,
        work_mode_max_onsite_days=2,
        accepts_more_office_days=True,
    )
    error = candidate_commute.rejection_fields_error(move, work_mode_rejection=True)
    assert error is not None and "Chce mniej dni w biurze" in error


@pytest.mark.parametrize("willing", [None, False])
def test_relocation_targets_need_willing_true(willing):
    move = _move(
        work_mode_issue="distance",
        relocation_willing=willing,
        relocation_targets=["Wrocław"],
    )
    error = candidate_commute.rejection_fields_error(move, work_mode_rejection=True)
    assert error is not None and "przeprowadz" in error


def test_relocation_anywhere_is_allowed():
    move = _move(
        work_mode_issue="distance", relocation_willing=True, relocation_targets=[]
    )
    assert (
        candidate_commute.rejection_fields_error(move, work_mode_rejection=True) is None
    )


# ── Linia opisu w historii procesu ──────────────────────────────────────────


def test_distance_note_lists_every_given_part_before_recruiter_text():
    move = _move(
        work_mode_issue="distance",
        residence_city="Kraków",
        commute_office_cities=["Kraków", "Katowice"],
        work_mode_max_onsite_days=3,
        occasional_commute=True,
        relocation_willing=True,
        relocation_targets=["Wrocław"],
    )
    assert candidate_commute.rejection_note(move, notes=" dzwonić w marcu ") == (
        "Za daleko do biura · mieszka: Kraków · dojedzie do: Kraków, Katowice"
        " · do 3 dni w biurze · inne miasto: raz w miesiącu"
        " · przeprowadzka: tak (Wrocław) — dzwonić w marcu"
    )


def test_distance_note_says_no_and_skips_missing_parts():
    move = _move(
        work_mode_issue="distance", occasional_commute=False, relocation_willing=False
    )
    assert candidate_commute.rejection_note(move, notes=None) == (
        "Za daleko do biura · inne miasto: nie · przeprowadzka: nie"
    )
    bare = _move(work_mode_issue="distance")
    assert candidate_commute.rejection_note(bare, notes="") == "Za daleko do biura"
    anywhere = _move(
        work_mode_issue="distance", relocation_willing=True, relocation_targets=[]
    )
    assert candidate_commute.rejection_note(anywhere, notes=None) == (
        "Za daleko do biura · przeprowadzka: tak"
    )


def test_office_days_note_with_and_without_consent():
    move = _move(work_mode_issue="office_days", work_mode_max_onsite_days=2)
    assert candidate_commute.rejection_note(move, notes=None) == (
        "Chce mniej dni w biurze · do 2 dni"
    )
    yes = _move(
        work_mode_issue="office_days",
        work_mode_max_onsite_days=2,
        accepts_more_office_days=True,
    )
    assert candidate_commute.rejection_note(yes, notes="x") == (
        "Chce mniej dni w biurze · do 2 dni · więcej przy wyjątkowym projekcie: tak — x"
    )
    no = _move(
        work_mode_issue="office_days",
        work_mode_max_onsite_days=0,
        accepts_more_office_days=False,
    )
    assert candidate_commute.rejection_note(no, notes=None) == (
        "Chce mniej dni w biurze · tylko zdalnie"
        " · więcej przy wyjątkowym projekcie: nie"
    )


def test_old_calls_keep_recruiter_text_as_is():
    move = _move(work_mode_max_onsite_days=0)
    assert candidate_commute.rejection_note(move, notes="zdalnie") == "zdalnie"
    assert candidate_commute.rejection_note(move, notes=None) is None


# ── Preferencje dojazdu na profilu ──────────────────────────────────────────

_ORIGIN = {
    "source": "rejection",
    "job_id": 11,
    "job_title": "Java Developer",
    "at": "2026-11-27T10:00:00+00:00",
    "user_id": 33,
}


def _cand(**kw):
    data = dict(id=7, preferences=None, city=None, country=None, location=None)
    data.update(kw)
    return SimpleNamespace(**data)


def test_commute_answers_land_in_preferences_with_source():
    cand = _cand(preferences={"remote_modes": ["remote"], "office_cities": ["Łódź"]})
    changed = candidate_commute.apply_commute_from_rejection(
        cand,
        office_cities=["Kraków", "Katowice"],
        occasional_commute=True,
        relocation_willing=True,
        relocation_targets=["Wrocław"],
        origin=_ORIGIN,
    )
    assert cand.preferences == {
        "remote_modes": ["remote"],
        "office_cities": ["Kraków", "Katowice"],
        "occasional_commute": True,
        "relocation": {"willing": True, "targets": ["Wrocław"]},
        "commute_source": _ORIGIN,
    }
    assert changed == {
        "office_cities": {"before": ["Łódź"], "after": ["Kraków", "Katowice"]},
        "occasional_commute": {"before": None, "after": True},
        "relocation": {
            "before": None,
            "after": {"willing": True, "targets": ["Wrocław"]},
        },
    }


def test_unchanged_or_missing_answers_leave_preferences_alone():
    prefs = {
        "office_cities": ["Kraków"],
        "relocation": {"willing": False, "targets": []},
    }
    cand = _cand(preferences=dict(prefs))
    changed = candidate_commute.apply_commute_from_rejection(
        cand,
        office_cities=["Kraków"],
        occasional_commute=None,
        relocation_willing=False,
        relocation_targets=None,
        origin=_ORIGIN,
    )
    assert changed == {}
    assert cand.preferences == prefs

    empty = _cand()
    assert (
        candidate_commute.apply_commute_from_rejection(
            empty,
            office_cities=[],
            occasional_commute=None,
            relocation_willing=None,
            relocation_targets=None,
            origin=_ORIGIN,
        )
        == {}
    )
    assert empty.preferences is None


def test_relocation_no_drops_targets():
    cand = _cand(preferences={"relocation": {"willing": True, "targets": ["Gdańsk"]}})
    changed = candidate_commute.apply_commute_from_rejection(
        cand,
        office_cities=None,
        occasional_commute=False,
        relocation_willing=False,
        relocation_targets=None,
        origin=_ORIGIN,
    )
    assert cand.preferences["relocation"] == {"willing": False, "targets": []}
    assert cand.preferences["occasional_commute"] is False
    assert set(changed) == {"relocation", "occasional_commute"}


# ── Miasto zamieszkania na profilu ──────────────────────────────────────────


class _Db:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, row) -> None:
        self.added.append(row)


def test_city_from_rejection_locks_city_sets_poland_and_audits():
    person = _cand(city="Warszawa", location="Warszawa", cv_extracted_data=["x"])
    db = _Db()
    assert residence.record_city_from_rejection(
        db, person, city=" Kraków ", user_id=1, job_id=2, stage_id=3
    )
    assert (person.city, person.country, person.location) == (
        "Kraków",
        "PL",
        "Kraków, PL",
    )
    assert person.cv_extracted_data["_manual_override_city"] is True
    assert person.cv_extracted_data["_manual_override_country"] is True
    (audit,) = db.added
    assert audit.action == candidate_audit.LOCATION_CHANGED
    assert audit.details == {
        "changed_fields": ["city", "country"],
        "manual_lock": True,
        "source": "rejection",
        "job_id": 2,
        "stage_id": 3,
    }


def test_city_from_rejection_keeps_existing_country_and_foreign_city():
    person = _cand(country="DE", cv_extracted_data=None)
    db = _Db()
    assert residence.record_city_from_rejection(
        db, person, city="Kraków", user_id=1, job_id=2, stage_id=3
    )
    assert (person.city, person.country) == ("Kraków", "DE")
    assert db.added[0].details["changed_fields"] == ["city"]

    abroad = _cand(cv_extracted_data=None)
    assert residence.record_city_from_rejection(
        _Db(), abroad, city="Berlin", user_id=1, job_id=2, stage_id=3
    )
    assert (abroad.city, abroad.country) == ("Berlin", None)


def test_same_city_is_not_a_change():
    person = _cand(city="Kraków", country="PL", cv_extracted_data=None)
    db = _Db()
    assert not residence.record_city_from_rejection(
        db, person, city="kraków", user_id=1, job_id=2, stage_id=3
    )
    assert db.added == [] and person.cv_extracted_data is None


# ── Odczyt: tokeny biura i preferencje w odpowiedzi ─────────────────────────


def test_office_tokens_include_manual_relocation_targets():
    willing = _cand(
        city="Kraków",
        preferences={"relocation": {"willing": True, "targets": ["Wrocław"]}},
        cv_extracted_data=None,
    )
    assert candidate_office_tokens(willing) >= {"kraków", "wrocław"}
    unwilling = _cand(
        city="Kraków",
        preferences={"relocation": {"willing": False, "targets": ["Wrocław"]}},
        cv_extracted_data=None,
    )
    assert "wrocław" not in candidate_office_tokens(unwilling)


def test_profile_read_keeps_commute_preferences():
    prefs = {
        "office_cities": ["Kraków"],
        "occasional_commute": True,
        "relocation": {"willing": True, "targets": []},
        "commute_source": _ORIGIN,
    }
    assert sanitize_candidate_preferences(prefs) == prefs
