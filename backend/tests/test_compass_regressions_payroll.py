"""Błędy Compassa w płacach i premiach — każdy z testem, który by go złapał.

1. Raport płacowy sumował godziny z KAŻDEGO statusu timesheetu, także szkicu
   (``internal-payroll.ts:76-103``) → liczą się tylko zatwierdzone.
2. Zakładka „all” dokładała konsultantów (``internal-payroll.ts:331``) →
   lista płac = osoby z kartoteką (+ odbiorcy premii).
3. Każdy manager mógł zmienić/potwierdzić/usunąć dowolny placement i dać
   premię spoza zespołu → przełożony działa tylko w swoim zespole.
4. ``deletePlacementBonus`` kasował premię na twardo → anulowanie miękkie,
   trasy DELETE dla premii nie ma.
5. ``/api/internal/payroll-export`` w styczniu zwracał grudzień BIEŻĄCEGO roku.
6. Reguła dodatkowej premii DL zaszyta w kodzie z adresami e-mail osób →
   ustawienie, w kodzie nikogo.
7. Admin zatwierdzał sam sobie → CHECK w bazie: nikt nie przyznaje ani nie
   zatwierdza premii sobie.

Dane fikcyjne.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_payroll import EmployeeRate, HrBonus, PayrollLine, PayrollPeriod
from app.models.hr_profile import EmployeeProfile
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr import payroll_report
from app.services.hr.payroll_periods import add_months, previous_month
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

BACKEND = Path(__file__).resolve().parents[1]


def _headers(user: User) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(subject=user.id, role=user.role.value)}"
    }


async def _user(db, role: str, *, profile: bool = True, **values) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"regress-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(EmployeeProfile(user_id=user.id, **values))
        await db.flush()
    return user


async def _set_modules(value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


async def _wipe() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PayrollLine))
        await db.execute(delete(PayrollPeriod))
        await db.execute(delete(HrBonus))
        await db.execute(delete(EmployeeRate))
        await db.commit()


@pytest_asyncio.fixture
async def payroll_on():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({key: True for key in HR_MODULE_KEYS})
    await _wipe()
    yield
    await _wipe()
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


async def _timesheet(
    db, user_id: int, year: int, month: int, status: str, hours: str
) -> None:
    row = await db.execute(
        text(
            "INSERT INTO timesheets (user_id, year, month, status) "
            "VALUES (:u, :y, :m, :s) RETURNING id"
        ),
        {"u": user_id, "y": year, "m": month, "s": status},
    )
    await db.execute(
        text(
            "INSERT INTO timesheet_entries (timesheet_id, work_date, hours, description) "
            "VALUES (:t, :d, :h, 'Praca w projekcie')"
        ),
        {"t": row.scalar_one(), "d": date(year, month, 2), "h": Decimal(hours)},
    )


@pytest.mark.asyncio
async def test_payroll_counts_only_approved_timesheets(payroll_on) -> None:
    today = business_today()
    year, month = add_months(today.year, today.month, -1)
    async with AsyncSessionLocal() as db:
        approved = await _user(db, "employee")
        drafting = await _user(db, "employee")
        waiting = await _user(db, "employee")
        await _timesheet(db, approved.id, year, month, "approved", "8")
        await _timesheet(db, drafting.id, year, month, "draft", "8")
        await _timesheet(db, waiting.id, year, month, "submitted", "8")
        await db.commit()
        people = {
            p.user_id: p for p in await payroll_report.compute_live(db, year, month)
        }
    assert people[approved.id].hours == Decimal("8.00")
    assert people[drafting.id].hours == 0
    assert people[waiting.id].hours == 0
    assert people[drafting.id].timesheet_status == "draft"


@pytest.mark.asyncio
async def test_payroll_list_has_employees_not_consultants(payroll_on) -> None:
    today = business_today()
    year, month = add_months(today.year, today.month, -1)
    async with AsyncSessionLocal() as db:
        employee = await _user(db, "employee")
        consultant_account = await _user(db, "recruiter", profile=False)
        left_before = await _user(
            db,
            "employee",
            employment_status="exited",
            last_working_day=date(year, month, 1) - timedelta(days=1),
        )
        starts_later = await _user(
            db, "employee", work_start_date=date(*add_months(year, month, 2), 1)
        )
        await db.commit()
        ids = {p.user_id for p in await payroll_report.compute_live(db, year, month)}
    assert employee.id in ids
    assert consultant_account.id not in ids
    assert left_before.id not in ids
    assert starts_later.id not in ids


@pytest.mark.asyncio
async def test_bonus_after_leaving_still_reaches_payroll(payroll_on) -> None:
    today = business_today()
    year, month = add_months(today.year, today.month, -1)
    async with AsyncSessionLocal() as db:
        payer = await _user(db, "finance", profile=False)
        gone = await _user(
            db,
            "employee",
            employment_status="exited",
            last_working_day=date(*add_months(year, month, -2), 1),
        )
        db.add(
            HrBonus(
                recipient_user_id=gone.id,
                proposed_by=payer.id,
                amount=Decimal("400"),
                category="custom",
                period_year=year,
                period_month=month,
                status="assigned",
                assigned_by=payer.id,
                assigned_at=local_now(),
            )
        )
        await db.commit()
        people = {
            p.user_id: p for p in await payroll_report.compute_live(db, year, month)
        }
    assert people[gone.id].lines[0].bonus_total == Decimal("400.00")


@pytest.mark.asyncio
async def test_manager_cannot_touch_bonuses_outside_own_team(
    app_client, payroll_on
) -> None:
    today = business_today()
    async with AsyncSessionLocal() as db:
        boss = await _user(db, "recruiter")
        other_boss = await _user(db, "recruiter")
        theirs = await _user(db, "employee", manager_user_id=other_boss.id)
        await _user(db, "employee", manager_user_id=boss.id)
        proposal = HrBonus(
            recipient_user_id=theirs.id,
            amount=Decimal("772.80"),
            category="delivery_lead",
            period_year=today.year,
            period_month=today.month,
            status="proposed",
            source="contract_placement",
            source_key=f"contract:regress-{uuid.uuid4().hex}:dl",
            eligible_on=today,
        )
        db.add(proposal)
        await db.commit()

    for method, url, body in (
        ("post", f"/api/hr/payroll/bonuses/{proposal.id}/approve", None),
        ("post", f"/api/hr/payroll/bonuses/{proposal.id}/cancel", {}),
        ("patch", f"/api/hr/payroll/bonuses/{proposal.id}", {"amount": "1"}),
    ):
        kwargs = {"headers": _headers(boss)}
        if body is not None:
            kwargs["json"] = body
        response = await getattr(app_client, method)(url, **kwargs)
        assert response.status_code == 404, (url, response.text)

    given = await app_client.post(
        "/api/hr/payroll/bonuses",
        json={
            "recipient_user_id": theirs.id,
            "amount": "100",
            "period_year": today.year,
            "period_month": today.month,
        },
        headers=_headers(boss),
    )
    assert given.status_code == 403
    async with AsyncSessionLocal() as db:
        assert (await db.get(HrBonus, proposal.id)).status == "proposed"


def test_bonuses_have_no_hard_delete_route() -> None:
    from app.api.hr_payroll import router

    deletes = [
        route.path
        for route in router.routes
        if "DELETE" in getattr(route, "methods", set()) and "bonus" in route.path
    ]
    assert deletes == []


@pytest.mark.parametrize(
    ("today", "expected"),
    [(date(2027, 1, 10), (2026, 12)), (date(2026, 10, 1), (2026, 9))],
)
def test_previous_month_in_january_is_december_of_previous_year(
    today, expected
) -> None:
    assert previous_month(today) == expected


def test_extra_dl_rule_names_nobody_in_code() -> None:
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    for name in ("bonus_rules.py", "placement_bonuses.py", "league_bonuses.py"):
        source = (BACKEND / "app" / "services" / "hr" / name).read_text(
            encoding="utf-8"
        )
        assert not email.search(source), name


@pytest.mark.asyncio
async def test_nobody_proposes_or_approves_own_bonus_in_database(payroll_on) -> None:
    today = business_today()
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin", profile=False)
        await db.commit()
    for values in (
        {"proposed_by": admin.id, "status": "proposed"},
        {"assigned_by": admin.id, "status": "assigned", "assigned_at": local_now()},
    ):
        async with AsyncSessionLocal() as db:
            db.add(
                HrBonus(
                    recipient_user_id=admin.id,
                    amount=Decimal("100"),
                    category="custom",
                    period_year=today.year,
                    period_month=today.month,
                    **values,
                )
            )
            with pytest.raises(IntegrityError):
                await db.commit()


@pytest.mark.asyncio
async def test_payroll_permission_alone_grants_access_without_role(
    app_client, payroll_on
) -> None:
    async with AsyncSessionLocal() as db:
        clerk = await _user(db, "recruiter", profile=False)
        db.add(UserActionOverride(user_id=clerk.id, action="payroll", access="manage"))
        await db.commit()
    assert (
        await app_client.get("/api/hr/payroll/months", headers=_headers(clerk))
    ).status_code == 200
