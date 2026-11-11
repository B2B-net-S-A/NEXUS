"""Sprzedaż → Dzwonienie → Skuteczność: co daje dzwonienie (decyzje Artura 11.11.2026).

Reguły: ``docs/claude/sprzedaz/dzwonienie-skutecznosc.md``. W skrócie:

* źródłem są telefony z dziennika (``sales_activities.kind = 'call'`` z wynikiem),
  także te z karty szansy. Telefon z kolejki ma ``external_source = 'call_queue'``
  i ``external_id = "<id rekordu>:<numer próby>"`` (para jest unikalna w obrębie firmy,
  jak wymaga ``ux_sales_activities_outlook``), więc da się go przypisać do kampanii
  i listy;
* „rozmowa” to telefon z wynikiem innym niż „Nie odebrał”;
* spotkanie „z terminem” ma termin w bloku przekazania albo spotkanie w dzienniku
  firmy od dnia założenia szansy; werdykt bierzemy z bloku przekazania (#3293);
* osoby są w tabeli z liczbami i sortowaniem (ranking jest decyzją Artura z
  11.11.2026); kolejka dalej nie ma rankingu ani celu dziennego;
* wnioski liczą reguły z progiem próby, nie model: przy kilkunastu rozmowach
  różnica procentów nic nie znaczy, więc zdanie się wtedy nie pojawia.

Zapytania tylko czytają. Agregacja jest w czystej funkcji ``summarize``.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import String, and_, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, is_business_day, local_day_start_utc
from app.models.sales import (
    SalesActivity,
    SalesCallCampaign,
    SalesCallRecord,
    SalesOpportunity,
)
from app.models.user import User
from app.services import sales_schema as schema
from app.services.sales import handoff_state
from app.services.sales.calling import CALL_SOURCE, MEETING_BOOKED, NEW
from app.services.sales.calls import DO_NOT_CONTACT
from app.services.sales.touch import not_cancelled

Period = Literal["week", "4w", "all"]

ZONE = ZoneInfo(DEFAULT_TZ)
NO_ANSWER = "no_answer"
OFFER_SENT = "offer_sent"
#: Godziny i dni mapy „Kiedy odbierają” (pon–pt, 8:00–17:59).
HOURS: tuple[int, ...] = tuple(range(8, 18))
WEEKDAYS = 5
#: Komórka mapy z mniejszą liczbą telefonów nie ma procentu.
MIN_CELL_CALLS = 5
#: Progi wniosków: poniżej nich różnica procentów to szum.
MIN_CALLS_FOR_HOURS = 100
MIN_HOUR_CALLS = 20
MIN_SOURCE_TALKS = 30
FOUR_WEEKS = 28
NO_CAMPAIGN = "Bez kampanii"
NO_SOURCE = "Bez źródła"
LEAD_SOURCE = "Szanse z etapu „Lead”"
CARD_SOURCE = "Telefon z karty szansy"


@dataclass(frozen=True)
class CallRow:
    user_id: int
    at: datetime
    outcome: str
    record_id: Optional[int] = None
    campaign_id: Optional[int] = None
    #: „Skąd kontakt” rekordu; ``None`` dla rekordu bez listy.
    contact_source: Optional[str] = None
    #: Rekord szansy z etapu „Lead” (bez kampanii).
    from_opportunity: bool = False
    opportunity_id: Optional[int] = None


@dataclass(frozen=True)
class MeetingRow:
    opportunity_id: int
    dated: bool
    verdict: Optional[str]


@dataclass(frozen=True)
class CampaignInfo:
    id: int
    name: str
    service: Optional[str]
    on_list: int
    left: int


@dataclass(frozen=True)
class Funnel:
    calls: int
    talks: int
    offers: int
    meetings: int
    dated: int
    held: int
    qualified: int


@dataclass(frozen=True)
class CampaignStats:
    id: Optional[int]
    name: str
    service: Optional[str]
    on_list: Optional[int]
    left: Optional[int]
    days_left: Optional[int]
    calls: int
    talks: int
    offers: int
    meetings: int


@dataclass(frozen=True)
class SourceStats:
    source: str
    records: int
    reached: int
    talks: int
    meetings: int
    objections: int


@dataclass(frozen=True)
class HourCell:
    weekday: int
    hour: int
    calls: int
    talks: int
    #: Odsetek rozmów; ``None`` przy mniej niż ``MIN_CELL_CALLS`` telefonach.
    rate: Optional[float]


@dataclass(frozen=True)
class PersonStats:
    user_id: int
    name: str
    days: int
    calls: int
    talks: int
    offers: int
    meetings: int
    dated: int
    qualified: int


@dataclass(frozen=True)
class Insight:
    tone: Literal["info", "warning", "success"]
    text: str


@dataclass(frozen=True)
class Effectiveness:
    start: date
    end: date
    workdays: int
    funnel: Funnel
    outcomes: dict[str, int]
    campaigns: list[CampaignStats]
    sources: list[SourceStats]
    hours: list[HourCell]
    offer_followup: dict[str, int]
    people: list[PersonStats]
    insights: list[Insight]
    campaign_options: list[tuple[int, str]] = field(default_factory=list)


# ── Okres ─────────────────────────────────────────────────────────────────


def period_bounds(
    period: Period, today: date, first_day: Optional[date]
) -> tuple[date, date]:
    """Zakres dni w kalendarzu firmy; ``all`` zaczyna się od pierwszego telefonu."""

    if period == "week":
        return today - timedelta(days=today.weekday()), today
    if period == "4w":
        return today - timedelta(days=FOUR_WEEKS - 1), today
    return (first_day or today), today


def workdays_between(start: date, end: date) -> int:
    """Dni robocze w ``[start, end]`` (święta jak w kalendarzu firmy)."""

    if end < start:
        return 0
    count = 0
    day = start
    while day <= end:
        if is_business_day(datetime.combine(day, time(12), tzinfo=ZONE)):
            count += 1
        day += timedelta(days=1)
    return count


# ── Agregacja ─────────────────────────────────────────────────────────────


def _is_talk(outcome: str) -> bool:
    return outcome != NO_ANSWER


def _meeting_count(calls: list[CallRow]) -> int:
    """Umówione spotkania: raz na szansę, telefon bez szansy (karta) jako jedno.

    Rekord szansy zostaje w kolejce po „Umówionym spotkaniu”, więc ten sam wynik
    może paść dwa razy; liczony per telefon dawałby „1 z 2 bez terminu” dla
    jednego spotkania z terminem.
    """

    booked = [c for c in calls if c.outcome == MEETING_BOOKED]
    with_opportunity = {
        c.opportunity_id for c in booked if c.opportunity_id is not None
    }
    return len(with_opportunity) + sum(1 for c in booked if c.opportunity_id is None)


def _source_of(call: CallRow) -> str:
    if call.record_id is None:
        return CARD_SOURCE
    if call.from_opportunity:
        return LEAD_SOURCE
    return (call.contact_source or "").strip() or NO_SOURCE


def _rate(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%"


def _insights(
    funnel: Funnel,
    hours: list[HourCell],
    sources: list[SourceStats],
    followup: dict[str, int],
) -> list[Insight]:
    found: list[Insight] = []
    if funnel.calls == 0:
        return [
            Insight(
                "info",
                "W tym okresie nie ma zapisanych telefonów. Wyniki z kolejki pojawią się tu same.",
            )
        ]
    undated = funnel.meetings - funnel.dated
    if undated > 0:
        found.append(
            Insight(
                "warning",
                f"{undated} z {funnel.meetings} umówionych spotkań nie ma terminu w NEXUSIE. "
                "Bez terminu handlowiec nie wie, kiedy jedzie.",
            )
        )
    if funnel.calls >= MIN_CALLS_FOR_HOURS:
        per_hour: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        for cell in hours:
            per_hour[cell.hour][0] += cell.calls
            per_hour[cell.hour][1] += cell.talks
        rated = [
            (talks / calls, hour)
            for hour, (calls, talks) in per_hour.items()
            if calls >= MIN_HOUR_CALLS
        ]
        if len(rated) >= 2:
            best, worst = max(rated), min(rated)
            if best[0] - worst[0] >= 0.1:
                found.append(
                    Insight(
                        "success",
                        f"Najczęściej odbierają o {best[1]}:00 ({round(best[0] * 100)}% rozmów), "
                        f"najrzadziej o {worst[1]}:00 ({round(worst[0] * 100)}%).",
                    )
                )
    compared = [s for s in sources if s.talks >= MIN_SOURCE_TALKS]
    if len(compared) >= 2:
        ranked = sorted(compared, key=lambda s: s.meetings / s.talks, reverse=True)
        top, low = ranked[0], ranked[-1]
        found.append(
            Insight(
                "info",
                f"Lista „{top.source}” daje spotkanie w {_rate(top.meetings, top.talks)} rozmów, "
                f"„{low.source}” w {_rate(low.meetings, low.talks)}.",
            )
        )
    waiting = followup.get(OFFER_SENT, 0)
    if waiting:
        found.append(
            Insight(
                "info",
                f"Oferty ogólne z tego okresu czekające na oddzwonienie: {waiting}. "
                "Kolejka podsunie je same w swoim dniu.",
            )
        )
    return found


def summarize(
    *,
    calls: list[CallRow],
    meetings: dict[int, MeetingRow],
    campaigns: list[CampaignInfo],
    record_states: dict[int, str],
    names: dict[int, str],
    start: date,
    end: date,
    today: date,
) -> Effectiveness:
    """Liczy cały ekran z telefonów okresu; bez dostępu do bazy."""

    workdays = workdays_between(start, min(end, today))
    outcomes: Counter[str] = Counter(call.outcome for call in calls)
    talks = sum(n for outcome, n in outcomes.items() if _is_talk(outcome))

    booked_ids = {
        call.opportunity_id
        for call in calls
        if call.outcome == MEETING_BOOKED and call.opportunity_id is not None
    }
    booked = [meetings[i] for i in booked_ids if i in meetings]
    funnel = Funnel(
        calls=len(calls),
        talks=talks,
        offers=outcomes.get(OFFER_SENT, 0),
        meetings=_meeting_count(calls),
        dated=sum(1 for m in booked if m.dated),
        held=sum(1 for m in booked if m.verdict in handoff_state.HELD_VERDICTS),
        qualified=sum(1 for m in booked if m.verdict == "qualified"),
    )

    # Kampanie: liczby okresu + stan listy dziś.
    by_campaign: dict[Optional[int], list[CallRow]] = defaultdict(list)
    for call in calls:
        by_campaign[call.campaign_id].append(call)
    campaign_rows: list[CampaignStats] = []
    for info in campaigns:
        rows = by_campaign.get(info.id, [])
        touched = len({c.record_id for c in rows if c.record_id is not None})
        pace = touched / workdays if workdays else 0
        campaign_rows.append(
            CampaignStats(
                id=info.id,
                name=info.name,
                service=info.service,
                on_list=info.on_list,
                left=info.left,
                days_left=math.ceil(info.left / pace) if pace and info.left else None,
                calls=len(rows),
                talks=sum(1 for c in rows if _is_talk(c.outcome)),
                offers=sum(1 for c in rows if c.outcome == OFFER_SENT),
                meetings=_meeting_count(rows),
            )
        )
    loose = by_campaign.get(None, [])
    if loose:
        campaign_rows.append(
            CampaignStats(
                id=None,
                name=NO_CAMPAIGN,
                service=None,
                on_list=None,
                left=None,
                days_left=None,
                calls=len(loose),
                talks=sum(1 for c in loose if _is_talk(c.outcome)),
                offers=sum(1 for c in loose if c.outcome == OFFER_SENT),
                meetings=_meeting_count(loose),
            )
        )
    campaign_rows.sort(key=lambda row: (row.id is None, -row.calls, row.name.lower()))

    # Listy („Skąd kontakt”): rekord liczy się raz, rozmowy i spotkania każdy wynik.
    by_source: dict[str, list[CallRow]] = defaultdict(list)
    for call in calls:
        by_source[_source_of(call)].append(call)
    sources = []
    for source, rows in by_source.items():
        records: dict[Any, bool] = {}
        for c in rows:
            key = c.record_id if c.record_id is not None else ("a", id(c))
            records[key] = records.get(key, False) or _is_talk(c.outcome)
        sources.append(
            SourceStats(
                source=source,
                records=len(records),
                reached=sum(1 for reached in records.values() if reached),
                talks=sum(1 for c in rows if _is_talk(c.outcome)),
                meetings=_meeting_count(rows),
                objections=sum(1 for c in rows if c.outcome == DO_NOT_CONTACT),
            )
        )
    sources.sort(key=lambda s: (-s.records, s.source.lower()))

    # Kiedy odbierają: pon–pt × godziny w kalendarzu firmy.
    grid: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])
    for call in calls:
        local = call.at.astimezone(ZONE)
        if local.weekday() < WEEKDAYS and local.hour in HOURS:
            cell = grid[(local.weekday(), local.hour)]
            cell[0] += 1
            cell[1] += int(_is_talk(call.outcome))
    hours = [
        HourCell(
            weekday=day,
            hour=hour,
            calls=grid[(day, hour)][0],
            talks=grid[(day, hour)][1],
            rate=(
                grid[(day, hour)][1] / grid[(day, hour)][0]
                if grid[(day, hour)][0] >= MIN_CELL_CALLS
                else None
            ),
        )
        for day in range(WEEKDAYS)
        for hour in HOURS
    ]

    # Oferta ogólna → co dalej: dzisiejszy stan rekordów, którym w okresie wysłano ofertę.
    offered = {c.record_id for c in calls if c.outcome == OFFER_SENT and c.record_id}
    followup: Counter[str] = Counter(
        record_states[i] for i in offered if i in record_states
    )

    # Osoby: pełna tabela, kolejność od liczby spotkań (sortuje też front).
    by_user: dict[int, list[CallRow]] = defaultdict(list)
    for call in calls:
        by_user[call.user_id].append(call)
    people = []
    for user_id, rows in by_user.items():
        own_booked = [
            meetings[i]
            for i in {
                c.opportunity_id
                for c in rows
                if c.outcome == MEETING_BOOKED and c.opportunity_id is not None
            }
            if i in meetings
        ]
        people.append(
            PersonStats(
                user_id=user_id,
                name=names.get(user_id, f"Konto {user_id}"),
                days=len({c.at.astimezone(ZONE).date() for c in rows}),
                calls=len(rows),
                talks=sum(1 for c in rows if _is_talk(c.outcome)),
                offers=sum(1 for c in rows if c.outcome == OFFER_SENT),
                meetings=_meeting_count(rows),
                dated=sum(1 for m in own_booked if m.dated),
                qualified=sum(1 for m in own_booked if m.verdict == "qualified"),
            )
        )
    people.sort(key=lambda p: (-p.meetings, -p.talks, p.name.lower()))

    return Effectiveness(
        start=start,
        end=end,
        workdays=workdays,
        funnel=funnel,
        outcomes={
            o: outcomes.get(o, 0) for o in schema.CALL_OUTCOMES if outcomes.get(o)
        },
        campaigns=campaign_rows,
        sources=sources,
        hours=hours,
        offer_followup=dict(followup),
        people=people,
        insights=_insights(funnel, hours, sources, dict(followup)),
    )


# ── Odczyt z bazy ─────────────────────────────────────────────────────────


async def _first_call_day(db: AsyncSession) -> Optional[date]:
    first = await db.scalar(
        select(func.min(SalesActivity.occurred_at)).where(
            SalesActivity.kind == "call", SalesActivity.outcome.is_not(None)
        )
    )
    return first.astimezone(ZONE).date() if first else None


async def _calls(
    db: AsyncSession,
    start: date,
    end: date,
    *,
    user_id: Optional[int],
    campaign_id: Optional[int],
) -> list[CallRow]:
    record_join = and_(
        SalesActivity.external_source == CALL_SOURCE,
        # ``external_id`` = „rekord:próba”; porównanie tekstem, bo inne źródła mają tu
        # identyfikatory Outlooka, których nie da się rzutować na liczbę.
        func.split_part(SalesActivity.external_id, ":", 1)
        == cast(SalesCallRecord.id, String),
    )
    query = (
        select(
            SalesActivity.created_by_user_id,
            SalesActivity.occurred_at,
            SalesActivity.outcome,
            SalesActivity.opportunity_id,
            SalesCallRecord.id,
            SalesCallRecord.campaign_id,
            SalesCallRecord.contact_source,
        )
        .outerjoin(SalesCallRecord, record_join)
        .where(
            SalesActivity.kind == "call",
            SalesActivity.outcome.is_not(None),
            SalesActivity.created_by_user_id.is_not(None),
            SalesActivity.occurred_at >= local_day_start_utc(start),
            SalesActivity.occurred_at < local_day_start_utc(end + timedelta(days=1)),
        )
    )
    if user_id is not None:
        query = query.where(SalesActivity.created_by_user_id == user_id)
    if campaign_id is not None:
        query = query.where(SalesCallRecord.campaign_id == campaign_id)
    rows = (await db.execute(query)).all()
    return [
        CallRow(
            user_id=row[0],
            at=row[1],
            outcome=row[2],
            opportunity_id=row[3],
            record_id=row[4],
            campaign_id=row[5],
            contact_source=row[6],
            from_opportunity=row[4] is not None and row[5] is None,
        )
        for row in rows
    ]


async def _meetings(
    db: AsyncSession, opportunity_ids: set[int]
) -> dict[int, MeetingRow]:
    if not opportunity_ids:
        return {}
    logged = (
        select(SalesActivity.id)
        .where(
            SalesActivity.kind == "meeting",
            *not_cancelled(),
            or_(
                SalesActivity.opportunity_id == SalesOpportunity.id,
                SalesActivity.company_id == SalesOpportunity.company_id,
            ),
            func.coalesce(SalesActivity.occurred_at, SalesActivity.due_at)
            >= func.date_trunc("day", SalesOpportunity.created_at),
        )
        .correlate(SalesOpportunity)
    )
    rows = (
        await db.execute(
            select(SalesOpportunity, exists(logged)).where(
                SalesOpportunity.id.in_(opportunity_ids)
            )
        )
    ).all()
    found: dict[int, MeetingRow] = {}
    for opportunity, has_meeting in rows:
        data = handoff_state.block(opportunity) or {}
        verdict = data.get("verdict")
        found[opportunity.id] = MeetingRow(
            opportunity_id=opportunity.id,
            dated=bool(has_meeting or data.get("meeting_at")),
            verdict=verdict.get("kind") if isinstance(verdict, dict) else None,
        )
    return found


async def _campaigns(
    db: AsyncSession, campaign_id: Optional[int]
) -> tuple[list[CampaignInfo], list[tuple[int, str]]]:
    left = func.count(SalesCallRecord.id).filter(SalesCallRecord.state == NEW)
    query = (
        select(
            SalesCallCampaign.id,
            SalesCallCampaign.name,
            SalesCallCampaign.service,
            func.count(SalesCallRecord.id),
            left,
        )
        .outerjoin(SalesCallRecord, SalesCallRecord.campaign_id == SalesCallCampaign.id)
        .where(SalesCallCampaign.archived_at.is_(None))
        .group_by(SalesCallCampaign.id)
        .order_by(func.lower(SalesCallCampaign.name), SalesCallCampaign.id)
    )
    rows = (await db.execute(query)).all()
    options = [(row[0], row[1]) for row in rows]
    infos = [
        CampaignInfo(
            id=row[0],
            name=row[1],
            service=row[2],
            on_list=int(row[3]),
            left=int(row[4]),
        )
        for row in rows
        if campaign_id is None or row[0] == campaign_id
    ]
    return infos, options


async def load_effectiveness(
    db: AsyncSession,
    *,
    period: Period,
    today: date,
    user_id: Optional[int] = None,
    campaign_id: Optional[int] = None,
) -> Effectiveness:
    start, end = period_bounds(period, today, await _first_call_day(db))
    calls = await _calls(db, start, end, user_id=user_id, campaign_id=campaign_id)
    booked = {
        c.opportunity_id
        for c in calls
        if c.outcome == MEETING_BOOKED and c.opportunity_id is not None
    }
    offered = {c.record_id for c in calls if c.outcome == OFFER_SENT and c.record_id}
    states = (
        dict(
            (
                await db.execute(
                    select(SalesCallRecord.id, SalesCallRecord.state).where(
                        SalesCallRecord.id.in_(offered)
                    )
                )
            ).all()
        )
        if offered
        else {}
    )
    user_ids = {c.user_id for c in calls}
    names = (
        dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(user_ids))
                )
            ).all()
        )
        if user_ids
        else {}
    )
    campaigns, options = await _campaigns(db, campaign_id)
    result = summarize(
        calls=calls,
        meetings=await _meetings(db, booked),
        campaigns=campaigns,
        record_states=states,
        names=names,
        start=start,
        end=end,
        today=today,
    )
    return Effectiveness(**{**result.__dict__, "campaign_options": options})
