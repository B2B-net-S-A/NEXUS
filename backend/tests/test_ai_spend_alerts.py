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


def test_stamp_is_written_before_the_post_not_after():
    """Kolejnosc decyduje, czy restart powtorzy alarm.

    Prod restartuje sie przy KAZDYM pushu na main (Coolify). Gdyby stempel szedl
    po POST-cie, twardy restart w tym oknie cofalby transakcje i kolejny przebieg
    wyslalby to samo ostrzezenie jeszcze raz. Ten sam porzadek maja juz
    `slack_sla_alerts` i `contract_alerts`.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(mod._scan_once).lstrip())

    def _called(node):
        """Nazwa wolanej funkcji w OBU formach.

        `db.commit()` to `ast.Attribute` (pole `attr`), a `_post_to_slack(...)`
        to `ast.Name` (pole `id`). Dopasowywanie tylko po `attr` dawalo pusta
        liste dla drugiego i test oblewal POPRAWNY kod - ten sam blad, ktory
        naprawiono juz w `tests/_ast_calls.py`.
        """
        f = node.func
        return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")

    # `ast.walk` NIE chodzi w kolejnosci zrodlowej, wiec bierzemy min(lineno),
    # a nie "pierwszy napotkany".
    calls = [(n.lineno, _called(n)) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    commits = [ln for ln, name in calls if name == "commit"]
    posts = [ln for ln, name in calls if name == "_post_to_slack"]

    assert commits, "brak commita stempla"
    assert posts, "brak wysylki"
    assert min(commits) < min(posts), (
        f"stempel commitowany PO wyslaniu (commit@{min(commits)}, "
        f"post@{min(posts)}) - restart w tym oknie powtorzy alarm"
    )


@pytest.mark.asyncio
async def test_loop_exits_without_webhook(monkeypatch):
    """Brak SLACK_WEBHOOK_URL ma KONCZYC petle, nie budzic jej co godzine."""
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    # Gdyby petla nie wychodzila, ten await nigdy by nie wrocil.
    await mod.ai_spend_alerts_loop()
