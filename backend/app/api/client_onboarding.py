"""Pakiet klienta i mail powitalny konsultanta (etap 3, O2, O3, O6).

Prefiks ``/api/client-onboarding`` (wpina koordynator w ``app/main.py``).
Moduł „Wejście i odejście” (``HrModule.lifecycle``): wyłączony = 404
(admin przechodzi). Każda trasa ma bramkę ``require_hr_*``.

Kto co może (O2, O6):

* **pakiet — odczyt**: „Klienci, kontrakty i zamówienia: podgląd” albo „Sprzęt”;
  Delivery Lead u swoich klientów, recepcja u wszystkich,
* **pakiet — zapis**: „Klienci: dodawanie i edycja” (Delivery Lead u swoich
  klientów); część sprzętową (flaga, rzeczy, wzory protokołu) także „Sprzęt”,
* **mail powitalny — podgląd**: podgląd Delivery w zakresie klienta kontraktu,
* **mail powitalny — wysyłka**: jak podgląd + rola opiekuna (Delivery Lead,
  Talent Community Manager, admin — ``care_access.is_care_worker``); za
  przełącznikiem ``consultant_welcome_mail`` (domyślnie wyłączony → 409),
* **przełącznik maila**: tylko admin.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.config import settings
from app.core.database import get_db
from app.models.client import Client
from app.models.user import User, UserRole
from app.services.access_scope import (
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
)
from app.services.action_permissions import ProductAction, has_permission
from app.services.care import access as care_access
from app.services.equipment.errors import EquipmentError
from app.services.hr import client_pack, welcome_mail
from app.services.hr.modules import HrModule
from app.services.permission_denial import ensure_any_permission

router = APIRouter()

SENDER_DENIED = (
    "Mail powitalny wysyła opiekun konsultanta: Delivery Lead, Talent Community "
    "Manager albo administrator."
)
EQUIPMENT_ONLY_DENIED = (
    "Z uprawnieniem „Sprzęt” zmienisz tylko część sprzętową pakietu. Resztę "
    "zmienia osoba z uprawnieniem „Klienci: dodawanie i edycja”."
)
ADMIN_ONLY = "Wysyłkę maili powitalnych włącza i wyłącza administrator."


def _http(exc: EquipmentError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


# ── Bramki ────────────────────────────────────────────────────────────────────


def require_hr_onboarding(*permissions: ProductAction):
    """Moduł „Wejście i odejście” włączony i jedno z ``permissions``."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        # Uprawnienie przed modułem: odmowa bez sięgania do bazy (wzorzec
        # dostępu ``authz_golden`` widzi wtedy, kto naprawdę ma wstęp).
        ensure_any_permission(current_user, *permissions)
        await ensure_module(db, current_user, HrModule.lifecycle)
        return current_user

    _check.required_permissions = permissions
    return _check


def require_hr_welcome_mail_sender():
    """Wysyłka maila powitalnego: podgląd Delivery + rola opiekuna."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        ensure_any_permission(current_user, ProductAction.delivery_view)
        if not care_access.is_care_worker(current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, SENDER_DENIED)
        await ensure_module(db, current_user, HrModule.lifecycle)
        return current_user

    _check.required_permissions = (ProductAction.delivery_view,)
    return _check


def require_hr_welcome_mail_admin():
    """Przełącznik wysyłki maili powitalnych — administrator."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not current_user.has_role(UserRole.admin):
            raise HTTPException(status.HTTP_403_FORBIDDEN, ADMIN_ONLY)
        await ensure_module(db, current_user, HrModule.lifecycle)
        return current_user

    return _check


_pack_reader = require_hr_onboarding(
    ProductAction.delivery_view, ProductAction.equipment
)
_pack_editor = require_hr_onboarding(
    ProductAction.clients_edit, ProductAction.equipment
)
_mail_reader = require_hr_onboarding(ProductAction.delivery_view)
_mail_sender = require_hr_welcome_mail_sender()
_mail_admin = require_hr_welcome_mail_admin()


async def _client_in_scope(
    db: AsyncSession, user: User, client_id: int, *, equipment_only: bool
) -> None:
    """Recepcja („Sprzęt”) czyta i zmienia sprzęt u wszystkich klientów;
    reszta — jak w Klientach (Delivery Lead u swoich)."""
    if await db.get(Client, client_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego klienta.")
    if equipment_only and has_permission(user, ProductAction.equipment):
        return
    assert_delivery_lead_client_visible(
        client_id, await resolve_delivery_lead_client_ids(user, db)
    )


def _can_edit(user: User) -> dict[str, bool]:
    rest = has_permission(user, ProductAction.clients_edit)
    return {
        "equipment": rest or has_permission(user, ProductAction.equipment),
        "rest": rest,
    }


# ── Modele żądań ──────────────────────────────────────────────────────────────


class PackItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    note: Optional[str] = Field(default=None, max_length=300)
    assignee: Optional[str] = Field(default=None, max_length=24)
    offset_days: Optional[int] = Field(default=None, ge=-60, le=120)
    required: bool = True
    requires_file: bool = False


Provider = Literal["nasz", "klienta", "nieznany"]


class EquipmentPartIn(BaseModel):
    #: Tylko przy zmianie flagi; ``expected_provider`` = wartość, od której
    #: osoba zaczęła (inna na kliencie = 409, jak ``expected_version``).
    provider: Optional[Provider] = None
    expected_provider: Optional[Provider] = None
    issue_template_id: Optional[int] = None
    return_template_id: Optional[int] = None
    ours: list[PackItemIn] = Field(default_factory=list, max_length=30)
    client: list[PackItemIn] = Field(default_factory=list, max_length=30)


class FirstDayIn(BaseModel):
    contact_id: Optional[int] = None
    place: Optional[str] = Field(default=None, max_length=300)
    time: Optional[str] = Field(default=None, max_length=5)
    bring: Optional[str] = Field(default=None, max_length=500)


class PackIn(BaseModel):
    expected_version: Optional[int] = None
    equipment: Optional[EquipmentPartIn] = None
    first_day: Optional[FirstDayIn] = None
    documents: Optional[list[PackItemIn]] = Field(default=None, max_length=30)
    accesses: Optional[list[PackItemIn]] = Field(default=None, max_length=30)


class WelcomeMailIn(BaseModel):
    subject: str = Field(min_length=1, max_length=welcome_mail.MAX_SUBJECT)
    body: str = Field(min_length=1, max_length=welcome_mail.MAX_BODY)


class SwitchIn(BaseModel):
    enabled: bool


# ── Pakiet klienta ────────────────────────────────────────────────────────────


async def _pack_response(db: AsyncSession, user: User, client_id: int) -> dict:
    try:
        pack = await client_pack.load_pack(db, client_id)
    except EquipmentError as exc:
        raise _http(exc) from exc
    names = await care_access.user_names(db, [pack.updated_by])
    return {
        **client_pack.pack_payload(pack),
        "updated_by_name": names.get(pack.updated_by) if pack.updated_by else None,
        "live_contracts": await client_pack.live_contract_count(db, client_id),
        "options": await client_pack.options(db, client_id, pack),
        "can_edit": _can_edit(user),
    }


@router.get("/clients/{client_id}/pack")
async def get_client_pack(
    client_id: int,
    current_user: User = Depends(_pack_reader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _client_in_scope(
        db,
        current_user,
        client_id,
        equipment_only=not has_permission(current_user, ProductAction.delivery_view),
    )
    return await _pack_response(db, current_user, client_id)


@router.put("/clients/{client_id}/pack")
async def save_client_pack(
    client_id: int,
    payload: PackIn,
    current_user: User = Depends(_pack_editor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    changes: dict = {}
    if payload.equipment is not None:
        changes["equipment"] = payload.equipment.model_dump()
    if payload.first_day is not None:
        changes["first_day"] = payload.first_day.model_dump()
    if payload.documents is not None:
        changes["documents"] = [item.model_dump() for item in payload.documents]
    if payload.accesses is not None:
        changes["accesses"] = [item.model_dump() for item in payload.accesses]
    equipment_only = set(changes) <= {"equipment"}
    if not equipment_only and not has_permission(
        current_user, ProductAction.clients_edit
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, EQUIPMENT_ONLY_DENIED)
    await _client_in_scope(db, current_user, client_id, equipment_only=equipment_only)
    try:
        await client_pack.save_pack(
            db,
            client_id,
            changes,
            actor=current_user,
            expected_version=payload.expected_version,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return await _pack_response(db, current_user, client_id)


@router.get("/clients/{client_id}/pack/welcome-preview")
async def client_pack_welcome_preview(
    client_id: int,
    current_user: User = Depends(_pack_reader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Podgląd maila powitalnego z pakietu (imię i dzień startu w nawiasach)."""
    await _client_in_scope(
        db,
        current_user,
        client_id,
        equipment_only=not has_permission(current_user, ProductAction.delivery_view),
    )
    try:
        subject, body = await welcome_mail.client_preview(db, client_id)
    except EquipmentError as exc:
        raise _http(exc) from exc
    return {"subject": subject, "body": body}


# ── Mail powitalny ────────────────────────────────────────────────────────────


async def _mail_state(
    db: AsyncSession,
    user: User,
    contract_id: int,
    sender: Optional[welcome_mail.WelcomeMailSender],
) -> dict:
    enabled = await welcome_mail.is_enabled(db)
    mailbox_ready = bool((settings.ADMIN_CASES_MAILBOX or "").strip())
    transport_ready = sender is not None
    sent = await welcome_mail.sent_for(db, contract_id)
    state: dict = {
        "contract_id": contract_id,
        "enabled": enabled,
        "mailbox_ready": mailbox_ready,
        "transport_ready": transport_ready,
        "can_toggle": user.has_role(UserRole.admin),
        "is_sender": care_access.is_care_worker(user),
        "sent": None,
        "draft": None,
        "issues": [],
        "can_send": False,
    }
    if sent is not None:
        names = await care_access.user_names(db, [sent.sent_by])
        state["sent"] = welcome_mail.sent_payload(
            sent, sender_name=names.get(sent.sent_by) if sent.sent_by else None
        )
        return state
    try:
        draft = await welcome_mail.draft_for(db, contract_id)
    except EquipmentError as exc:
        raise _http(exc) from exc
    state["draft"] = {
        "recipient_email": draft.recipient_email,
        "recipient_name": draft.recipient_name,
        "subject": draft.subject,
        "body": draft.body,
    }
    state["issues"] = [issue.as_dict() for issue in draft.issues]
    state["can_send"] = bool(
        enabled
        and mailbox_ready
        and transport_ready
        and state["is_sender"]
        and draft.blocking is None
    )
    return state


@router.get("/contracts/{contract_id}/welcome-mail")
async def get_welcome_mail(
    contract_id: int,
    current_user: User = Depends(_mail_reader),
    db: AsyncSession = Depends(get_db),
    sender: Optional[welcome_mail.WelcomeMailSender] = Depends(
        welcome_mail.default_sender
    ),
) -> dict:
    await care_access.load_contract(db, contract_id, current_user)
    return await _mail_state(db, current_user, contract_id, sender)


@router.post(
    "/contracts/{contract_id}/welcome-mail", status_code=status.HTTP_201_CREATED
)
async def send_welcome_mail(
    contract_id: int,
    payload: WelcomeMailIn,
    current_user: User = Depends(_mail_sender),
    db: AsyncSession = Depends(get_db),
    sender: Optional[welcome_mail.WelcomeMailSender] = Depends(
        welcome_mail.default_sender
    ),
) -> dict:
    await care_access.load_contract(db, contract_id, current_user)
    try:
        await welcome_mail.send(
            db,
            contract_id,
            subject=payload.subject,
            body=payload.body,
            actor=current_user,
            sender=sender,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
    return await _mail_state(db, current_user, contract_id, sender)


@router.get("/welcome-mail/switch")
async def get_welcome_mail_switch(
    _: User = Depends(_mail_reader), db: AsyncSession = Depends(get_db)
) -> dict:
    return {"enabled": await welcome_mail.is_enabled(db)}


@router.put("/welcome-mail/switch")
async def set_welcome_mail_switch(
    payload: SwitchIn,
    current_user: User = Depends(_mail_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {
        "enabled": await welcome_mail.set_enabled(
            db, payload.enabled, actor=current_user
        )
    }
