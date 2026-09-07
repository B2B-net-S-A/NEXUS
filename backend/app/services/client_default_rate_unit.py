"""Domyślna jednostka stawki dopasowana do klienta.

Zamiast twardego `monthly` (żaden klient nie rozlicza się miesięcznie —
`CLAUDE.md` „Domyślna jednostka stawki dopasowana do klienta") tworzenie NOWEGO
zamówienia (formularz „Nowy kontraktor" i endpoint `contract-with-order`)
przyjmuje domyślnie jednostkę NAJCZĘŚCIEJ już stosowaną u danego klienta,
wyliczoną z jego istniejących zamówień (`client_orders`). Ścieżki DZIEDZICZĄCE
(uzupełnianie/przedłużanie/ingest z maila) biorą jednostkę z kontraktu — którą
przy tworzeniu ustawiła już ta domyślna — bo mają stawki w jednostce kontraktu
i podmiana zniekształciłaby kwotę.

`monthly` jest z tego wyboru WYKLUCZONE — i to jest sedno reguły, nie tylko
tie-break. Po pierwsze produkt tego wymaga wprost („Jednostka miesięczna nigdy
nie jest ustawiana jako domyślna"). Po drugie historyczne wiersze niosą `monthly`
głównie jako ślad dawnego twardego defaultu, więc policzenie go zafałszowałoby
„najczęstszą" jednostkę u klienta, który realnie rozlicza się godzinowo/dziennie.

Kolejność rozstrzygania (pierwszy niepusty wygrywa):
1. najczęstsza NIE-miesięczna jednostka wśród zamówień TEGO klienta,
2. najczęstsza NIE-miesięczna jednostka w CAŁEJ bazie zamówień (prior dla klienta
   bez historii — data-driven, żeby nie zgadywać arbitralnie),
3. `_ULTIMATE_FALLBACK` — sięgany tylko, gdy w całej bazie nie ma ANI JEDNEGO
   nie-miesięcznego zamówienia (świeża instalacja / testy). W produkcji
   nieosiągalny; arbitralny, ale nigdy `monthly`.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder
from app.models.contract import RateUnit

# Ostateczny bezpiecznik, gdy nie ma ŻADNEGO sygnału (zero nie-miesięcznych
# zamówień w całej bazie). Nigdy `monthly`.
_ULTIMATE_FALLBACK = RateUnit.hourly

# Determinizm remisu: przy równej liczbie wystąpień wygrywa `daily` (MD to
# dominująca jednostka body-leasingu), potem `hourly`. Bez tego „najczęstsza"
# jednostka bywałaby losowa między odczytami przy identycznych licznikach.
_TIE_BREAK: dict[RateUnit, int] = {RateUnit.daily: 0, RateUnit.hourly: 1}


def _pick(rows: list[tuple[RateUnit, int]]) -> RateUnit | None:
    """Najczęstsza NIE-miesięczna jednostka z par (jednostka, liczność)."""

    ranked = sorted(
        (row for row in rows if row[0] != RateUnit.monthly),
        key=lambda row: (-row[1], _TIE_BREAK.get(row[0], 9)),
    )
    return ranked[0][0] if ranked else None


async def _tally(
    session: AsyncSession, *, client_id: int | None
) -> list[tuple[RateUnit, int]]:
    stmt = (
        select(ClientOrder.rate_unit, func.count())
        .where(ClientOrder.rate_unit != RateUnit.monthly)
        .group_by(ClientOrder.rate_unit)
    )
    if client_id is not None:
        stmt = stmt.where(ClientOrder.client_id == client_id)
    result = await session.execute(stmt)
    return [(unit, count) for unit, count in result.all()]


async def default_rate_unit_for_client(
    session: AsyncSession, client_id: int
) -> RateUnit:
    """Domyślna jednostka stawki dla nowego/uzupełnianego zamówienia klienta.

    Nigdy nie zwraca ``monthly``.
    """

    return (
        _pick(await _tally(session, client_id=client_id))
        or _pick(await _tally(session, client_id=None))
        or _ULTIMATE_FALLBACK
    )
