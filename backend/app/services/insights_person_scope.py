"""Kto stoi w tabelach i rankingach osób w Insights (decyzja Artura 24.09.2026).

Konta administracyjne są poza rankingami osób — tak jak w Hall of Fame. Ta sama
reguła ról (`competitions.HALL_OF_FAME_ROLES` + `_HOF_ROLE_PREDICATE`): w tabeli
jest konto z którąkolwiek rolą rekrutacyjną (sourcer, TAC, rekruter, Delivery
Lead, Head of Recruitment). Admin, Finanse i inne konta bez takiej roli
lądują w jednym wierszu „konta administracyjne i spoza rekrutacji".

Powód: na produkcji konto administracyjne miało 32 z 77 placementów Q3 (42%)
w „Analizie placementów" — jako jedna „osoba" na czele rankingu, choć to
domykanie pipeline'u, nie praca rekrutera. Hall of Fame wykluczał je od
09.2026, reszta ekranów nie.

Sumy firmy się NIE zmieniają: dorobek kont spoza zakresu jest osobnym
wierszem, a nie znika. Ta reguła dotyczy wyłącznie tabel osób w Insights —
wyścigi wypłacające nagrody mają własną listę ról i jej tu nie ruszamy.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.competitions import _HOF_ROLE_PREDICATE, HALL_OF_FAME_ROLES

# Etykieta zbiorczego wiersza — jedna dla wszystkich tabel osób.
OUTSIDE_SCOPE_LABEL = "Konta administracyjne i spoza rekrutacji"


async def outside_scope_user_ids(
    db: AsyncSession, user_ids: Iterable[int | None]
) -> set[int]:
    """Istniejące konta z ``user_ids`` BEZ roli rekrutacyjnej (reguła Hall of Fame).

    Konto, którego już nie ma w ``users``, NIE trafia do zbioru — jego dorobek
    zostaje tam, gdzie był (wiersz „Nieznany użytkownik”), bo nie wiemy, czy
    było administracyjne.
    """
    ids = sorted({int(uid) for uid in user_ids if uid is not None})
    if not ids:
        return set()
    rows = await db.execute(
        text(
            f"""
            SELECT u.id
            FROM users u
            WHERE u.id = ANY(:ids)
              AND NOT COALESCE({_HOF_ROLE_PREDICATE}, FALSE)
            """
        ),
        {"ids": ids, "roles": list(HALL_OF_FAME_ROLES)},
    )
    return {int(r[0]) for r in rows.all()}


__all__ = ["OUTSIDE_SCOPE_LABEL", "outside_scope_user_ids"]
