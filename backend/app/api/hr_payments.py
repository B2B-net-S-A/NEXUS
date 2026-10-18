"""Rozliczenia zespołu (etap 4, R5 i R9) — „Dla Finansów”, wyciąg, paczka przelewów, Symfonia.

Prefiks ``/api/hr/payments`` (wpina koordynator w ``app/main.py``). Każda trasa
ma nazwaną bramkę ``require_hr_*`` i przełącznik modułu ``settlements``
(wyłączony = 404 każdemu poza adminem).

Bramki:

* ``require_hr_payments_admin`` — uprawnienie „Płace” (Finanse z roli, admin
  zawsze): lista do zapłaty, CSV, lista NIP-ów, wyciąg, paczka przelewów,
  ustawienia płatności i słowniki Symfonii,
* ``require_hr_symfonia_exporter`` — „Płace” albo „Kadry”: paczka dla
  Symfonii; kwoty dostają Płace, plik zdarzeń (rodzaj nieobecności, D6) —
  Kadry. Admin dostaje wszystko.

Pełny rachunek nie trafia do żadnej odpowiedzi JSON ani komunikatu — tylko
4 ostatnie cyfry; pełny numer ma wyłącznie plik paczki przelewów (opcja).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Annotated, Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.hr_settlement import PayrollPayment
from app.models.user import User
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import audit, symfonia_export
from app.services.hr.bank import batches, finance, statements
from app.services.hr.bank import settings as payment_settings
from app.services.hr.bank.parsed import StatementError
from app.services.hr.employment_terms import FORM_SHORT_LABELS
from app.services.hr.modules import HrModule
from app.services.hr.payroll_access import is_payroll
from app.services.hr.payroll_errors import PayrollError
from app.services.hr.payroll_periods import validate_period
from app.services.permission_denial import permission_denied

router = APIRouter()

MODULE = HrModule.settlements


# ── Bramki ────────────────────────────────────────────────────────────────────


def require_hr_payments_admin():
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


def require_hr_symfonia_exporter():
    """Paczka dla Symfonii: „Płace” albo „Kadry” (admin zawsze)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if is_payroll(current_user) or has_permission(
            current_user, ProductAction.people_admin
        ):
            return current_user
        raise permission_denied(ProductAction.payroll, ProductAction.people_admin)

    _check.required_permissions = (ProductAction.payroll, ProductAction.people_admin)
    return _check


PaymentsAdmin = Annotated[User, Depends(require_hr_payments_admin())]
SymfoniaExporter = Annotated[User, Depends(require_hr_symfonia_exporter())]


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except PayrollError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except StatementError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


def _file(content: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _period(
    year: Optional[int], month: Optional[int]
) -> tuple[Optional[int], Optional[int]]:
    if (year is None) != (month is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Podaj rok i miesiąc albo żadne z nich.",
        )
    if year is not None and month is not None:
        with _http_errors():
            validate_period(year, month)
    return year, month


# ── Ustawienia płatności i słowniki Symfonii ─────────────────────────────────


class PaymentSettingsIn(BaseModel):
    payout_day: Optional[int] = None
    transfer_batch: Optional[dict[str, Any]] = None
    symfonia: Optional[dict[str, Any]] = None


@router.get("/settings")
async def get_settings(
    current_user: PaymentsAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return payment_settings.api_payload(await payment_settings.load_settings(db))


@router.put("/settings")
async def put_settings(
    payload: PaymentSettingsIn,
    current_user: PaymentsAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        saved = await payment_settings.save_settings(
            db, payload.model_dump(exclude_none=True), actor_id=current_user.id
        )
    body = payment_settings.api_payload(saved)
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="app_setting",
        entity_id=payment_settings.SETTING_KEY,
        action="payment_settings_changed",
        sensitivity="payroll",
        details={
            "payout_day": saved.payout_day,
            "transfer_batch_enabled": saved.transfer_batch.enabled,
            "transfer_batch_format": saved.transfer_batch.format,
            "sender_account_set": saved.transfer_batch.sender_account is not None,
            "symfonia": body["symfonia"],
        },
    )
    return body


# ── Dla Finansów ──────────────────────────────────────────────────────────────


def _row_payload(row: finance.PayableRow, today: date) -> dict[str, Any]:
    return {
        "settlement_id": row.settlement_id,
        "user_id": row.user_id,
        "name": row.name,
        "employment_type": row.employment_type,
        "form_label": FORM_SHORT_LABELS.get(row.employment_type, row.employment_type),
        "year": row.year,
        "month": row.month,
        "currency": row.currency,
        "expected_amount": str(row.expected_amount),
        "amount_basis": row.amount_basis,
        "amount_to_pay": str(row.amount_to_pay)
        if row.amount_to_pay is not None
        else None,
        "due_on": row.due_on.isoformat() if row.due_on else None,
        "overdue": bool(row.due_on and row.due_on < today),
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "approved_by_name": row.approved_by_name,
        "title": row.title,
        "invoices": [
            {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "ksef_number": invoice.ksef_number,
                "gross_amount": str(invoice.gross_amount),
                "kind": invoice.kind,
            }
            for invoice in row.invoices
        ],
        "nip": row.nip,
        "registry_name": row.registry_name,
        "account_last4": row.account_last4,
        "account_source": row.account_source,
        "account_checked_at": row.account_checked_at.isoformat()
        if row.account_checked_at
        else None,
        "white_list_override": row.white_list_override,
        "batch_key": row.batch_key,
    }


@router.get("/finance")
async def finance_list(
    current_user: PaymentsAdmin,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
) -> dict[str, Any]:
    year, month = _period(year, month)
    today = business_today()
    rows = await finance.payable_rows(db, year=year, month=month)
    totals: dict[str, str] = {}
    sums: dict[str, Any] = {}
    for row in rows:
        if row.amount_to_pay is not None:
            sums[row.currency] = sums.get(row.currency, 0) + row.amount_to_pay
    totals = {currency: str(value) for currency, value in sorted(sums.items())}
    unmatched = await db.scalar(
        select(func.count())
        .select_from(PayrollPayment)
        .where(
            PayrollPayment.kind == "statement_line",
            PayrollPayment.match_status == "unmatched",
        )
    )
    settings = await payment_settings.load_settings(db)
    return {
        "year": year,
        "month": month,
        "rows": [_row_payload(row, today) for row in rows],
        "totals_to_pay": totals,
        "stats": {
            "payable": len(rows),
            "b2b": sum(1 for row in rows if row.employment_type == "b2b"),
            "payroll_program": sum(1 for row in rows if row.employment_type != "b2b"),
            "overdue": sum(1 for row in rows if row.due_on and row.due_on < today),
            "unmatched_lines": int(unmatched or 0),
        },
        "transfer_batch_enabled": settings.transfer_batch.enabled,
    }


@router.get("/finance/export.csv")
async def finance_export(
    current_user: PaymentsAdmin,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
) -> Response:
    year, month = _period(year, month)
    rows = await finance.payable_rows(db, year=year, month=month)
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="payroll_settlement",
        entity_id=f"{year}-{month:02d}" if year and month else "all",
        action="finance_list_exported",
        sensitivity="payroll",
        details={"rows": len(rows), "year": year, "month": month},
    )
    suffix = f"{year}-{month:02d}" if year and month else "wszystkie"
    return _file(
        finance.finance_csv(rows), f"do-zaplaty-{suffix}.csv", "text/csv; charset=utf-8"
    )


@router.get("/nip-list.csv")
async def nip_list(
    current_user: PaymentsAdmin, db: AsyncSession = Depends(get_db)
) -> Response:
    rows = await finance.nip_rows(db, today=business_today())
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="employee_billing_details",
        entity_id="nip_list",
        action="nip_list_exported",
        sensitivity="payroll",
        details={"rows": len(rows)},
    )
    return _file(finance.nip_csv(rows), "nip-zespolu.csv", "text/csv; charset=utf-8")


# ── Wyciąg z banku ────────────────────────────────────────────────────────────


@router.post("/statements")
async def upload_statement(
    current_user: PaymentsAdmin,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="Wyciąg MT940 albo CAMT.053"),
) -> dict[str, Any]:
    raw = await file.read(statements.MAX_STATEMENT_BYTES + 1)
    with _http_errors():
        result = await statements.import_statement(
            db,
            raw,
            actor_id=current_user.id,
            # Zapłatę faktury klienta stwierdzają Finanse, nie same Płace.
            match_credits=has_permission(current_user, ProductAction.finance_module),
        )
    return result.as_dict()


@router.get("/statements")
async def statement_overview(
    current_user: PaymentsAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return {
        "recent": await statements.recent_imports(db),
        "unmatched": await statements.unmatched_lines(db),
    }


class StatementLineAssignIn(BaseModel):
    settlement_id: int = Field(..., gt=0)


class IgnoreIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


@router.post("/statement-lines/{payment_id}/assign")
async def assign_statement_line(
    payment_id: int,
    payload: StatementLineAssignIn,
    current_user: PaymentsAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        return await statements.assign_line(
            db, payment_id, payload.settlement_id, actor_id=current_user.id
        )


@router.post("/statement-lines/{payment_id}/ignore")
async def ignore_statement_line(
    payment_id: int,
    payload: IgnoreIn,
    current_user: PaymentsAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        return await statements.ignore_line(
            db, payment_id, reason=payload.reason, actor_id=current_user.id
        )


# ── Paczka przelewów (opcja) ─────────────────────────────────────────────────


class BatchIn(BaseModel):
    settlement_ids: Optional[list[int]] = Field(None, max_length=500)
    execution_date: Optional[date] = None


class ConfirmIn(BaseModel):
    paid_on: Optional[date] = None


@router.get("/batches")
async def list_batches(
    current_user: PaymentsAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    settings = await payment_settings.load_settings(db)
    return {
        "enabled": settings.transfer_batch.enabled,
        "format": settings.transfer_batch.format,
        "batches": await batches.list_batches(db),
    }


@router.post("/batches/preview")
async def preview_batch(
    payload: BatchIn,
    current_user: PaymentsAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        settings = await payment_settings.load_settings(db)
        batches.ensure_enabled(settings)
        items = await batches.plan(
            db,
            settlement_ids=payload.settlement_ids,
            today=business_today(),
            actor_id=current_user.id,
        )
    return {"items": [batches.item_payload(item) for item in items]}


@router.post("/batches", status_code=status.HTTP_201_CREATED)
async def create_batch(
    payload: BatchIn,
    current_user: PaymentsAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        return await batches.create_batch(
            db,
            settlement_ids=payload.settlement_ids,
            execution_date=payload.execution_date,
            actor_id=current_user.id,
            today=business_today(),
        )


@router.get("/batches/{batch_key}/file")
async def batch_file(
    batch_key: str,
    current_user: PaymentsAdmin,
    db: AsyncSession = Depends(get_db),
) -> Response:
    with _http_errors():
        filename, content, media_type = await batches.batch_file(db, batch_key)
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="transfer_batch",
        entity_id=batch_key,
        action="transfer_batch_downloaded",
        sensitivity="payroll",
        details={"filename": filename},
    )
    return _file(content, filename, media_type)


@router.post("/batches/{batch_key}/confirm")
async def confirm_batch(
    batch_key: str,
    payload: ConfirmIn,
    current_user: PaymentsAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    today = business_today()
    paid_on = payload.paid_on or today
    if paid_on > today:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Data zapłaty nie może być w przyszłości.",
        )
    with _http_errors():
        return await batches.confirm_batch(
            db, batch_key, paid_on=paid_on, actor_id=current_user.id
        )


@router.post("/batches/{batch_key}/cancel")
async def cancel_batch(
    batch_key: str,
    current_user: PaymentsAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        return await batches.cancel_batch(db, batch_key, actor_id=current_user.id)


# ── Symfonia ──────────────────────────────────────────────────────────────────


@router.get("/symfonia/{year}/{month}/preview")
async def symfonia_preview(
    year: int,
    month: int,
    current_user: SymfoniaExporter,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        package = await symfonia_export.collect(
            db, year=year, month=month, rights=symfonia_export.rights_of(current_user)
        )
    return symfonia_export.preview_payload(package)


@router.get("/symfonia/{year}/{month}/package.zip")
async def symfonia_package(
    year: int,
    month: int,
    current_user: SymfoniaExporter,
    db: AsyncSession = Depends(get_db),
) -> Response:
    with _http_errors():
        package = await symfonia_export.collect(
            db, year=year, month=month, rights=symfonia_export.rights_of(current_user)
        )
    filename, content = await symfonia_export.build_zip(
        db, package, author=current_user.name
    )
    symfonia_export.record_export(db, package, actor_id=current_user.id)
    return _file(content, filename, "application/zip")


__all__ = ["router"]
