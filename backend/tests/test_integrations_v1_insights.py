"""API v1 — Insights (scope ``insights:read``).

Bez bazy: okno ``from``/``to`` (domyślnie poprzedni pełny miesiąc, jeden
parametr bez drugiego i okno ponad 366 dni = 422), cięcie na miesiące,
dzień wyceny, kwoty na trzech poziomach klucza (przychód od sprzedaży,
koszt, marża i nagrody konkursów tylko z ``amounts:read``), zejścia tą samą
definicją co tabele rok do roku, lejek bez wolnego tekstu notatek.

Na bazie (CI): każda trasa — kształt, filtr okresu, kwoty na poziomach
none/sales/all, 403 bez scope'u, 404 dla rekrutacji ukrytego klienta.

Dane są zmyślone (repo jest publiczne). Baza testowa jest wspólna
i nieczyszczona: testy biorą lata, których nie używa nikt inny (1977–1979),
a liczby sprawdzają na własnym kliencie i własnej rekrutacji.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.analytics.periods import PeriodError
from app.api.deps import Caller
from app.api.integrations_v1 import insights as v1_insights
from app.api.integrations_v1.common import AmountLevel
from app.models.competition_winner import CompetitionType
from app.models.contract import ContractStatus, ContractTerminationReason
from app.services import integration_insights as svc
from app.services.insights_board_yoy import _departures_by_month
from app.services.service_account_auth import ServicePrincipal

V1 = "/api/integrations/v1"
WARSAW = ZoneInfo("Europe/Warsaw")


def _caller(*scopes: str) -> Caller:
    return Caller(
        service=ServicePrincipal(
            account_id=1, slug="test", key_id="v2$00", scopes=frozenset(scopes)
        )
    )


# ── Bez bazy: okno i miesiące ────────────────────────────────────────────────


class TestWindow:
    def test_without_parameters_it_is_the_previous_full_month(self):
        period = svc.resolve_window(None, None, today=date(2026, 10, 15))
        assert svc.window_days(period) == (date(2026, 9, 1), date(2026, 9, 30))

    def test_january_falls_back_to_december_of_the_previous_year(self):
        period = svc.resolve_window(None, None, today=date(2027, 1, 1))
        assert svc.window_days(period) == (date(2026, 12, 1), date(2026, 12, 31))

    @pytest.mark.parametrize(
        "date_from,date_to",
        [(date(2026, 1, 1), None), (None, date(2026, 1, 31))],
    )
    def test_one_end_without_the_other_is_an_error(self, date_from, date_to):
        with pytest.raises(PeriodError):
            svc.resolve_window(date_from, date_to, today=date(2026, 10, 15))

    def test_window_longer_than_366_days_is_an_error(self):
        with pytest.raises(PeriodError):
            svc.resolve_window(
                date(2025, 1, 1), date(2026, 1, 2), today=date(2026, 10, 15)
            )

    def test_reversed_window_is_an_error(self):
        with pytest.raises(PeriodError):
            svc.resolve_window(
                date(2026, 2, 1), date(2026, 1, 1), today=date(2026, 10, 15)
            )

    def test_custom_window_is_inclusive_on_both_ends(self):
        period = svc.resolve_window(
            date(2026, 1, 15), date(2026, 3, 10), today=date(2026, 10, 15)
        )
        assert svc.window_days(period) == (date(2026, 1, 15), date(2026, 3, 10))
        assert period.start == datetime(2026, 1, 15, tzinfo=WARSAW)
        assert period.end == datetime(2026, 3, 11, tzinfo=WARSAW)

    def test_route_maps_period_errors_to_422_invalid_period(self):
        with pytest.raises(HTTPException) as exc:
            v1_insights._window(date(2026, 1, 1), None, date(2026, 10, 15))
        assert exc.value.status_code == 422
        assert exc.value.detail["error"] == "invalid_period"


class TestMonthSlices:
    def test_months_are_clipped_to_the_window(self):
        period = svc.resolve_window(
            date(2026, 1, 15), date(2026, 3, 10), today=date(2026, 10, 15)
        )
        slices = svc.month_slices(period, today=date(2026, 10, 15))
        assert [(s.month, s.date_from, s.date_to, s.complete) for s in slices] == [
            ("2026-01", date(2026, 1, 15), date(2026, 1, 31), False),
            ("2026-02", date(2026, 2, 1), date(2026, 2, 28), True),
            ("2026-03", date(2026, 3, 1), date(2026, 3, 10), False),
        ]

    def test_month_in_progress_is_not_complete(self):
        period = svc.resolve_window(
            date(2026, 10, 1), date(2026, 10, 31), today=date(2026, 10, 15)
        )
        (only,) = svc.month_slices(period, today=date(2026, 10, 15))
        assert only.complete is False

    def test_full_year_window_gives_thirteen_slices_at_most(self):
        period = svc.resolve_window(
            date(2025, 6, 15), date(2026, 6, 15), today=date(2026, 10, 15)
        )
        slices = svc.month_slices(period, today=date(2026, 10, 15))
        assert len(slices) == 13
        assert slices[0].date_from == date(2025, 6, 15)
        assert slices[-1].date_to == date(2026, 6, 15)

    def test_slice_period_covers_exactly_its_days(self):
        period = svc.resolve_window(
            date(2026, 2, 1), date(2026, 2, 28), today=date(2026, 10, 15)
        )
        (only,) = svc.month_slices(period, today=date(2026, 10, 15))
        assert only.period.start == period.start
        assert only.period.end == period.end


class TestValuationDay:
    def test_past_slice_is_valued_on_its_last_day(self):
        assert svc.valuation_day(
            date(2026, 1, 1), date(2026, 1, 31), date(2026, 10, 15)
        ) == date(2026, 1, 31)

    def test_slice_in_progress_is_valued_today(self):
        assert svc.valuation_day(
            date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 15)
        ) == date(2026, 10, 15)

    def test_future_slice_has_no_valuation(self):
        assert (
            svc.valuation_day(date(2026, 11, 1), date(2026, 11, 30), date(2026, 10, 15))
            is None
        )


# ── Bez bazy: zejścia i wejścia ──────────────────────────────────────────────


def _contract(**extra):
    values = {
        "status": ContractStatus.active,
        "start_date": date(2026, 1, 10),
        "end_date": None,
        "terminated_at": None,
        "termination_reason": None,
        "client_id": 1,
    }
    values.update(extra)
    return SimpleNamespace(**values)


_CONTRACTS = [
    _contract(),
    _contract(
        status=ContractStatus.ended,
        start_date=date(2025, 5, 1),
        end_date=date(2026, 2, 14),
        termination_reason=ContractTerminationReason.consultant_resigned,
    ),
    _contract(
        status=ContractStatus.ended,
        start_date=date(2025, 5, 1),
        end_date=None,
        terminated_at=date(2026, 3, 3),
        termination_reason=ContractTerminationReason.poached_by_client,
    ),
    # Aneks przedłużenia: pierwsze wypowiedzenie zostaje w `terminated_at`,
    # a decyduje data końca umowy.
    _contract(
        status=ContractStatus.ended,
        start_date=date(2025, 5, 1),
        end_date=date(2026, 6, 30),
        terminated_at=date(2026, 2, 1),
    ),
    # Kończący się kontrakt nie jest zejściem, dopóki nie ma statusu `ended`.
    _contract(status=ContractStatus.ending, end_date=date(2026, 2, 20)),
]


class TestContractFlows:
    def test_departures_match_the_year_over_year_definition(self):
        departures, resignations, _ = _departures_by_month(_CONTRACTS)
        for year, month in [(2026, 2), (2026, 3), (2026, 6)]:
            first = date(year, month, 1)
            last = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
            flows = svc.contract_flows(_CONTRACTS, first, last - timedelta(days=1))
            assert flows.ends == departures.get((year, month), 0)
            assert flows.resignations == resignations.get((year, month), 0)

    def test_starts_ends_and_resignations_in_a_window(self):
        flows = svc.contract_flows(_CONTRACTS, date(2026, 1, 1), date(2026, 3, 31))
        assert flows == svc.ContractFlows(starts=2, ends=2, resignations=1)

    def test_departure_day_prefers_the_end_date(self):
        assert svc.departure_day(_CONTRACTS[3]) == date(2026, 6, 30)
        assert svc.departure_day(_CONTRACTS[2]) == date(2026, 3, 3)
        assert svc.departure_day(_CONTRACTS[4]) is None


def _priced(contract_id, client_id, start, end, client_rate, candidate_rate, **extra):
    """Kontrakt w pamięci (bez bazy) ze stawkami miesięcznymi w PLN."""
    from app.models.candidate import Candidate
    from app.models.contract import Contract, RateUnit

    contract = Contract(
        id=contract_id,
        client_id=client_id,
        status=extra.pop("status", ContractStatus.ended),
        start_date=start,
        end_date=end,
        rate_client=Decimal(client_rate),
        rate_candidate=Decimal(candidate_rate),
        rate_unit=RateUnit.monthly,
        **extra,
    )
    contract.candidate = Candidate(
        id=1000 + contract_id,
        name="Osoba",
        lastname=f"Testowa-{contract_id}",
        email=f"osoba-{contract_id}@example.com",
    )
    contract.candidate_rate_schedule = []
    contract.client_rate_schedule = []
    contract.framework_rate_schedule = []
    return contract


async def test_contract_report_values_months_and_client_groups(monkeypatch):
    """Wycena per miesiąc i per grupa klienta — ta sama ``fold_money`` co
    kokpit Rady; klient spoza listy (grupa ``None``) liczy się raz w sumie."""

    async def pln_only(_db, by_date):
        return {day: {"PLN": Decimal("1")} for day in by_date}

    monkeypatch.setattr(svc, "rates_to_pln_by_date", pln_only)
    contracts = [
        _priced(
            1,
            10,
            date(2025, 1, 10),
            date(2025, 2, 15),
            "20000",
            "15000",
            termination_reason=ContractTerminationReason.consultant_resigned,
        ),
        _priced(2, 10, date(2024, 6, 1), date(2025, 12, 31), "10000", "8000"),
        _priced(3, 20, date(2025, 1, 5), date(2025, 12, 31), "12000", "9000"),
    ]
    today = date(2025, 10, 15)
    period = svc.resolve_window(date(2025, 1, 1), date(2025, 2, 28), today=today)
    slices = svc.month_slices(period, today=today)

    report = await svc.contract_report(
        None,
        contracts,
        slices,
        today=today,
        group_key=lambda client_id: client_id if client_id == 10 else None,
    )

    january, february = report.months
    assert january.flows == svc.ContractFlows(starts=2, ends=0, resignations=0)
    assert february.flows == svc.ContractFlows(starts=0, ends=1, resignations=1)
    assert january.money.valuation_day == date(2025, 1, 31)
    assert january.money.revenue == Decimal("42000")
    assert january.money.margin == Decimal("10000")
    assert january.money.consultants == 3
    # 28 lutego Ola już nie pracuje.
    assert february.money.revenue == Decimal("22000")
    assert report.window_valuation_day == date(2025, 2, 28)

    mine = report.groups[10]
    assert mine.flows == svc.ContractFlows(starts=1, ends=1, resignations=1)
    assert (mine.money.revenue, mine.money.cost, mine.money.margin) == (
        Decimal("10000"),
        Decimal("8000"),
        Decimal("2000"),
    )
    assert mine.money.margin_pct == 20.0
    assert mine.money.consultants == 1
    assert report.groups[None].flows.starts == 1
    assert report.groups[None].money.revenue == Decimal("12000")


# ── Bez bazy: kwoty ──────────────────────────────────────────────────────────

_SNAPSHOT = svc.MoneySnapshot(
    valuation_day=date(2026, 1, 31),
    revenue=Decimal("20000"),
    cost=Decimal("15000"),
    margin=Decimal("5000"),
    margin_pct=25.0,
    consultants=1,
    active_contracts=1,
    priced_contracts=1,
    contracts_without_cost_leg=0,
    contracts_without_revenue_leg=0,
    complete=True,
    missing_currencies=(),
)


class TestMoneyLevels:
    def test_without_amounts_every_amount_is_null(self):
        out = v1_insights.money_out(_SNAPSHOT, AmountLevel.none)
        assert out.revenue_monthly_pln is None
        assert out.consultant_cost_monthly_pln is None
        assert out.margin_monthly_pln is None
        assert out.margin_pct is None
        assert out.valuation_day == date(2026, 1, 31)

    def test_sales_level_shows_revenue_only(self):
        out = v1_insights.money_out(_SNAPSHOT, AmountLevel.sales)
        assert out.revenue_monthly_pln == Decimal("20000")
        assert out.consultant_cost_monthly_pln is None
        assert out.margin_monthly_pln is None
        assert out.margin_pct is None

    def test_all_amounts(self):
        out = v1_insights.money_out(_SNAPSHOT, AmountLevel.all)
        assert out.revenue_monthly_pln == Decimal("20000")
        assert out.consultant_cost_monthly_pln == Decimal("15000")
        assert out.margin_monthly_pln == Decimal("5000")
        assert out.margin_pct == 25.0
        assert out.model_dump(mode="json")["margin_monthly_pln"] == "5000.00"

    def test_no_valuation_means_no_money_object(self):
        assert v1_insights.money_out(None, AmountLevel.all) is None

    @pytest.mark.parametrize(
        "scopes,level,sales_redacted,costs_redacted",
        [
            (("insights:read",), "none", True, True),
            (("insights:read", "sales_amounts:read"), "sales", False, True),
            (("insights:read", "amounts:read"), "all", False, False),
        ],
    )
    def test_amount_flags(self, scopes, level, sales_redacted, costs_redacted):
        flags = v1_insights._amounts(_caller(*scopes))
        assert flags.amount_level == level
        assert flags.sales_redacted is sales_redacted
        assert flags.costs_redacted is costs_redacted


_RECRUITER_ROW = {
    "user_id": 7,
    "name": "Jan Testowy",
    "metric_value": 385,
    "hit_ratio": None,
    "role": "recruiter",
    "placements": 3,
    "interviews": 5,
    "recommendations": 10,
    "verifications": 20,
    "qualified": True,
    "required_placements": 3,
    "disqualification_reasons": [],
    "rank": 1,
    "tied": False,
    "excluded": False,
    "prize_pln": 5000,
}
_DL_ROW = {
    "user_id": 8,
    "name": "Ewa Przykładowa",
    "metric_value": 4,
    "hit_ratio": 40.0,
    "requests": 10,
    "requests_basis": "closed_in_quarter",
    "rank": 1,
    "tied": False,
    "excluded": False,
    "prize_pln": 5000,
}


class TestLeagueEntries:
    @pytest.mark.parametrize("level", [AmountLevel.none, AmountLevel.sales])
    def test_prize_is_a_cost(self, level):
        entry = v1_insights.league_entry(
            _RECRUITER_ROW, CompetitionType.quarterly_champions_recruiter, level
        )
        assert entry.prize_pln is None

    def test_prize_with_all_amounts(self):
        entry = v1_insights.league_entry(
            _RECRUITER_ROW,
            CompetitionType.quarterly_champions_recruiter,
            AmountLevel.all,
        )
        assert entry.prize_pln == Decimal("5000")

    def test_recruiter_league_points_and_counts(self):
        entry = v1_insights.league_entry(
            _RECRUITER_ROW,
            CompetitionType.quarterly_champions_recruiter,
            AmountLevel.none,
        )
        assert (entry.points, entry.placements, entry.interviews) == (385, 3, 5)
        assert entry.hit_ratio is None and entry.closed_requests is None

    def test_dl_league_placements_and_hit_ratio(self):
        entry = v1_insights.league_entry(
            _DL_ROW, CompetitionType.quarterly_champions_dl, AmountLevel.none
        )
        assert entry.points is None
        assert (entry.placements, entry.hit_ratio, entry.closed_requests) == (
            4,
            40.0,
            10,
        )
        assert entry.qualified is True

    def test_unplaced_person_has_no_rank_and_no_prize(self):
        row = {**_RECRUITER_ROW, "rank": None, "prize_pln": None, "qualified": False}
        entry = v1_insights.league_entry(
            row, CompetitionType.quarterly_champions_recruiter, AmountLevel.all
        )
        assert entry.rank is None and entry.prize_pln is None
        assert entry.qualified is False


def test_funnel_drops_free_text_details_of_other_reasons():
    raw = {
        "rows": [
            {
                "column": "new",
                "column_label": "Nowi",
                "key": "added",
                "label": "Dodani",
                "is_main": True,
                "reached": 4,
                "now": 2,
            }
        ],
        "closed_by": [
            {
                "key": "recruiter",
                "label": "Odrzucony przez nas",
                "count": 3,
                "top_reasons": [
                    {
                        "label": "Inne",
                        "count": 3,
                        "kind": "other",
                        "details": ["Pan Testowy wybrał inną ofertę"],
                    }
                ],
            }
        ],
    }
    out = v1_insights.funnel_out(raw)
    dumped = out.model_dump()
    assert dumped["stages"][0]["reached"] == 4
    assert dumped["closed"][0]["reasons"] == [
        {"label": "Inne", "count": 3, "kind": "other"}
    ]
    assert "Pan Testowy" not in str(dumped)


# ── Na bazie ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _insights_uncached(monkeypatch):
    """Trasy ekranu Insights i cele zespołu cache'ują wynik per okno w procesie.

    Testy na wspólnej bazie dosiewają dane i pytają o to samo okno — z cache'em
    dostawałyby wynik poprzedniego testu.
    """
    from app.api import insights_charts, insights_recruitment, insights_stage_breakdown

    for module in (insights_charts, insights_recruitment, insights_stage_breakdown):
        monkeypatch.setattr(module, "CACHE_TTL_SECONDS", -1)
    monkeypatch.setattr(svc, "GOALS_CACHE_TTL_SECONDS", -1)


def _h(api_key: str) -> dict:
    return {"X-API-Key": api_key}


async def _key(app_client: AsyncClient, headers: dict, scopes: list[str]) -> str:
    from tests.test_service_accounts import _account_with_key

    _, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return api_key


def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, tzinfo=WARSAW)


async def _recruitment_world(*, hidden_client: bool = False) -> dict:
    """Rekrutacja 1978: trzy osoby, zatrudnienie, odrzucenie z powodem."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineTemplate,
        RejectionReason,
        TerminalType,
    )
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"V1 Insights rekrutacja {tag}", hidden=hidden_client)
        template = PipelineTemplate(name=f"V1 insights {tag}")
        db.add_all([client, template])
        await db.flush()
        reason = RejectionReason(
            template_id=template.id,
            name=f"Za mało doświadczenia {tag}",
            category=TerminalType.rejected,
        )
        job = Job(
            title=f"Analityk danych {tag}",
            client_id=client.id,
            status=JobStatus.published,
        )
        anna = Candidate(name="Anna", lastname=f"Przykładowa-{tag}")
        jan = Candidate(name="Jan", lastname=f"Testowy-{tag}")
        ewa = Candidate(name="Ewa", lastname=f"Wzorcowa-{tag}")
        db.add_all([reason, job, anna, jan, ewa])
        await db.flush()

        def move(candidate, stage, when, **extra):
            return CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=stage,
                moved_at=when,
                **extra,
            )

        db.add_all(
            [
                move(anna, PipelineStage.new, _at(1978, 1, 5)),
                move(anna, PipelineStage.verified, _at(1978, 1, 10)),
                move(anna, PipelineStage.cv_sent, _at(1978, 1, 20)),
                move(anna, PipelineStage.client_interview, _at(1978, 2, 3)),
                move(anna, PipelineStage.hired, _at(1978, 2, 10)),
                move(jan, PipelineStage.new, _at(1978, 1, 6)),
                move(
                    jan,
                    PipelineStage.rejected,
                    _at(1978, 2, 12),
                    rejection_reason_id=reason.id,
                    ended_by="recruiter",
                ),
                move(ewa, PipelineStage.new, _at(1977, 12, 20)),
                move(ewa, PipelineStage.verified, _at(1978, 1, 15)),
            ]
        )
        await db.commit()
        return {"job_id": job.id, "reason": reason.name}


def _reached(funnel: dict) -> dict:
    return {row["key"]: row["reached"] for row in funnel["stages"]}


def _closed(funnel: dict) -> dict:
    return {group["key"]: group for group in funnel["closed"]}


class TestRecruitmentRoute:
    async def test_job_funnel_totals_months_and_reasons(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _recruitment_world()
        api_key = await _key(app_client, app_auth_headers, ["insights:read"])
        resp = await app_client.get(
            f"{V1}/insights/recruitment",
            headers=_h(api_key),
            params={
                "from": "1978-01-01",
                "to": "1978-02-28",
                "job_id": world["job_id"],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["period"]["from"] == "1978-01-01"
        assert body["period"]["to"] == "1978-02-28"
        assert body["period"]["timezone"] == "Europe/Warsaw"
        assert body["job_id"] == world["job_id"]
        assert body["generated_at"]
        assert body["definitions"]["placements"] == "first_hired_per_candidate_job"

        totals = _reached(body["totals"])
        # Ewa weszła do rekrutacji w grudniu — w oknie tylko jej weryfikacja.
        assert totals["added"] == 2
        assert totals["verified"] == 2
        assert totals["cv_sent"] == 1
        assert totals["client_interview"] == 1
        assert totals["hired"] == 1
        recruiter = _closed(body["totals"])["recruiter"]
        assert recruiter["count"] == 1
        assert [r["label"] for r in recruiter["reasons"]] == [world["reason"]]
        assert "details" not in recruiter["reasons"][0]

        months = body["months"]
        assert [m["month"] for m in months] == ["1978-01", "1978-02"]
        assert all(m["complete"] for m in months)
        january, february = (_reached(m) for m in months)
        assert (january["added"], january["verified"], january["cv_sent"]) == (2, 2, 1)
        assert (february["client_interview"], february["hired"]) == (1, 1)
        assert january["hired"] == 0
        assert _closed(months[1])["recruiter"]["count"] == 1
        assert _closed(months[0])["recruiter"]["count"] == 0

        now = {row["key"]: row["now"] for row in body["current"]}
        assert now["hired"] == 1
        assert now["verified"] == 1

    async def test_window_outside_the_activity_is_all_zero(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _recruitment_world()
        api_key = await _key(app_client, app_auth_headers, ["insights:read"])
        resp = await app_client.get(
            f"{V1}/insights/recruitment",
            headers=_h(api_key),
            params={
                "from": "1978-03-01",
                "to": "1978-03-31",
                "job_id": world["job_id"],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(_reached(body["totals"]).values()) == {0}
        assert len(body["months"]) == 1

    async def test_hidden_client_job_is_404(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _recruitment_world(hidden_client=True)
        api_key = await _key(app_client, app_auth_headers, ["insights:read"])
        resp = await app_client.get(
            f"{V1}/insights/recruitment",
            headers=_h(api_key),
            params={"job_id": world["job_id"]},
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "not_found"

    @pytest.mark.parametrize(
        "params",
        [
            {"from": "1978-01-01"},
            {"from": "1977-01-01", "to": "1978-01-02"},
            {"from": "1978-02-01", "to": "1978-01-01"},
        ],
    )
    async def test_bad_window_is_422_invalid_period(
        self, app_client: AsyncClient, app_auth_headers: dict, params: dict
    ):
        api_key = await _key(app_client, app_auth_headers, ["insights:read"])
        resp = await app_client.get(
            f"{V1}/insights/recruitment", headers=_h(api_key), params=params
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "invalid_period"

    async def test_default_window_is_the_previous_month(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        from app.core.scheduling import business_today

        api_key = await _key(app_client, app_auth_headers, ["insights:read"])
        resp = await app_client.get(f"{V1}/insights/recruitment", headers=_h(api_key))
        assert resp.status_code == 200, resp.text
        first_of_month = business_today().replace(day=1)
        last = first_of_month - timedelta(days=1)
        assert resp.json()["period"]["from"] == last.replace(day=1).isoformat()
        assert resp.json()["period"]["to"] == last.isoformat()


async def _placements_world() -> dict:
    """Klient 1977: placement, wejście, rezygnacja i konsultant w dniu wyceny.

    Kontrakty mają status ``ended`` z datą końca w 1977 — nie wchodzą do
    dzisiejszych sum innych testów.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract
    from app.models.contract_candidate_rate import ContractCandidateRate
    from app.models.contract_client_rate import ContractClientRate
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"V1 Insights placementy {tag}")
        hidden = Client(name=f"V1 Insights ukryty {tag}", hidden=True)
        ola = Candidate(name="Ola", lastname=f"Testowa-{tag}")
        piotr = Candidate(name="Piotr", lastname=f"Przykładowy-{tag}")
        marek = Candidate(name="Marek", lastname=f"Wzorcowy-{tag}")
        db.add_all([client, hidden, ola, piotr, marek])
        await db.flush()
        job = Job(
            title=f"Tester {tag}", client_id=client.id, status=JobStatus.published
        )
        db.add(job)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=ola.id,
                job_id=job.id,
                stage=PipelineStage.hired,
                moved_at=_at(1977, 1, 20),
            )
        )
        leaving = Contract(
            candidate_id=ola.id,
            client_id=client.id,
            status=ContractStatus.ended,
            start_date=date(1977, 1, 10),
            end_date=date(1977, 2, 15),
            termination_reason=ContractTerminationReason.consultant_resigned,
        )
        staying = Contract(
            candidate_id=piotr.id,
            client_id=client.id,
            status=ContractStatus.ended,
            start_date=date(1976, 6, 1),
            end_date=date(1977, 12, 31),
        )
        elsewhere = Contract(
            candidate_id=marek.id,
            client_id=hidden.id,
            status=ContractStatus.ended,
            start_date=date(1977, 1, 5),
            end_date=date(1977, 12, 31),
        )
        db.add_all([leaving, staying, elsewhere])
        await db.flush()
        for contract, client_rate, candidate_rate in (
            (leaving, "20000", "15000"),
            (staying, "10000", "8000"),
            (elsewhere, "12000", "9000"),
        ):
            db.add_all(
                [
                    ContractClientRate(
                        contract_id=contract.id,
                        rate=Decimal(client_rate),
                        effective_from=contract.start_date,
                    ),
                    ContractCandidateRate(
                        contract_id=contract.id,
                        rate=Decimal(candidate_rate),
                        effective_from=contract.start_date,
                    ),
                ]
            )
        await db.commit()
        return {"client_id": client.id, "hidden_id": hidden.id}


class TestPlacementsRoute:
    async def test_months_clients_and_money_on_three_levels(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _placements_world()
        params = {"from": "1977-01-01", "to": "1977-02-28"}
        bodies = {}
        for name, scopes in (
            ("none", ["insights:read"]),
            ("sales", ["insights:read", "sales_amounts:read"]),
            ("all", ["insights:read", "amounts:read"]),
        ):
            api_key = await _key(app_client, app_auth_headers, scopes)
            resp = await app_client.get(
                f"{V1}/insights/placements", headers=_h(api_key), params=params
            )
            assert resp.status_code == 200, resp.text
            bodies[name] = resp.json()

        body = bodies["all"]
        assert body["amount_level"] == "all"
        assert body["window_valuation_day"] == "1977-02-28"
        assert body["definitions"]["ends"] == "ended_contracts_by_effective_end_date"
        assert body["coverage_note"]
        assert [m["month"] for m in body["months"]] == ["1977-01", "1977-02"]
        january, february = body["months"]
        assert january["placements"] >= 1 and january["starts"] >= 2
        assert february["ends"] >= 1 and february["resignations"] >= 1
        assert january["money"]["valuation_day"] == "1977-01-31"
        assert january["consultants"] >= 3

        clients = {c["client_id"]: c for c in body["clients"]}
        mine = clients[world["client_id"]]
        assert mine["name"].startswith("V1 Insights placementy")
        assert (mine["placements"], mine["starts"], mine["ends"]) == (1, 1, 1)
        assert mine["resignations"] == 1
        # W dniu wyceny okna (28.02) pracuje już tylko Piotr.
        assert mine["consultants"] == 1
        assert mine["money"]["revenue_monthly_pln"] == "10000.00"
        assert mine["money"]["consultant_cost_monthly_pln"] == "8000.00"
        assert mine["money"]["margin_monthly_pln"] == "2000.00"
        assert mine["money"]["margin_pct"] == 20.0
        # Klient ukryty nie istnieje dla klucza — jego wejście idzie do wiersza
        # bez klienta, więc sumy dalej się zgadzają.
        assert world["hidden_id"] not in clients
        assert clients[None]["starts"] >= 1
        assert body["clients"][-1]["client_id"] is None

        sales = {c["client_id"]: c for c in bodies["sales"]["clients"]}
        sales_money = sales[world["client_id"]]["money"]
        assert bodies["sales"]["costs_redacted"] is True
        assert sales_money["revenue_monthly_pln"] == "10000.00"
        assert sales_money["consultant_cost_monthly_pln"] is None
        assert sales_money["margin_monthly_pln"] is None
        assert sales_money["margin_pct"] is None

        none = {c["client_id"]: c for c in bodies["none"]["clients"]}
        none_money = none[world["client_id"]]["money"]
        assert bodies["none"]["sales_redacted"] is True
        assert none_money["revenue_monthly_pln"] is None
        assert none_money["margin_monthly_pln"] is None
        # Liczby bez kwot zostają.
        assert none[world["client_id"]]["consultants"] == 1
        for month in bodies["none"]["months"]:
            assert month["money"]["revenue_monthly_pln"] is None

    async def test_future_window_has_no_valuation(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(
            app_client, app_auth_headers, ["insights:read", "amounts:read"]
        )
        resp = await app_client.get(
            f"{V1}/insights/placements",
            headers=_h(api_key),
            params={"from": "2953-01-01", "to": "2953-01-31"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["window_valuation_day"] is None
        assert body["months"][0]["money"] is None
        assert body["months"][0]["consultants"] is None


class TestTeamRoute:
    async def test_activity_and_both_leagues_of_the_window_quarter(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        api_key = await _key(app_client, app_auth_headers, ["insights:read"])
        resp = await app_client.get(
            f"{V1}/insights/team",
            headers=_h(api_key),
            params={"from": "1979-01-01", "to": "1979-02-28"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["period"]["from"] == "1979-01-01"
        assert body["amount_level"] == "none"
        assert isinstance(body["activity"]["entries"], list)
        assert set(body["activity"]["outside_scope"]) == {
            "label",
            "users",
            "actions",
            "placements",
        }
        assert body["activity"]["note"]
        leagues = {league["type"]: league for league in body["leagues"]}
        assert set(leagues) == {
            "quarterly_champions_recruiter",
            "quarterly_champions_dl",
        }
        assert {league["period"] for league in leagues.values()} == {"Q1 1979"}
        for league in leagues.values():
            for entry in league["entries"]:
                assert entry["prize_pln"] is None


class TestGoalsRoute:
    async def test_definitions_and_team_progress(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        from app.services.kpi_catalog import KPI_CATALOG

        api_key = await _key(app_client, app_auth_headers, ["insights:read"])
        resp = await app_client.get(f"{V1}/insights/goals", headers=_h(api_key))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["generated_at"] and body["as_of"]
        definitions = {d["goal_id"]: d for d in body["definitions"]}
        assert {k.kpi_id for k in KPI_CATALOG} <= set(definitions)
        assert definitions["monthly_placements"]["applies_to_roles"] == ["recruiter"]
        assert definitions["monthly_precision"]["unit"] == "pct"
        assert definitions["dl_hit_ratio_quarter"]["target"] == 30.0
        progress = body["company_progress"]
        assert progress["scope_label"] == "Zespół rekrutacji"
        assert isinstance(progress["goals"], list)
        assert "rows" not in progress


_ROUTES = [
    "/insights/recruitment",
    "/insights/placements",
    "/insights/team",
    "/insights/goals",
]


class TestScope:
    @pytest.mark.parametrize("path", _ROUTES)
    async def test_other_scope_is_403(
        self, app_client: AsyncClient, app_auth_headers: dict, path: str
    ):
        api_key = await _key(app_client, app_auth_headers, ["academy:read"])
        resp = await app_client.get(f"{V1}{path}", headers=_h(api_key))
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "insufficient_scope"

    @pytest.mark.parametrize("path", _ROUTES)
    async def test_user_jwt_is_401(
        self, app_client: AsyncClient, app_auth_headers: dict, path: str
    ):
        resp = await app_client.get(f"{V1}{path}", headers=app_auth_headers)
        assert resp.status_code == 401, resp.text
