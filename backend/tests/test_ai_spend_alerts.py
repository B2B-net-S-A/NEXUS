"""Ostrzezenie o skoku zuzycia AI - i o tym, czego NIE ma robic.

Artur zdecydowal (#202): zadnych sufitow, tylko alert. Prog do wpisania byl
odrzucony swiadomie - prog, ktorego nikt nie ustawi, nigdy nie zadziala,
a to dokladnie tryb awarii ze znaleziska #204 (workflow raportujacy sukces
kazdego ranka, nie robiac nic). Wszystkie 11 wierszy `ai_features` istnieje
dzis z `monthly_limit = 0` i nikt tej liczby nie wybral przez rok.

Dlatego alarm liczy sie WZGLEDEM POPRZEDNIEGO OKRESU. Testy pilnuja obu
kierunkow: ma sie odezwac przy skoku ORAZ ma MILCZEC przy szumie. Alarm,
ktory dzwoni zawsze, uczy sie go ignorowac - i wtedy jest gorszy niz jego brak.
"""

import pytest

from app.tasks import ai_spend_alerts as mod


def test_spike_over_baseline_alerts():
    """Trzykrotny wzrost ponad podloge => poziom 1."""
    assert mod._level_for(used=900, baseline=300) >= 1


def test_growth_below_the_absolute_floor_is_silent():
    """Wzrost z 3 na 12 wywolan to czterokrotnosc, ktora nikogo nie obchodzi.

    Bez podlogi kanal zapchalby sie szumem z funkcji uzywanych sporadycznie.
    """
    assert mod._level_for(used=12, baseline=3) == 0


def test_normal_month_over_month_growth_is_silent():
    """Wzrost o polowe to normalna praca, nie awaria."""
    assert mod._level_for(used=1500, baseline=1000) == 0


def test_no_history_is_not_treated_as_infinite_growth():
    """Pierwszy miesiac zycia funkcji ma zerowa baze.

    Bez tego wyjatku kazde uzycie byloby 'nieskonczonym wzrostem' i alarm
    dzwonilby przy kazdej nowej funkcji AI.
    """
    assert mod._level_for(used=10, baseline=0) == 0, "ponizej podlogi ma milczec"
    assert mod._level_for(used=5000, baseline=0) == 1, "powyzej podlogi ma ostrzec raz"


def test_levels_escalate_so_a_growing_spike_keeps_talking():
    """Jednorazowy alert milczalby, gdy zuzycie ROSNIE dalej.

    Stempel trzyma krotnosc, przy ktorej ostatnio ostrzegalismy, wiec kolejne
    podwojenie odzywa sie ponownie - a wlasnie wtedy jest najciekawsze.
    """
    l1 = mod._level_for(used=900, baseline=300)
    l2 = mod._level_for(used=1800, baseline=300)
    l3 = mod._level_for(used=3600, baseline=300)
    assert l1 < l2 < l3, f"poziomy nie rosna: {l1}, {l2}, {l3}"


@pytest.mark.parametrize(
    "used,baseline,floor,expected",
    [
        (9, 0, 10, 0),
        (10, 0, 10, 1),
        (20, 0, 10, 2),
        (20, 10, 10, 0),
        (30, 10, 10, 1),
        (60, 10, 10, 2),
    ],
)
def test_daily_cost_and_token_pace(used, baseline, floor, expected):
    assert mod._daily_level(used, baseline, floor) == expected


async def test_loop_does_not_exit_when_slack_is_missing(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    scan = AsyncMock(side_effect=asyncio.CancelledError)
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=object())
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(mod, "AsyncSessionLocal", factory)
    monkeypatch.setattr(mod, "_scan_once", scan)
    with pytest.raises(asyncio.CancelledError):
        await mod.ai_spend_alerts_loop()
    assert scan.await_args.args[1] == ""
