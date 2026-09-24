"""Kto stoi w tabelach i rankingach osób w Insights (decyzja Artura 24.09.2026).

Konta administracyjne są poza rankingami osób — jak w Hall of Fame. Reguła ról
to `competitions.HALL_OF_FAME_ROLES` (sourcer, TAC, rekruter, Delivery Lead,
Head of Recruitment) plus Talent Community Manager: TCM rekomenduje i domyka
placementy jak rekruter, a decyzja Artura dotyczyła wyłącznie kont admina.
Admin, Finanse i inne konta bez takiej roli lądują w jednym wierszu
„Konta administracyjne".

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

# Role, z którymi konto stoi w tabelach osób (Hall of Fame + TCM).
PEOPLE_TABLE_ROLES: tuple[str, ...] = (
    *HALL_OF_FAME_ROLES,
    "talent_community_manager",
)

# Etykieta zbiorczego wiersza — jedna dla wszystkich tabel osób.
OUTSIDE_SCOPE_LABEL = "Konta administracyjne"


async def outside_scope_user_ids(
    db: AsyncSession, user_ids: Iterable[int | None]
) -> set[int]:
    """Istniejące konta z ``user_ids`` bez żadnej z ``PEOPLE_TABLE_ROLES``.

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
        {"ids": ids, "roles": list(PEOPLE_TABLE_ROLES)},
    )
    return {int(r[0]) for r in rows.all()}


__all__ = ["OUTSIDE_SCOPE_LABEL", "PEOPLE_TABLE_ROLES", "outside_scope_user_ids"]
