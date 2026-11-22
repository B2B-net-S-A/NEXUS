"""Przełącznik źródła urlopów w testach przydziału i zastępstw.

Od 22.11.2026 (Compass wygaszony) jedynym źródłem dostępności są urlopy
NEXUSA (``app_settings['hr_availability_source'] = local``). Testy ustawiają
go bez bazy; ``monkeypatch`` przywraca stan po teście.
"""

import time

import pytest

from app.services.hr import availability_local


def use_nexus_leave_source(monkeypatch: pytest.MonkeyPatch, on: bool = True) -> None:
    """Włącz albo wyłącz źródło urlopów na czas testu.

    ``checked`` = teraz, więc ``refresh_source`` przez minutę nie czyta
    ``app_settings`` i nie nadpisuje ustawienia z testu.
    """
    monkeypatch.setitem(availability_local._SOURCE, "local", on)
    monkeypatch.setitem(availability_local._SOURCE, "checked", time.monotonic())
