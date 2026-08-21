"""Dostępność v2 — kara wyłącznie za twardą kolizję jawnych dat.

Rdzeń kontraktu: data WYPROWADZONA z wypowiedzenia ("1 miesiąc") NIGDY nie
uruchamia kary — to była przyczyna NO-GO fallbacku (R@20n −24%: karanie
kandydatów bogatych w dane względem tych bez żadnego sygnału).
"""

from datetime import date
from types import SimpleNamespace

from app.core.config import settings
from app.services.scoring_service import (
    _AVAILABILITY_CONFLICT_PENALTY,
    _champion_availability_conflict_factor,
)


def _cand(availability_date=None, insights=None):
    extracted = {"_notes_insights": insights} if insights is not None else None
    return SimpleNamespace(
        availability_date=availability_date, cv_extracted_data=extracted
    )


def _job(start_date=None):
    profile = {"start_date": start_date} if start_date is not None else {}
    return SimpleNamespace(champion_profile=profile)


TODAY = date(2026, 8, 17)


def _on(monkeypatch):
    monkeypatch.setattr(
        settings, "CHAMPION_AVAILABILITY_CONFLICT_ENABLED", True, raising=False
    )


def test_flag_off_is_verbatim(monkeypatch):
    monkeypatch.setattr(
        settings, "CHAMPION_AVAILABILITY_CONFLICT_ENABLED", False, raising=False
    )
    cand = _cand(availability_date=date(2027, 6, 1))
    f, reason = _champion_availability_conflict_factor(
        cand, _job("2026-09-01"), today=TODAY
    )
    assert f == 1.0 and reason is None


def test_hard_conflict_from_column_penalizes(monkeypatch):
    _on(monkeypatch)
    cand = _cand(availability_date=date(2026, 12, 1))  # 91 dni po starcie
    f, reason = _champion_availability_conflict_factor(
        cand, _job("2026-09-01"), today=TODAY
    )
    assert f == 1.0 - _AVAILABILITY_CONFLICT_PENALTY
    assert reason and "kara" in reason


def test_within_grace_is_silent(monkeypatch):
    _on(monkeypatch)
    cand = _cand(availability_date=date(2026, 9, 20))  # +19 dni <= 30 grace
    f, _ = _champion_availability_conflict_factor(cand, _job("2026-09-01"), today=TODAY)
    assert f == 1.0


def test_derived_notice_never_penalizes(monkeypatch):
    # KLUCZOWY kontrakt: samo "3 miesiące wypowiedzenia" (bez jawnej daty)
    # nie może uruchomić kary, choćby wyprowadzona data była po starcie.
    _on(monkeypatch)
    cand = _cand(
        insights={"availability": {"notice_period": "3 miesiące", "raw": "3 mies"}}
    )
    f, _ = _champion_availability_conflict_factor(cand, _job("2026-09-01"), today=TODAY)
    assert f == 1.0


def test_explicit_notes_date_conflict_penalizes(monkeypatch):
    _on(monkeypatch)
    cand = _cand(insights={"availability": {"available_from": "2027-01-15"}})
    f, _ = _champion_availability_conflict_factor(cand, _job("2026-09-01"), today=TODAY)
    assert f == 1.0 - _AVAILABILITY_CONFLICT_PENALTY


def test_missing_either_side_is_silent(monkeypatch):
    _on(monkeypatch)
    # Brak startu Championa.
    f1, _ = _champion_availability_conflict_factor(
        _cand(availability_date=date(2027, 1, 1)), _job(None), today=TODAY
    )
    # Brak jakiejkolwiek daty kandydata.
    f2, _ = _champion_availability_conflict_factor(
        _cand(), _job("2026-09-01"), today=TODAY
    )
    assert f1 == 1.0 and f2 == 1.0


def test_asap_start_uses_pinned_today(monkeypatch):
    _on(monkeypatch)
    cand = _cand(availability_date=date(2026, 11, 1))  # 76 dni po "dziś"
    f, _ = _champion_availability_conflict_factor(cand, _job("ASAP"), today=TODAY)
    assert f == 1.0 - _AVAILABILITY_CONFLICT_PENALTY


def test_flag_registered_in_cache_inputs():
    from app.services.scoring_service import _SCORING_CACHE_INPUTS

    assert "CHAMPION_AVAILABILITY_CONFLICT_ENABLED" in _SCORING_CACHE_INPUTS


def test_available_before_start_is_silent(monkeypatch):
    # Cicha większość: kandydat dostępny PRZED startem — late_days ujemne,
    # kara nie może się odpalić (refaktor progu nie ma prawa tego odwrócić).
    _on(monkeypatch)
    cand = _cand(availability_date=date(2026, 8, 20))
    f, reason = _champion_availability_conflict_factor(
        cand, _job("2026-09-01"), today=TODAY
    )
    assert f == 1.0 and reason is None
