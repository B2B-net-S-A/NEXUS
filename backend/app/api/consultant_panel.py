"""Panel konsultanta od strony NEXUSA: aktywacja, materiały, szablon rozliczenia, wyłącznik.

Prefiks ``/api/consultant-panel`` (wpięty w ``app/main.py`` za ``_HR_PROGRAM``). Działa bez
modułu ``back_office``, bo pierwsza wersja panelu idzie na test na jednej osobie, zanim
tablica ruszy (decyzja Artura 05.11.2026). Moduł nie jest więc tu warunkiem wstępu.

* **aktywacja i materiały**: zespół Opieka, kierownik back office'u, admin,
* **szablon rozliczenia**: zapis Finanse (``FinanceModuleUser``), odczyt też Opieka,
* **wyłącznik panelu i maila powitalnego**: tylko admin.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser, require_onboarded_user
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.back_office import access
from app.services.consultant_panel_schema import (
    INSTRUCTIONS_MAX,
    MATERIAL_TITLE_MAX,
    MATERIAL_URL_MAX,
    SETTLEMENT_MODES,
)
from app.services.consultant_portal import activation, materials, portal_settings
from app.services.consultant_portal.auth import PortalError
from app.services.consultant_portal.documents import MAX_FILE_BYTES
from app.services.consultant_portal_schema import STATES
from app.services.equipment.errors import EquipmentError
from app.services.hr import audit, welcome_mail

router = APIRouter()

OPERATOR_ONLY = "Panel konsultanta aktywuje zespół Opieka albo kierownik back office'u."
ADMIN_ONLY = "Wyłącznik panelu konsultanta zmienia administrator."
FILE_TOO_LARGE = "Plik może mieć najwyżej 20 MB."
PANEL_CLOSED_FOR_MAIL = "Panel tej osoby jest zamknięty, więc mail powitalny nie wyszedł. Wyślesz go po włączeniu panelu."

SettlementMode = Literal["client_report", "report_with_approval", "own_report"]
assert set(SettlementMode.__args__) == set(SETTLEMENT_MODES)
PortalState = Literal["off", "pilot", "all"]
assert set(PortalState.__args__) == set(STATES)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _translate(exc: PortalError) -> HTTPException:
    return HTTPException(exc.status, {"message": exc.message, "code": exc.code})


def require_hr_panel_operator():
    """Opieka, kierownik albo admin; moduł ``back_office`` nie jest tu warunkiem."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not (await access.load_viewer(db, current_user)).owns("care"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, OPERATOR_ONLY)
        return current_user

    return _check


def require_hr_panel_admin():
    """Wysyłka do ludzi spoza firmy: decyzję podejmuje admin."""

    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        if not current_user.has_role(UserRole.admin):
            raise HTTPException(status.HTTP_403_FORBIDDEN, ADMIN_ONLY)
        return current_user

    return _check


def require_hr_panel_rule_reader():
    """Szablon rozliczenia czyta Opieka, kierownik, admin i Finanse."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if has_permission(current_user, ProductAction.finance_module):
            return current_user
        if not (await access.load_viewer(db, current_user)).owns("care"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, OPERATOR_ONLY)
        return current_user

    return _check


PanelOperator = Annotated[User, Depends(require_hr_panel_operator())]
PanelRuleReader = Annotated[User, Depends(require_hr_panel_rule_reader())]
PanelAdmin = Annotated[User, Depends(require_hr_panel_admin())]


# ── Wyłącznik ────────────────────────────────────────────────────────────────


async def _switches(db: AsyncSession) -> dict[str, Any]:
    state = await portal_settings.load_raw_state(db)
    return {"state": state, "welcome_mail": await welcome_mail.is_enabled(db)}


@router.get("/settings")
async def get_settings(
    current_user: PanelOperator, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await _switches(db)


class SwitchBody(BaseModel):
    state: Optional[PortalState] = None
    welcome_mail: Optional[bool] = None


@router.put("/settings")
async def save_settings(
    body: SwitchBody, current_user: PanelAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    if body.state is not None:
        await portal_settings.save(db, state=body.state)
        audit.record(
            db,
            actor_user_id=current_user.id,
            subject_user_id=None,
            entity_type="consultant_portal",
            entity_id=0,
            action="portal_switch_changed",
            details={"state": body.state},
        )
    if body.welcome_mail is not None:
        await welcome_mail.set_enabled(db, body.welcome_mail, actor=current_user)
    await db.flush()
    return await _switches(db)


# ── Aktywacja ────────────────────────────────────────────────────────────────


def _state_row(state: activation.ActivationState) -> dict[str, Any]:
    return {
        "active": state.active,
        "email": state.email,
        "activated_at": state.activated_at.isoformat() if state.activated_at else None,
        "activated_by": state.activated_by,
        "deactivated_at": state.deactivated_at.isoformat()
        if state.deactivated_at
        else None,
        "last_login_at": state.last_login_at.isoformat()
        if state.last_login_at
        else None,
        "address_changed": state.address_changed,
    }


@router.get("/contracts/{contract_id}")
async def contract_panel(
    contract_id: int,
    current_user: PanelOperator,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await materials.proposal(db, contract_id)
    except PortalError as exc:
        raise _translate(exc) from exc


class ActivateBody(BaseModel):
    email: EmailStr
    material_ids: list[int] = Field(default_factory=list, max_length=200)
    send_mail: bool = False
    subject: Optional[str] = Field(default=None, max_length=welcome_mail.MAX_SUBJECT)
    body: Optional[str] = Field(default=None, max_length=welcome_mail.MAX_BODY)


async def _send_welcome(
    db: AsyncSession,
    contract_id: int,
    *,
    subject: Optional[str],
    body: Optional[str],
    actor: User,
) -> Optional[str]:
    """Powód, dla którego mail nie wyszedł, albo ``None``.

    Mail jest jeden na kontrakt, a prowadzi do panelu, więc przy zamkniętym panelu nie wychodzi.
    """

    if not (await portal_settings.load(db)).open_for(contract_id):
        return PANEL_CLOSED_FOR_MAIL
    try:
        await welcome_mail.send(
            db,
            contract_id,
            subject=subject or "",
            body=body or "",
            actor=actor,
            sender=welcome_mail.default_sender(),
        )
    except EquipmentError as exc:
        return exc.message
    return None


@router.post("/contracts/{contract_id}/activation")
async def activate(
    contract_id: int,
    payload: ActivateBody,
    current_user: PanelOperator,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        row = await activation.activate(
            db, contract_id, email=payload.email, actor=current_user, now=_now()
        )
        await materials.choose(db, row, contract_id, payload.material_ids)
    except PortalError as exc:
        raise _translate(exc) from exc
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="contract",
        entity_id=contract_id,
        action="portal_activated",
        details={"materials": len(payload.material_ids), "mail": payload.send_mail},
    )
    # Aktywacja jest zapisana przed mailem: odmowa wysyłki nie cofa dostępu, a osoba
    # aktywująca dostaje powód i może wysłać mail później.
    await db.commit()
    mail_error: Optional[str] = None
    if payload.send_mail:
        mail_error = await _send_welcome(
            db,
            contract_id,
            subject=payload.subject,
            body=payload.body,
            actor=current_user,
        )
    state = await activation.state_for(db, contract_id)
    return {"activation": _state_row(state), "mail_error": mail_error}


class WelcomeBody(BaseModel):
    subject: str = Field(min_length=1, max_length=welcome_mail.MAX_SUBJECT)
    body: str = Field(min_length=1, max_length=welcome_mail.MAX_BODY)


@router.post("/contracts/{contract_id}/welcome-mail")
async def send_welcome_mail(
    contract_id: int,
    payload: WelcomeBody,
    current_user: PanelOperator,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Mail po aktywacji: gdy wtedy nie wyszedł albo Opieka go odłożyła."""

    error = await _send_welcome(
        db, contract_id, subject=payload.subject, body=payload.body, actor=current_user
    )
    if error:
        raise HTTPException(status.HTTP_409_CONFLICT, error)
    return {"ok": True}


@router.post("/contracts/{contract_id}/deactivation")
async def deactivate(
    contract_id: int,
    current_user: PanelOperator,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        await activation.deactivate(db, contract_id, actor=current_user, now=_now())
    except PortalError as exc:
        raise _translate(exc) from exc
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="contract",
        entity_id=contract_id,
        action="portal_deactivated",
    )
    await db.flush()
    return {"activation": _state_row(await activation.state_for(db, contract_id))}


# ── Materiały ────────────────────────────────────────────────────────────────


@router.post("/materials", status_code=status.HTTP_201_CREATED)
async def add_material(
    current_user: PanelOperator,
    title: Annotated[str, Form(min_length=1, max_length=MATERIAL_TITLE_MAX)],
    client_id: Annotated[Optional[int], Form()] = None,
    url: Annotated[Optional[str], Form(max_length=MATERIAL_URL_MAX)] = None,
    file: Annotated[Optional[UploadFile], File()] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    content: Optional[bytes] = None
    if file is not None:
        content = await file.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, FILE_TOO_LARGE)
    try:
        return await materials.add(
            db,
            client_id=client_id,
            title=title,
            url=url,
            content=content,
            file_name=file.filename if file else None,
            actor=current_user,
        )
    except PortalError as exc:
        raise _translate(exc) from exc


@router.delete("/materials/{material_id}")
async def retire_material(
    material_id: int,
    current_user: PanelOperator,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    try:
        await materials.retire(db, material_id)
    except PortalError as exc:
        raise _translate(exc) from exc
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="onboarding_material",
        entity_id=material_id,
        action="onboarding_material_retired",
    )
    await db.flush()
    return {"ok": True}


# ── Szablon rozliczenia ──────────────────────────────────────────────────────


@router.get("/clients/{client_id}/settlement")
async def get_settlement(
    client_id: int,
    current_user: PanelRuleReader,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await materials.settlement_rule(db, client_id)


class SettlementBody(BaseModel):
    mode: SettlementMode
    instructions: str = Field(default="", max_length=INSTRUCTIONS_MAX)


@router.put("/clients/{client_id}/settlement")
async def save_settlement(
    client_id: int,
    payload: SettlementBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        saved = await materials.save_settlement_rule(
            db,
            client_id,
            mode=payload.mode,
            instructions=payload.instructions,
            actor=current_user,
        )
    except PortalError as exc:
        raise _translate(exc) from exc
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="client",
        entity_id=client_id,
        action="settlement_rule_saved",
        details={"mode": payload.mode},
    )
    await db.flush()
    return saved
