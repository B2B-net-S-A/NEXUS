"""Zasiew testów rozliczeń zespołu (etap 4). Dane fikcyjne — repo jest publiczne.

NIP-y i rachunki są wymyślone, ale mają poprawne sumy kontrolne (``fake_nip``,
``fake_account``) — walidacja ich nie odrzuci. Numery KSeF też są zmyślone.
Baza testowa jest wspólna: fixture ``settlements_on`` czyści tabele płac
i rozliczeń przed i po teście, a włącza wszystkie moduły „Ludzi”.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

import pytest_asyncio
from sqlalchemy import delete, select, text

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_payroll import EmployeeRate, HrBonus, PayrollLine, PayrollPeriod
from app.models.hr_profile import EmployeeProfile
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollInvoice,
    PayrollPayment,
    PayrollSettlement,
)
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr.payroll_periods import add_months
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

PREFIX = "/api/hr/settlements"
_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_RNG = random.Random()


def tag() -> str:
    return uuid.uuid4().hex[:8]


def headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


def fake_nip() -> str:
    """Zmyślony NIP z poprawną sumą kontrolną."""

    while True:
        digits = [_RNG.randint(1, 9)] + [_RNG.randint(0, 9) for _ in range(8)]
        check = sum(d * w for d, w in zip(digits, _NIP_WEIGHTS)) % 11
        if check != 10:
            return "".join(map(str, digits)) + str(check)


def fake_account() -> str:
    """Zmyślony rachunek NRB (26 cyfr) z poprawnymi cyframi kontrolnymi."""

    bban = "".join(str(_RNG.randint(0, 9)) for _ in range(24))
    check = 98 - int(f"{bban}252100") % 97
    return f"{check:02d}{bban}"


def fake_ksef_number(nip: str, day: date) -> str:
    return f"{nip}-{day:%Y%m%d}-{uuid.uuid4().hex[:12].upper()}-{uuid.uuid4().hex[:2].upper()}"


def months_ago(n: int) -> tuple[int, int]:
    today = business_today()
    return add_months(today.year, today.month, -n)


def warsaw(day: date, hour: int = 10) -> datetime:
    return datetime.combine(day, time(hour, 0), tzinfo=ZoneInfo("Europe/Warsaw"))


async def make_user(
    role: str = "employee",
    *,
    grants: tuple[str, ...] = (),
    profile: bool = True,
    name: str = "Osoba Przykładowa",
    **profile_values,
) -> User:
    marker = tag()
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"rozliczenia-{marker}@example.com",
            name=f"{name} {marker}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
        )
        db.add(user)
        await db.flush()
        for action in grants:
            db.add(UserActionOverride(user_id=user.id, action=action, access="manage"))
        if profile:
            db.add(EmployeeProfile(user_id=user.id, **profile_values))
        await db.commit()
        await db.refresh(user)
        return user


async def set_setting(key: str, value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, key)
        if value is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        await db.commit()


async def wipe() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PayrollPayment))
        await db.execute(delete(PayrollInvoice))
        await db.execute(delete(PayrollSettlement))
        await db.execute(delete(EmployeeBillingDetails))
        await db.execute(delete(PayrollLine))
        await db.execute(delete(PayrollPeriod))
        await db.execute(delete(HrBonus))
        await db.execute(delete(EmployeeRate))
        await db.commit()


async def _modules_value():
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )


@pytest_asyncio.fixture
async def settlements_on():
    previous = await _modules_value()
    await set_setting(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    await wipe()
    yield
    await wipe()
    await set_setting(
        HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS}
    )


@pytest_asyncio.fixture
async def settlements_off():
    previous = await _modules_value()
    await set_setting(
        HR_MODULES_SETTING,
        {key: key != "settlements" for key in HR_MODULE_KEYS},
    )
    await wipe()
    yield
    await wipe()
    await set_setting(
        HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS}
    )


@dataclass
class Team:
    finance: User  # Płace (uprawnienie)
    finance2: User  # druga osoba z Płac
    hr: User  # Kadry
    boss: User  # przełożony
    b2b: User
    mandate: User  # zlecenie
    uop: User


async def make_team() -> Team:
    finance = await make_user(
        "recruiter", grants=("payroll",), profile=False, name="Filip Finansowy"
    )
    finance2 = await make_user(
        "recruiter", grants=("payroll",), profile=False, name="Fabian Drugi"
    )
    hr = await make_user(
        "recruiter", grants=("people_admin",), profile=False, name="Ewa Kadrowa"
    )
    boss = await make_user("recruiter", employment_type="uop", name="Marta Przełożona")
    b2b = await make_user(
        "employee", employment_type="b2b", manager_user_id=boss.id, name="Ola Nowak"
    )
    mandate = await make_user(
        "employee",
        employment_type="zlecenie",
        manager_user_id=boss.id,
        name="Celina Testowa",
        student_contribution_exempt=True,
        contribution_exempt_until=date(2027, 6, 30),
    )
    uop = await make_user(
        "employee", employment_type="uop", manager_user_id=boss.id, name="Ewa Etatowa"
    )
    return Team(finance, finance2, hr, boss, b2b, mandate, uop)


async def closed_period(year: int, month: int) -> int:
    async with AsyncSessionLocal() as db:
        period = PayrollPeriod(
            year=year,
            month=month,
            status="closed",
            close_count=1,
            closed_at=warsaw(date(*add_months(year, month, 1), 2)),
        )
        db.add(period)
        await db.commit()
        return period.id


async def add_line(
    period_id: int,
    user: User,
    *,
    employment_type: Optional[str],
    hours: str = "160",
    rate: Optional[str] = "95.00",
    bonus_total: str = "0",
    currency: str = "PLN",
    timesheet_status: Optional[str] = "approved",
) -> int:
    hours_value = Decimal(hours)
    hours_amount = (
        (hours_value * Decimal(rate)).quantize(Decimal("0.01")) if rate else None
    )
    total = (hours_amount or Decimal("0")) + Decimal(bonus_total)
    async with AsyncSessionLocal() as db:
        line = PayrollLine(
            period_id=period_id,
            user_id=user.id,
            person_name=user.name,
            employment_type=employment_type,
            currency=currency,
            hours=hours_value,
            overtime_hours=Decimal("0"),
            hourly_rate=Decimal(rate) if rate else None,
            hours_amount=hours_amount,
            bonus_total=Decimal(bonus_total),
            total=total,
            timesheet_status=timesheet_status,
        )
        db.add(line)
        await db.commit()
        return line.id


async def add_bonus(
    user: User,
    year: int,
    month: int,
    amount: str,
    *,
    assigned_by: User,
    description: str = "Placement: Data Engineer",
    currency: str = "PLN",
) -> int:
    async with AsyncSessionLocal() as db:
        bonus = HrBonus(
            recipient_user_id=user.id,
            proposed_by=assigned_by.id,
            amount=Decimal(amount),
            currency=currency,
            category="recruiter",
            period_year=year,
            period_month=month,
            status="assigned",
            source="manual",
            description=description,
            assigned_by=assigned_by.id,
            assigned_at=warsaw(date(year, month, 20)),
        )
        db.add(bonus)
        await db.commit()
        return bonus.id


async def add_timesheet(
    user: User,
    year: int,
    month: int,
    *,
    approved_by: Optional[User],
    work: list[tuple[int, str]],
    leave_paid: list[int] = (),
    status: str = "approved",
) -> int:
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text(
                "INSERT INTO timesheets (user_id, year, month, status, approved_by, "
                "approved_at) VALUES (:u, :y, :m, :s, :a, :at) RETURNING id"
            ),
            {
                "u": user.id,
                "y": year,
                "m": month,
                "s": status,
                "a": approved_by.id if approved_by and status == "approved" else None,
                "at": warsaw(date(year, month, 28)) if status == "approved" else None,
            },
        )
        timesheet_id = row.scalar_one()
        for day, hours in work:
            await db.execute(
                text(
                    "INSERT INTO timesheet_entries (timesheet_id, work_date, hours, "
                    "description, source) VALUES (:t, :d, :h, 'Praca w projekcie', 'manual')"
                ),
                {"t": timesheet_id, "d": date(year, month, day), "h": Decimal(hours)},
            )
        for day in leave_paid:
            await db.execute(
                text(
                    "INSERT INTO timesheet_entries (timesheet_id, work_date, hours, "
                    "description, source) VALUES (:t, :d, 8, 'Płatny dzień przerwy', 'leave_paid')"
                ),
                {"t": timesheet_id, "d": date(year, month, day)},
            )
        await db.commit()
        return timesheet_id


async def set_billing(
    user: User,
    *,
    nip: Optional[str] = None,
    account: Optional[str] = None,
    source: Optional[str] = None,
    terms: int = 14,
    vat_status: Optional[str] = None,
) -> None:
    """Rachunek z białej listy = osoba sprawdzona w wykazie (czynny VAT)."""

    from app.core.encryption import get_token_cipher

    if vat_status is None and account and source == "white_list":
        vat_status = "active"
    async with AsyncSessionLocal() as db:
        db.add(
            EmployeeBillingDetails(
                user_id=user.id,
                nip=nip,
                vat_status=vat_status,
                account_encrypted=get_token_cipher().encrypt(account)
                if account
                else None,
                account_last4=account[-4:] if account else None,
                account_source=source if account else None,
                account_check_request_id="Ab12-fikcyjne-sprawdzenie"
                if account and source == "white_list"
                else None,
                payment_terms_days=terms,
            )
        )
        await db.commit()


def invoice(
    *,
    nip: str,
    net: str,
    year: int,
    month: int,
    number: str = "FV 10/2026",
    kind: str = "original",
    corrects: Optional[int] = None,
    acquired: Optional[date] = None,
    currency: str = "PLN",
    period: bool = True,
    sale_date: Optional[date] = None,
    items: Optional[list[dict]] = None,
) -> PayrollInvoice:
    net_value = Decimal(net)
    vat = (net_value * Decimal("0.23")).quantize(Decimal("0.01"))
    acquired = acquired or date(*add_months(year, month, 1), 4)
    ksef = fake_ksef_number(nip, acquired)
    return PayrollInvoice(
        source="ksef",
        ksef_number=ksef,
        ksef_acquired_at=warsaw(acquired),
        seller_nip=nip,
        invoice_number=number,
        invoice_kind=kind,
        corrects_invoice_id=corrects,
        issue_date=acquired,
        sale_date=sale_date,
        period_year=year if period else None,
        period_month=month if period else None,
        currency=currency,
        net_amount=net_value,
        vat_amount=vat,
        gross_amount=net_value + vat,
        items=items or [],
        xml_sha256=hashlib.sha256(ksef.encode()).hexdigest(),
        match_status="unmatched",
    )


async def delete_settlement_rows(db, period_id: Optional[int] = None) -> None:
    """Testy płac kasują okresy, a rozliczenie trzyma okres (FK RESTRICT).

    Wiersze rozliczeń (płatności, faktury, rozliczenia) idą pierwsze — całe
    albo tylko z jednego okresu. Bez commita.
    """

    if period_id is None:
        await db.execute(delete(PayrollPayment))
        await db.execute(delete(PayrollInvoice))
        await db.execute(delete(PayrollSettlement))
        return
    ids = select(PayrollSettlement.id).where(PayrollSettlement.period_id == period_id)
    await db.execute(
        delete(PayrollPayment).where(PayrollPayment.settlement_id.in_(ids))
    )
    await db.execute(
        delete(PayrollInvoice).where(PayrollInvoice.settlement_id.in_(ids))
    )
    await db.execute(
        delete(PayrollSettlement).where(PayrollSettlement.period_id == period_id)
    )
