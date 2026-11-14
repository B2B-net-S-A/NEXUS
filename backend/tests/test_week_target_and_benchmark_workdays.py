"""Cel tygodnia kafelka „Mój tydzień” i średnia 3 miesięcy z dni pracy (14.11.2026).

Obie wartości liczyły się z kalendarza: kafelek „cel dnia × Pon–Pt, które
minęły”, a „Aktywność rekrutacyjna” — cel dnia bez proporcji i średnia przez
stałe 3 miesiące. Teraz idą z `person_workdays` (święto, urlop, dzień
onboardingu z Poligonu NEXUSA). Bez nieobecności wynik jest ten sam co
wcześniej.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import cache as cache_module
from app.models.user import User, UserRole
from app.services import person_workdays
from app.services import recruitment_activity as activity_service
from app.services.kpi_engine import WARSAW, week_to_date_target

# Środa 28.10.2026, południe — tydzień od poniedziałku 26.10.
WED = datetime(2026, 10, 28, 12, 0, tzinfo=WARSAW)
MON = date(2026, 10, 26)
TUE = date(2026, 10, 27)


# ── Cel tygodnia do dziś (czyste funkcje) ───────────────────────────────────


def test_week_target_without_absence_is_daily_times_weekdays_so_far() -> None:
    # Jak dotąd na froncie: środa = 3 dni × 4.
    assert week_to_date_target(4, WED, {}) == 12
    # Poniedziałek rano = 1 dzień, weekend = cały tydzień (5 dni).
    assert week_to_date_target(4, datetime(2026, 10, 26, 8, 0, tzinfo=WARSAW), {}) == 4
    assert week_to_date_target(4, datetime(2026, 11, 1, 18, 0, tzinfo=WARSAW), {}) == 20


def test_week_target_skips_leave_day() -> None:
    assert week_to_date_target(4, WED, {MON: 1.0}) == 8
    assert week_to_date_target(4, WED, {MON: 0.5}) == 10


def test_week_target_skips_onboarding_day() -> None:
    # `absence_by_user` podaje dzień onboardingu jako cały dzień nieobecności.
    assert week_to_date_target(4, WED, {TUE: 1.0}) == 8


def test_week_target_skips_public_holiday() -> None:
    # Środa 11.11.2026 to święto: w piątek 13.11 tydzień ma 4 dni robocze.
    friday = datetime(2026, 11, 13, 12, 0, tzinfo=WARSAW)
    assert week_to_date_target(4, friday, {}) == 16


def test_week_target_ignores_absence_after_today_and_on_weekend() -> None:
    assert week_to_date_target(4, WED, {date(2026, 10, 30): 1.0}) == 12
    assert week_to_date_target(4, WED, {date(2026, 10, 25): 1.0}) == 12


def test_week_target_whole_week_away_and_no_target() -> None:
    assert week_to_date_target(4, WED, {MON: 1.0, TUE: 1.0, WED.date(): 1.0}) == 0
    assert week_to_date_target(0, WED, {}) == 0


def test_months_worked() -> None:
    assert activity_service._months_worked(64.0, 64) == 3.0
    assert activity_service._months_worked(32.0, 64) == 1.5
    assert activity_service._months_worked(0.0, 64) == 0.0
    # Brak wpisu albo okno bez dni roboczych — pełne 3 miesiące.
    assert activity_service._months_worked(None, 64) == 3.0
    assert activity_service._months_worked(0.0, 0) == 3.0


# ── „Aktywność rekrutacyjna” na atrapie bazy ────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_cache():
    cache_module._cache.clear()
    yield
    cache_module._cache.clear()


def _user(role: UserRole, user_id: int) -> User:
    return User(
        id=user_id,
        email=f"workdays-week-{user_id}@example.com",
        name=f"Osoba {user_id}",
        role=role,
        roles=[role.value],
        is_active=True,
        profile_completed=True,
    )


def _row(uid: int, stage: str, *, day: int = 0, bench: int = 0) -> dict:
    return {
        "credit_user": uid,
        "stage": stage,
        "day_count": day,
        "month_count": 0,
        "benchmark_count": bench,
    }


def _result(rows):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    result.scalars.return_value.all.return_value = rows
    return result


def _absence(per_user: dict[int, dict[date, float]]):
    async def fake(db, user_ids, start, end, **_kwargs):
        ids = {int(uid) for uid in user_ids}
        return {
            uid: {d: f for d, f in days.items() if start <= d <= end}
            for uid, days in per_user.items()
            if uid in ids
        }

    return fake


# Okno porównania dla sierpnia oglądanego 26.09.2026: czerwiec–sierpień
# (miniony miesiąc jest ostatnim pełnym miesiącem okna).
JUN_1, AUG_31 = date(2026, 6, 1), date(2026, 8, 31)


def _benchmark_business() -> list[date]:
    return person_workdays.business_days(JUN_1, AUG_31)


async def _team_summary(monkeypatch, absence: dict[int, dict[date, float]]):
    monkeypatch.setattr(person_workdays, "absence_by_user", _absence(absence))
    head = _user(UserRole.head_of_recruitment, 1)
    first = _user(UserRole.recruiter, 11)
    second = _user(UserRole.recruiter, 12)
    outside = MagicMock()
    outside.all.return_value = []
    db = AsyncMock()
    db.execute.side_effect = [
        _result([head, first, second]),
        _result([_row(11, "verified", bench=60), _row(12, "verified", bench=30)]),
        outside,
        _result([]),
    ]
    result = await activity_service.build_recruitment_activity_summary(
        db,
        head,
        selected_day=date(2026, 8, 20),
        selected_month=date(2026, 8, 1),
        team_scope=True,
        today=date(2026, 9, 26),
    )
    return {item.metric: item for item in result.comparisons}


@pytest.mark.asyncio
@pytest.mark.usefixtures("empty_credited_snapshot")
async def test_team_average_without_absence_is_unchanged(monkeypatch) -> None:
    comparisons = await _team_summary(monkeypatch, {})
    # 90 weryfikacji na 2 osoby × 3 miesiące — jak przed zmianą.
    assert comparisons["verification"].team_average == round(90 / (2 * 3), 1)
    assert comparisons["verification"].months == 3


@pytest.mark.asyncio
@pytest.mark.usefixtures("empty_credited_snapshot")
async def test_team_average_counts_months_worked(monkeypatch) -> None:
    business = _benchmark_business()
    # Osoba 12 była nieobecna przez połowę dni roboczych okna.
    half = {day: 1.0 for day in business[: len(business) // 2]}
    comparisons = await _team_summary(monkeypatch, {12: half})
    worked_12 = len(business) - len(half)
    months = 3 + 3 * worked_12 / len(business)
    assert comparisons["verification"].team_average == round(90 / months, 1)
    assert comparisons["verification"].team_average > round(90 / 6, 1)


async def _person_summary(monkeypatch, absence, *, day_target: int = 4):
    monkeypatch.setattr(person_workdays, "absence_by_user", _absence(absence))

    async def fake_target(db, *, user, kpi_id):
        return day_target

    monkeypatch.setattr(activity_service, "resolve_kpi_target", fake_target)
    recruiter = _user(UserRole.recruiter, 11)
    no_rows = MagicMock()
    no_rows.all.return_value = []
    db = AsyncMock()
    db.execute.side_effect = [
        _result([recruiter]),
        _result([_row(11, "verified", day=1, bench=60)]),
        no_rows,
        _result([]),
    ]
    return await activity_service.build_recruitment_activity_summary(
        db,
        recruiter,
        selected_day=date(2026, 9, 24),
        selected_month=date(2026, 9, 1),
        today=date(2026, 9, 24),
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("empty_credited_snapshot")
async def test_personal_average_and_day_target_without_absence(monkeypatch) -> None:
    # Wrzesień oglądany 24.09: okno czerwiec–sierpień.
    result = await _person_summary(monkeypatch, {})
    comparisons = {item.metric: item for item in result.comparisons}
    assert comparisons["verification"].personal_average == 20.0
    assert result.verification_progress is not None
    assert result.verification_progress.target == 4
    assert result.verification_progress.remaining == 3


@pytest.mark.asyncio
@pytest.mark.usefixtures("empty_credited_snapshot")
async def test_personal_average_counts_months_worked(monkeypatch) -> None:
    business = person_workdays.business_days(JUN_1, AUG_31)
    away = {day: 1.0 for day in business[: len(business) // 3]}
    result = await _person_summary(monkeypatch, {11: away})
    comparisons = {item.metric: item for item in result.comparisons}
    months = 3 * (len(business) - len(away)) / len(business)
    assert comparisons["verification"].personal_average == round(60 / months, 1)


@pytest.mark.asyncio
@pytest.mark.usefixtures("empty_credited_snapshot")
async def test_day_target_is_zero_on_onboarding_or_leave_day(monkeypatch) -> None:
    # Dzień onboardingu / urlopu = cały dzień nieobecności: bez paska celu.
    result = await _person_summary(monkeypatch, {11: {date(2026, 9, 24): 1.0}})
    assert result.verification_progress is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("empty_credited_snapshot")
async def test_day_target_halves_on_half_day_leave(monkeypatch) -> None:
    result = await _person_summary(monkeypatch, {11: {date(2026, 9, 24): 0.5}})
    assert result.verification_progress is not None
    assert result.verification_progress.target == 2


# ── Panel „Moje KPI” na bazie: dzień onboardingu w tygodniu ─────────────────


@pytest.mark.asyncio
async def test_my_panel_week_target_skips_onboarding_day(monkeypatch) -> None:
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal
    from app.data.novelties import PoligonPlan, load_poligon
    from app.services import onboarding_day
    from app.services.kpi_panel import compute_my_panel

    plan = PoligonPlan.model_validate(
        {**load_poligon().model_dump(mode="json"), "required_since": "2000-01-01"}
    )
    monkeypatch.setattr(onboarding_day, "load_poligon", lambda: plan)

    async with AsyncSessionLocal() as db:
        people = []
        for tag in ("new", "regular"):
            user = User(
                email=f"week-target-{tag}-{uuid.uuid4().hex[:8]}@example.com",
                name=f"Osoba {tag}",
                role=UserRole.recruiter,
                roles=[UserRole.recruiter.value],
                is_active=True,
            )
            db.add(user)
            people.append(user)
        await db.flush()
        new, regular = people
        await db.execute(
            text(
                """
                INSERT INTO novelty_progress (user_id, novelty_id, seen_count, completed_at, completed_via)
                VALUES (:uid, 'poligon-lista-zakres', 0, :at, 'used')
                """
            ),
            {"uid": new.id, "at": datetime(2026, 10, 26, 10, 0, tzinfo=WARSAW)},
        )
        new_panel = await compute_my_panel(db, user=new, now=WED)
        regular_panel = await compute_my_panel(db, user=regular, now=WED)
        await db.rollback()

    daily = regular_panel.target_verifications_daily
    assert daily > 0
    assert regular_panel.target_verifications_week_to_date == daily * 3
    assert new_panel.target_verifications_week_to_date == daily * 2
