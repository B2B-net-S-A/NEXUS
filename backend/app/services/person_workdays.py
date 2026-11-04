"""Dni pracy osoby — mianownik statystyk „na dzień” i skala celów (28.10.2026).

Decyzja Artura z 28.10.2026: staty liczą się tylko z dni, które osoba
faktycznie mogła przepracować. Urlop, przerwa w świadczeniu usług albo inna
zatwierdzona nieobecność nie może dawać gorszego wyniku. Jedna reguła dla
wszystkich ekranów: plakietka i próg Wyścigu Rekomendacji, „Weryf. / dzień”
w Insights → Zespół, tempo i cele „Moich KPI” oraz cele zespołu.

* **Dzień roboczy** — Pon–Pt bez polskich świąt (ta sama definicja co próg
  wyścigu i ``workdays_between``).
* **Dzień pracy** — dzień roboczy minus zatwierdzona nieobecność z
  ``leave_request_days`` (pół dnia = 0,5). Nieobecność w weekend albo w
  święto niczego nie odejmuje.
* **Cel** skaluje się udziałem dni pracy w dniach roboczych okresu, w górę do
  pełnej sztuki: cel 4 przy 15 z 20 dni to 3.

Nieobecności liczą się tylko przy urlopach NEXUSA
(``hr_availability_source = local``); przy innym źródle osoba ma pełne dni
roboczych, tak jak przed tą zmianą. Rodzaj nieobecności nigdy tu nie wchodzi.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import _polish_holidays


def business_days(start: date, end: date) -> list[date]:
    """Dni robocze (Pon–Pt bez polskich świąt) w przedziale domkniętym."""
    days: list[date] = []
    day = start
    while day <= end:
        if day.weekday() < 5 and day not in _polish_holidays(day.year):
            days.append(day)
        day += timedelta(days=1)
    return days


def worked_days(business: Sequence[date], absence: Mapping[date, float]) -> float:
    """Dni robocze minus nieobecność na nich (dzień najwyżej 1, nigdy poniżej 0)."""
    absent = sum(min(1.0, absence.get(day, 0.0)) for day in business)
    return max(0.0, round(len(business) - absent, 1))


def prorated_target(target: int, business: int, worked: float) -> int:
    """Cel okresu w proporcji do dni pracy, w górę do pełnej sztuki.

    Bez dni roboczych w okresie (sam weekend) cel zostaje bez zmian — nie ma
    z czego liczyć proporcji. Cały okres nieobecności = cel 0.
    """
    if target <= 0 or business <= 0 or worked >= business:
        return target
    # Zaokrąglenie do 6 miejsc zanim ceil: 4 × 15/20 = 3.0000000000000004.
    return math.ceil(round(target * worked / business, 6))


def target_for_window(
    target: int, start: date, end: date, absence: Mapping[date, float]
) -> int:
    """Cel okresu ``[start, end]`` przeliczony na dni pracy przy tej nieobecności."""
    business = business_days(start, end)
    return prorated_target(target, len(business), worked_days(business, absence))


async def nexus_absences_known(db: AsyncSession) -> bool:
    """Czy nieobecności liczą się z urlopów NEXUSA.

    Stan przełącznika z pamięci procesu, jak w ``kpi_engine.personal_days_off``
    — odświeżają go pętle dostępności i dni roboczych.
    """
    from app.services.hr.availability_local import local_source_active

    return local_source_active()


async def absence_by_user(
    db: AsyncSession, user_ids: Iterable[int], start: date, end: date
) -> dict[int, dict[date, float]]:
    """Zatwierdzona nieobecność w oknie: ``{user_id: {dzień: ułamek}}``."""
    ids = sorted({int(uid) for uid in user_ids})
    if not ids or not await nexus_absences_known(db):
        return {}
    rows = (
        await db.execute(
            text(
                """
                SELECT d.user_id, d.day, d.fraction
                FROM leave_request_days d
                JOIN leave_requests r ON r.id = d.leave_request_id
                WHERE r.status = 'approved' AND d.active
                  AND d.user_id = ANY(:ids)
                  AND d.day BETWEEN :start AND :end
                """
            ),
            {"ids": ids, "start": start, "end": end},
        )
    ).all()
    out: dict[int, dict[date, float]] = {}
    for row in rows:
        per_day = out.setdefault(int(row.user_id), {})
        per_day[row.day] = per_day.get(row.day, 0.0) + float(row.fraction)
    return out


async def workdays_by_user(
    db: AsyncSession, user_ids: Iterable[int], start: date, end: date
) -> dict[int, float]:
    """Dni pracy każdej osoby w ``[start, end]`` — wpis dla każdego id."""
    ids = sorted({int(uid) for uid in user_ids})
    business = business_days(start, end)
    absence = await absence_by_user(db, ids, start, end)
    return {uid: worked_days(business, absence.get(uid, {})) for uid in ids}


async def prorated_targets(
    db: AsyncSession,
    targets: Mapping[int, int],
    start: date,
    end: date,
) -> dict[int, int]:
    """Cele osób na okres ``[start, end]`` przeliczone na ich dni pracy."""
    absence = await absence_by_user(db, targets.keys(), start, end)
    return {
        uid: target_for_window(int(target), start, end, absence.get(uid, {}))
        for uid, target in targets.items()
    }
