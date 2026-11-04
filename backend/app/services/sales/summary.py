"""Podsumowanie lejka sprzedaży: otwarte szanse, wartość ważona, MRR, zaniedbane.

Definicje jak w pulpicie sprzedaży Atlasa (``src/services/sales_dashboard_service.py``):
wartość = ``value`` (MRR + jednorazowa, tak jak zapisuje ją cykl życia),
ważona = wartość × prawdopodobieństwo / 100, szansa „bez ruchu” = ostatni
dotyk starszy niż 14 dni. Ostatni dotyk to późniejsza z dat: najnowsza
aktywność szansy (``occurred_at``, a bez niej ``created_at``) i
``last_activity_at``; bez żadnej z nich — ``updated_at``.

Okres liczymy w kalendarzu firmy (``business_today``), po
``expected_close_date`` w przedziale [początek, koniec).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import (
    SalesActivity,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
)
from app.models.user import User

STALE_DAYS = 14
Period = Literal["all", "quarter", "next_quarter"]
_CENT = Decimal("0.01")


def _add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    return date(day.year + index // 12, index % 12 + 1, 1)


def period_range(period: Period, today: date) -> tuple[Optional[date], Optional[date]]:
    """[początek, koniec) kwartału bieżącego albo następnego; ``all`` bez granic."""

    quarter_start = date(today.year, (today.month - 1) // 3 * 3 + 1, 1)
    if period == "quarter":
        return quarter_start, _add_months(quarter_start, 3)
    if period == "next_quarter":
        start = _add_months(quarter_start, 3)
        return start, _add_months(start, 3)
    return None, None


@dataclass
class OwnerTotals:
    owner_id: Optional[int]
    owner_name: Optional[str]
    open: int = 0
    value: Decimal = Decimal(0)
    weighted: Decimal = Decimal(0)
    mrr: Decimal = Decimal(0)
    stale: int = 0
    no_close: int = 0


@dataclass
class StageTotals:
    stage_id: int
    name: str
    position: int
    count: int = 0
    value: Decimal = Decimal(0)


@dataclass
class Summary:
    pipeline_id: int
    pipeline_name: str
    open_count: int = 0
    value: Decimal = Decimal(0)
    weighted: Decimal = Decimal(0)
    mrr: Decimal = Decimal(0)
    stale_count: int = 0
    by_owner: list[OwnerTotals] = field(default_factory=list)
    by_stage: list[StageTotals] = field(default_factory=list)


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENT)


async def build_summary(
    db: AsyncSession,
    pipeline: SalesPipeline,
    *,
    period: Period,
    today: date,
    now: datetime,
) -> Summary:
    last_activity = (
        select(
            SalesActivity.opportunity_id.label("opportunity_id"),
            func.max(
                func.coalesce(SalesActivity.occurred_at, SalesActivity.created_at)
            ).label("touched_at"),
        )
        .where(SalesActivity.opportunity_id.is_not(None))
        .group_by(SalesActivity.opportunity_id)
        .subquery()
    )
    last_touch = func.coalesce(
        func.greatest(last_activity.c.touched_at, SalesOpportunity.last_activity_at),
        SalesOpportunity.updated_at,
    )
    rows = (
        await db.execute(
            select(
                SalesOpportunity.owner_user_id,
                User.name,
                SalesOpportunity.stage_id,
                SalesOpportunity.value,
                SalesOpportunity.mrr_value,
                SalesOpportunity.probability,
                SalesOpportunity.expected_close_date,
                last_touch.label("last_touch"),
            )
            .outerjoin(
                last_activity, last_activity.c.opportunity_id == SalesOpportunity.id
            )
            .outerjoin(User, User.id == SalesOpportunity.owner_user_id)
            .where(
                SalesOpportunity.pipeline_id == pipeline.id,
                SalesOpportunity.status == "open",
                SalesOpportunity.archived_at.is_(None),
            )
        )
    ).all()
    stages = (
        await db.execute(
            select(SalesPipelineStage)
            .where(
                SalesPipelineStage.pipeline_id == pipeline.id,
                SalesPipelineStage.outcome == "open",
            )
            .order_by(SalesPipelineStage.position, SalesPipelineStage.id)
        )
    ).scalars()
    by_stage = {
        stage.id: StageTotals(stage.id, stage.name, stage.position) for stage in stages
    }

    start, end = period_range(period, today)
    stale_before = now - timedelta(days=STALE_DAYS)
    summary = Summary(pipeline_id=pipeline.id, pipeline_name=pipeline.name)
    owners: dict[Optional[int], OwnerTotals] = {}

    def owner_row(owner_id: Optional[int], name: Optional[str]) -> OwnerTotals:
        return owners.setdefault(owner_id, OwnerTotals(owner_id, name))

    weighted_by_owner: dict[Optional[int], Decimal] = defaultdict(Decimal)
    for row in rows:
        close = row.expected_close_date
        if close is None:
            # Higiena lejka: brak daty zamknięcia liczymy w każdym okresie.
            owner_row(row.owner_user_id, row.name).no_close += 1
        if start is not None and (close is None or not start <= close < end):
            continue
        value = Decimal(row.value or 0)
        weighted = value * row.probability / 100
        mrr = Decimal(row.mrr_value or 0)
        stale = row.last_touch is None or row.last_touch < stale_before

        owner = owner_row(row.owner_user_id, row.name)
        owner.open += 1
        owner.value += value
        weighted_by_owner[row.owner_user_id] += weighted
        owner.mrr += mrr
        owner.stale += int(stale)

        summary.open_count += 1
        summary.value += value
        summary.weighted += weighted
        summary.mrr += mrr
        summary.stale_count += int(stale)

        stage = by_stage.get(row.stage_id)
        if stage is not None:
            stage.count += 1
            stage.value += value

    for owner_id, owner in owners.items():
        owner.value = _q(owner.value)
        owner.weighted = _q(weighted_by_owner[owner_id])
        owner.mrr = _q(owner.mrr)
    summary.value = _q(summary.value)
    summary.weighted = _q(summary.weighted)
    summary.mrr = _q(summary.mrr)
    summary.by_owner = sorted(
        owners.values(),
        key=lambda o: (-o.value, -o.open, o.owner_id is None, o.owner_name or ""),
    )
    summary.by_stage = [
        StageTotals(s.stage_id, s.name, s.position, s.count, _q(s.value))
        for s in by_stage.values()
    ]
    return summary
