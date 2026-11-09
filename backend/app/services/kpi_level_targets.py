"""Poziom rekrutera a osobisty cel placementów (decyzja Artura 09.11.2026).

Cel placementów zależy od poziomu: junior 1, senior 2, ekspert 3. Poziom liczy
Ścieżka rozwoju, a cel żyje we wpisach osobowych. Ten moduł je łączy, w obie strony:

* **Awans podnosi cel od następnego miesiąca.** Poziom liczymy na koniec
  poprzedniego miesiąca, więc awans z bieżącego czeka do pierwszego dnia
  kolejnego. Cel tylko rośnie: wyższy wpis ręczny zostaje, a wpis 0 to świadome
  wyłączenie celu i automat go nie rusza.
* **Cel pokazuje poziom.** Kto ma cel seniora albo eksperta, a nie ma jeszcze
  placementów, bo tak go przyjęliśmy, na ekranie Ścieżki ma ten poziom.

Premia 200% czyta cel bieżący także za miesiąc miniony, a wynik zapisuje dopiero
po jego końcu. Dlatego automat czeka, aż wynik miesiąca z programu będzie
zapisany: inaczej awans z listopada podniósłby próg premii za listopad.
"""

import logging
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.kpi_target import UserKpiTarget
from app.services import kpi_target_editor as editor
from app.services.hr import bonus_rules, double_bonus
from app.services.hr.bonus_rules import DoubleBonusRule
from app.services.insights_seniority import (
    LEVEL_EXPERT,
    LEVEL_JUNIOR,
    LEVEL_PLACEMENT_TARGETS,
    LEVEL_SENIOR,
    compute_seniority,
    load_thresholds,
)

logger = logging.getLogger(__name__)

PLACEMENTS_KPI_ID = "monthly_placements"
# Alias sortuje się za nazwą kanoniczną, więc przy dwóch wierszach wygrywa ona.
_PLACEMENTS_KPI_IDS = (PLACEMENTS_KPI_ID, "placements_monthly")
AUTOMATION_ACTOR_NAME = "Automat: Ścieżka rozwoju"


def level_floor_for_target(target: Optional[int]) -> Optional[str]:
    """Poziom wynikający z osobistego celu; ``None``, gdy cel go nie wyznacza."""
    if target is None:
        return None
    if target >= LEVEL_PLACEMENT_TARGETS[LEVEL_EXPERT]:
        return LEVEL_EXPERT
    if target >= LEVEL_PLACEMENT_TARGETS[LEVEL_SENIOR]:
        return LEVEL_SENIOR
    return None


def promotion_cutoff(today: date) -> date:
    """Ostatni dzień poprzedniego miesiąca: awans po tej dacie jeszcze czeka."""
    return today.replace(day=1) - timedelta(days=1)


def planned_raises(
    levels: Mapping[int, str], overrides: Mapping[int, int]
) -> dict[int, int]:
    """Kto ma dostać wyższy cel: ``{user_id: nowy cel}``."""
    junior_target = LEVEL_PLACEMENT_TARGETS[LEVEL_JUNIOR]
    raises: dict[int, int] = {}
    for user_id, level in levels.items():
        current = overrides.get(user_id, junior_target)
        if current == 0:
            continue
        wanted = LEVEL_PLACEMENT_TARGETS[level]
        if wanted > current:
            raises[user_id] = wanted
    return raises


def double_bonus_pending(
    rule: Optional[DoubleBonusRule], stored: Mapping[str, Any], cutoff: date
) -> Optional[str]:
    """Miesiąc programu 200%, którego wynik nie jest jeszcze zapisany."""
    month = (cutoff.year, cutoff.month)
    if rule is None or month not in rule.months:
        return None
    key = double_bonus.month_key(month)
    return None if key in stored else key


async def _placement_overrides(db: AsyncSession) -> dict[int, int]:
    rows = (
        await db.execute(
            select(UserKpiTarget.user_id, UserKpiTarget.target_value)
            .where(UserKpiTarget.kpi_id.in_(_PLACEMENTS_KPI_IDS))
            .order_by(UserKpiTarget.kpi_id)
        )
    ).all()
    overrides: dict[int, int] = {}
    for row in rows:
        overrides.setdefault(int(row.user_id), int(row.target_value))
    return overrides


async def target_level_floors(db: AsyncSession) -> dict[int, str]:
    """Poziom z osobistego celu dla każdej osoby, której cel go wyznacza."""
    overrides = await _placement_overrides(db)
    floors = {uid: level_floor_for_target(t) for uid, t in overrides.items()}
    return {uid: floor for uid, floor in floors.items() if floor is not None}


async def apply_level_targets(
    db: AsyncSession, *, today: Optional[date] = None
) -> dict[str, Any]:
    """Podnosi cele po awansach zamkniętych poprzednim miesiącem. Sam commituje."""
    cutoff = promotion_cutoff(today or business_today())
    rules = await bonus_rules.load_rules(db)
    pending = double_bonus_pending(
        rules.double_bonus, await double_bonus.stored_results(db), cutoff
    )
    if pending is not None:
        return {"raised": 0, "waiting_for_double_bonus": pending}

    computed = await compute_seniority(
        db, as_of=cutoff, thresholds=await load_thresholds(db)
    )
    raises = planned_raises(
        {row.user_id: row.level for row in computed.rows},
        await _placement_overrides(db),
    )
    for user_id, target in raises.items():
        await editor.set_user_target(
            db,
            user_id=user_id,
            kpi_id=PLACEMENTS_KPI_ID,
            target_value=target,
            actor=None,
            actor_name=AUTOMATION_ACTOR_NAME,
        )
    await db.commit()
    if raises:
        await editor.invalidate_target_caches()
    return {"raised": len(raises), "cutoff": cutoff.isoformat()}
