"""Filtry wyników zespołu: rola i klient (decyzja Artura z 10.11.2026).

Reguła: ``services/team_filters.py``; opis w
``docs/claude/finanse-insights/filtry-rola-i-klient.md``.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import cache as cache_module
from app.models.user import User, UserRole
from app.services import recruitment_activity as activity_service
from app.services.insights_team_signals import (
    FILTERED_OUT_LABEL,
    TeamPeople,
    people_payload,
)
from app.services.kpi_team import TeamMemberRow, TeamPanelResult, TeamTotals
from app.services.team_filters import in_role_group, team_role_user_ids

pytestmark = pytest.mark.usefixtures("empty_credited_snapshot")


@pytest.fixture(autouse=True)
def _clean_cache():
    cache_module._cache.clear()
    yield
    cache_module._cache.clear()


def _user(user_id: int, *roles: UserRole, active: bool = True) -> User:
    return User(
        id=user_id,
        email=f"filters-{user_id}@example.com",
        name=f"Osoba {user_id}",
        role=roles[0],
        roles=[role.value for role in roles],
        is_active=active,
        profile_completed=True,
    )


# ── Kto jest w grupie roli ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("roles", "recruiter", "delivery_lead"),
    [
        ((UserRole.recruiter,), True, False),
        # DL, który ma też rolę rekrutera i weryfikuje, zostaje w „Rekruterach”.
        ((UserRole.delivery_lead, UserRole.recruiter), True, True),
        ((UserRole.talent_community_manager, UserRole.recruiter), True, False),
        ((UserRole.delivery_lead,), False, True),
        ((UserRole.talent_community_manager,), False, False),
        # Kierownictwo z rolą rekrutera nie jest liczone jako rekruter.
        (
            (UserRole.admin, UserRole.head_of_recruitment, UserRole.recruiter),
            False,
            False,
        ),
        ((UserRole.head_of_recruitment, UserRole.recruiter), False, False),
        ((UserRole.finance,), False, False),
    ],
)
def test_role_groups(roles, recruiter, delivery_lead) -> None:
    user = _user(1, *roles)
    assert in_role_group(user, "recruiter") is recruiter
    assert in_role_group(user, "delivery_lead") is delivery_lead
    assert in_role_group(user, "all") is True


@pytest.mark.asyncio
async def test_all_roles_needs_no_query() -> None:
    db = AsyncMock()
    assert await team_role_user_ids(db, "all") is None
    db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_role_group_counts_inactive_accounts() -> None:
    """Dorobek osoby, która odeszła, zostaje w jej grupie."""
    db = AsyncMock()
    db.scalars.return_value.all = MagicMock(
        return_value=[
            _user(1, UserRole.recruiter),
            _user(2, UserRole.recruiter, active=False),
            _user(3, UserRole.delivery_lead),
            _user(4, UserRole.head_of_recruitment, UserRole.recruiter),
        ]
    )
    assert await team_role_user_ids(db, "recruiter") == frozenset({1, 2})


# ── Tabela „Ludzie”: wiersz poza filtrem ──────────────────────────────────


def _member(uid: int, *, verifications: int = 0, placements: int = 0) -> TeamMemberRow:
    return TeamMemberRow(
        user_id=uid,
        name=f"Osoba {uid}",
        role="recruiter",
        weryfikacje=verifications,
        rekomendacje=0,
        interview=0,
        akceptacje=0,
        placementy=placements,
        cv_to_base=0,
        precision_pct=None,
        precision_verified_30d=0,
        precision_sent_30d=0,
    )


def _panel(*rows: TeamMemberRow) -> TeamPanelResult:
    return TeamPanelResult(
        period="month",
        precision_target_pct=75,
        rows=tuple(rows),
        totals=TeamTotals(
            weryfikacje=sum(r.weryfikacje for r in rows),
            rekomendacje=0,
            interview=0,
            akceptacje=0,
            placementy=sum(r.placementy for r in rows),
            cv_to_base=0,
            precision_pct=None,
            people=len(rows),
        ),
    )


def test_people_outside_role_group_are_one_row_and_sums_stay() -> None:
    people = TeamPeople(
        current=_panel(
            _member(1, verifications=10, placements=1),
            _member(2, verifications=7),
            _member(3),
            _member(99, verifications=2),
        ),
        previous=_panel(_member(1), _member(5, placements=2), _member(6, placements=1)),
        workdays=10,
        outside_user_ids=frozenset({99}),
        role_user_ids=frozenset({1, 6}),
    )
    payload = people_payload(people)

    assert {row["user_id"] for row in payload["rows"]} == {1, 6}
    filtered = payload["filtered_out"]
    assert filtered["label"] == FILTERED_OUT_LABEL
    # Osoba 3 bez wyniku nie jest liczona jako osoba, ale nie znika z sumy.
    assert filtered["people"] == 1
    assert filtered["verifications"] == 7
    assert filtered["previous_placements"] == 2
    # Konta administracyjne zostają w swoim wierszu, suma firmy bez zmian.
    assert payload["outside_scope"]["verifications"] == 2
    visible = sum(row["verifications"] for row in payload["rows"])
    assert (
        visible + filtered["verifications"] + payload["outside_scope"]["verifications"]
        == payload["totals"]["verifications"]
    )


def test_without_role_filter_there_is_no_filtered_row() -> None:
    people = TeamPeople(
        current=_panel(_member(1, verifications=1)),
        previous=_panel(),
        workdays=10,
    )
    assert people_payload(people)["filtered_out"] is None


# ── Lista „Kto się liczy” i kafle ─────────────────────────────────────────


def _result(rows):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    result.scalars.return_value.all.return_value = rows
    return result


def _summary(total: int = 0) -> MagicMock:
    summary = MagicMock()
    summary.mappings.return_value.one.return_value = {
        "total": total,
        "people": 0,
        "moved_by_credited": 0,
        **{f"state_{name}": 0 for name in activity_service.DETAIL_STATES},
        "history_total": 0,
    }
    return summary


@pytest.mark.asyncio
async def test_team_list_with_role_filters_people_and_client(monkeypatch) -> None:
    head = _user(1, UserRole.head_of_recruitment)

    async def _ids(_db, role):
        assert role == "recruiter"
        return frozenset({11, 12})

    monkeypatch.setattr(activity_service, "team_role_user_ids", _ids)
    db = AsyncMock()
    clients = _result([{"client_id": 7, "client_name": "Klient A", "cnt": 3}])
    db.execute.side_effect = [_result([head]), _summary(), clients]

    response = await activity_service.list_recruitment_activity_details(
        db,
        head,
        metric="interview",
        window="range",
        selected_day=date(2026, 11, 1),
        selected_month=date(2026, 11, 1),
        date_from=date(2026, 11, 1),
        date_to=date(2026, 11, 10),
        subject_user_id=None,
        team_scope=True,
        page=1,
        page_size=25,
        role="recruiter",
        client_id=7,
    )

    summary_sql, params = db.execute.await_args_list[1].args
    assert "credit_user IN" in str(summary_sql)
    assert params["user_ids"] == [11, 12]
    assert params["client_id"] == 7
    assert "filter_job.client_id" in str(summary_sql)
    # Odpowiedź dalej mówi „cały zespół”, a lista klientów idzie do filtra.
    assert response.scope == "team"
    assert [(c.id, c.name, c.count) for c in response.clients] == [(7, "Klient A", 3)]


@pytest.mark.asyncio
async def test_person_list_ignores_role_group(monkeypatch) -> None:
    """Osoba ma jedną rolę — grupa roli dotyczy tylko zakresu zespołu."""
    recruiter = _user(11, UserRole.recruiter)
    called = False

    async def _ids(_db, _role):
        nonlocal called
        called = True
        return frozenset()

    monkeypatch.setattr(activity_service, "team_role_user_ids", _ids)
    db = AsyncMock()
    db.execute.side_effect = [_result([recruiter]), _summary()]

    response = await activity_service.list_recruitment_activity_details(
        db,
        recruiter,
        metric="verification",
        window="month",
        selected_day=date(2026, 11, 1),
        selected_month=date(2026, 11, 1),
        subject_user_id=None,
        team_scope=False,
        page=1,
        page_size=25,
        role="recruiter",
    )

    assert called is False
    assert response.scope == "person"
    assert response.clients == []


@pytest.mark.asyncio
async def test_team_tiles_count_only_role_group(monkeypatch) -> None:
    head = _user(1, UserRole.head_of_recruitment)

    async def _ids(_db, _role):
        return frozenset({11})

    monkeypatch.setattr(activity_service, "team_role_user_ids", _ids)
    outside = MagicMock()
    outside.all.return_value = []
    db = AsyncMock()
    db.execute.side_effect = [
        _result([head]),
        _result(
            [
                {
                    "credit_user": 11,
                    "stage": "verified",
                    "day_count": 1,
                    "month_count": 5,
                    "benchmark_count": 0,
                },
                # DL bez roli rekrutera: w sumie firmy, poza kaflem „Rekruterzy”.
                {
                    "credit_user": 21,
                    "stage": "verified",
                    "day_count": 2,
                    "month_count": 3,
                    "benchmark_count": 0,
                },
            ]
        ),
        outside,
        _result([]),
    ]

    result = await activity_service.build_recruitment_activity_summary(
        db,
        head,
        selected_day=date(2026, 11, 10),
        selected_month=date(2026, 11, 1),
        team_scope=True,
        today=date(2026, 11, 10),
        role="recruiter",
        client_id=7,
    )

    verification = next(m for m in result.metrics if m.metric == "verification")
    assert verification.month == 5
    assert verification.day == 1
    overview_params = db.execute.await_args_list[1].args[1]
    assert overview_params["client_id"] == 7


def test_client_filter_is_in_every_team_query() -> None:
    from app.services import kpi_team

    assert "filter_job.client_id" in str(activity_service._OVERVIEW_SQL)
    assert "filter_job.client_id" in str(kpi_team._TEAM_FUNNEL_SQL)
    for statement in activity_service._DETAIL_SUMMARY_SQL.values():
        assert "filter_job.client_id" in str(statement)
