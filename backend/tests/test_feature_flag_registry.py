"""Strażnik rejestru flag: flaga wyłączona domyślnie nie wisi bez decyzji.

Czerwony wynik po terminie jest celowy: blokuje kolejkę, dopóki ktoś nie włączy
flagi na stałe, nie usunie jej z kodem albo nie przedłuży wpisu nową datą.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.config import Settings
from app.core.feature_flag_registry import (
    MAX_DAYS_WITHOUT_DECISION,
    OFF_BEFORE_REGISTRY,
    REGISTERED_FLAGS,
    FeatureFlag,
)
from app.core.scheduling import business_today

# Termin mija z kalendarza, bez zmiany w żadnym pliku, więc test biegnie na każdym PR-ze.
pytestmark = pytest.mark.static

_REGISTERED = {flag.name: flag for flag in REGISTERED_FLAGS}


def _expired(flags: tuple[FeatureFlag, ...], today: date) -> list[str]:
    return [flag.name for flag in flags if flag.expires < today]


def _off_by_default() -> set[str]:
    return {
        name
        for name, field in Settings.model_fields.items()
        if field.annotation is bool and field.default is False
    }


def test_new_off_by_default_flag_needs_a_registry_entry() -> None:
    unregistered = _off_by_default() - set(_REGISTERED) - OFF_BEFORE_REGISTRY
    assert not unregistered, (
        f"Flagi domyślnie wyłączone bez wpisu: {sorted(unregistered)}. "
        "Dopisz je do REGISTERED_FLAGS w app/core/feature_flag_registry.py z terminem decyzji."
    )


def test_registered_flag_exists_and_is_still_off_by_default() -> None:
    stale = sorted(set(_REGISTERED) - _off_by_default())
    assert not stale, f"Decyzja zapadła albo flagi już nie ma, usuń wpisy: {stale}."


def test_name_is_in_one_list_only() -> None:
    assert not set(_REGISTERED) & OFF_BEFORE_REGISTRY


def test_no_flag_gets_more_than_sixty_days_per_decision() -> None:
    too_long = [
        flag.name
        for flag in REGISTERED_FLAGS
        if flag.expires - flag.decided > timedelta(days=MAX_DAYS_WITHOUT_DECISION)
    ]
    assert not too_long, f"Termin dalej niż {MAX_DAYS_WITHOUT_DECISION} dni od decyzji: {too_long}."


def test_no_registered_flag_is_past_its_deadline() -> None:
    expired = _expired(REGISTERED_FLAGS, business_today())
    assert not expired, (
        f"Minął termin decyzji dla: {expired}. Włącz na stałe, usuń z kodem "
        "albo wpisz nową datę `decided` i `expires` w feature_flag_registry.py."
    )


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2027, 1, 6), []),
        (date(2027, 1, 7), ["PRZYKLAD_ENABLED"]),
    ],
)
def test_deadline_day_is_still_allowed_and_the_next_day_is_not(
    today: date, expected: list[str]
) -> None:
    flag = FeatureFlag(
        name="PRZYKLAD_ENABLED",
        purpose="test",
        decided=date(2026, 11, 7),
        expires=date(2027, 1, 6),
    )
    assert _expired((flag,), today) == expected
