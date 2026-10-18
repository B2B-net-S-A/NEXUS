"""Nazwy rodzajów nieobecności są JEDNE — urlopy, „Mój miesiąc”, maile i front.

Do 17.10.2026 „Mój miesiąc” miał własny słownik (``time_month``) z innymi
nazwami niż wniosek („Krwiodawstwo” zamiast „Oddanie krwi”, „Szkolenie”
zamiast „Urlop szkoleniowy”) — ta sama osoba widziała ten sam dzień pod
dwiema nazwami. Źródło: ``leave_policy.LEAVE_TYPE_LABELS``; front ma lustro
słowo w słowo (``frontend/src/components/hr/leave/leave-format.ts``).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.services.hr import time_month
from app.services.hr.leave_policy import LEAVE_TYPE_LABELS, type_label

_FRONT = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "components"
    / "hr"
    / "leave"
    / "leave-format.ts"
)
_BLOCK = re.compile(
    r"export const LEAVE_TYPE_LABELS: Record<LeaveType, string> = \{(.*?)\n\};", re.S
)
_ENTRY = re.compile(r'^\s+(\w+): "([^"]*)",$', re.M)


def test_frontend_leave_labels_are_the_backend_labels_word_for_word() -> None:
    match = _BLOCK.search(_FRONT.read_text(encoding="utf-8"))
    assert match, "Nie znaleziono LEAVE_TYPE_LABELS w leave-format.ts"
    assert dict(_ENTRY.findall(match.group(1))) == LEAVE_TYPE_LABELS


def test_my_month_has_no_own_leave_dictionary() -> None:
    assert not hasattr(time_month, "LEAVE_TYPE_LABELS")
    assert type_label("blood_donation", "uop") == "Oddanie krwi"
    assert type_label("training", None) == "Urlop szkoleniowy"
    # Na B2B dzień z puli to przerwa, nie urlop (słowa formy, D4).
    assert type_label("vacation", "b2b") == "Przerwa w świadczeniu usług"
