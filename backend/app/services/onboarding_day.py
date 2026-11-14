"""Dzień onboardingu — pierwszy dzień nowej osoby poza normami (decyzja Artura 14.11.2026).

Nowa osoba pierwszego dnia przechodzi Poligon NEXUSA (``/poligon``), który
blokuje resztę ekranów, dopóki go nie skończy. Ten dzień nie może jej obniżać
statystyk: nie jest dniem pracy w mianowniku „na dzień”, w celach i tempie
KPI, w progu Wyścigu Rekomendacji ani w Porcji dnia. Weryfikacje
i rekomendacje zrobione mimo to tego dnia liczą się normalnie — to prawdziwa
praca, a zdjęcie jej z wyników tylko by osobie zaszkodziło.

* **Dzień onboardingu** = dzień (kalendarz firmy) pierwszego zaliczonego
  ćwiczenia poligonu (``novelty_progress`` z id ``poligon-…``), tylko u osoby,
  której poligon jest wymagany (``poligon.json``: rola i konto założone od
  ``required_since``). Obecni, którzy zajrzą na poligon z ciekawości, nie
  dostają przez to wolnego dnia w statystykach.
* Bez migracji: dzień wynika z istniejących wierszy postępu.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.data.novelties import PoligonPlan, load_poligon

POLIGON_ID_PREFIX = "poligon-"


def _role_values(user: Any) -> set[str]:
    try:
        return {getattr(r, "value", str(r)) for r in user.get_all_roles()}
    except Exception:  # noqa: BLE001 — rola główna wystarcza jako zapas
        return {getattr(user.role, "value", str(user.role))}


def _created_on(user: Any) -> date | None:
    created = getattr(user, "created_at", None)
    if created is None:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created.astimezone(ZoneInfo(DEFAULT_TZ)).date()


def poligon_required(user: Any, plan: PoligonPlan | None = None) -> bool:
    """Czy poligon blokuje tę osobę, dopóki go nie przejdzie."""
    plan = plan or load_poligon()
    created = _created_on(user)
    return (
        created is not None
        and created >= plan.required_since
        and bool(_role_values(user) & set(plan.required_roles))
    )


def poligon_open(user: Any, plan: PoligonPlan | None = None) -> bool:
    """Czy osoba może przechodzić poligon i zapisywać postęp."""
    return bool(_role_values(user) & set((plan or load_poligon()).roles))


async def onboarding_days(
    db: AsyncSession, user_ids: Iterable[int], start: date, end: date
) -> dict[int, date]:
    """Dzień onboardingu osób, o ile wypada w ``[start, end]``: ``{user_id: dzień}``."""
    ids = sorted({int(uid) for uid in user_ids})
    if not ids:
        return {}
    plan = load_poligon()
    rows = (
        await db.execute(
            text(
                """
                SELECT p.user_id, MIN(p.completed_at) AS first_done
                FROM novelty_progress p
                JOIN users u ON u.id = p.user_id
                WHERE p.novelty_id LIKE :prefix
                  AND p.completed_at IS NOT NULL
                  AND p.user_id = ANY(:ids)
                  AND (u.created_at AT TIME ZONE :tz)::date >= :since
                GROUP BY p.user_id
                """
            ),
            {
                "prefix": f"{POLIGON_ID_PREFIX}%",
                "ids": ids,
                "tz": DEFAULT_TZ,
                "since": plan.required_since,
            },
        )
    ).all()
    tz = ZoneInfo(DEFAULT_TZ)
    out: dict[int, date] = {}
    for row in rows:
        first: datetime = row.first_done
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        day = first.astimezone(tz).date()
        if start <= day <= end:
            out[int(row.user_id)] = day
    return out
