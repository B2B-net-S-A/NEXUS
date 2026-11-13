"""Finanse → „Koszty” i „Kontrahenci” (księgowość E0 i E1, 0696).

Prefiksy ``/api/finance/costs`` i ``/api/finance/counterparties``
(``app/main.py``, za wyłącznikiem programu „Ludzi w NEXUSIE”). Bramki:
sekcja Finanse (router), uprawnienie „Moduł Finanse” (``FinanceModuleUser``)
i moduł „Księgowość” (``app_settings['finance_accounting']``; wyłączony = 404,
admin widzi zawsze). Przełącznik modułu zmienia tylko admin.

Koszty (serwis ``services/finance_ledger/costs.py``):

* ``GET /module``, ``PUT /module`` — stan i przełącznik modułu,
* ``GET ?stage=&month=&category=&flag=&q=`` — zakładka etapu z licznikami,
* ``GET /{id}`` — karta faktury z „Kogo dotyczy” i historią,
* ``POST /actions`` — Przyjmij, Odrzuć (z powodem), Zweryfikuj, Gotowa do
  księgowania, Cofnij o krok, dodaj/zdejmij flagę; dla zaznaczonych,
* ``PATCH /{id}`` — kategoria, flagi, termin płatności, notatka.

Kontrahenci (``counterparties.py``, ``counterparty_import.py``):

* ``GET ?q=&role=`` — kartoteka z rolą wyliczaną z NEXUSA,
* ``PATCH /{id}`` — konta Symfonii, ID partnera, e-mail,
* ``POST /import?save=`` — plik z eBI24: podgląd (``save=false``) i zapis.
"""

from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.user import User
from app.services.finance_ledger import costs, counterparties
from app.services.finance_ledger import counterparty_import as importer
from app.services.finance_ledger import settings as module_settings
from app.services.finance_ledger_schema import FLAGS, REASON_MAX
from app.services.hr.payroll_access import is_payroll

costs_router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)
counterparties_router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

MONTH_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])$"
Stage = Literal["received", "new", "verified", "ready", "booked", "rejected"]
Action = Literal[
    "accept", "reject", "verify", "ready", "back", "flag_add", "flag_remove"
]
Category = Literal["contractor", "team", "office", "benefit", "proforma", "other"]
Flag = Literal["mpp", "no_mpp", "hold_payment", "tax_office_account", "duplicate"]
#: Filtr flag: konkretna flaga albo „bez flag”.
FlagFilter = Literal[
    "mpp", "no_mpp", "hold_payment", "tax_office_account", "duplicate", "none"
]


class ModuleIn(BaseModel):
    enabled: bool


class ActionIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=costs.BULK_MAX)
    action: Action
    reason: Optional[str] = Field(default=None, max_length=REASON_MAX)
    flag: Optional[Flag] = None


class EntryPatch(BaseModel):
    category: Optional[Category] = None
    flags: Optional[list[Flag]] = Field(default=None, max_length=len(FLAGS))
    due_date: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=4000)


class CounterpartyPatch(BaseModel):
    symfonia_partner_id: Optional[str] = Field(default=None, max_length=64)
    cost_account: Optional[str] = Field(default=None, max_length=64)
    revenue_account: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=255)


async def _open(db: AsyncSession, user: User) -> None:
    enabled = await module_settings.is_enabled(db)
    if not module_settings.open_for(user, enabled):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, module_settings.MODULE_DISABLED_DETAIL
        )


def _ledger_fail(exc: costs.LedgerError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


def _month(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    return date(int(raw[:4]), int(raw[5:7]), 1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Koszty ───────────────────────────────────────────────────────────────────


@costs_router.get("/module")
async def module_state(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Czy pokazać zakładki „Koszty” i „Kontrahenci” (moduł włączony albo admin)."""

    enabled = await module_settings.is_enabled(db)
    return {"enabled": enabled, "open": module_settings.open_for(current_user, enabled)}


@costs_router.put("/module")
async def set_module(
    body: ModuleIn, current_user: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    value = await module_settings.set_enabled(db, body.enabled, actor=current_user)
    await db.commit()
    return {**value, "open": module_settings.open_for(current_user, value["enabled"])}


@costs_router.get("")
async def list_costs(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    stage: Stage = Query("received"),
    month: Optional[str] = Query(None, pattern=MONTH_PATTERN),
    category: Optional[Category] = Query(None),
    flag: Optional[FlagFilter] = Query(None),
    q: Optional[str] = Query(None, max_length=120),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    await _open(db, current_user)
    return await costs.list_view(
        db,
        stage=stage,
        filters=costs.Filters(month=_month(month), category=category, flag=flag, q=q),
        limit=limit,
        offset=offset,
        viewer_id=current_user.id,
        payroll=is_payroll(current_user),
    )


@costs_router.post("/actions")
async def cost_actions(
    body: ActionIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        result = await costs.act(
            db,
            body.ids,
            body.action,
            actor_id=current_user.id,
            now=_now(),
            payroll=is_payroll(current_user),
            reason=body.reason,
            flag=body.flag,
        )
    except costs.LedgerError as exc:
        await db.rollback()
        raise _ledger_fail(exc) from exc
    await db.commit()
    return result


@costs_router.get("/{entry_id}")
async def cost_card(
    entry_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        return await costs.card(
            db, entry_id, viewer_id=current_user.id, payroll=is_payroll(current_user)
        )
    except costs.LedgerError as exc:
        raise _ledger_fail(exc) from exc


@costs_router.patch("/{entry_id}")
async def update_cost(
    entry_id: int,
    body: EntryPatch,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        await costs.update(
            db,
            entry_id,
            body.model_dump(exclude_unset=True),
            actor_id=current_user.id,
            now=_now(),
            payroll=is_payroll(current_user),
        )
    except costs.LedgerError as exc:
        await db.rollback()
        raise _ledger_fail(exc) from exc
    await db.commit()
    return await costs.card(
        db, entry_id, viewer_id=current_user.id, payroll=is_payroll(current_user)
    )


# ── Kontrahenci ──────────────────────────────────────────────────────────────


@counterparties_router.get("")
async def list_counterparties(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(None, max_length=120),
    role: Optional[Literal["client", "team", "contractor", "supplier"]] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    await _open(db, current_user)
    return await counterparties.list_view(
        db, today=business_today(), q=q, role=role, limit=limit, offset=offset
    )


@counterparties_router.patch("/{counterparty_id}")
async def update_counterparty(
    counterparty_id: int,
    body: CounterpartyPatch,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        row = await counterparties.update(
            db,
            counterparty_id,
            body.model_dump(exclude_unset=True),
            actor_id=current_user.id,
        )
    except counterparties.CounterpartyError as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.message) from exc
    index = await counterparties.role_index(db, business_today())
    payload = counterparties.payload(row, index.role(row.id_type, row.id_value))
    await db.commit()
    return payload


@counterparties_router.post("/import")
async def import_counterparties(
    current_user: FinanceModuleUser,
    file: UploadFile = File(..., description="Kontrahenci z eBI24 (XLSX albo CSV)"),
    save: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    content = await file.read(importer.MAX_BYTES + 1)
    try:
        parsed = importer.parse(content)
    except importer.ImportFileError as exc:
        raise HTTPException(422, str(exc)) from exc
    result = await counterparties.apply_import(
        db, parsed, save=save, actor_id=current_user.id, now=_now()
    )
    if save:
        await db.commit()
    return result.as_dict(parsed, saved=save)
