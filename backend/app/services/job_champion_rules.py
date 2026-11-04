"""Reguły championów rekrutacji bez bazy (decyzje Artura D1–D9, 15.10.2026).

Czyste funkcje — czyta je ``services/job_champions`` i testy bez Postgresa.

* D4: championem może być osoba, której karta stoi od „CV wysłane” wzwyż
  (klient ją zna). Kolejność listy = jak daleko zaszła.
* D5: rekrutacja przestaje szukać, gdy championów razem z zatrudnionymi jest
  co najmniej tyle, ile miejsc (``max(headcount, 1)``). Przy jednym miejscu
  wystarczy pierwszy champion, kolejni są zapasem.
* D8: dzwonek tylko przy zapisie listy, która coś zmieniła, i przy powrocie
  do szukania.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

# Kolumny Tablicy, z których da się wskazać championa — od najdalszej.
ELIGIBLE_COLUMNS: tuple[str, ...] = ("hired", "contract", "client_interview", "cv_sent")
_COLUMN_RANK = {column: rank for rank, column in enumerate(ELIGIBLE_COLUMNS)}

# Stany pracy, z których zapis niepustej listy przestawia na „Szukamy” (D9).
WAKE_STATES: frozenset[str] = frozenset({"to_review", "client_silent"})

NOTIFY_CHANGED = "changed"
NOTIFY_RESUMED = "resumed"


def is_eligible_column(column: Optional[str]) -> bool:
    return column in _COLUMN_RANK


def column_rank(column: Optional[str]) -> int:
    """Pozycja na liście „Championi” — mniejsza = dalej w procesie."""
    return _COLUMN_RANK.get(column or "", len(ELIGIBLE_COLUMNS))


def seats(headcount: Optional[int]) -> int:
    return max(headcount or 1, 1)


def search_stops(
    champion_ids: Iterable[int], hired_ids: Iterable[int], headcount: Optional[int]
) -> bool:
    """D5: czy rekrutacja z tymi championami przestaje szukać.

    Bez żadnego championa flaga nie powstaje — komplet samych zatrudnionych
    to status „Obsadzona”, liczony osobno.
    """
    champions = set(champion_ids)
    if not champions:
        return False
    return len(champions | set(hired_ids)) >= seats(headcount)


def ordered_unique(ids: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(int(i) for i in ids))


def diff(current: Iterable[int], wanted: Iterable[int]) -> tuple[list[int], list[int]]:
    """(dodani, zdjęci) — w kolejności z listy żądania / obecnej."""
    current_list = ordered_unique(current)
    wanted_list = ordered_unique(wanted)
    added = [cid for cid in wanted_list if cid not in set(current_list)]
    removed = [cid for cid in current_list if cid not in set(wanted_list)]
    return added, removed


def notification_kind(
    *, before_stopped: bool, after_stopped: bool, changed: bool, has_champions: bool
) -> Optional[str]:
    """D8: który dzwonek wysłać po zmianie (albo żaden)."""
    if before_stopped and not after_stopped:
        return NOTIFY_RESUMED
    if changed and has_champions:
        return NOTIFY_CHANGED
    return None
