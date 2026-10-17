"""Pomocnicze dla testów płatności i paczki Symfonii (etap 4, R-C).

Dane wyłącznie fikcyjne: NIP-y i rachunki z poprawnymi sumami kontrolnymi,
ale z numerami banków 9999xxxx (takich w Polsce nie ma), numery KSeF zmyślone.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.encryption import get_token_cipher
from app.core.scheduling import local_now
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
from app.services.hr.bank.accounts import iban_check_digits
from app.services.hr.bank.settings import SETTING_KEY
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def nip(base9: str) -> str:
    """Fikcyjny NIP z poprawną cyfrą kontrolną (``base9`` = 9 cyfr)."""

    check = sum(int(d) * w for d, w in zip(base9, NIP_WEIGHTS)) % 11
    assert check != 10, "wybierz inne 9 cyfr"
    return f"{base9}{check}"


def account(sort_code: str, number: str) -> str:
    """Fikcyjny rachunek NRB (26 cyfr) z poprawną sumą kontrolną."""

    bban = f"{sort_code}{number.zfill(16)}"
    return iban_check_digits(bban) + bban


def headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def make_user(
    db: AsyncSession,
    role: str = "recruiter",
    *,
    name: Optional[str] = None,
    permissions: tuple[str, ...] = (),
    profile: Optional[dict[str, Any]] = None,
) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"payments-{marker}@example.com",
        name=name or f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    for action in permissions:
        db.add(UserActionOverride(user_id=user.id, action=action, access="manage"))
    if profile is not None:
        db.add(EmployeeProfile(user_id=user.id, **profile))
    await db.flush()
    return user


async def set_billing(
    db: AsyncSession,
    user: User,
    *,
    nip_value: Optional[str] = None,
    account_value: Optional[str] = None,
    source: str = "white_list",
    symfonia_id: Optional[str] = None,
    registry_name: Optional[str] = None,
) -> EmployeeBillingDetails:
    details = EmployeeBillingDetails(
        user_id=user.id,
        nip=nip_value,
        registry_name=registry_name,
        symfonia_id=symfonia_id,
        payment_terms_days=14,
    )
    if account_value:
        details.account_encrypted = get_token_cipher().encrypt(account_value)
        details.account_last4 = account_value[-4:]
        details.account_source = source
        if source == "white_list":
            details.account_check_request_id = "sim-test-0001"
            details.account_checked_at = local_now()
    db.add(details)
    await db.flush()
    return details


async def closed_period(db: AsyncSession, year: int, month: int) -> PayrollPeriod:
    period = PayrollPeriod(
        year=year, month=month, status="closed", closed_at=local_now(), close_count=1
    )
    db.add(period)
    await db.flush()
    return period


async def line(
    db: AsyncSession,
    period: PayrollPeriod,
    user: User,
    *,
    employment_type: str,
    total: str,
    hours: str = "0",
    rate: Optional[str] = None,
    bonus: str = "0",
    currency: str = "PLN",
) -> PayrollLine:
    row = PayrollLine(
        period_id=period.id,
        user_id=user.id,
        person_name=user.name,
        employment_type=employment_type,
        currency=currency,
        hours=Decimal(hours),
        overtime_hours=Decimal("0"),
        hourly_rate=Decimal(rate) if rate is not None else None,
        hours_amount=(Decimal(hours) * Decimal(rate)) if rate is not None else None,
        bonus_total=Decimal(bonus),
        total=Decimal(total),
        paid_leave_days=Decimal("0"),
        other_leave_days=Decimal("0"),
        timesheet_status="approved",
    )
    db.add(row)
    await db.flush()
    return row


async def settlement(
    db: AsyncSession,
    period: PayrollPeriod,
    user: User,
    *,
    employment_type: str,
    expected: str,
    status: str = "approved",
    approver: Optional[User] = None,
    due_on: Optional[date] = None,
    currency: str = "PLN",
    override_white_list_by: Optional[tuple[User, User]] = None,
) -> PayrollSettlement:
    row = PayrollSettlement(
        period_id=period.id,
        user_id=user.id,
        employment_type=employment_type,
        currency=currency,
        expected_amount=Decimal(expected),
        amount_basis="net" if employment_type == "b2b" else "gross",
        status=status,
        due_on=due_on,
    )
    if status in ("approved", "paid") and approver is not None:
        row.approved_by = approver.id
        row.approved_at = local_now()
    if status == "paid":
        row.paid_at = local_now()
        row.paid_source = "statement"
        row.paid_amount = Decimal(expected)
    if override_white_list_by is not None:
        first, second = override_white_list_by
        row.override_kind = "white_list"
        row.override_reason = "Rachunek potwierdzony telefonicznie"
        row.override_requested_by = first.id
        row.override_requested_at = local_now()
        row.override_confirmed_by = second.id
        row.override_confirmed_at = local_now()
    db.add(row)
    await db.flush()
    return row


async def invoice(
    db: AsyncSession,
    settlement_row: PayrollSettlement,
    *,
    seller_nip: str,
    invoice_number: str,
    ksef_number: Optional[str],
    net: str,
    gross: str,
    kind: str = "original",
    issue_date: date = date(2026, 11, 4),
) -> PayrollInvoice:
    row = PayrollInvoice(
        source="ksef" if ksef_number else "manual_pdf",
        ksef_number=ksef_number,
        seller_nip=seller_nip,
        user_id=settlement_row.user_id,
        invoice_number=invoice_number,
        invoice_kind=kind,
        issue_date=issue_date,
        currency=settlement_row.currency,
        net_amount=Decimal(net),
        vat_amount=Decimal(gross) - Decimal(net),
        gross_amount=Decimal(gross),
        items=[],
        xml_sha256=("a" * 64) if ksef_number else None,
        pdf_storage_key=None if ksef_number else "hr/invoices/test.pdf",
        settlement_id=settlement_row.id,
        match_status="matched",
    )
    db.add(row)
    await db.flush()
    return row


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


async def set_setting(key: str, value: Any) -> None:
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


async def get_setting(key: str) -> Any:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(AppSetting.value).where(AppSetting.key == key))


async def modules(enabled: bool) -> None:
    await set_setting(HR_MODULES_SETTING, {key: enabled for key in HR_MODULE_KEYS})


__all__ = [
    "SETTING_KEY",
    "account",
    "closed_period",
    "get_setting",
    "headers",
    "invoice",
    "line",
    "make_user",
    "modules",
    "nip",
    "set_billing",
    "set_setting",
    "settlement",
    "wipe",
]
