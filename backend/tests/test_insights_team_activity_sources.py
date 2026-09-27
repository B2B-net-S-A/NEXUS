"""Runda 10 (R10-N2-1): „Aktywność zespołu” nie sumuje martwych typów akcji.

Do 27.09.2026 cztery kolumny rankingu sumowały typy ``user_activities``
(``screening_done``, ``interview_scheduled``, ``placement_closed``,
``call_made``), których żaden kod nie zapisywał — tabela pokazywała stałe
zera. Ten test czyta źródło serwisu: każdy typ akcji, o który serwis pyta,
musi mieć w ``app/`` zapis ``UserActionType.<typ>`` poza modelem, serwisem
i słownikiem etykiet.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.user_activity import UserActionType

APP = Path(__file__).resolve().parents[1] / "app"
SERVICE = APP / "services" / "insights_team_activity.py"
_SKIP = {
    APP / "models" / "user_activity.py",
    SERVICE,
}


def _written_action_types() -> set[str]:
    written: set[str] = set()
    for path in APP.rglob("*.py"):
        if path in _SKIP:
            continue
        written.update(re.findall(r"UserActionType\.(\w+)", path.read_text()))
    return written


def _queried_action_types() -> set[str]:
    code = SERVICE.read_text()
    # Pomijamy docstring modułu — opisuje historię, w tym martwe typy.
    body = code[code.index("from __future__ import annotations") :]
    names = {t.value for t in UserActionType}
    queried = set(re.findall(r"UserActionType\.(\w+)", body))
    queried |= {n for n in names if f"'{n}'" in body}
    return queried


def test_service_only_queries_action_types_that_something_writes():
    queried = _queried_action_types()
    assert queried, "serwis powinien pytać co najmniej o candidate_added"
    missing = queried - _written_action_types()
    assert not missing, (
        f"Serwis sumuje typy akcji, których nic nie zapisuje: {sorted(missing)}"
    )


def test_dead_action_types_are_not_queried():
    dead = {"screening_done", "interview_scheduled", "placement_closed", "call_made"}
    assert not (_queried_action_types() & dead)
