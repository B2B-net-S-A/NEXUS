"""Finanse → „Koszty” i „Kontrahenci” (księgowość E0 i E1, 0695).

Prefiksy ``/api/finance/costs`` i ``/api/finance/counterparties``
(``app/main.py``, za wyłącznikiem programu „Ludzi w NEXUSIE”). Bramki:
sekcja Finanse (router), uprawnienie „Moduł Finanse” (``FinanceModuleUser``)
i moduł „Księgowość” (``app_settings['finance_accounting']``; wyłączony = 404,
admin widzi zawsze). Przełącznik modułu zmienia tylko admin.

Koszty (serwis ``services/finance_ledger/costs.py``):

* ``GET /module``, ``PUT /module`` — stan i przełącznik modułu,
* ``GET ?stage=&month=&journal=&category=&flag=&q=`` — zakładka etapu
  z licznikami etapów i dzienników (Kontraktorzy, Zakupy pozostałe, Biuro),
* ``GET /{id}`` — karta faktury z „Kogo dotyczy” i historią,
* ``GET /{id}/pdf`` — „Podgląd PDF”: wizualizacja XML-a z KSeF (pobranego na
  żądanie i zapamiętanego) albo PDF spoza KSeF (``invoice_preview.py``),
* ``POST /actions`` — Przyjmij, Odrzuć (z powodem), Zweryfikuj, Gotowa do
  księgowania, Cofnij o krok, dodaj/zdejmij flagę; dla zaznaczonych.
  „Zweryfikuj” fakturę kontraktora — lista „Weryfikujący kontraktorów” albo
  „Księgowi”, „Gotowa” i jej cofnięcie — „Księgowi” (403 dla reszty),
* ``PATCH /{id}`` — kategoria, flagi, termin płatności, notatka.

Kontrahenci (``counterparties.py``, ``counterparty_import.py``):

* ``GET ?q=&role=`` — kartoteka z rolą wyliczaną z NEXUSA,
* ``PATCH /{id}`` — konta Symfonii, ID partnera, e-mail,
* ``POST /import?save=`` — plik z eBI24 albo odesłany plik „czeka na Symfonię”:
  podgląd (``save=false``) i zapis,
* ``GET /pending`` — kontrahenci bez ID Symfonii (kartoteka, sprzedawcy
  i nabywcy spoza niej) i ``GET /pending/file`` — ich plik CSV dla księgowej.
"""

from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.scheduling import business_today
from app.models.user import User
from app.services.finance_ledger import approvers as cost_approvers
from app.services.finance_ledger import (
    costs,
    counterparties,
    invoice_preview,
    symfonia_partners,
)
from app.services.finance_ledger import counterparty_import as importer
from app.services.finance_ledger import settings as module_settings
from app.services.finance_ledger_schema import FLAGS, REASON_MAX
from app.services.hr.payroll_access import is_payroll

costs_router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)
counterparties_router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

MONTH_PATTERN = r"^(20[0-9]{2}|2100)-(0[1-9]|1[0-2])$"
Stage = Literal["received", "new", "verified", "ready", "booked", "rejected"]
Action = Literal[
    "accept", "reject", "verify", "ready", "back", "flag_add", "flag_remove"
]
Category = Literal["contractor", "team", "office", "benefit", "proforma", "other"]
Journal = Literal["contractors", "purchases", "office"]
Flag = Literal["mpp", "no_mpp", "hold_payment", "tax_office_account", "duplicate"]
#: Filtr flag: konkretna flaga albo „bez flag”.
FlagFilter = Literal[
    "mpp", "no_mpp", "hold_payment", "tax_office_account", "duplicate", "none"
]
#: Filtr „Zapłata” (E3, ``finance_payments``).
PaymentFilter = Literal["unpaid", "in_batch", "paid", "partially_paid"]


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
    journal: Optional[Journal] = Query(None),
    category: Optional[Category] = Query(None),
    flag: Optional[FlagFilter] = Query(None),
    q: Optional[str] = Query(None, max_length=120),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    payment: Optional[PaymentFilter] = Query(None),
) -> dict[str, Any]:
    await _open(db, current_user)
    return await costs.list_view(
        db,
        stage=stage,
        filters=costs.Filters(
            month=_month(month),
            category=category,
            journal=journal,
            flag=flag,
            q=q,
            payment=payment,
        ),
        limit=limit,
        offset=offset,
        viewer_id=current_user.id,
        payroll=is_payroll(current_user),
        approvers=await cost_approvers.load(db, current_user),
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
            approvers=await cost_approvers.load(db, current_user),
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
            db,
            entry_id,
            viewer_id=current_user.id,
            payroll=is_payroll(current_user),
            approvers=await cost_approvers.load(db, current_user),
        )
    except costs.LedgerError as exc:
        raise _ledger_fail(exc) from exc


@costs_router.get("/{entry_id}/pdf", response_model=None)
async def cost_pdf(
    entry_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> Response:
    await _open(db, current_user)
    try:
        preview = await invoice_preview.preview(
            db, entry_id, payroll=is_payroll(current_user), now=_now()
        )
    except costs.LedgerError as exc:
        raise _ledger_fail(exc) from exc
    headers = {
        "Content-Disposition": content_disposition(preview.filename, "inline"),
        "Cache-Control": "private, no-store",
    }
    if preview.path is not None:
        return FileResponse(
            preview.path, media_type=preview.media_type, headers=headers
        )
    return Response(preview.content, media_type=preview.media_type, headers=headers)


@costs_router.patch("/{entry_id}")
async def update_cost(
    entry_id: int,
    body: EntryPatch,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    approvers = await cost_approvers.load(db, current_user)
    try:
        await costs.update(
            db,
            entry_id,
            body.model_dump(exclude_unset=True),
            actor_id=current_user.id,
            now=_now(),
            payroll=is_payroll(current_user),
            approvers=approvers,
        )
    except costs.LedgerError as exc:
        await db.rollback()
        raise _ledger_fail(exc) from exc
    await db.commit()
    return await costs.card(
        db,
        entry_id,
        viewer_id=current_user.id,
        payroll=is_payroll(current_user),
        approvers=approvers,
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


@counterparties_router.get("/pending")
async def pending_counterparties(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Kontrahenci, którzy czekają na ID Symfonii (E0b)."""

    await _open(db, current_user)
    return await symfonia_partners.view(db, payroll=is_payroll(current_user))


@counterparties_router.get("/pending/file")
async def pending_counterparties_file(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> Response:
    """CSV roboczy dla księgowej: tylko ci z poprawnym numerem i nazwą."""

    await _open(db, current_user)
    items = await symfonia_partners.pending(db, payroll=is_payroll(current_user))
    content, count = symfonia_partners.render_csv(items)
    if count == 0:
        raise HTTPException(409, "Nikt nie czeka na założenie w Symfonii.")
    name = f"kontrahenci-do-symfonii-{business_today().isoformat()}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": content_disposition(name),
            "Cache-Control": "no-store",
        },
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
