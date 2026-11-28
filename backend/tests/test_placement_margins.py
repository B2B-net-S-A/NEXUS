"""Marża na liście placementów „Kto się liczy” (decyzje Artura 27.11.2026).

- Kwoty widzi „Moduł Finanse” (wszyscy klienci) i Delivery Lead (klienci
  z portfela); Head of Recruitment, TCM i rekruter — nie.
- Marża jak eksport „Placementy”: klient − koszt z kontraktu, zł/h z dnia
  startu; bez stawki klienta w kontrakcie — stawka z rekrutacji ze znakiem.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.user import User, UserRole
from app.services import placement_margins
from app.services import recruitment_activity as activity_service

pytestmark = pytest.mark.usefixtures("empty_credited_snapshot", "no_person_absences")

TODAY = date(2026, 11, 28)


def _user(user_id: int, *roles: UserRole) -> User:
    return User(
        id=user_id,
        email=f"margin-{user_id}@example.com",
        name=f"Osoba {user_id}",
        role=roles[0],
        roles=[role.value for role in roles],
        is_active=True,
        profile_completed=True,
    )


def _contract(
    contract_id: int,
    *,
    candidate_id: int = 501,
    job_id: int = 77,
    cost: str | None = "100",
    client: str | None = "150",
    start: date | None = date(2026, 11, 23),
    unit: RateUnit = RateUnit.hourly,
) -> Contract:
    return Contract(
        id=contract_id,
        candidate_id=candidate_id,
        job_id=job_id,
        client_id=41,
        rate_candidate=None if cost is None else Decimal(cost),
        rate_client=None if client is None else Decimal(client),
        rate_unit=unit,
        rate_candidate_currency="PLN",
        rate_client_currency="PLN",
        currency="PLN",
        billing_hours_per_month=168,
        start_date=start,
        status=ContractStatus.active,
    )


def _scalars(rows):
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _rows(rows):
    result = MagicMock()
    result.all.return_value = rows
    return result


# ── Kto widzi ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.admin, UserRole.finance])
async def test_finance_module_sees_every_client(role) -> None:
    audience = await placement_margins.margin_audience(AsyncMock(), _user(1, role))

    assert audience.scope == "all"
    assert audience.sees(_user(1, role), 999)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "roles",
    [
        (UserRole.head_of_recruitment,),
        (UserRole.talent_community_manager,),
        (UserRole.recruiter,),
    ],
)
async def test_head_of_recruitment_tcm_and_recruiter_get_no_amounts(
    roles, monkeypatch
) -> None:
    # Nawet z „Stawki i kwoty: podgląd” z ekranu uprawnień (reguła 24.09.2026).
    monkeypatch.setattr(placement_margins, "has_permission", lambda *_: True)
    user = _user(2, *roles)

    audience = await placement_margins.margin_audience(AsyncMock(), user)

    assert audience.scope is None
    assert not audience.sees(user, 41)


@pytest.mark.asyncio
async def test_delivery_lead_sees_only_the_portfolio(monkeypatch) -> None:
    monkeypatch.setattr(placement_margins, "has_permission", lambda *_: True)
    monkeypatch.setattr(
        "app.api.financial_access.has_permission", lambda *_: True
    )
    resolver = AsyncMock(return_value=frozenset({103, 12}))
    monkeypatch.setattr(
        placement_margins, "resolve_delivery_lead_finance_client_ids", resolver
    )
    # Druga rola (HoR) nie rozszerza portfela na całą firmę.
    user = _user(3, UserRole.delivery_lead, UserRole.head_of_recruitment)

    audience = await placement_margins.margin_audience(AsyncMock(), user)

    assert audience.scope == "portfolio"
    assert audience.sees(user, 103)
    assert not audience.sees(user, 41)


@pytest.mark.asyncio
async def test_delivery_lead_without_amounts_permission_gets_none(monkeypatch) -> None:
    monkeypatch.setattr(placement_margins, "has_permission", lambda *_: False)
    user = _user(4, UserRole.delivery_lead)

    audience = await placement_margins.margin_audience(AsyncMock(), user)

    assert audience.scope is None


@pytest.mark.asyncio
async def test_delivery_lead_with_unresolved_portfolio_fails_closed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(placement_margins, "has_permission", lambda *_: True)
    monkeypatch.setattr(
        placement_margins,
        "resolve_delivery_lead_finance_client_ids",
        AsyncMock(return_value=None),
    )

    audience = await placement_margins.margin_audience(
        AsyncMock(), _user(5, UserRole.delivery_lead)
    )

    assert audience.scope is None


# ── Ile ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_margin_from_contract_rates_on_start_day() -> None:
    db = AsyncMock()
    db.execute.side_effect = [_scalars([_contract(1)]), _rows([])]

    margins = await placement_margins.pair_margins(db, [(501, 77)], TODAY)

    margin = margins[(501, 77)]
    assert margin.per_hour == Decimal("50.00")
    assert margin.per_month == Decimal("8400.00")
    assert margin.percent == Decimal("33.3")
    assert margin.client_from_recruitment is False
    assert margin.missing is None


@pytest.mark.asyncio
async def test_negative_margin_stays_negative() -> None:
    # Kontrakt 476 na produkcji: koszt 220, klient 219 zł/h.
    db = AsyncMock()
    db.execute.side_effect = [
        _scalars([_contract(476, cost="220", client="219")]),
        _rows([]),
    ]

    margin = (await placement_margins.pair_margins(db, [(501, 77)], TODAY))[
        (501, 77)
    ]

    assert margin.per_hour == Decimal("-1.00")
    assert margin.per_month == Decimal("-168.00")


@pytest.mark.asyncio
async def test_missing_client_rate_uses_the_recruitment_rate_with_a_mark() -> None:
    db = AsyncMock()
    db.execute.side_effect = [
        _scalars([_contract(2, client=None)]),
        _rows([(501, 77, Decimal("1200"), "daily", "PLN")]),
    ]

    margin = (await placement_margins.pair_margins(db, [(501, 77)], TODAY))[
        (501, 77)
    ]

    # 1200 zł/MD ÷ 8 h = 150 zł/h.
    assert margin.client_per_hour == Decimal("150")
    assert margin.per_hour == Decimal("50.00")
    assert margin.client_from_recruitment is True


@pytest.mark.asyncio
async def test_missing_cost_or_contract_is_no_number() -> None:
    db = AsyncMock()
    db.execute.side_effect = [
        _scalars([_contract(3, cost=None, client="150")]),
        _rows([(501, 77, Decimal("150"), "hourly", "PLN")]),
    ]

    margins = await placement_margins.pair_margins(
        db, [(501, 77), (502, 78)], TODAY
    )

    assert margins[(501, 77)].per_hour is None
    assert margins[(501, 77)].missing == "missing_rates"
    assert margins[(502, 78)].missing == "no_contract"


@pytest.mark.asyncio
async def test_latest_start_wins_when_a_pair_has_two_contracts() -> None:
    db = AsyncMock()
    # Zapytanie sortuje od najpóźniejszego startu — bierzemy pierwszy.
    db.execute.side_effect = [
        _scalars(
            [
                _contract(9, cost="120", client="160", start=date(2026, 12, 1)),
                _contract(8, cost="100", client="150", start=date(2025, 2, 18)),
            ]
        ),
        _rows([]),
    ]

    margin = (await placement_margins.pair_margins(db, [(501, 77)], TODAY))[
        (501, 77)
    ]

    assert margin.per_hour == Decimal("40.00")


@pytest.mark.asyncio
async def test_no_pairs_no_queries() -> None:
    db = AsyncMock()

    assert await placement_margins.pair_margins(db, [], TODAY) == {}
    db.execute.assert_not_awaited()


# ── Lista ──────────────────────────────────────────────────────────────────


def _summary(**overrides: int) -> MagicMock:
    summary = MagicMock()
    summary.mappings.return_value.one.return_value = {
        "total": 0,
        "people": 0,
        "moved_by_credited": 0,
        **{f"state_{name}": 0 for name in activity_service.DETAIL_STATES},
        "history_total": 0,
        **overrides,
    }
    return summary


def _mapped(rows):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    result.scalars.return_value.all.return_value = rows
    return result


def _detail_row(candidate_id: int, job_id: int, client_id: int) -> dict:
    return {
        "candidate_id": candidate_id,
        "candidate_name": "Anna Przykładowa",
        "job_id": job_id,
        "job_title": "Java Developer",
        "job_working_title": None,
        "job_client_reference": None,
        "client_name": "Bank Przykładowy",
        "client_id": client_id,
        "credit_user": 11,
        "credit_user_name": "Osoba 11",
        "credit_user_role": "recruiter",
        "reached_at": datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc),
        "mover_id": None,
        "mover_name": None,
        "mover_role": None,
        "state": "hired",
        "latest_stage": "hired",
        "latest_at": datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc),
        "state_stage_name": "Zatrudniony",
        "reason_name": None,
        "candidate_jobs": 1,
        "client_interview_at": None,
        "client_interview_tentative_at": None,
        "start_on": date(2026, 11, 23),
    }


async def _placements(db, user):
    return await activity_service.list_recruitment_activity_details(
        db,
        user,
        metric="placement",
        window="month",
        selected_day=date(2026, 11, 28),
        selected_month=date(2026, 11, 1),
        subject_user_id=None,
        team_scope=True,
        page=1,
        page_size=25,
    )


@pytest.mark.asyncio
async def test_delivery_lead_list_hides_amounts_outside_the_portfolio(
    monkeypatch,
) -> None:
    lead = _user(30, UserRole.delivery_lead)
    monkeypatch.setattr(
        activity_service,
        "margin_audience",
        AsyncMock(
            return_value=placement_margins.MarginAudience(
                "portfolio", frozenset({103})
            )
        ),
    )
    monkeypatch.setattr(
        placement_margins.MarginAudience,
        "sees",
        lambda self, _user, client_id: client_id in (self.client_ids or set()),
    )
    margins = AsyncMock(
        return_value={(501, 77): placement_margins.PairMargin(per_hour=Decimal("20"))}
    )
    monkeypatch.setattr(activity_service, "pair_margins", margins)
    db = AsyncMock()
    db.execute.side_effect = [
        _mapped([lead]),
        _summary(total=2, people=2, state_hired=2),
        _mapped([]),  # klienci filtra
        _mapped([_detail_row(501, 77, 103), _detail_row(502, 78, 41)]),
        _mapped(
            [
                {"candidate_id": 501, "job_id": 77, "client_id": 103},
                {"candidate_id": 502, "job_id": 78, "client_id": 41},
            ]
        ),
    ]

    result = await _placements(db, lead)

    assert margins.await_args.args[1] == {(501, 77)}
    assert result.margin_scope == "portfolio"
    assert result.items[0].margin is not None
    assert result.items[0].margin.per_hour == 20.0
    assert result.items[0].margin_hidden is False
    assert result.items[1].margin is None
    assert result.items[1].margin_hidden is True
    assert result.margin_summary is not None
    assert result.margin_summary.counted == 1
    assert result.margin_summary.hidden == 1
    assert result.margin_summary.per_month == 3360.0


@pytest.mark.asyncio
async def test_list_without_amount_rights_carries_no_margin(monkeypatch) -> None:
    head = _user(31, UserRole.head_of_recruitment)
    margins = AsyncMock()
    monkeypatch.setattr(activity_service, "pair_margins", margins)
    db = AsyncMock()
    db.execute.side_effect = [
        _mapped([head]),
        _summary(total=1, people=1, state_hired=1),
        _mapped([]),
        _mapped([_detail_row(501, 77, 103)]),
    ]

    result = await _placements(db, head)

    margins.assert_not_awaited()
    assert result.margin_scope is None
    assert result.margin_summary is None
    assert result.items[0].margin is None
    assert result.items[0].margin_hidden is False
    payload = result.model_dump()
    assert payload["items"][0]["margin"] is None


@pytest.mark.asyncio
async def test_list_row_carries_the_stage_name() -> None:
    recruiter = _user(11, UserRole.recruiter)
    row = {
        **_detail_row(501, 77, 103),
        "state": "before_client",
        "latest_stage": "interview",
        "state_stage_name": "Wysłać do Cpro",
    }
    db = AsyncMock()
    db.execute.side_effect = [
        _mapped([recruiter]),
        _summary(total=1, people=1, state_before_client=1),
        _mapped([row]),
    ]

    result = await activity_service.list_recruitment_activity_details(
        db,
        recruiter,
        metric="verification",
        window="month",
        selected_day=date(2026, 11, 28),
        selected_month=date(2026, 11, 1),
        subject_user_id=None,
        team_scope=False,
        page=1,
        page_size=25,
    )

    assert result.items[0].state_stage_name == "Wysłać do Cpro"
    assert result.margin_scope is None


def test_dropped_stage_is_read_only_for_ended_pairs() -> None:
    sql = activity_service._DESCRIBED_CTE
    assert "coalesce(dropped.stage_def_id, latest.stage_def_id)" in sql
    assert "WHERE latest.stage IN ('rejected', 'withdrawn')" in sql
