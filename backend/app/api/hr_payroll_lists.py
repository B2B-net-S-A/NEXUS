"""Płace liczone w NEXUSIE (K7a) — `/api/hr/payroll-lists`.

Moduł stoi za przełącznikiem „Płace” Księgowości (``ledger.settings``, klucz
``payroll``): wyłączony = 404 dla każdego poza administratorem. Kwoty, listy,
parametry i pliki — uprawnienie „Płace” (admin zawsze, D2). Dane
kadrowo-płacowe osób — Kadry, Płace, admin (``person_data.can_edit``).

Nazwy bramek zaczynają się od ``require_hr_`` — test kontraktu tras
(``tests/test_route_authz_contract.py``) rozpoznaje je jako bramki.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import MODULE_DISABLED_DETAIL
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractType
from app.models.hr_payroll_lists import PayrollListLine, PayrollPersonData
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.action_permissions import ProductAction
from app.services.hr import audit
from app.services.hr.payroll_access import is_payroll
from app.services.hr.payroll_errors import PayrollError
from app.services.hr.payroll_lists import (
    documents,
    forms_pdf,
    lists,
    parameters,
    payslip_pdf,
    person_data,
    pesel,
    pit_forms,
    sources,
    transfers,
)
from app.services.hr.payroll_lists.person_data import Subject
from app.services.hr_foundation_schema import EmploymentStatus
from app.services.ledger import settings as ledger_settings
from app.services.permission_denial import permission_denied

router = APIRouter()
MODULE = "payroll"


async def ensure_payroll_module(db: AsyncSession, user: User) -> None:
    settings = await ledger_settings.load(db)
    if not ledger_settings.module_open(user, settings, MODULE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, MODULE_DISABLED_DETAIL)


def require_hr_payroll_lists_payroll():
    """Uprawnienie „Płace” (admin zawsze) przy otwartym module Płac Księgowości."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_payroll_module(db, current_user)
        if not is_payroll(current_user):
            raise permission_denied(ProductAction.payroll)
        return current_user

    _check.required_permissions = (ProductAction.payroll,)
    return _check


def require_hr_payroll_lists_people():
    """Dane kadrowo-płacowe: Kadry, Płace, admin — przy otwartym module Płac."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_payroll_module(db, current_user)
        if not person_data.can_edit(current_user):
            raise permission_denied(ProductAction.people_admin, ProductAction.payroll)
        return current_user

    return _check


PayrollGate = Annotated[User, Depends(require_hr_payroll_lists_payroll())]
PeopleGate = Annotated[User, Depends(require_hr_payroll_lists_people())]


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except PayrollError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


def _file(content: bytes, name: str, media: str) -> Response:
    return Response(
        content=content,
        media_type=media,
        headers={
            "Content-Disposition": content_disposition(name),
            "Cache-Control": "no-store",
        },
    )


# ── Ciała żądań ──────────────────────────────────────────────────────────────


class ParametersBody(BaseModel):
    effective_from: date
    params: dict[str, Any]
    note: Optional[str] = Field(default=None, max_length=500)


class CompanyBody(BaseModel):
    regon: Optional[str] = Field(default=None, max_length=20)
    short_name: Optional[str] = Field(default=None, max_length=40)
    tax_office_code: Optional[str] = Field(default=None, max_length=8)
    zus_account: Optional[str] = Field(default=None, max_length=64)
    tax_account: Optional[str] = Field(default=None, max_length=64)


class PersonBody(BaseModel):
    """Zmiany danych osoby: tylko przesłane pola; ``null`` czyści pole."""

    model_config = {"extra": "forbid"}

    expected_version: Optional[int] = Field(default=None, ge=0)
    # Pola z numerami bez walidacji Pydantica: 422 FastAPI odsyła wartość wejścia,
    # a walidacja serwisu numeru nie powtarza.
    pesel: Optional[Any] = None
    document_type: Optional[str] = Field(default=None, max_length=12)
    document_number: Optional[Any] = None
    birth_date: Optional[date] = None
    sex: Optional[Literal["F", "M"]] = None
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    citizenship: Optional[str] = Field(default=None, max_length=4)
    address: Optional[dict[str, Optional[str]]] = None
    tax_office_code: Optional[str] = Field(default=None, max_length=8)
    tax_office_name: Optional[str] = Field(default=None, max_length=150)
    zus_title_code: Optional[str] = Field(default=None, max_length=10)
    nfz_code: Optional[str] = Field(default=None, max_length=4)
    nip: Optional[Any] = None
    work_time: Optional[str] = Field(default=None, max_length=6)
    pit2: Optional[int] = None
    kup: Optional[Literal["standard", "increased"]] = None
    reliefs: Optional[list[str]] = Field(default=None, max_length=3)
    youth_relief_waived: Optional[bool] = None
    student_exempt_until: Optional[date] = None
    mandate_pension_insurance: Optional[bool] = None
    mandate_sickness_voluntary: Optional[bool] = None
    mandate_accident_insurance: Optional[bool] = None
    ppk: Optional[dict[str, Any]] = None
    labour_fund_exempt_until: Optional[date] = None
    fgsp_exempt_until: Optional[date] = None
    bank_account: Optional[Any] = None


class ComputeBody(BaseModel):
    pay_date: Optional[date] = None


class InputBody(BaseModel):
    user_id: Optional[int] = Field(default=None, ge=1)
    contract_id: Optional[int] = Field(default=None, ge=1)
    kind: Literal["uop", "zlecenie", "dzielo"]
    gross: Optional[str] = Field(default=None, max_length=20)
    note: Optional[str] = Field(default=None, max_length=500)


class CancelBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class OpeningBody(BaseModel):
    through_month: int = Field(ge=1, le=12)
    amounts: dict[str, Optional[str]]
    note: Optional[str] = Field(default=None, max_length=500)


# ── Parametry i płatnik ──────────────────────────────────────────────────────


@router.get("/parameters")
async def get_parameters(
    current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    payload = await parameters.history_payload(db, on=business_today())
    payload["company"] = parameters.company_payload(await parameters.load_company(db))
    return payload


@router.post("/parameters", status_code=201)
async def save_parameters(
    body: ParametersBody, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        await parameters.save_version(
            db,
            actor=current_user,
            effective_from=body.effective_from,
            values=body.params,
            note=body.note,
        )
    return await parameters.history_payload(db, on=business_today())


@router.post("/parameters/{version_id}/confirm")
async def confirm_parameters(
    version_id: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        await parameters.confirm_version(db, actor=current_user, version_id=version_id)
    return await parameters.history_payload(db, on=business_today())


@router.post("/parameters/{version_id}/withdraw")
async def withdraw_parameters(
    version_id: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        await parameters.withdraw_version(db, actor=current_user, version_id=version_id)
    return await parameters.history_payload(db, on=business_today())


@router.put("/company")
async def save_company(
    body: CompanyBody, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        company = await parameters.save_company(
            db, actor=current_user, values=body.model_dump()
        )
    return parameters.company_payload(company)


# ── Dane osób ────────────────────────────────────────────────────────────────


@router.get("/people")
async def list_people(
    current_user: PeopleGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Osoby na płacach: zespół na UoP i zleceniu oraz zleceniobiorcy u klientów."""

    team = (
        await db.execute(
            select(User.id, User.name, EmployeeProfile.employment_type)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .where(
                EmployeeProfile.employment_type.in_(("uop", "zlecenie")),
                EmployeeProfile.employment_status != EmploymentStatus.exited,
            )
            .order_by(User.name)
        )
    ).all()
    contractors = (
        await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname)
            .join(Contract, Contract.candidate_id == Candidate.id)
            .where(
                Contract.contract_type == ContractType.uzlecenie,
                Contract.status.in_(sources.MANDATE_STATUSES),
            )
            .distinct()
            .order_by(Candidate.lastname, Candidate.name, Candidate.id)
        )
    ).all()
    records = await person_data.records_for(
        db, {int(row[0]) for row in team}, {int(row[0]) for row in contractors}
    )

    def item(key: str, name: str, kind: str, **ids: Any) -> dict[str, Any]:
        record: Optional[PayrollPersonData] = records.get(key)
        missing = list(record.missing) if record else ["person_data"]
        return {
            "subject": key,
            **ids,
            "name": name,
            "kind": kind,
            "exists": record is not None,
            "missing": missing,
            "missing_labels": [
                person_data.FIELD_LABELS.get(code, "dane płacowe") for code in missing
            ],
            "pesel_masked": pesel.masked(record.pesel_last4) if record else None,
            "own": key == f"u{current_user.id}",
        }

    return {
        "people": [
            *(
                item(
                    f"u{uid}", str(name), str(kind), user_id=int(uid), candidate_id=None
                )
                for uid, name, kind in team
            ),
            *(
                item(
                    f"c{cid}",
                    " ".join(part for part in (first, last) if part),
                    "zlecenie",
                    user_id=None,
                    candidate_id=int(cid),
                )
                for cid, first, last in contractors
            ),
        ]
    }


@router.get("/people/users/{user_id}")
async def get_user_data(
    user_id: int, current_user: PeopleGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        return await person_data.get(
            db,
            actor=current_user,
            subject=Subject(user_id=user_id),
            today=business_today(),
        )


@router.put("/people/users/{user_id}")
async def put_user_data(
    user_id: int,
    body: PersonBody,
    current_user: PeopleGate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    expected = changes.pop("expected_version", None)
    with _http_errors():
        return await person_data.update(
            db,
            actor=current_user,
            subject=Subject(user_id=user_id),
            changes=changes,
            expected_version=expected,
            today=business_today(),
        )


@router.get("/people/candidates/{candidate_id}")
async def get_candidate_data(
    candidate_id: int, current_user: PeopleGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        return await person_data.get(
            db,
            actor=current_user,
            subject=Subject(candidate_id=candidate_id),
            today=business_today(),
        )


@router.put("/people/candidates/{candidate_id}")
async def put_candidate_data(
    candidate_id: int,
    body: PersonBody,
    current_user: PeopleGate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    expected = changes.pop("expected_version", None)
    with _http_errors():
        return await person_data.update(
            db,
            actor=current_user,
            subject=Subject(candidate_id=candidate_id),
            changes=changes,
            expected_version=expected,
            today=business_today(),
        )


# ── Lista płac miesiąca ──────────────────────────────────────────────────────


@router.get("/months/{year}/{month}")
async def get_month(
    year: int, month: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        return await lists.month_payload(
            db, viewer=current_user, year=year, month=month
        )


@router.post("/months/{year}/{month}/compute")
async def compute_month(
    year: int,
    month: int,
    body: ComputeBody,
    current_user: PayrollGate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        await lists.compute(
            db, actor=current_user, year=year, month=month, pay_date=body.pay_date
        )
        return await lists.month_payload(
            db, viewer=current_user, year=year, month=month
        )


@router.put("/months/{year}/{month}/inputs")
async def put_input(
    year: int,
    month: int,
    body: InputBody,
    current_user: PayrollGate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        await lists.set_gross_input(
            db,
            actor=current_user,
            year=year,
            month=month,
            user_id=body.user_id,
            contract_id=body.contract_id,
            kind=body.kind,
            gross=body.gross,
            note=body.note,
        )
        return await lists.month_payload(
            db, viewer=current_user, year=year, month=month
        )


async def _list_or_404(db: AsyncSession, list_id: int, *, lock: bool = False):
    with _http_errors():
        return await lists.get_list(db, list_id, lock=lock)


@router.post("/lists/{list_id}/approve")
async def approve_list(
    list_id: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        approved = await lists.approve(db, actor=current_user, list_id=list_id)
        return await lists.month_payload(
            db, viewer=current_user, year=approved.year, month=approved.month
        )


@router.post("/lists/{list_id}/cancel")
async def cancel_list(
    list_id: int,
    body: CancelBody,
    current_user: PayrollGate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        cancelled = await lists.cancel(
            db, actor=current_user, list_id=list_id, reason=body.reason
        )
        return await lists.month_payload(
            db, viewer=current_user, year=cancelled.year, month=cancelled.month
        )


@router.get("/lists/{list_id}/payslips.pdf")
async def payslips_pdf(
    list_id: int,
    current_user: PayrollGate,
    line_id: Optional[int] = None,
    employer: bool = False,
    db: AsyncSession = Depends(get_db),
) -> Response:
    lst = await _list_or_404(db, list_id)
    if lst.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Lista jest anulowana.")
    query = select(PayrollListLine).where(PayrollListLine.list_id == lst.id)
    if line_id is not None:
        query = query.where(PayrollListLine.id == line_id)
    rows = [
        line
        for line in await db.scalars(query.order_by(PayrollListLine.person_name))
        if line.result
    ]
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brak pozycji z kwotą.")
    slips = [
        payslip_pdf.Payslip(
            list_number=lst.number,
            year=lst.year,
            month=lst.month,
            pay_date=lst.pay_date,
            approved=lst.status == "approved",
            person_name=line.person_name,
            kind=line.kind,
            source_label=lists.SOURCE_LABEL.get(line.source, line.source),
            basis=line.basis or {},
            result=line.result or {},
        )
        for line in rows
    ]
    content = await asyncio.to_thread(payslip_pdf.render_pdf, slips, employer=employer)
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=rows[0].user_id if line_id is not None else None,
        entity_type="payroll_list",
        entity_id=lst.id,
        action="payroll_payslips_downloaded",
        sensitivity="payroll",
        details={"number": lst.number, "lines": len(rows), "line_id": line_id},
    )
    name = payslip_pdf.filename(
        lst.number, rows[0].person_name if line_id is not None else None
    )
    return _file(content, name, "application/pdf")


@router.get("/lists/{list_id}/transfers")
async def transfers_plan(
    list_id: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    lst = await _list_or_404(db, list_id)
    rows, _accounts = await transfers.plan(db, lst)
    return {
        "list_id": lst.id,
        "number": lst.number,
        "status": lst.status,
        "rows": transfers.plan_payload(rows),
        "transfers_created_at": lst.transfers_created_at.isoformat()
        if lst.transfers_created_at
        else None,
        "paid_at": lst.paid_at.isoformat() if lst.paid_at else None,
    }


@router.post("/lists/{list_id}/transfers/file")
async def transfers_file(
    list_id: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> Response:
    lst = await _list_or_404(db, list_id, lock=True)
    with _http_errors():
        content, name, media, _rows = await transfers.build_file(
            db, actor=current_user, lst=lst
        )
    return _file(content, name, media)


@router.post("/lists/{list_id}/paid")
async def mark_list_paid(
    list_id: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    lst = await _list_or_404(db, list_id, lock=True)
    with _http_errors():
        await transfers.mark_paid(db, actor=current_user, lst=lst)
        return await lists.month_payload(
            db, viewer=current_user, year=lst.year, month=lst.month
        )


# ── Pliki ZUS: KEDU i zgłoszenia ─────────────────────────────────────────────


@router.get("/declarations/{year}/{month}/kedu.xml")
async def kedu_month(
    year: int, month: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> Response:
    """DRA + RCA za miesiąc wypłaty (wszystkie zatwierdzone listy z wypłatą w nim)."""

    if not 2020 <= year <= 2100 or not 1 <= month <= 12:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Niepoprawny miesiąc."
        )
    with _http_errors():
        content, name, numbers = await documents.kedu_month_file(
            db, year=year, month=month, created_on=business_today()
        )
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="payroll_declaration",
        entity_id=f"{year}-{month:02d}",
        action="payroll_kedu_downloaded",
        sensitivity="payroll",
        details={"lists": numbers},
    )
    return _file(content, name, "application/xml")


def _range(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Koniec zakresu przed początkiem."
        )


@router.get("/registrations")
async def registrations_preview(
    date_from: date,
    date_to: date,
    current_user: PayrollGate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Zgłoszenia i wyrejestrowania w zakresie dat — podgląd bez danych osób."""

    _range(date_from, date_to)
    with _http_errors():
        content, _name, found, skipped = await documents.registrations_file(
            db, date_from=date_from, date_to=date_to, created_on=business_today()
        )
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "events": found,
        "skipped": [item.payload() for item in skipped],
        "file_available": content is not None,
    }


@router.get("/registrations.xml")
async def registrations_file(
    date_from: date,
    date_to: date,
    current_user: PayrollGate,
    db: AsyncSession = Depends(get_db),
) -> Response:
    _range(date_from, date_to)
    with _http_errors():
        content, name, found, skipped = await documents.registrations_file(
            db, date_from=date_from, date_to=date_to, created_on=business_today()
        )
    if content is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "nothing_to_register",
                "message": "Brak zgłoszeń do pliku w tym zakresie.",
                "skipped": [item.payload() for item in skipped],
            },
        )
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="payroll_registrations",
        entity_id=f"{date_from.isoformat()}:{date_to.isoformat()}",
        action="payroll_registrations_downloaded",
        sensitivity="payroll",
        details={"events": len(found), "skipped": len(skipped)},
    )
    return _file(content, name, "application/xml")


# ── Roczne PIT: PIT-11, PIT-4R, PIT-8AR ──────────────────────────────────────


def _year_ok(year: int) -> None:
    if not 2020 <= year <= 2100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Rok poza zakresem.")


def _form_pdf(document: pit_forms.FormDocument) -> bytes:
    from weasyprint import HTML

    html = forms_pdf.document_html(document, generated_on=business_today())
    return HTML(string=html).write_pdf()


def _audit_form(
    db: AsyncSession, actor: User, form: str, year: int, **details: Any
) -> None:
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="payroll_tax_form",
        entity_id=f"{form}:{year}",
        action="payroll_tax_form_downloaded",
        sensitivity="payroll",
        details={"form": form, "year": year, **details},
    )


@router.get("/years/{year}/pit-11")
async def pit11_preview(
    year: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Kto dostanie PIT-11 i komu czego brakuje (bez danych osób)."""

    _year_ok(year)
    with _http_errors():
        files = await documents.pit11_documents(db, year)
    return {
        "year": year,
        "people": [
            {
                "person_key": item.person_key,
                "name": item.name,
                "ready": item.document is not None,
                "missing": [
                    person_data.FIELD_LABELS.get(code, "NIP osoby bez PESEL-u")
                    for code in item.missing
                ],
            }
            for item in files
        ],
    }


@router.get("/years/{year}/pit-11.zip")
async def pit11_zip(
    year: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> Response:
    """PIT-11 wszystkich osób: XML i PDF; braki w ``BRAKI.txt``."""

    _year_ok(year)
    with _http_errors():
        files = await documents.pit11_documents(db, year)
    ready = [item for item in files if item.document is not None]
    if not ready:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "pit11_nothing_ready",
                "message": "Żaden PIT-11 nie jest gotowy — uzupełnij dane osób.",
            },
        )
    pdfs = await asyncio.to_thread(
        lambda: [_form_pdf(item.document) for item in ready]  # type: ignore[arg-type]
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for item, pdf in zip(ready, pdfs):
            stem = forms_pdf.filename("PIT-11", year, item.name)[:-4]
            archive.writestr(f"{stem}.xml", pit_forms.render(item.document))  # type: ignore[arg-type]
            archive.writestr(f"{stem}.pdf", pdf)
        skipped = [item for item in files if item.document is None]
        if skipped:
            lines = [
                f"{item.name}: brakuje — "
                + ", ".join(
                    person_data.FIELD_LABELS.get(code, "NIP osoby bez PESEL-u")
                    for code in item.missing
                )
                for item in skipped
            ]
            archive.writestr("BRAKI.txt", "\n".join(lines) + "\n")
    _audit_form(
        db,
        current_user,
        "PIT-11",
        year,
        ready=len(ready),
        skipped=len(files) - len(ready),
    )
    return _file(buffer.getvalue(), f"pit-11-{year}.zip", "application/zip")


async def _yearly(
    db: AsyncSession, actor: User, year: int, form: str, kind: str
) -> Response:
    _year_ok(year)
    with _http_errors():
        if form == "PIT-4R":
            document = await documents.pit4r_document(db, year)
        else:
            document = await documents.pit8ar_document(db, year)
    _audit_form(db, actor, form, year, format=kind)
    stem = forms_pdf.filename(form, year)[:-4]
    if kind == "xml":
        return _file(pit_forms.render(document), f"{stem}.xml", "application/xml")
    content = await asyncio.to_thread(_form_pdf, document)
    return _file(content, f"{stem}.pdf", "application/pdf")


@router.get("/years/{year}/pit-4r.xml")
async def pit4r_xml(
    year: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> Response:
    return await _yearly(db, current_user, year, "PIT-4R", "xml")


@router.get("/years/{year}/pit-4r.pdf")
async def pit4r_pdf(
    year: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> Response:
    return await _yearly(db, current_user, year, "PIT-4R", "pdf")


@router.get("/years/{year}/pit-8ar.xml")
async def pit8ar_xml(
    year: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> Response:
    return await _yearly(db, current_user, year, "PIT-8AR", "xml")


@router.get("/years/{year}/pit-8ar.pdf")
async def pit8ar_pdf(
    year: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> Response:
    return await _yearly(db, current_user, year, "PIT-8AR", "pdf")


# ── Otwarcie roku ────────────────────────────────────────────────────────────


@router.get("/openings/{year}")
async def get_openings(
    year: int, current_user: PayrollGate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    if not 2020 <= year <= 2100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Rok poza zakresem.")
    items = await sources.openings(db, year)
    return {
        "year": year,
        "keys": list(sources.OPENING_KEYS),
        "items": [
            {
                "subject": key,
                "user_id": opening.user_id,
                "candidate_id": opening.candidate_id,
                "through_month": opening.through_month,
                "amounts": opening.amounts,
                "note": opening.note,
                "entered_at": opening.entered_at.isoformat()
                if opening.entered_at
                else None,
            }
            for key, opening in sorted(items.items())
        ],
    }


async def _put_opening(
    db: AsyncSession, actor: User, subject: Subject, year: int, body: OpeningBody
) -> dict[str, Any]:
    with _http_errors():
        opening = await lists.set_opening(
            db,
            actor=actor,
            subject=subject,
            year=year,
            through_month=body.through_month,
            amounts=body.amounts,
            note=body.note,
        )
    return {
        "subject": subject.key,
        "year": opening.year,
        "through_month": opening.through_month,
        "amounts": opening.amounts,
        "note": opening.note,
    }


@router.put("/openings/{year}/users/{user_id}")
async def put_user_opening(
    year: int,
    user_id: int,
    body: OpeningBody,
    current_user: PayrollGate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _put_opening(db, current_user, Subject(user_id=user_id), year, body)


@router.put("/openings/{year}/candidates/{candidate_id}")
async def put_candidate_opening(
    year: int,
    candidate_id: int,
    body: OpeningBody,
    current_user: PayrollGate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _put_opening(
        db, current_user, Subject(candidate_id=candidate_id), year, body
    )
