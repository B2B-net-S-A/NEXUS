"""Insights → Zespół: ludzie, „Do uwagi” i rekrutacje bez ruchu (24.09.2026).

Trzy trasy widoku Zespół. Wszystkie za capability ``VIEW_TEAM_KPI`` (HoR,
Delivery Lead, TCM, Finanse, admin) — to imienne wyniki cudzej pracy, ta sama
bramka co ``/api/kpis/team/panel`` od 22.09.2026. Bez kwot.
"""

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.capabilities import AnalyticsCapability, require_capability
from app.analytics.periods import PeriodError, resolve_period
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.cache import cache_get, cache_set, cache_single_flight
from app.core.database import get_db
from app.core.scheduling import business_today, local_now
from app.models.user import User, UserRole
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)
from app.services.insights_person_scope import outside_scope_user_ids
from app.services.insights_team_signals import (
    LOW_PRECISION_PCT,
    STALE_JOB_DAYS,
    current_team_panel,
    people_payload,
    stale_jobs,
    team_people,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

CACHE_TTL_SECONDS = 300

TeamViewer = Annotated[
    User, Depends(require_capability(AnalyticsCapability.VIEW_TEAM_KPI))
]


def _resolve(kind: str, offset: int, anchor, date_from, date_to):
    try:
        return resolve_period(
            kind, offset=offset, anchor=anchor, date_from=date_from, date_to=date_to
        )
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/team/people")
async def insights_team_people(
    _: TeamViewer,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(week|month|quarter|year|custom)$"),
    offset: int = Query(0),
    anchor: date | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """Tabela „Ludzie”: lejek per osoba, weryfikacje na dzień roboczy,
    precyzja (30 dni) i placementy z tego samego odcinka poprzedniego okresu.

    Konta administracyjne (bez roli rekrutacyjnej — reguła Hall of Fame) są
    poza wierszami osób, jako jeden wiersz ``outside_scope``; ``totals`` to
    nadal suma całej firmy.
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)
    now = local_now()
    today = business_today()
    # v2 (24.09.2026): precyzja jako kohorta i konta administracyjne poza
    # tabelą — stary kształt z cache'u nie może przeżyć wdrożenia.
    cache_key = f"insights:team:people:v2:{resolved.cache_suffix}:{today}"
    async with cache_single_flight(cache_key, db=db):
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached
        people = await team_people(db, resolved, now=now, today=today)
        result = {"period": resolved.as_payload(), **people_payload(people)}
        await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
        return result


@router.get("/recruitment/stale-jobs")
async def insights_stale_jobs(
    _: TeamViewer,
    db: AsyncSession = Depends(get_db),
    days: int = Query(STALE_JOB_DAYS, ge=7, le=180),
):
    """Raport „Rekrutacje bez ruchu”: opublikowane, bez ruchu od ``days`` dni."""
    items = await stale_jobs(db, now=local_now(), days=days)
    return {"days": days, "items": items, "total": len(items)}


@router.get("/team/attention")
async def insights_team_attention(
    current_user: TeamViewer,
    db: AsyncSession = Depends(get_db),
):
    """„Do uwagi”: tylko sygnały ponad próg, każdy z odnośnikiem do raportu.

    Pusta lista = nic nie wymaga uwagi. Słabe prepy widzą wyłącznie admin i
    Head of Recruitment (raport ocenia pracę konkretnych osób).
    """
    today = business_today()
    items = list(await _attention_base(db, today=today))

    # Ta sama bramka co raport „Jakość prepów": rola lidera I sekcja Pipeline.
    if (
        current_user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)
        and section_access_for_user(current_user, ProductSection.pipeline)
        >= SectionAccess.read
    ):
        weak = await _weak_preps(db, current_user=current_user, today=today)
        if weak:
            items.append(
                {
                    "kind": "weak_preps",
                    "count": weak,
                    "label": "prepów ocenionych jako słabe w ostatnich 7 dniach",
                    "report": "prepy",
                }
            )

    return {"items": items}


async def _attention_base(db: AsyncSession, *, today: date) -> list[dict]:
    """Sygnały wspólne dla wszystkich liderów: rekrutacje bez ruchu i precyzja.

    Cache 5 min z jednym wykonawcą (`cache_single_flight`). Do 24.09.2026
    każde wejście lidera na Zespół liczyło od zera dwa pełne przebiegi
    atrybucji (5,2 s na produkcji), w tym poprzedni okres, którego ta
    odpowiedź nie czyta — teraz liczymy tylko bieżący miesiąc. Wynik nie
    zależy od osoby, więc klucz jest jeden na dzień.
    """
    cache_key = f"insights:team:attention:base:v2:{today}"
    async with cache_single_flight(cache_key, db=db):
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached
        now = local_now()
        items: list[dict] = []

        stale = await stale_jobs(db, now=now)
        if stale:
            items.append(
                {
                    "kind": "stale_jobs",
                    "count": len(stale),
                    "label": f"rekrutacji bez żadnego ruchu od {STALE_JOB_DAYS} dni",
                    "report": "bez-ruchu",
                }
            )

        month = _resolve("month", 0, None, None, None)
        panel = await current_team_panel(db, month, now=now)
        # Konta administracyjne nie stoją w tabeli osób, więc „Zobacz w tabeli”
        # nie może na nie wskazywać.
        outside = await outside_scope_user_ids(db, [r.user_id for r in panel.rows])
        low = [
            r
            for r in panel.rows
            if r.is_active
            and r.user_id not in outside
            and r.precision_pct is not None
            and r.precision_pct < LOW_PRECISION_PCT
        ]
        if low:
            items.append(
                {
                    "kind": "low_precision",
                    "count": len(low),
                    "label": (
                        f"osób z precyzją rekomendacji poniżej {LOW_PRECISION_PCT:g}% "
                        "(30 dni)"
                    ),
                    "user_ids": [r.user_id for r in low],
                    "report": None,
                }
            )
        await cache_set(cache_key, items, ttl_seconds=CACHE_TTL_SECONDS)
        return items


async def _weak_preps(db: AsyncSession, *, current_user: User, today: date) -> int:
    """Słabe prepy z 7 dni — raport organizacyjny, ten sam dla każdego lidera."""
    cache_key = f"insights:team:attention:preps:v1:{today}"
    async with cache_single_flight(cache_key, db=db):
        cached = await cache_get(cache_key)
        if cached is not None:
            return int(cached)
        # Import leniwy: moduł prepów ciągnie za sobą kalendarz i Teams.
        from app.api.prep_meetings import prep_quality_report

        try:
            preps = await prep_quality_report(current_user=current_user, days=7, db=db)
        except HTTPException:
            return 0
        weak = sum(row.weak for row in preps.rows)
        await cache_set(cache_key, weak, ttl_seconds=CACHE_TTL_SECONDS)
        return weak
