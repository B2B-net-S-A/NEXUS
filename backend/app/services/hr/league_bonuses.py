"""Premie z Ligi — propozycje z rozstrzygniętych rywalizacji NEXUSA.

Źródło: ``competition_winners`` (``prize_pln`` > 0) okresów zamkniętych
w ``competition_period_closures`` jako ``frozen`` albo ``tie_resolved``
(remis czekający na decyzję admina nie ma jeszcze wierszy podium). Domyślnie
tylko kwartalna Liga (5000 / 3000 / 2000 zł); wyścig miesięczny daje voucher,
nie przelew (rodzaje rywalizacji to ustawienie ``league_types``).

Propozycja trafia do miesiąca po końcu okresu (Q3 → październik; zamknięty
miesiąc → pierwszy otwarty), status ``proposed`` — zatwierdzają Płace.
Klucz ``league:{rodzaj}:{okres}:{osoba}`` czyni przebieg idempotentnym;
w Compassie Ligę wpisywano ręcznie (0 wpisów przez pięć miesięcy).
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competition_period_closure import (
    CLOSURE_FROZEN,
    CLOSURE_TIE_RESOLVED,
    CompetitionPeriodClosure,
)
from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.models.hr_payroll import HrBonus
from app.services.hr.bonus_rules import BonusRules, load_rules
from app.services.hr.payroll_periods import (
    add_months,
    first_open_month_locked,
    month_end,
)

logger = logging.getLogger(__name__)

SOURCE = "league"
_QUARTER = re.compile(r"^Q([1-4]) (\d{4})$")
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")

TYPE_LABELS: dict[str, str] = {
    CompetitionType.quarterly_champions_dl.value: "Liga Mistrzów DL",
    CompetitionType.quarterly_champions_recruiter.value: "Liga Mistrzów rekruterów",
    CompetitionType.monthly_recommendations.value: "Wyścig rekomendacji",
    CompetitionType.monthly_placements.value: "Wyścig placementów",
}


def period_end(period: str) -> Optional[date]:
    """Ostatni dzień okresu rywalizacji („Q3 2026” albo „2026-09”)."""

    quarter = _QUARTER.match(period)
    if quarter:
        q, year = int(quarter.group(1)), int(quarter.group(2))
        return month_end(year, q * 3)
    monthly = _MONTH.match(period)
    if monthly:
        year, month = int(monthly.group(1)), int(monthly.group(2))
        if 1 <= month <= 12:
            return month_end(year, month)
    return None


def source_key(competition_type: str, period: str, user_id: int) -> str:
    return f"league:{competition_type}:{period}:{user_id}"


async def sync_league(
    db: AsyncSession, *, today: date, rules: Optional[BonusRules] = None
) -> dict[str, int]:
    rules = rules or await load_rules(db)
    counts = {"created": 0, "existing": 0, "skipped_period": 0}
    if not rules.league_types:
        return counts
    floor = rules.automation_since or (today - timedelta(days=rules.lookback_days))
    closures = list(
        await db.execute(
            select(
                CompetitionPeriodClosure.competition_type,
                CompetitionPeriodClosure.period,
            )
            .where(
                CompetitionPeriodClosure.status.in_(
                    [CLOSURE_FROZEN, CLOSURE_TIE_RESOLVED]
                ),
                CompetitionPeriodClosure.competition_type.in_(list(rules.league_types)),
            )
            .order_by(CompetitionPeriodClosure.id)
        )
    )
    for competition_type, period in closures:
        end = period_end(period)
        if end is None or end < floor or end >= today:
            counts["skipped_period"] += 1
            continue
        winners = list(
            await db.scalars(
                select(CompetitionWinner)
                .where(
                    CompetitionWinner.competition_type == competition_type,
                    CompetitionWinner.period == period,
                    CompetitionWinner.prize_pln > 0,
                )
                .order_by(CompetitionWinner.rank)
            )
        )
        if not winners:
            continue
        keys = [source_key(competition_type, period, w.user_id) for w in winners]
        present = set(
            await db.scalars(
                select(HrBonus.source_key).where(HrBonus.source_key.in_(keys))
            )
        )
        # Miesiąc pod blokadą współdzieloną — trwające zamknięcie nie dostanie
        # propozycji po sprawdzeniu „wszystkie mają decyzję”.
        target = await first_open_month_locked(db, *add_months(end.year, end.month, 1))
        for winner, key in zip(winners, keys):
            if key in present:
                counts["existing"] += 1
                continue
            snapshot: dict[str, Any] = {
                "rule": "league",
                "competition_type": competition_type,
                "period": period,
                "rank": winner.rank,
                "points": winner.points,
                "prize_pln": winner.prize_pln,
            }
            label = TYPE_LABELS.get(competition_type, "Liga")
            db.add(
                HrBonus(
                    recipient_user_id=winner.user_id,
                    proposed_by=None,
                    amount=Decimal(winner.prize_pln),
                    currency="PLN",
                    category="league",
                    period_year=target[0],
                    period_month=target[1],
                    status="proposed",
                    source=SOURCE,
                    source_key=key,
                    rule_snapshot=snapshot,
                    description=f"{label} — {period}, {winner.rank}. miejsce",
                )
            )
            counts["created"] += 1
    await db.flush()
    return counts


__all__ = ["period_end", "source_key", "sync_league"]
