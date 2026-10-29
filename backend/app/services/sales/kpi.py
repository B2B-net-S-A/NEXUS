"""KPI tygodniowe handlowców i krzywa WON MRR względem celu firmy (0620).

Definicje 1:1 z Atlasa (``src/services/team_kpi.py``,
``sales_dashboard_service.py``, ``api/routes/team_finance.py``), poza
„Ofertami”, których NEXUS nie ma (decyzja Artura 28.10.2026):

* **Spotkania** — aktywności ``meeting`` przy szansach (w tym transkrypcje
  Fireflies z importu), przypisane opiekunowi szansy, z czasem
  ``COALESCE(occurred_at, due_at)``, bez szans zarchiwizowanych; plus
  wydarzenia z kalendarza Outlooka (``external_source='msgraph-event'``)
  przypisane osobie, której skrzynka je zsynchronizowała, bez odwołanych
  („Canceled:” / „Anulowano:”). To samo spotkanie bywa w kilku źródłach
  z czasem różnym o kilka minut, więc w obrębie osoby i tygodnia znaczniki
  odległe od poprzedniego o ≤ 15 min liczą się raz.
* **Leady** — szanse z ``qualified_at`` w tygodniu, wg obecnego opiekuna.
* **Oferty (etap)** — wejścia szansy na etap ``offer-sent`` z historii zmian
  szansy (``sales_opportunity_events``, ``field='stage_id'``; założenie
  i ruch po etapach, historia od wdrożenia 0618), wg obecnego opiekuna; kilka
  szans tej samej firmy w tygodniu liczy się raz — jak Atlas liczył oferty
  per firma.
* **Światła** — zielone ≥ cel, żółte ≥ 50% celu, czerwone poniżej. Bez celu
  (0 albo brak wiersza) światła nie ma — w Atlasie było wtedy zielone.
* **WON MRR** — wygrane szanse bez body leasingu (``service_line`` albo tag
  „Body leasing”), netto = MRR × marża / 100, narastająco po miesiącu wygranej.
  Postęp celu marży osoby to ta sama suma dla jej szans, bez okresu.

Tygodnie (ISO, od poniedziałku) i miesiące liczymy w kalendarzu firmy.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date, local_day_start_utc
from app.models.sales import (
    SalesActivity,
    SalesOpportunity,
    SalesOpportunityEvent,
    SalesPipelineStage,
    SalesTarget,
)
from app.models.user import User

MEETING_DEDUP_WINDOW = timedelta(minutes=15)
OFFER_STAGE_KEY = "offer-sent"
STAGE_FIELD = "stage_id"
CALENDAR_SOURCE = "msgraph-event"
CANCELLED_PREFIXES = ("Canceled:", "Anulowano:")
BODY_LEASING = "bodyleasing"
METRICS = ("meetings", "qualified", "offers_stage")
_CENT = Decimal("0.01")

Light = Literal["green", "yellow", "red"]


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def recent_weeks(today: date, count: int) -> list[date]:
    """Poniedziałki ``count`` ostatnich tygodni, od najstarszego; bieżący na końcu."""

    current = week_start(today)
    return [current - timedelta(weeks=offset) for offset in range(count - 1, -1, -1)]


def dedup_count(
    times: Iterable[datetime], window: timedelta = MEETING_DEDUP_WINDOW
) -> int:
    """Liczba spotkań po sklejeniu znaczników odległych od poprzedniego o ≤ ``window``."""

    ordered = sorted(times)
    if not ordered:
        return 0
    clusters = 1
    for previous, current in zip(ordered, ordered[1:]):
        if current - previous > window:
            clusters += 1
    return clusters


def light(actual: int, target: int) -> Optional[Light]:
    if target <= 0:
        return None
    if actual >= target:
        return "green"
    if actual * 2 >= target:
        return "yellow"
    return "red"


def _cell(actual: int, target: int) -> Cell:
    return Cell(actual, target, light(actual, target))


def is_body_leasing(service_line: Optional[str], tags: Optional[list]) -> bool:
    if (service_line or "").strip().lower() == BODY_LEASING:
        return True
    return any(
        isinstance(tag, str) and tag.strip().lower() == "body leasing"
        for tag in tags or ()
    )


def net_mrr(mrr_value: Optional[Decimal], margin_pct: Optional[Decimal]) -> Decimal:
    return Decimal(mrr_value or 0) * Decimal(margin_pct or 0) / 100


@dataclass(frozen=True)
class Cell:
    actual: int
    target: int
    light: Optional[Light]


@dataclass
class PersonKpi:
    user_id: int
    name: str
    team: Optional[str]
    has_targets: bool
    targets: dict[str, int]
    weeks: list[dict[str, Cell]]
    margin_goal_amount: Optional[Decimal]
    margin_goal_deadline: Optional[date]
    margin_actual: Decimal


@dataclass(frozen=True)
class MonthPoint:
    month: date
    net_mrr: Decimal
    cum_net_mrr: Decimal


@dataclass
class CompanyKpi:
    net_mrr_goal: Optional[Decimal]
    goal_deadline: Optional[date]
    won_net_mrr: Decimal
    missing_margin: int
    months: list[MonthPoint] = field(default_factory=list)


@dataclass
class Kpi:
    weeks: list[date]
    people: list[PersonKpi]
    company: CompanyKpi
    offers_history_since: Optional[date]


def _bucket(
    rows: Iterable[tuple[Optional[int], Optional[datetime]]], mondays: set[date]
) -> dict[tuple[int, date], list[datetime]]:
    out: dict[tuple[int, date], list[datetime]] = defaultdict(list)
    for owner, moment in rows:
        if owner is None or moment is None:
            continue
        monday = week_start(business_date(moment))
        if monday in mondays:
            out[(owner, monday)].append(moment)
    return out


async def _meetings(
    db: AsyncSession, start: datetime, end: datetime, mondays: set[date]
) -> dict[tuple[int, date], int]:
    at = func.coalesce(SalesActivity.occurred_at, SalesActivity.due_at)
    logged = (
        await db.execute(
            select(SalesOpportunity.owner_user_id, at)
            .join(SalesOpportunity, SalesOpportunity.id == SalesActivity.opportunity_id)
            .where(
                SalesActivity.kind == "meeting",
                SalesOpportunity.archived_at.is_(None),
                SalesOpportunity.owner_user_id.is_not(None),
                or_(
                    SalesActivity.external_source.is_(None),
                    SalesActivity.external_source != CALENDAR_SOURCE,
                ),
                at >= start,
                at < end,
            )
        )
    ).all()
    subject = func.coalesce(SalesActivity.subject, "")
    calendar = (
        await db.execute(
            select(SalesActivity.created_by_user_id, SalesActivity.occurred_at).where(
                SalesActivity.external_source == CALENDAR_SOURCE,
                SalesActivity.created_by_user_id.is_not(None),
                SalesActivity.occurred_at >= start,
                SalesActivity.occurred_at < end,
                *(subject.not_ilike(f"{prefix}%") for prefix in CANCELLED_PREFIXES),
            )
        )
    ).all()
    buckets = _bucket([*logged, *calendar], mondays)
    return {key: dedup_count(times) for key, times in buckets.items()}


async def _qualified(
    db: AsyncSession, start: datetime, end: datetime, mondays: set[date]
) -> dict[tuple[int, date], int]:
    rows = (
        await db.execute(
            select(SalesOpportunity.owner_user_id, SalesOpportunity.qualified_at).where(
                SalesOpportunity.owner_user_id.is_not(None),
                SalesOpportunity.qualified_at >= start,
                SalesOpportunity.qualified_at < end,
            )
        )
    ).all()
    return {key: len(times) for key, times in _bucket(rows, mondays).items()}


async def _offers_stage(
    db: AsyncSession, start: datetime, end: datetime, mondays: set[date]
) -> dict[tuple[int, date], int]:
    offer_stages = [
        str(stage_id)
        for stage_id in (
            await db.execute(
                select(SalesPipelineStage.id).where(
                    SalesPipelineStage.key == OFFER_STAGE_KEY
                )
            )
        ).scalars()
    ]
    if not offer_stages:
        return {}
    rows = (
        await db.execute(
            select(
                SalesOpportunity.owner_user_id,
                SalesOpportunityEvent.created_at,
                SalesOpportunity.company_id,
            )
            .join(
                SalesOpportunity,
                SalesOpportunity.id == SalesOpportunityEvent.opportunity_id,
            )
            .where(
                SalesOpportunityEvent.field == STAGE_FIELD,
                SalesOpportunityEvent.new_value.in_(offer_stages),
                SalesOpportunity.owner_user_id.is_not(None),
                SalesOpportunityEvent.created_at >= start,
                SalesOpportunityEvent.created_at < end,
            )
        )
    ).all()
    companies: dict[tuple[int, date], set[int]] = defaultdict(set)
    for owner, moved_at, company_id in rows:
        monday = week_start(business_date(moved_at))
        if monday in mondays:
            companies[(owner, monday)].add(company_id)
    return {key: len(ids) for key, ids in companies.items()}


async def _won(db: AsyncSession, today: date) -> tuple[CompanyKpi, dict[int, Decimal]]:
    rows = (
        await db.execute(
            select(
                SalesOpportunity.owner_user_id,
                SalesOpportunity.won_at,
                SalesOpportunity.mrr_value,
                SalesOpportunity.margin_pct,
                SalesOpportunity.service_line,
                SalesOpportunity.tags,
            ).where(
                SalesOpportunity.status == "won",
                SalesOpportunity.archived_at.is_(None),
            )
        )
    ).all()
    by_month: dict[date, Decimal] = defaultdict(Decimal)
    by_owner: dict[int, Decimal] = defaultdict(Decimal)
    total = Decimal(0)
    missing = 0
    for owner, won_at, mrr, margin, service_line, tags in rows:
        if is_body_leasing(service_line, tags) or not mrr or mrr <= 0:
            continue
        if margin is None:
            missing += 1
        net = net_mrr(mrr, margin)
        total += net
        if owner is not None:
            by_owner[owner] += net
        if won_at is not None:
            day = business_date(won_at)
            by_month[date(day.year, day.month, 1)] += net

    company = CompanyKpi(
        net_mrr_goal=None,
        goal_deadline=None,
        won_net_mrr=total.quantize(_CENT),
        missing_margin=missing,
    )
    if by_month:
        cursor = min(by_month)
        last = max(date(today.year, today.month, 1), max(by_month))
        cumulative = Decimal(0)
        while cursor <= last:
            month_net = by_month.get(cursor, Decimal(0))
            cumulative += month_net
            company.months.append(
                MonthPoint(
                    cursor, month_net.quantize(_CENT), cumulative.quantize(_CENT)
                )
            )
            index = cursor.month
            cursor = date(cursor.year + index // 12, index % 12 + 1, 1)
    return company, {owner: total.quantize(_CENT) for owner, total in by_owner.items()}


async def build_kpi(db: AsyncSession, *, today: date, weeks: int) -> Kpi:
    mondays = recent_weeks(today, weeks)
    monday_set = set(mondays)
    start = local_day_start_utc(mondays[0])
    end = local_day_start_utc(mondays[-1] + timedelta(weeks=1))

    actuals = {
        "meetings": await _meetings(db, start, end, monday_set),
        "qualified": await _qualified(db, start, end, monday_set),
        "offers_stage": await _offers_stage(db, start, end, monday_set),
    }
    company, margin_by_owner = await _won(db, today)

    targets = list((await db.execute(select(SalesTarget))).scalars())
    company_row = next((t for t in targets if t.user_id is None), None)
    if company_row is not None:
        company.net_mrr_goal = company_row.margin_goal_amount
        company.goal_deadline = company_row.margin_goal_deadline
    by_user = {t.user_id: t for t in targets if t.user_id is not None}

    with_activity = {owner for metric in actuals.values() for owner, _ in metric}
    user_ids = set(by_user) | with_activity
    users = (
        {
            u.id: u
            for u in (
                await db.execute(select(User).where(User.id.in_(user_ids)))
            ).scalars()
        }
        if user_ids
        else {}
    )

    people: list[PersonKpi] = []
    for user_id in user_ids:
        user = users.get(user_id)
        if user is None:
            continue
        row = by_user.get(user_id)
        # Nieaktywne konto bez wyników w oknie nie zajmuje wiersza.
        if not user.is_active and user_id not in with_activity:
            continue
        goal = {metric: getattr(row, metric) if row else 0 for metric in METRICS}
        people.append(
            PersonKpi(
                user_id=user_id,
                name=user.name,
                team=row.team if row else None,
                has_targets=row is not None,
                targets=goal,
                weeks=[
                    {
                        metric: _cell(
                            actuals[metric].get((user_id, monday), 0), goal[metric]
                        )
                        for metric in METRICS
                    }
                    for monday in mondays
                ],
                margin_goal_amount=row.margin_goal_amount if row else None,
                margin_goal_deadline=row.margin_goal_deadline if row else None,
                margin_actual=margin_by_owner.get(user_id, Decimal(0)),
            )
        )
    people.sort(key=lambda p: (p.team is None, p.team or "", not p.has_targets, p.name))

    first_event = (
        await db.execute(
            select(func.min(SalesOpportunityEvent.created_at)).where(
                SalesOpportunityEvent.field == STAGE_FIELD
            )
        )
    ).scalar()
    return Kpi(
        weeks=mondays,
        people=people,
        company=company,
        offers_history_since=business_date(first_event) if first_event else None,
    )
