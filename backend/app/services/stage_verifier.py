"""Kto zweryfikował parę (kandydat, rekrutacja) — jedna reguła dla ekranów.

Weryfikujący to autor PIERWSZEGO wiersza „Zweryfikowany” pary, w kolejności
premii rekrutera (``hr.placement_bonuses.load_verifiers``): czas akceptacji
etapu, a bez niej czas ruchu, potem id. Wiersz bez autora (import) nikogo
nie wskazuje.

Najnowszy wiersz „Zweryfikowany” bywa cofnięciem karty z „QC CV” przez
Delivery Leada — to nie weryfikacja (zgłoszenie 21.10.2026: karta Tablicy
i przegląd DL pokazywały DL-a zamiast rekruterki, która zweryfikowała).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol, TypeVar


class _StageRow(Protocol):
    id: int
    moved_by: Optional[int]
    moved_at: datetime
    approved_at: Optional[datetime]


Row = TypeVar("Row", bound=_StageRow)


def first_verifier(current: Optional[Row], row: Row) -> Optional[Row]:
    """Z dwóch wierszy „Zweryfikowany” ten, który wskazuje weryfikującego."""

    if row.moved_by is None:
        return current
    if current is None:
        return row
    return min(current, row, key=lambda r: (r.approved_at or r.moved_at, r.id))
