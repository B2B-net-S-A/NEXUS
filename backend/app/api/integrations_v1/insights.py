"""Insights w API v1: raporty i wskaźniki firmy (odczyt).

Scope ``insights:read``. Liczby liczą TE SAME funkcje co ekran Insights —
nowych definicji metryk tu nie ma:

* ``/insights/recruitment`` — „Lejek po etapach” (``insights_stage_breakdown``):
  ile par (kandydat, rekrutacja) pierwszy raz doszło do etapu, ile stoi tam
  teraz i kto zakończył proces z jakim powodem; opcjonalnie dla jednej
  rekrutacji (``job_id``).
* ``/insights/placements`` — placementy (D2) z „Analizy placementów”
  (``insights_charts.insights_placement_analysis``) oraz wejścia, zejścia,
  konsultanci i kwoty z kontraktów (``services/integration_insights``,
  ``fold_money`` kokpitu Rady).
* ``/insights/team`` — aktywność zespołu (raport „Aktywność zespołu”,
  ``insights_recruitment.insights_team_activity``) i Liga Mistrzów
  (``competitions.get_current`` — ta sama numeracja co podium i pasek).
  Oba ekran pokazuje KAŻDEJ roli (decyzja D7, rekruter ma
  ``view_recruitment_ranking``). Imiennych KPI zespołu — tabela „Ludzie”,
  „Do uwagi”, panel „KPI zespołu”, cele i precyzja osób — API NIE wystawia:
  ekran pokazuje je tylko rolom z ``view_team_kpi`` (kierownictwo, DL), a rola
  „Automatyzacje” (0446) tej capability nie ma.
* ``/insights/goals`` — katalog celów KPI i postęp zespołu rekrutacji (sumy,
  jak cele zespołu u Head of Recruitment).

Kwoty przez ``amount_level``: przychód od ``sales_amounts:read``; koszt,
marża i nagrody konkursów tylko z ``amounts:read``. Okno ``from``/``to`` to
dni kalendarzowe Europe/Warsaw (włącznie, najwyżej 366 dni); bez obu —
poprzedni pełny miesiąc. Rekrutacje ukrytych i usuniętych klientów nie
istnieją dla klucza (``job_id`` → 404); w rozbiciu na klientów ich liczby
idą do wiersza ``client_id = null`` (razem z placementami bez klienta), więc
sumy dalej się zgadzają.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import ANALYTICS_TIMEZONE, Period, PeriodError
from app.api import competitions as competitions_routes
from app.api import insights_charts, insights_recruitment, insights_stage_breakdown
from app.api.deps import Caller
from app.api.integrations_v1.common import (
    INT4_MAX,
    AmountLevel,
    InsightsRead,
    IntegrationRoute,
    Money,
    amount_level,
    principal_rate_key,
    read_rate_limit,
)
from app.api.jobs import jobs_register_base_clause
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.scheduling import business_today, local_now
from app.models.competition_winner import CompetitionType
from app.models.job import Job
from app.services import competitions as comp_service
from app.services import integration_insights as svc
from app.services.insights_stage_breakdown import compute_stage_breakdown
from app.services.kpi_catalog import KPI_CATALOG, KpiMetric, kpi_available
from app.services.kpi_targets import resolve_org_target
from app.services.metric_definitions import (
    CONTRACTOR_DEPARTURE,
    CONTRACTOR_RESIGNATION,
    DL_HIT_RATIO_TARGET_PCT,
    FIRST_HIRED_PER_CANDIDATE_JOB,
)

router = APIRouter(route_class=IntegrationRoute)

FromQuery = Query(
    None,
    alias="from",
    description="Pierwszy dzień okna (Europe/Warsaw, włącznie). Razem z `to`.",
)
ToQuery = Query(
    None,
    alias="to",
    description="Ostatni dzień okna (włącznie, najwyżej 366 dni od `from`).",
)

#: Ile osób w rankingu aktywności (limit raportu „Aktywność zespołu”).
ACTIVITY_LIMIT = 50

_COVERAGE_NOTE = (
    "Wejścia, zejścia, konsultanci i kwoty liczą się z kontraktów zapisanych "
    "w NEXUSIE, a ta ewidencja jest młodsza niż firma — dla wcześniejszych "
    "okresów liczby są zaniżone, a porównanie lat opisuje rozrastanie się "
    "ewidencji, nie wynik (podstawa: priced_contracts). Placementy idą "
    "z historii rekrutacji, która sięga wstecz."
)


# ── Okno, kwoty ──────────────────────────────────────────────────────────────


def _window(date_from: Optional[date], date_to: Optional[date], today: date) -> Period:
    try:
        return svc.resolve_window(date_from, date_to, today=today)
    except PeriodError as exc:
        raise HTTPException(
            422, detail={"error": "invalid_period", "message": str(exc)}
        ) from exc


class PeriodOut(BaseModel):
    """Okno raportu: dni ``from``–``to`` włącznie = przedział ``[start, end)``."""

    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from", description="Pierwszy dzień okna (włącznie).")
    to: date = Field(description="Ostatni dzień okna (włącznie).")
    start: datetime
    end: datetime = Field(description="Północ pierwszego dnia PO oknie.")
    timezone: str


def _period_out(period: Period) -> PeriodOut:
    first, last = svc.window_days(period)
    return PeriodOut(
        from_=first,
        to=last,
        start=period.start,
        end=period.end,
        timezone=ANALYTICS_TIMEZONE,
    )


def _generated_at() -> datetime:
    return datetime.now(timezone.utc)


class MoneyOut(BaseModel):
    """Miesięczne kwoty kontraktów wykonywanych w dniu wyceny (PLN).

    Przychód od ``sales_amounts:read``; koszt konsultantów, marża i marża %
    tylko z ``amounts:read``. Bez scope'u pole jest ``null``."""

    valuation_day: date
    revenue_monthly_pln: Money
    consultant_cost_monthly_pln: Money
    margin_monthly_pln: Money
    margin_pct: Optional[float]
    contracts_without_cost_leg: int
    contracts_without_revenue_leg: int
    complete: bool = Field(
        description="False = brak kursu NBP dla części walut; kwoty niepełne."
    )
    missing_currencies: list[str]


def money_out(
    snapshot: Optional[svc.MoneySnapshot], level: AmountLevel
) -> Optional[MoneyOut]:
    """Kwoty ze stanu na dzień wyceny z redakcją według poziomu klucza."""
    if snapshot is None:
        return None
    sales = level >= AmountLevel.sales
    costs = level is AmountLevel.all
    return MoneyOut(
        valuation_day=snapshot.valuation_day,
        revenue_monthly_pln=snapshot.revenue if sales else None,
        consultant_cost_monthly_pln=snapshot.cost if costs else None,
        margin_monthly_pln=snapshot.margin if costs else None,
        margin_pct=snapshot.margin_pct if costs else None,
        contracts_without_cost_leg=snapshot.contracts_without_cost_leg,
        contracts_without_revenue_leg=snapshot.contracts_without_revenue_leg,
        complete=snapshot.complete,
        missing_currencies=list(snapshot.missing_currencies),
    )


class AmountsOut(BaseModel):
    amount_level: str = Field(description="none | sales | all")
    sales_redacted: bool
    costs_redacted: bool


def _amounts(caller: Caller) -> AmountsOut:
    level = amount_level(caller)
    return AmountsOut(
        amount_level=level.name,
        sales_redacted=level < AmountLevel.sales,
        costs_redacted=level is not AmountLevel.all,
    )


# ── Rekrutacja: lejek po etapach ─────────────────────────────────────────────


class FunnelStageOut(BaseModel):
    key: str
    label: str
    column: str = Field(description="Kolumna Tablicy, do której należy etap.")
    column_label: str
    is_main: bool = Field(description="Wiersz główny kolumny (reszta to odznaki).")
    reached: int = Field(
        description="Pary (kandydat, rekrutacja), które PIERWSZY raz weszły "
        "na etap w okresie."
    )


class ClosedReasonOut(BaseModel):
    label: str
    count: int
    kind: str = Field(description="reason | other | none")


class ClosedOut(BaseModel):
    key: str = Field(description="candidate | recruiter | delivery_lead | client")
    label: str
    count: int
    reasons: list[ClosedReasonOut]


class FunnelOut(BaseModel):
    stages: list[FunnelStageOut]
    closed: list[ClosedOut]


class RecruitmentMonthOut(FunnelOut):
    model_config = ConfigDict(populate_by_name=True)

    month: str = Field(description="YYYY-MM")
    from_: date = Field(alias="from")
    to: date
    complete: bool = Field(
        description="Cały miesiąc w oknie i już zakończony (liczby się nie zmienią)."
    )


class StageNowOut(BaseModel):
    key: str
    label: str
    now: int = Field(
        description="Osoby stojące dziś na etapie (rekrutacje opublikowane)."
    )


class RecruitmentInsightsOut(BaseModel):
    period: PeriodOut
    generated_at: datetime
    job_id: Optional[int]
    definitions: dict[str, str]
    totals: FunnelOut
    current: list[StageNowOut] = Field(description="Stan na dziś — nie zależy od okna.")
    months: list[RecruitmentMonthOut]


def funnel_out(raw: dict) -> FunnelOut:
    """Wiersze „Lejka po etapach” bez treści wolnego tekstu (``details``).

    Dymek „Inne” na ekranie wymienia jednorazowe notatki odrzucenia — to
    wolny tekst o konkretnych osobach, więc API podaje tylko liczbę.
    """
    return FunnelOut(
        stages=[
            FunnelStageOut(
                key=row["key"],
                label=row["label"],
                column=row["column"],
                column_label=row["column_label"],
                is_main=row["is_main"],
                reached=row["reached"],
            )
            for row in raw["rows"]
        ],
        closed=[
            ClosedOut(
                key=group["key"],
                label=group["label"],
                count=group["count"],
                reasons=[
                    ClosedReasonOut(
                        label=reason["label"],
                        count=reason["count"],
                        kind=reason["kind"],
                    )
                    for reason in group["top_reasons"]
                ],
            )
            for group in raw["closed_by"]
        ],
    )


async def _visible_job_or_404(db: AsyncSession, job_id: int) -> None:
    found = await db.scalar(
        select(Job.id).where(Job.id == job_id, jobs_register_base_clause())
    )
    if found is None:
        raise HTTPException(404, detail="Rekrutacja nie istnieje.")


async def _breakdown(db: AsyncSession, period: Period, job_id: Optional[int]) -> dict:
    if job_id is not None:
        return await compute_stage_breakdown(
            db, start=period.start, end=period.end, job_ids=[job_id]
        )
    # Cała firma: trasa ekranu (z jej cache'em per okno).
    first, last = svc.window_days(period)
    return await insights_stage_breakdown.insights_stage_breakdown(
        current_user=None,
        db=db,
        period="custom",
        offset=0,
        anchor=None,
        date_from=first,
        date_to=last,
    )


@router.get(
    "/insights/recruitment",
    response_model=RecruitmentInsightsOut,
    summary="Lejek rekrutacji w okresie: etapy, zakończenia i powody, per miesiąc",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def recruitment_insights(
    request: Request,
    _caller: InsightsRead,
    db: AsyncSession = Depends(get_db),
    date_from: Optional[date] = FromQuery,
    date_to: Optional[date] = ToQuery,
    job_id: Optional[int] = Query(
        None, ge=1, le=INT4_MAX, description="Tylko ta rekrutacja."
    ),
) -> RecruitmentInsightsOut:
    """Raport „Lejek po etapach” dla okna i każdego miesiąca w nim.

    ``stages[].reached`` — pary (kandydat, rekrutacja), które pierwszy raz
    doszły do etapu w okresie (dodani, screening, zweryfikowani, QC CV,
    wysłani do klienta, rozmowy u klienta, akceptacja, zatrudnieni…);
    zatrudnieni to placementy D2. ``closed`` — procesy zakończone w okresie:
    kto zakończył (kandydat, my, DL, klient) i najczęstsze powody. Miesiące
    sumują się do okna (poza listą powodów, której „Inne” grupuje się
    w każdym odcinku osobno). Bez danych osobowych — same liczniki.
    """
    today = business_today()
    period = _window(date_from, date_to, today)
    if job_id is not None:
        await _visible_job_or_404(db, job_id)
    slices = svc.month_slices(period, today=today)
    totals_raw = await _breakdown(db, period, job_id)
    if len(slices) == 1:
        month_raws = [totals_raw]
    else:
        month_raws = [await _breakdown(db, s.period, job_id) for s in slices]
    return RecruitmentInsightsOut(
        period=_period_out(period),
        generated_at=_generated_at(),
        job_id=job_id,
        definitions={
            **dict(totals_raw.get("definitions") or {}),
            "placements": FIRST_HIRED_PER_CANDIDATE_JOB,
        },
        totals=funnel_out(totals_raw),
        current=[
            StageNowOut(key=row["key"], label=row["label"], now=row["now"])
            for row in totals_raw["rows"]
        ],
        months=[
            RecruitmentMonthOut(
                month=s.month,
                from_=s.date_from,
                to=s.date_to,
                complete=s.complete,
                **funnel_out(raw).model_dump(),
            )
            for s, raw in zip(slices, month_raws)
        ],
    )


# ── Placementy, wejścia i zejścia konsultantów ───────────────────────────────


class PlacementMonthOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    month: str = Field(description="YYYY-MM")
    from_: date = Field(alias="from")
    to: date
    complete: bool
    placements: int = Field(description="Pierwsze zatrudnienie pary (D2).")
    starts: int = Field(description="Kontrakty z datą startu w odcinku.")
    ends: int = Field(description="Zejścia: kontrakty zakończone w odcinku.")
    resignations: int = Field(description="Zejścia z powodu po stronie konsultanta.")
    consultants: Optional[int] = Field(
        description="Konsultanci pracujący w dniu wyceny (null = odcinek w przyszłości)."
    )
    active_contracts: Optional[int]
    priced_contracts: Optional[int] = Field(
        description="Kontrakty z wycenioną stawką do klienta — podstawa kwot."
    )
    money: Optional[MoneyOut]


class PlacementClientOut(BaseModel):
    client_id: Optional[int] = Field(
        description="null = placementy bez klienta oraz klienci ukryci lub usunięci."
    )
    name: Optional[str]
    placements: int
    starts: int
    ends: int
    resignations: int
    consultants: Optional[int] = Field(description="W dniu wyceny okna.")
    active_contracts: Optional[int]
    money: Optional[MoneyOut]


class PlacementTotalsOut(BaseModel):
    placements: int
    starts: int
    ends: int
    resignations: int
    clients_with_placements: int


class PlacementsInsightsOut(AmountsOut):
    period: PeriodOut
    generated_at: datetime
    definitions: dict[str, str]
    coverage_note: str
    window_valuation_day: Optional[date] = Field(
        description="Dzień wyceny konsultantów i kwot klientów (ostatni dzień "
        "okna albo dziś)."
    )
    totals: PlacementTotalsOut
    months: list[PlacementMonthOut]
    clients: list[PlacementClientOut]


async def _placements_for(db: AsyncSession, s: svc.MonthSlice) -> dict:
    return await insights_charts.insights_placement_analysis(
        current_user=None,
        db=db,
        period="custom",
        offset=0,
        anchor=None,
        date_from=s.date_from,
        date_to=s.date_to,
    )


@router.get(
    "/insights/placements",
    response_model=PlacementsInsightsOut,
    summary="Placementy, wejścia i zejścia konsultantów per miesiąc i per klient",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def placements_insights(
    request: Request,
    caller: InsightsRead,
    db: AsyncSession = Depends(get_db),
    date_from: Optional[date] = FromQuery,
    date_to: Optional[date] = ToQuery,
) -> PlacementsInsightsOut:
    """Placementy (D2) i ruch konsultantów w okresie, z kwotami MRR.

    Per miesiąc: placementy, wejścia (start kontraktu), zejścia i rezygnacje,
    konsultanci i kwoty na dzień wyceny (ostatni dzień miesiąca albo dziś).
    Per klient: te same przepływy za całe okno i stan na dzień wyceny okna.
    Kwoty: przychód od ``sales_amounts:read``, koszt i marża tylko
    z ``amounts:read``. Liczby z kontraktów sprzed startu ewidencji są
    zaniżone — patrz ``coverage_note`` i ``priced_contracts``.
    """
    today = business_today()
    period = _window(date_from, date_to, today)
    slices = svc.month_slices(period, today=today)
    level = amount_level(caller)

    placement_months = [await _placements_for(db, s) for s in slices]
    first, last = svc.window_days(period)
    contracts = await svc.load_contracts(db, first=first, last=last)
    labels = await svc.client_labels(
        db,
        [c["client_id"] for p in placement_months for c in p["by_client"]]
        + [contract.client_id for contract in contracts],
    )

    def group_key(client_id: Optional[int]) -> Optional[int]:
        label = labels.get(client_id) if client_id is not None else None
        return client_id if label is not None and label.listed else None

    report = await svc.contract_report(
        db, contracts, slices, today=today, group_key=group_key
    )

    placements_by_client: dict = {}
    for month in placement_months:
        for row in month["by_client"]:
            key = group_key(row["client_id"])
            placements_by_client[key] = placements_by_client.get(key, 0) + int(
                row["placements"]
            )

    months = []
    for s, placements, part in zip(slices, placement_months, report.months):
        money = part.money
        months.append(
            PlacementMonthOut(
                month=s.month,
                from_=s.date_from,
                to=s.date_to,
                complete=s.complete,
                placements=int(placements["totals"]["placements"]),
                starts=part.flows.starts,
                ends=part.flows.ends,
                resignations=part.flows.resignations,
                consultants=money.consultants if money else None,
                active_contracts=money.active_contracts if money else None,
                priced_contracts=money.priced_contracts if money else None,
                money=money_out(money, level),
            )
        )

    empty = svc.ContractPart(flows=svc.ContractFlows(0, 0, 0), money=None)
    clients = []
    for key in set(placements_by_client) | set(report.groups):
        part = report.groups.get(key, empty)
        money = part.money
        consultants = money.consultants if money else None
        if (
            not placements_by_client.get(key)
            and not part.flows.starts
            and not part.flows.ends
            and not consultants
        ):
            continue
        clients.append(
            PlacementClientOut(
                client_id=key,
                name=labels[key].name if key is not None else None,
                placements=placements_by_client.get(key, 0),
                starts=part.flows.starts,
                ends=part.flows.ends,
                resignations=part.flows.resignations,
                consultants=consultants,
                active_contracts=money.active_contracts if money else None,
                money=money_out(money, level),
            )
        )
    clients.sort(
        key=lambda c: (
            c.client_id is None,
            -c.placements,
            -(c.consultants or 0),
            (c.name or "").casefold(),
        )
    )

    return PlacementsInsightsOut(
        **_amounts(caller).model_dump(),
        period=_period_out(period),
        generated_at=_generated_at(),
        definitions={
            "placements": FIRST_HIRED_PER_CANDIDATE_JOB,
            "starts": svc.STARTS_DEFINITION,
            "ends": CONTRACTOR_DEPARTURE,
            "resignations": CONTRACTOR_RESIGNATION,
            "money": svc.MONEY_BASIS,
        },
        coverage_note=_COVERAGE_NOTE,
        window_valuation_day=report.window_valuation_day,
        totals=PlacementTotalsOut(
            placements=sum(m.placements for m in months),
            starts=sum(m.starts for m in months),
            ends=sum(m.ends for m in months),
            resignations=sum(m.resignations for m in months),
            clients_with_placements=sum(
                1 for c in clients if c.client_id is not None and c.placements
            ),
        ),
        months=months,
        clients=clients,
    )


# ── Zespół: aktywność i Liga Mistrzów ────────────────────────────────────────


class ActivityEntryOut(BaseModel):
    rank: int
    user_id: int
    name: str
    candidates_added: int
    screenings: int
    interviews: int = Field(description="Rozmowy u klienta (pierwsze wejście pary).")
    placements: int
    calls: int
    total_actions: int


class ActivityOutsideOut(BaseModel):
    """Konta bez roli rekrutacyjnej (admin, Finanse…) — jeden wiersz, nie osoby."""

    label: str
    users: int
    actions: int
    placements: int


class TeamActivityOut(BaseModel):
    entries: list[ActivityEntryOut]
    outside_scope: ActivityOutsideOut
    note: str


class LeagueEntryOut(BaseModel):
    rank: Optional[int] = Field(
        description="Miejsce w klasyfikacji; null = bez miejsca (próg niespełniony "
        "albo wykluczony)."
    )
    user_id: int
    name: str
    points: Optional[int] = Field(description="Liga rekruterów; null w lidze DL.")
    placements: int
    interviews: Optional[int]
    recommendations: Optional[int]
    verifications: Optional[int]
    hit_ratio: Optional[float] = Field(description="Liga DL, %.")
    closed_requests: Optional[int] = Field(
        description="Liga DL: rekrutacje zamknięte w kwartale (mianownik hit ratio)."
    )
    qualified: bool
    tied: bool = Field(description="Remis o płatne miejsce — rozstrzyga admin.")
    excluded: bool
    prize_pln: Money = Field(description="Nagroda — tylko z amounts:read.")


class LeagueTieOut(BaseModel):
    positions: list[int]
    user_ids: list[int]


class LeagueOut(BaseModel):
    type: str = Field(
        description="quarterly_champions_recruiter | quarterly_champions_dl"
    )
    period: str = Field(description="Kwartał, np. „Q3 2026”.")
    requirement: Optional[str]
    points_formula: Optional[dict[str, Any]]
    entries: list[LeagueEntryOut]
    ties: list[LeagueTieOut]


class TeamInsightsOut(AmountsOut):
    period: PeriodOut
    generated_at: datetime
    activity: TeamActivityOut
    leagues: list[LeagueOut] = Field(
        description="Kwartał, w którym leży ostatni dzień okna."
    )


_LEAGUES = (
    CompetitionType.quarterly_champions_recruiter,
    CompetitionType.quarterly_champions_dl,
)


def league_entry(
    row: dict, ctype: CompetitionType, level: AmountLevel
) -> LeagueEntryOut:
    """Wiersz rankingu ``award_ranked_rows`` (bez marży/h — ta jest wycięta
    już w serwisie). Nagroda to kwota wypłacana osobie — koszt."""
    dl = ctype is CompetitionType.quarterly_champions_dl
    prize = row.get("prize_pln")
    return LeagueEntryOut(
        rank=row.get("rank"),
        user_id=int(row["user_id"]),
        name=str(row.get("name") or ""),
        points=None if dl else int(row.get("metric_value") or 0),
        placements=int((row.get("metric_value") if dl else row.get("placements")) or 0),
        interviews=None if dl else row.get("interviews"),
        recommendations=None if dl else row.get("recommendations"),
        verifications=None if dl else row.get("verifications"),
        hit_ratio=row.get("hit_ratio") if dl else None,
        closed_requests=row.get("requests") if dl else None,
        qualified=bool(row.get("qualified", True)),
        tied=bool(row.get("tied")),
        excluded=bool(row.get("excluded")),
        prize_pln=(prize if prize is not None and level is AmountLevel.all else None),
    )


def league_out(current: dict, ctype: CompetitionType, level: AmountLevel) -> LeagueOut:
    return LeagueOut(
        type=ctype.value,
        period=str(current["period"]),
        requirement=current.get("requirement"),
        points_formula=current.get("points_formula"),
        entries=[league_entry(row, ctype, level) for row in current["full_ranking"]],
        ties=[
            LeagueTieOut(
                positions=list(tie["positions"]), user_ids=list(tie["user_ids"])
            )
            for tie in current.get("ties") or []
        ],
    )


@router.get(
    "/insights/team",
    response_model=TeamInsightsOut,
    summary="Aktywność zespołu i Liga Mistrzów (imienne rankingi widoczne każdej roli)",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def team_insights(
    request: Request,
    caller: InsightsRead,
    db: AsyncSession = Depends(get_db),
    date_from: Optional[date] = FromQuery,
    date_to: Optional[date] = ToQuery,
) -> TeamInsightsOut:
    """Ranking aktywności zespołu w oknie (top 50) i Liga Mistrzów kwartału.

    Wystawiamy wyłącznie to, co ekran pokazuje KAŻDEJ roli (decyzja D7):
    raport „Aktywność zespołu” i Ligi Mistrzów z „Rywalizacji” / górnego
    paska. Imienne KPI zespołu (precyzja, cele osób, „Do uwagi”, panel KPI
    zespołu) ekran daje tylko z ``view_team_kpi`` — tu ich nie ma.
    Liga liczy kwartał, w którym leży ostatni dzień okna.
    """
    today = business_today()
    period = _window(date_from, date_to, today)
    level = amount_level(caller)
    first, last = svc.window_days(period)
    activity = await insights_recruitment.insights_team_activity(
        current_user=None,
        db=db,
        period="custom",
        offset=0,
        anchor=None,
        date_from=first,
        date_to=last,
        limit=ACTIVITY_LIMIT,
    )
    quarter = comp_service.current_quarter_period(last)
    leagues = []
    for ctype in _LEAGUES:
        current = await competitions_routes.get_current(
            _user=None, db=db, type=ctype.value, period=quarter
        )
        leagues.append(league_out(current, ctype, level))
    outside = activity["outside_scope"]
    return TeamInsightsOut(
        **_amounts(caller).model_dump(),
        period=_period_out(period),
        generated_at=_generated_at(),
        activity=TeamActivityOut(
            entries=[
                ActivityEntryOut(**{k: entry[k] for k in ActivityEntryOut.model_fields})
                for entry in activity["entries"]
            ],
            outside_scope=ActivityOutsideOut(
                label=outside["label"],
                users=outside["users"],
                actions=outside["actions"],
                placements=outside["placements"],
            ),
            note=activity["coverage"]["note"],
        ),
        leagues=leagues,
    )


# ── Cele ─────────────────────────────────────────────────────────────────────


class GoalDefinitionOut(BaseModel):
    goal_id: str
    title: str
    short_title: str
    description: str
    period: str = Field(description="day | week | month | quarter")
    unit: str = Field(description="count | pct")
    target: Optional[float] = Field(
        description="Cel roli (domyślny albo z Ustawień); cele osobiste mogą się "
        "różnić i nie są wystawiane."
    )
    applies_to_roles: list[str]
    available: bool = Field(description="False = brak źródła danych (np. telefonii).")


class GoalProgressOut(BaseModel):
    goal_id: str
    title: str
    short_title: str
    period: str
    unit: str
    target: float
    current: Optional[float] = Field(description="null = niepoliczony, nie zero.")
    progress_pct: Optional[float]
    state: Optional[str] = Field(description="on_track | ahead | behind | hit | missed")
    expected: Optional[float] = Field(description="Ile powinno być „na teraz”.")
    note: Optional[str]


class CompanyGoalsOut(BaseModel):
    scope_label: str
    people: Optional[int] = Field(description="Aktywni rekruterzy w zespole.")
    goals: list[GoalProgressOut]


class GoalsInsightsOut(BaseModel):
    generated_at: datetime
    as_of: datetime = Field(description="Chwila, względem której liczony jest postęp.")
    definitions: list[GoalDefinitionOut]
    company_progress: CompanyGoalsOut


_DL_HIT_RATIO_GOAL = GoalDefinitionOut(
    goal_id="dl_hit_ratio_quarter",
    title="Hit ratio portfela w kwartale",
    short_title="Hit ratio",
    description=(
        "Placementy podzielone przez rekrutacje zamknięte w kwartale w portfelu "
        "Delivery Leada (jak Liga Mistrzów DL). Cel placementów = 30% "
        "zamkniętych rekrutacji, w górę. Postęp osób: liga DL w /insights/team."
    ),
    period="quarter",
    unit="pct",
    target=DL_HIT_RATIO_TARGET_PCT,
    applies_to_roles=["delivery_lead"],
    available=True,
)


@router.get(
    "/insights/goals",
    response_model=GoalsInsightsOut,
    summary="Cele KPI: definicje i postęp zespołu rekrutacji",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def goals_insights(
    request: Request,
    _caller: InsightsRead,
    db: AsyncSession = Depends(get_db),
) -> GoalsInsightsOut:
    """Katalog celów (rekruter: dzień/tydzień/miesiąc, Delivery Lead: kwartał)
    z celami ról i postęp ZESPOŁU rekrutacji — sumy celów i pracy aktywnych
    rekruterów, jak cele zespołu u Head of Recruitment. Cele i wyniki
    poszczególnych osób nie są wystawiane."""
    now = local_now()
    definitions = []
    for kpi in KPI_CATALOG:
        definitions.append(
            GoalDefinitionOut(
                goal_id=kpi.kpi_id,
                title=kpi.title_pl,
                short_title=kpi.short_title_pl,
                description=kpi.description_pl,
                period=kpi.period.value,
                unit="pct" if kpi.metric is KpiMetric.precision else "count",
                target=float(await resolve_org_target(db, kpi.kpi_id)),
                applies_to_roles=sorted(
                    role.value
                    for role, value in kpi.default_targets.items()
                    if value > 0
                ),
                available=kpi_available(kpi),
            )
        )
    definitions.append(_DL_HIT_RATIO_GOAL)
    team = await svc.company_team_goals(db, now=now)
    return GoalsInsightsOut(
        generated_at=_generated_at(),
        as_of=now,
        definitions=definitions,
        company_progress=CompanyGoalsOut(
            scope_label=team.scope_label,
            people=team.people,
            goals=[
                GoalProgressOut(
                    goal_id=goal.goal_id,
                    title=goal.title_pl,
                    short_title=goal.short_title_pl,
                    period=goal.period,
                    unit=goal.unit,
                    target=goal.target,
                    current=goal.current,
                    progress_pct=goal.progress_pct,
                    state=goal.state,
                    expected=goal.expected,
                    note=goal.note,
                )
                for goal in team.goals
            ],
        ),
    )
