"""`phases=` — zawężenie biegu do wskazanych faz.

Powód istnienia: `candidate_files` jest DZIEWIĄTĄ z piętnastu faz, a
`candidates` przed nią trwa godzinami. Coolify restartuje kontener przy każdym
pushu na main, więc bieg ginie, zanim dojdzie do zamiatania plików. Na prodzie
11.08 kursor plików nie drgnął przez 2,5 h mimo trzech uruchomionych biegów,
a `__full__` stał na 19 lipca — czyli od tamtej pory ŻADEN pełny reconcile się
nie zakończył. Bez tego parametru domknięcie zaległości wymaga okna dłuższego
niż odstęp między deployami, więc w praktyce nie następuje.

Dwie rzeczy są tu ważniejsze od samego filtrowania i to one mają testy:

1. **Bieg częściowy NIE stempluje `__daily__`/`__full__`.** `__daily__` wyznacza
   `since` kolejnej delty, więc przesunięcie go po biegu, który pominął fazy,
   przeskoczyłoby dane, których nikt nie zaimportował — cicha strata. `__full__`
   kłamałby o zakończonym reconcile i uciszał sondę świeżości w `/api/health`.

2. **Literówka wybucha.** Cichy filtr na nieznaną nazwę nie uruchamia ŻADNEJ
   fazy, a bieg kończy się statusem „ok" — operator widzi sukces i odchodzi od
   klawiatury przekonany, że sweep leci.
"""

from __future__ import annotations

import pytest

from app.tasks import traffit_sync as ts


def test_phase_names_match_the_actual_plan() -> None:
    """`PHASE_NAMES` musi być lustrem `_phase_plan`, nie drugą listą obok niego.

    Rozjazd jest groźny w obie strony: brakująca nazwa to 422 za poprawne
    wywołanie, nadmiarowa — przepuszczenie nazwy, której plan nie zna, czyli
    filtr nieuruchamiający niczego przy statusie „ok".
    """

    class _StubImporter:
        def __getattr__(self, _name):
            return lambda *a, **kw: None

    plan = ts._phase_plan(_StubImporter(), None, None)
    planned = [name for name, _ in plan]

    # `cortex` jest warunkowy (CORTEX_SYNC_ENABLED), więc porównujemy zawieranie
    # w tę stronę, w którą jest ono zawsze prawdziwe, i osobno pilnujemy, żeby
    # PHASE_NAMES nie zawierało nazw spoza planu przy WŁĄCZONYM cortexie.
    assert set(planned) <= set(ts.PHASE_NAMES), (
        f"plan ma fazy nieznane PHASE_NAMES: {sorted(set(planned) - set(ts.PHASE_NAMES))}"
    )
    assert "cortex" in ts.PHASE_NAMES
    assert set(ts.PHASE_NAMES) - set(planned) <= {"cortex"}, (
        "PHASE_NAMES zawiera nazwy, których plan nie produkuje: "
        f"{sorted(set(ts.PHASE_NAMES) - set(planned) - {'cortex'})}"
    )


def test_unknown_phase_is_rejected_not_silently_dropped() -> None:
    with pytest.raises(ValueError) as exc:
        ts.validate_phases(["candidate_files", "candiate_files"])
    # Nazwa z literówką musi pojawić się w komunikacie — inaczej operator wie
    # tylko, że „coś" jest źle, przy 15 fazach do przejrzenia.
    assert "candiate_files" in str(exc.value)


def test_empty_phase_list_is_rejected() -> None:
    """Pusta lista to nie „uruchom wszystko" — to prośba bez treści.

    Gdyby przechodziła, `?phases=` (albo `?phases=,,`) uruchamiałoby PEŁNY plan
    razem ze stemplowaniem znaczników, czyli dokładnie odwrotność intencji.
    """
    with pytest.raises(ValueError):
        ts.validate_phases([])


def test_validate_returns_the_set_and_accepts_every_known_name() -> None:
    assert ts.validate_phases(["candidate_files"]) == frozenset({"candidate_files"})
    # Każda nazwa z kontraktu musi przechodzić — inaczej parametr jest martwy
    # dla części planu i nikt się o tym nie dowie aż do 422 na produkcji.
    assert ts.validate_phases(list(ts.PHASE_NAMES)) == frozenset(ts.PHASE_NAMES)


def test_budgeted_sweep_phases_are_selectable() -> None:
    """Fazy, dla których ten parametr powstał, muszą dać się wskazać.

    `_BUDGETED_SWEEP_PHASES` to zbiór, który zamiata bazę porcjami i parkuje
    kursor. Gdyby któraś z nich nie była w `PHASE_NAMES`, parametr nie
    rozwiązywałby problemu, dla którego istnieje.
    """
    assert ts.validate_phases(list(ts._BUDGETED_SWEEP_PHASES)) == frozenset(
        ts._BUDGETED_SWEEP_PHASES
    )


def test_phase_disabled_by_config_is_rejected_like_a_typo(monkeypatch) -> None:
    """Nazwa poprawna, ale wyłączona, kończy się TAK SAMO jak literówka:
    filtr nie dopasowuje niczego, bieg nie robi nic i raportuje sukces.

    `cortex` znika z planu przy `CORTEX_SYNC_ENABLED=false`, ale zostaje
    w `PHASE_NAMES` (to słownik pisowni). Bez osobnego sprawdzenia aktywności
    `?phases=cortex` przechodziło walidację i dawało „started" po biegu, który
    nie wykonał ani jednej fazy.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "CORTEX_SYNC_ENABLED", False)
    assert "cortex" not in ts.active_phase_names()
    with pytest.raises(ValueError) as exc:
        ts.validate_phases(["cortex"])
    assert "cortex" in str(exc.value)

    monkeypatch.setattr(settings, "CORTEX_SYNC_ENABLED", True)
    assert ts.validate_phases(["cortex"]) == frozenset({"cortex"})


def test_mixed_selection_survives_one_inactive_phase(monkeypatch) -> None:
    """Odrzucamy dopiero, gdy CAŁY wybór jest nieaktywny.

    `candidate_files,cortex` przy wyłączonym cortexie ma sens i ma pobiec —
    odrzucenie całości zmusiłoby operatora do pamiętania, które fazy są dziś
    włączone, zamiast po prostu wskazać te, których potrzebuje.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "CORTEX_SYNC_ENABLED", False)
    assert ts.validate_phases(["candidate_files", "cortex"]) == frozenset(
        {"candidate_files", "cortex"}
    )


def test_partial_run_does_not_stamp_the_run_markers() -> None:
    """Strażnik najdroższego błędu: `__daily__` przesunięty po biegu, który
    pominął fazy, wycina pominięte rekordy z okna następnej delty NA ZAWSZE.

    Sprawdzane na źródle, bo pełne wykonanie biegu wymaga żywego Traffita.
    Asercja jest strukturalna: stemplowanie znaczników musi być pod warunkiem
    „bieg objął cały plan".
    """
    import inspect

    src = inspect.getsource(ts.run_traffit_sync)
    # Test czyta ŹRÓDŁO, więc jest wrażliwy na mechaniczny refaktor: zmiana
    # nazwy `selected`, wyniesienie wyrażenia `FULL_MARKER …` do zmiennej albo
    # inne wcięcie wywalą go mimo identycznej semantyki. To świadomy kompromis —
    # alternatywą jest zamockowanie całego klienta Traffita tylko po to, żeby
    # sprawdzić jeden warunek. Jeśli tu jesteś po refaktorze: nie osłabiaj tej
    # asercji, tylko dopasuj ją do nowego kształtu i sprawdź, czy stemplowanie
    # `__daily__`/`__full__` NADAL jest pod warunkiem „bieg objął cały plan".
    marker_needle = "FULL_MARKER if mode =="
    guard_needle = "if selected is None:"
    assert marker_needle in src, (
        f"nie znalazłem {marker_needle!r} w run_traffit_sync — refaktor? "
        "Sprawdź RĘCZNIE, czy bieg częściowy nadal nie stempluje znaczników, "
        "i dopasuj ten test."
    )
    marker_pos = src.index(marker_needle)
    assert guard_needle in src[:marker_pos], (
        f"nie znalazłem {guard_needle!r} przed stemplowaniem znaczników — albo "
        "bramka zniknęła (BŁĄD: bieg częściowy przesunie watermark delty), albo "
        "zmieniono nazwę zmiennej i ten test wymaga aktualizacji."
    )
    guard_pos = src.rindex(guard_needle, 0, marker_pos)
    between = src[guard_pos:marker_pos]

    # Między bramką a stemplem nie może być nic, co ją zamyka — czyli żadnego
    # `else:`/`return` na tym poziomie.
    assert "\n                else:" not in between, (
        "stemplowanie znaczników wypadło spod bramki `selected is None`"
    )
    assert guard_pos < marker_pos, (
        "znaczniki __daily__/__full__ są stemplowane BEZ sprawdzenia, czy bieg "
        "objął cały plan — bieg częściowy przesunąłby watermark delty ponad "
        "danymi, których nie dotknął"
    )
