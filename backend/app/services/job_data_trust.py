"""Czy dane rekrutacji nadają się do policzenia tej metryki.

Powstało po audycie z 09.2026, który wykazał, że najgroźniejsze liczby
w systemie to nie te brakujące, tylko te OBECNE, kompletne i nieprawdziwe.
Trzy przykłady z produkcji, wszystkie z kolumn wypełnionych w 100%:

* mediana czasu realizacji = **0 dni** (3512 z 3947 rekrutacji „zamkniętych"
  w ciągu doby od „utworzenia") — bo `created_at` i `closed_at` opisywały
  moment importu, nie zdarzenia u klienta;
* `avg_time_to_fill` = 66,7 dnia dla klienta z 2005 rekrutacjami — liczone od
  fikcyjnego zera i na próbce okrojonej filtrem, który odsiewał wszystko sprzed
  importu;
* rozbicie powodów zamknięcia = `{"unknown": N}` u KAŻDEGO klienta, bo
  `close_reason` jest NULL na 3924 z 3924 zamkniętych rekrutacji.

Reguła, którą to repo stosuje już gdzie indziej (`insights_clients.ratio_pct`,
Power Calling w `reports.py`): **„nie wiemy" i „policzone zero" to dwie różne
rzeczy i nie wolno ich zlewać.** Ten moduł daje im wspólne słownictwo.

Predykaty są DANOZALEŻNE, nie sterowane flagą. To celowe: gdy pełny bieg
importera uzupełni `opened_at`, metryki wracają do życia same, bez wdrożenia.
Dopóki nie uzupełni — odpowiadają „brak danych źródłowych", co jest prawdą.

Funkcje są czyste i przyjmują cokolwiek z odpowiednimi atrybutami (encja `Job`
albo wiersz `Row` z wąskiego SELECT-a), więc nie wymuszają ładowania całej
encji tam, gdzie zapytanie i tak wybiera trzy kolumny.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

# Powody trafiające do odpowiedzi API obok `null`. Stringi, nie enum, bo lądują
# w JSON-ie i są czytane przez front — enum dałby tu tylko `.value` w każdym
# miejscu użycia.
REASON_NO_OPENED_AT = "no_opened_at"
REASON_NO_CLOSE_REASON = "no_close_reason"
REASON_NO_DECLARED_HEADCOUNT = "no_declared_headcount"

# Wartość pola `*_source` w kopercie odpowiedzi, gdy metryki nie da się policzyć.
SOURCE_UNAVAILABLE = "unavailable"

_TRAFFIT = "traffit"


def duration_available(job: Any) -> bool:
    """Czy z tej rekrutacji da się policzyć JAKIKOLWIEK czas trwania.

    Warunkiem jest `opened_at`, a nie `created_at`. Dla 4206 rekrutacji
    z Traffita `created_at` to znacznik importu — liczenie od niego nie jest
    przybliżeniem, tylko innym pytaniem („ile czasu minęło od migracji").
    """
    return getattr(job, "opened_at", None) is not None


def outcome_available(job: Any) -> bool:
    """Czy wiadomo, DLACZEGO ta rekrutacja się zamknęła.

    `close_reason` mapuje wyłącznie `POST /jobs/{id}/close`; importer Traffita
    nie ma tego pola w źródle. Brak znaczy „nie wiemy", a nie „inny powód" —
    dlatego kubełek `unknown` w rozbiciach musi być podpisany jako luka
    w danych, a nie jako kategoria obok pozostałych.
    """
    return getattr(job, "close_reason", None) is not None


def vacancies_declared(job: Any) -> bool:
    """Czy `headcount` tej rekrutacji ktoś naprawdę zadeklarował.

    Importer wpisuje tam stałą `1` (`_UPSERT_JOB`), a kolumna jest
    `NOT NULL DEFAULT 1` — więc samej wartości nie da się odróżnić od braku.
    Rozstrzyga pochodzenie wiersza. Skutek jest dziś rozległy (4206 z 4229
    rekrutacji), ale dokładnie taki powinien być: `fill_rate` przekraczający
    100% u siedmiu klientów brał się właśnie z tego, że mianownik był stałą.

    Gdy formularz zacznie zbierać `headcount`, ten predykat trzeba zawęzić do
    „wartość pochodzi od człowieka" — dziś nie ma po czym tego poznać.
    """
    return getattr(job, "external_source", None) != _TRAFFIT


def duration_days(job: Any, until: Optional[datetime | date] = None) -> Optional[int]:
    """Liczba dni od otwarcia rekrutacji do `until` (domyślnie: jej zamknięcia).

    Zwraca `None`, gdy którejkolwiek strony brakuje — NIGDY 0. Zero znaczyłoby
    „policzone i wyszło zero dni", czyli dokładnie to zdanie, którym system
    kłamał przez cztery miesiące.
    """
    opened = getattr(job, "opened_at", None)
    if opened is None:
        return None

    end = until if until is not None else getattr(job, "closed_at", None)
    if end is None:
        return None

    opened_d = opened.date() if isinstance(opened, datetime) else opened
    end_d = end.date() if isinstance(end, datetime) else end
    return max((end_d - opened_d).days, 0)


def coverage_pct(covered: int, total: int) -> Optional[float]:
    """Jaki odsetek wierszy w ogóle daje się policzyć — albo `None`.

    Lustro `insights_clients.ratio_pct`: zerowy mianownik to brak podstawy do
    oceny, nie wynik zerowy.
    """
    if total <= 0:
        return None
    return round(covered / total * 100, 1)
