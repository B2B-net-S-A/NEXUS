"""Umowy z ludźmi (etap 5, E5) — wzory, szkice, podpis przez Autenti albo ręcznie.

Prefiks ``/api/hr/agreements`` (wpina koordynator w ``app/main.py``). Każda
trasa ma nazwaną bramkę ``require_hr_*``:

* **Kadry** (``people_admin``; admin ma je zawsze) — wzory, szkice, wysyłka do
  podpisu (tylko na klik), wycofanie, anulowanie, podpis ręczny ze skanem,
  „Przepisz ponownie”,
* **Płace** (``payroll``) — odczyt umów i plików (stawki widzą z urzędu),
* przełożony, zespół i sama osoba — nic (podpisaną umowę osoba widzi
  w swoich dokumentach),
* moduł: włączony moduł „Ludzie” i przełącznik ``app_settings['hr_agreements']``
  (domyślnie wyłączony, przełącza admin) — wyłączony = 404 poza adminem.

Nikt nie przygotowuje, nie wysyła i nie oznacza podpisu umowy ze sobą (403).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Optional, Union

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.models.hr_agreement import HrAgreement
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import agreements, agreements_signing
from app.services.hr import agreements_document as document
from app.services.hr import agreements_templates as templates
from app.services.hr.agreements_errors import AgreementError
from app.services.hr.modules import HrModule
from app.services.hr_agreements_schema import TEMPLATE_MAX_BYTES
from app.services.permission_denial import ensure_any_permission

router = APIRouter()

_DOCX = templates.DOCX_MEDIA_TYPE
TemplateKind = Literal["b2b", "zlecenie", "uop", "annex"]


# ── Bramki ────────────────────────────────────────────────────────────────────


def require_hr_agreements(*permissions: ProductAction):
    """Moduł „Ludzie” i przełącznik umów włączone + jedno z ``permissions``."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.people)
        if not agreements.open_for(current_user, await agreements.load_enabled(db)):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, agreements.MODULE_DISABLED_DETAIL
            )
        ensure_any_permission(current_user, *permissions)
        return current_user

    _check.required_permissions = permissions
    return _check


def require_hr_agreements_settings_reader():
    """Stan przełącznika i Autenti — Kadry, Płace, admin (także przy wyłączonym module)."""

    permissions = (ProductAction.people_admin, ProductAction.payroll)

    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        ensure_any_permission(current_user, *permissions)
        return current_user

    _check.required_permissions = permissions
    return _check


def require_hr_agreements_switch():
    """Włączenie modułu — tylko administrator (jak przełączniki modułów „Ludzi”)."""

    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        if not current_user.has_role(UserRole.admin):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Moduł umów włącza administrator.",
            )
        return current_user

    return _check


_reader = require_hr_agreements(ProductAction.people_admin, ProductAction.payroll)
_writer = require_hr_agreements(ProductAction.people_admin)


def _http(exc: AgreementError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


def _is_writer(user: User) -> bool:
    return has_permission(user, ProductAction.people_admin)


def _file(content: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition(filename)},
    )


# ── Przełącznik ───────────────────────────────────────────────────────────────


class SettingsIn(BaseModel):
    enabled: bool


async def _settings_payload(db: AsyncSession) -> dict:
    return {
        "enabled": await agreements.load_enabled(db),
        "autenti_configured": agreements.autenti_configured(),
    }


@router.get("/settings")
async def get_settings(
    _: User = Depends(require_hr_agreements_settings_reader()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _settings_payload(db)


@router.put("/settings")
async def put_settings(
    payload: SettingsIn,
    current_user: User = Depends(require_hr_agreements_switch()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await agreements.save_enabled(db, payload.enabled, actor_id=current_user.id)
    return await _settings_payload(db)


# ── Wzory ─────────────────────────────────────────────────────────────────────


class TemplatePatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=300)
    is_active: Optional[bool] = None


@router.get("/templates")
async def list_templates(
    active: bool = Query(default=False),
    _: User = Depends(_writer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Wzory z wersjami i liczbą umów z każdej wersji oraz lista pól do wzoru."""
    return {
        "items": await templates.list_templates(db, active_only=active),
        "fields": list(templates.field_rows()),
        "required": templates.REQUIRED_FIELDS,
        "kinds": templates.KIND_LABELS,
        "max_bytes": TEMPLATE_MAX_BYTES,
    }


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def upload_template(
    file: UploadFile = File(...),
    kind: TemplateKind = Form(...),
    name: str = Form(..., min_length=1, max_length=120),
    description: Optional[str] = Form(default=None, max_length=300),
    current_user: User = Depends(_writer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    content = await file.read(TEMPLATE_MAX_BYTES + 1)
    try:
        template = await templates.create_template(
            db,
            kind=kind,
            name=name,
            description=description,
            filename=file.filename or "",
            content=content,
            actor=current_user,
        )
    except AgreementError as exc:
        raise _http(exc) from exc
    return {"id": template.id, "kind": template.kind, "name": template.name}


@router.post("/templates/{template_id}/versions", status_code=status.HTTP_201_CREATED)
async def upload_template_version(
    template_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(_writer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    content = await file.read(TEMPLATE_MAX_BYTES + 1)
    try:
        version = await templates.add_version(
            db,
            template_id,
            filename=file.filename or "",
            content=content,
            actor=current_user,
        )
    except AgreementError as exc:
        raise _http(exc) from exc
    return templates.version_payload(version)


@router.patch("/templates/{template_id}")
async def update_template(
    template_id: int,
    payload: TemplatePatch,
    current_user: User = Depends(_writer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        template = await templates.update_template(
            db, template_id, payload.model_dump(exclude_unset=True), actor=current_user
        )
    except AgreementError as exc:
        raise _http(exc) from exc
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "is_active": template.is_active,
    }


@router.get("/templates/versions/{version_id}/file")
async def template_version_file(
    version_id: int, _: User = Depends(_writer), db: AsyncSession = Depends(get_db)
) -> Response:
    try:
        version, _template = await templates.version_with_template(db, version_id)
        content = await templates.version_content(db, version_id)
    except AgreementError as exc:
        raise _http(exc) from exc
    return _file(content, version.file_name, _DOCX)


@router.get("/templates/versions/{version_id}/sample")
async def template_version_sample(
    version_id: int, _: User = Depends(_writer), db: AsyncSession = Depends(get_db)
) -> Response:
    """Wersja wzoru wypełniona fikcyjną umową — sprawdzenie przed użyciem."""
    try:
        version, template = await templates.version_with_template(db, version_id)
        sample = templates.sample_document(
            await templates.version_content(db, version_id), template.kind
        )
    except AgreementError as exc:
        raise _http(exc) from exc
    return _file(sample, f"Probka_{version.file_name}", _DOCX)


# ── Umowy osoby ───────────────────────────────────────────────────────────────


class AgreementIn(BaseModel):
    template_id: Optional[int] = None
    base_agreement_id: Optional[int] = None
    hourly_rate: Optional[Union[Decimal, str]] = None
    currency: Optional[str] = Field(default=None, max_length=3)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    agreement_date: Optional[date] = None
    hours_confirmation: Optional[bool] = None
    payout_day: Optional[int] = None
    coordinator_user_id: Optional[int] = None


class ReasonIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


@router.get("/people/{user_id}")
async def person_agreements(
    user_id: int,
    current_user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Umowy osoby i wartości domyślne okna „Nowa umowa albo aneks”."""
    try:
        return await agreements.person_overview(
            db, user_id, writer=_is_writer(current_user)
        )
    except AgreementError as exc:
        raise _http(exc) from exc


@router.post("/people/{user_id}", status_code=status.HTTP_201_CREATED)
async def create_agreement(
    user_id: int,
    payload: AgreementIn,
    current_user: User = Depends(_writer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        agreement, warning = await agreements.create_draft(
            db,
            user_id=user_id,
            values=payload.model_dump(exclude_unset=True),
            actor=current_user,
        )
    except AgreementError as exc:
        raise _http(exc) from exc
    return {**await agreements.payload(db, agreement, writer=True), "warning": warning}


async def _agreement_payload(db: AsyncSession, agreement_id: int, user: User) -> dict:
    agreement = await agreements.get_agreement(db, agreement_id)
    return await agreements.payload(db, agreement, writer=_is_writer(user))


@router.get("/{agreement_id}")
async def get_agreement(
    agreement_id: int,
    current_user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await _agreement_payload(db, agreement_id, current_user)
    except AgreementError as exc:
        raise _http(exc) from exc


@router.patch("/{agreement_id}")
async def update_agreement(
    agreement_id: int,
    payload: AgreementIn,
    current_user: User = Depends(_writer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        agreement, warning = await agreements.update_draft(
            db,
            agreement_id,
            payload.model_dump(exclude_unset=True),
            actor=current_user,
        )
    except AgreementError as exc:
        raise _http(exc) from exc
    return {**await agreements.payload(db, agreement, writer=True), "warning": warning}


async def _file_name(db: AsyncSession, agreement_id: int) -> tuple[HrAgreement, str]:
    agreement = await agreements.get_agreement(db, agreement_id)
    person = await db.get(User, agreement.user_id)
    return agreement, document.file_stem(agreement, person.name if person else "")


@router.get("/{agreement_id}/docx")
async def agreement_docx(
    agreement_id: int, _: User = Depends(_reader), db: AsyncSession = Depends(get_db)
) -> Response:
    try:
        agreement, stem = await _file_name(db, agreement_id)
        content = await document.render_docx(db, agreement)
    except AgreementError as exc:
        raise _http(exc) from exc
    return _file(content, f"{stem}.docx", _DOCX)


@router.get("/{agreement_id}/pdf")
async def agreement_pdf(
    agreement_id: int, _: User = Depends(_reader), db: AsyncSession = Depends(get_db)
) -> Response:
    """Podgląd PDF (LibreOffice); niedostępny = 503, plik Word dalej się pobiera."""
    try:
        agreement, stem = await _file_name(db, agreement_id)
        content = await document.render_pdf(db, agreement)
    except AgreementError as exc:
        raise _http(exc) from exc
    return _file(content, f"{stem}.pdf", "application/pdf")


@router.post("/{agreement_id}/send")
async def send_agreement(
    agreement_id: int,
    current_user: User = Depends(_writer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Wysyłka do podpisu przez Autenti — tylko na klik Kadr."""
    try:
        agreement = await agreements_signing.send(db, agreement_id, actor=current_user)
    except AgreementError as exc:
        raise _http(exc) from exc
    return await agreements.payload(db, agreement, writer=True)


@router.post("/{agreement_id}/withdraw")
async def withdraw_agreement(
    agreement_id: int,
    current_user: User = Depends(_writer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        agreement = await agreements_signing.withdraw(
            db, agreement_id, actor=current_user
        )
    except AgreementError as exc:
        raise _http(exc) from exc
    return await agreements.payload(db, agreement, writer=True)


@router.post("/{agreement_id}/cancel")
async def cancel_agreement(
    agreement_id: int,
    payload: ReasonIn,
    current_user: User = Depends(_writer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        agreement = await agreements_signing.cancel(
            db, agreement_id, actor=current_user, reason=payload.reason
        )
    except AgreementError as exc:
        raise _http(exc) from exc
    return await agreements.payload(db, agreement, writer=True)


@router.post("/{agreement_id}/mark-signed")
async def mark_agreement_signed(
    agreement_id: int,
    file: UploadFile = File(...),
    signed_on: date = Form(...),
    reason: str = Form(..., min_length=1, max_length=500),
    current_user: User = Depends(_writer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Podpis ręczny ze skanem (druga ścieżka) — podpis i kartoteka razem albo nic."""
    content = await file.read(agreements_signing.SCAN_MAX_BYTES + 1)
    try:
        agreement = await agreements_signing.mark_signed(
            db,
            agreement_id,
            actor=current_user,
            signed_on=signed_on,
            reason=reason,
            content=content,
        )
    except AgreementError as exc:
        raise _http(exc) from exc
    return await agreements.payload(db, agreement, writer=True)


@router.post("/{agreement_id}/apply")
async def apply_agreement(
    agreement_id: int,
    current_user: User = Depends(_writer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Przepisz ponownie” — podpisana w Autenti, nieprzepisana do kartoteki."""
    try:
        agreement = await agreements_signing.retry_apply(
            db, agreement_id, actor=current_user
        )
    except AgreementError as exc:
        raise _http(exc) from exc
    return await agreements.payload(db, agreement, writer=True)
