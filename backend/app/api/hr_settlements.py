"""Rozliczenia zespołu (etap 4) — panel osoby, kolejka Płac, dane do rozliczeń.

Prefiks ``/api/hr/settlements`` (wpina koordynator w ``app/main.py``). Każda
trasa ma nazwaną bramkę ``require_hr_*`` i przełącznik modułu
``settlements`` (wyłączony = 404 każdemu poza adminem).

Bramki:

* ``require_hr_settlements_payroll`` — uprawnienie „Płace” (Finanse z roli,
  admin zawsze): kolejka miesiąca, porównanie, decyzje, ręczne „opłacono”,
* ``require_hr_settlements_self`` — osoba z żywą kartoteką: własne
  rozliczenia i PDF rozliczenia zlecenia,
* ``require_hr_settlements_billing_reader`` — dane do rozliczeń: osoba
  (swoje), Kadry, Płace, admin; przełożony i reszta dostają 404 w handlerze,
* ``require_hr_settlements_billing_editor`` — zmiana danych do rozliczeń
  i biała lista: Kadry, Płace, admin.

Rachunku nie ma w żadnej odpowiedzi ani komunikacie — tylko 4 ostatnie cyfry.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import NO_PROFILE_DETAIL, ensure_module
from app.core.database import get_db
from app.core.scheduling import business_date, business_today
from app.models.hr_payroll import PayrollLine
from app.models.hr_profile import EmployeeProfile
from app.models.hr_settlement import PayrollSettlement
from app.models.user import User
from app.services.action_permissions import ProductAction
from app.services.hr import (
    audit,
    billing_details,
    payroll_rates,
    people,
    settlements,
    settlements_decisions,
    settlements_items,
    settlements_pdf,
    settlements_view,
)
from app.services.hr.modules import HrModule
from app.services.hr.payroll_access import is_payroll
from app.services.hr.payroll_errors import PayrollError
from app.services.hr.payroll_periods import get_period, validate_period
from app.services.permission_denial import permission_denied

router = APIRouter()

MODULE = HrModule.settlements
NOT_FOUND = "Nie ma takiego rozliczenia."
NOT_EDITOR = "Dane do rozliczeń zmieniają Kadry i Płace."


# ── Bramki ────────────────────────────────────────────────────────────────────


def require_hr_settlements_payroll():
    """Uprawnienie „Płace” (admin zawsze) przy włączonym module rozliczeń."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if not is_payroll(current_user):
            raise permission_denied(ProductAction.payroll)
        return current_user

    _check.required_permissions = (ProductAction.payroll,)
    return _check


def require_hr_settlements_self():
    """Własne rozliczenia: osoba z żywą kartoteką."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if not await people.has_live_profile(db, current_user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, NO_PROFILE_DETAIL)
        return current_user

    return _check


def require_hr_settlements_billing_reader():
    """Dane do rozliczeń: osoba z kartoteką albo Kadry/Płace (zakres w handlerze)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if billing_details.can_edit(current_user):
            return current_user
        if await people.has_live_profile(db, current_user.id):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_PROFILE_DETAIL)

    return _check


def require_hr_settlements_billing_editor():
    """Zmiana danych do rozliczeń: Kadry, Płace, admin."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if not billing_details.can_edit(current_user):
            raise permission_denied(ProductAction.people_admin, ProductAction.payroll)
        return current_user

    _check.required_permissions = (ProductAction.people_admin, ProductAction.payroll)
    return _check


PayrollGate = Annotated[User, Depends(require_hr_settlements_payroll())]
SelfGate = Annotated[User, Depends(require_hr_settlements_self())]
BillingReader = Annotated[User, Depends(require_hr_settlements_billing_reader())]
BillingEditor = Annotated[User, Depends(require_hr_settlements_billing_editor())]


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except PayrollError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


# ── Ciała żądań ───────────────────────────────────────────────────────────────


class BillingIn(BaseModel):
    """Tylko pola, które się zmieniają (brak pola = bez zmiany)."""

    nip: Optional[str] = Field(default=None, max_length=20)
    payment_terms_days: Optional[int] = None
    symfonia_id: Optional[str] = Field(default=None, max_length=64)
    # Bez ``max_length``: błąd walidacji Pydantic odsyła wartość w ``input``,
    # a numeru rachunku nie ma w żadnym komunikacie — długość sprawdza serwis.
    account: Optional[str] = None
    clear_account: bool = False


class AccountRefIn(BaseModel):
    ref: int = Field(ge=0, le=50)


class ReasonIn(BaseModel):
    reason: str = Field(max_length=500)


class ManualPaidIn(BaseModel):
    amount: Decimal
    paid_on: date
    reason: str = Field(max_length=500)


# ── Panel osoby ───────────────────────────────────────────────────────────────


@router.get("/me")
async def my_settlements(
    current_user: SelfGate,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
) -> dict[str, Any]:
    """„Mój czas → Rozliczenie”: dokument miesiąca według formy i jego stan."""

    today = business_today()
    return await settlements_view.person_months(
        db, user_id=current_user.id, year=year or today.year, today=today
    )


async def _pdf_response(
    db: AsyncSession, settlement: PayrollSettlement, actor: User
) -> Response:
    if settlement.employment_type != "zlecenie" or settlement.status == "cancelled":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "PDF rozliczenia jest dla umowy zlecenia (zamknięty miesiąc).",
        )
    line = await db.get(PayrollLine, settlement.line_id) if settlement.line_id else None
    if line is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Brak zamrożonej linii płac.")
    period = await settlements.period_of(db, settlement)
    amounts = await settlements_items.frozen_amounts(
        db, line, year=period.year, month=period.month
    )
    profile = await db.scalar(
        select(EmployeeProfile).where(EmployeeProfile.user_id == settlement.user_id)
    )
    minimums = await payroll_rates.load_minimum_rates(db)
    name = await settlements.person_name(db, settlement.user_id)
    doc = settlements_pdf.SettlementPdf(
        person_name=name,
        year=period.year,
        month=period.month,
        currency=settlement.currency,
        items=amounts.items,
        total=Decimal(settlement.expected_amount),
        hourly_rate=amounts.hourly_rate,
        minimum_rate=minimums.get(period.year),
        hours_confirmed_on=business_date(amounts.timesheet.approved_at)
        if amounts.timesheet.approved_at
        else None,
        hours_confirmed_by=amounts.timesheet.approved_by_name,
        student_exempt=bool(profile and profile.student_contribution_exempt),
        student_exempt_until=profile.contribution_exempt_until if profile else None,
        document_sha256=settlement.document_sha256
        or settlements_items.document_hash(
            user_id=settlement.user_id,
            amounts=amounts,
            expected_amount=settlement.expected_amount,
        ),
    )
    content = await asyncio.to_thread(settlements_pdf.render_pdf, doc)
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=settlement.user_id,
        entity_type="payroll_settlement",
        entity_id=settlement.id,
        action="settlement_pdf_downloaded",
        sensitivity="payroll",
        details={"year": period.year, "month": period.month},
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="'
                f'{settlements_pdf.filename(name, period.year, period.month)}"'
            )
        },
    )


@router.get("/me/{settlement_id}/pdf")
async def my_settlement_pdf(
    settlement_id: int, current_user: SelfGate, db: AsyncSession = Depends(get_db)
) -> Response:
    settlement = await db.get(PayrollSettlement, settlement_id)
    if settlement is None or settlement.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return await _pdf_response(db, settlement, current_user)


# ── Kolejka Płac ──────────────────────────────────────────────────────────────


async def _closed_period(db: AsyncSession, year: int, month: int):
    with _http_errors():
        validate_period(year, month)
    period = await get_period(db, year, month)
    if period is None or period.status != "closed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Rozliczenia powstają przy zamknięciu miesiąca płac.",
        )
    return period


@router.get("/months/{year}/{month}")
async def month_settlements(
    year: int, month: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        validate_period(year, month)
    return await settlements_view.month_queue(
        db, year=year, month=month, viewer_id=current_user.id
    )


@router.post("/months/{year}/{month}/prepare")
async def prepare_month(
    year: int, month: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Rozliczenia miesiąca zamkniętego przed włączeniem modułu (idempotentne)."""

    period = await _closed_period(db, year, month)
    with _http_errors():
        counts = await settlements.ensure_for_period(
            db, period, actor_id=current_user.id
        )
    return {"year": year, "month": month, **counts}


@router.post("/months/{year}/{month}/approve-ready")
async def approve_ready(
    year: int, month: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    period = await _closed_period(db, year, month)
    with _http_errors():
        result = await settlements_decisions.approve_ready(
            db, actor=current_user, period=period
        )
    return {"year": year, "month": month, **result}


# ── Dane do rozliczeń (M7) ────────────────────────────────────────────────────


async def _billing_payload(
    db: AsyncSession, user: User, user_id: int
) -> dict[str, Any]:
    profile = await billing_details.require_subject(db, user, user_id)
    details = await billing_details.get_details(db, user_id)
    return billing_details.payload(
        details,
        user_id=user_id,
        employment_type=profile.employment_type,
        editable=billing_details.can_edit(user),
    )


@router.get("/billing/{user_id}")
async def get_billing(
    user_id: int, current_user: BillingReader, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        return await _billing_payload(db, current_user, user_id)


@router.put("/billing/{user_id}")
async def put_billing(
    user_id: int,
    payload: BillingIn,
    current_user: BillingEditor,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True)
    with _http_errors():
        await billing_details.update_details(
            db, actor=current_user, user_id=user_id, changes=changes
        )
        return await _billing_payload(db, current_user, user_id)


@router.post("/billing/{user_id}/white-list")
async def white_list_lookup(
    user_id: int, current_user: BillingEditor, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        result = await billing_details.white_list_lookup(
            db, actor=current_user, user_id=user_id, on_date=business_today()
        )
        return {**result, "billing": await _billing_payload(db, current_user, user_id)}


@router.post("/billing/{user_id}/white-list/account")
async def white_list_account(
    user_id: int,
    payload: AccountRefIn,
    current_user: BillingEditor,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        await billing_details.select_white_list_account(
            db,
            actor=current_user,
            user_id=user_id,
            ref=payload.ref,
            on_date=business_today(),
        )
        return await _billing_payload(db, current_user, user_id)


# ── Rozliczenie (porównanie i decyzje) ────────────────────────────────────────


async def _detail(db: AsyncSession, settlement_id: int, viewer: User) -> dict[str, Any]:
    settlement = await db.get(PayrollSettlement, settlement_id)
    if settlement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    await db.refresh(settlement)
    return await settlements_view.settlement_detail(db, settlement, viewer_id=viewer.id)


@router.get("/{settlement_id}")
async def settlement_detail(
    settlement_id: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await _detail(db, settlement_id, current_user)


@router.get("/{settlement_id}/pdf")
async def settlement_pdf(
    settlement_id: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> Response:
    settlement = await db.get(PayrollSettlement, settlement_id)
    if settlement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return await _pdf_response(db, settlement, current_user)


@router.post("/{settlement_id}/approve")
async def approve_settlement(
    settlement_id: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        await settlements_decisions.approve(
            db, actor=current_user, settlement_id=settlement_id
        )
    return await _detail(db, settlement_id, current_user)


@router.post("/{settlement_id}/request-correction")
async def request_correction(
    settlement_id: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        await settlements_decisions.request_correction(
            db, actor=current_user, settlement_id=settlement_id
        )
    return await _detail(db, settlement_id, current_user)


@router.post("/{settlement_id}/override")
async def request_override(
    settlement_id: int,
    payload: ReasonIn,
    current_user: PayrollGate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        await settlements_decisions.request_override(
            db, actor=current_user, settlement_id=settlement_id, reason=payload.reason
        )
    return await _detail(db, settlement_id, current_user)


@router.post("/{settlement_id}/override/confirm")
async def confirm_override(
    settlement_id: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        await settlements_decisions.confirm_override(
            db, actor=current_user, settlement_id=settlement_id
        )
    return await _detail(db, settlement_id, current_user)


@router.delete("/{settlement_id}/override")
async def withdraw_override(
    settlement_id: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        await settlements_decisions.withdraw_override(
            db, actor=current_user, settlement_id=settlement_id
        )
    return await _detail(db, settlement_id, current_user)


@router.post("/{settlement_id}/mark-paid")
async def mark_paid(
    settlement_id: int,
    payload: ManualPaidIn,
    current_user: PayrollGate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        await settlements_decisions.manual_paid(
            db,
            actor=current_user,
            settlement_id=settlement_id,
            amount=payload.amount,
            paid_on=payload.paid_on,
            reason=payload.reason,
            today=business_today(),
        )
    return await _detail(db, settlement_id, current_user)
