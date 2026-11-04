"""Stan dnia w mini-tygodniu „Mojego zespołu” — czysta funkcja, bez bazy.

Audyt 21.10.2026: przy module czasu bez modułu urlopów nieobecności nie są
czytane, a dzień bez wpisu w „Moim miesiącu” wychodził jako „work” — ekran
mówił „w pracy” o osobie, która mogła być na urlopie. Bez urlopów zostają
zdalnie i delegacja, reszta to ``unknown`` („—”).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.hr import team


def _state(**overrides):
    values = {
        "working_day": True,
        "approved": None,
        "waiting": None,
        "presence": None,
        "absences_known": True,
    }
    values.update(overrides)
    return team.day_state(**values)


def test_unknown_is_a_week_state() -> None:
    assert "unknown" in team.WEEK_STATES


def test_without_leave_module_a_plain_day_is_unknown_not_work() -> None:
    assert _state(absences_known=False) == ("unknown", None)


def test_without_leave_module_remote_and_trip_stay() -> None:
    assert _state(absences_known=False, presence="remote") == ("remote", None)
    assert _state(absences_known=False, presence="business_trip") == (
        "business_trip",
        None,
    )


def test_with_leave_module_a_plain_day_is_work() -> None:
    assert _state() == ("work", None)


def test_priority_off_absent_pending_presence() -> None:
    approved = SimpleNamespace(half_day="morning")
    waiting = SimpleNamespace(half_day=None)
    assert _state(working_day=False, approved=approved) == ("off", None)
    assert _state(approved=approved, presence="remote") == ("absent", "morning")
    assert _state(waiting=waiting, presence="remote") == ("pending", None)
