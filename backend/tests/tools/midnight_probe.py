"""Sonda: symuluje bieg testów przekraczający północ.

Narzędzie pomiarowe, nie test — pytest jej nie zbiera (nazwa bez `test_`).
Wtyczkę podaje się jawnie, a repo musi być na `PYTHONPATH`:

    PYTHONPATH=. pytest <pliki> -p tests.tools.midnight_probe

Zmierzone tą sondą 17.09.2026 na 28 modułach liczących datę przy imporcie:

    bez przypięcia doby, +1 doba   → 204 z 394 testów PADA
    z przypięciem, 5 min po północy → 406/406 przechodzi
    z przypięciem, +1 doba          → 394/394 przechodzi
    próba kontrolna (zegar ruszony, ta sama data) → 394/394 przechodzi

Ostatni wiersz jest tu najważniejszy: bez niego nie wiadomo, czy pady biorą się
z rozjazdu daty, czy z samego manipulowania zegarem — a naprawa też manipuluje.

`MIDNIGHT_PROBE_MODE=realistic` (domyślny) odtwarza to, co faktycznie zdarzyło
się w CI: moduły zaimportowały się przed północą, a test wykonuje się kilka
minut po niej. `MIDNIGHT_PROBE_DAYS=N` przesuwa o pełne doby — ostrzejsze niż
rzeczywistość, przydatne do pomiaru zasięgu problemu.

`MIDNIGHT_PROBE_DAYS=0` to próba KONTROLNA: zegar ruszony, ale data ta sama.
Pady w kontroli pochodzą od samego manipulowania zegarem, nie od rozjazdu daty.
"""

import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import time_machine

WARSAW = ZoneInfo("Europe/Warsaw")
_MODE = os.environ.get("MIDNIGHT_PROBE_MODE", "realistic")
_DAYS = int(os.environ.get("MIDNIGHT_PROBE_DAYS", "1"))
_MINUTES_PAST = int(os.environ.get("MIDNIGHT_PROBE_MINUTES_PAST", "5"))


def _target() -> datetime:
    now = datetime.now(WARSAW)
    if _MODE == "realistic":
        return datetime.combine(
            now.date() + timedelta(days=1), time(0, _MINUTES_PAST), tzinfo=WARSAW
        )
    return now + timedelta(days=_DAYS)


# `pytest_runtest_protocol`, nie `pytest_runtest_call`: przesunięcie musi objąć
# także SETUP fixture'ów. Naprawa w conftest sprawdza datę przy setupie, więc
# sonda działająca dopiero w fazie wywołania omijałaby ją i mierzyła nie to.
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    with time_machine.travel(_target(), tick=True):
        yield
