"""Krajowy Rejestr Zadłużonych przy umowie B2B z Generatora (0801, 27.11.2026).

Reguły i kształt zapisu: ``services/b2b_contract_generator/krz.py``. Tu dwie
trasy rejestru:

* ``PUT /generated/{id}/krz`` — wynik sprawdzenia zaznaczony przez osobę, która
  wysyła albo potwierdza podpis tej umowy (ta sama reguła co „Wyślij do
  podpisu” i „Oznacz jako podpisaną”);
* ``POST /generated/{id}/krz/decision`` — Delivery Lead klienta (bez niego
  Head of Recruitment; admin i Head of Recruitment zawsze) dopuszcza umowę do
  podpisu mimo wpisu albo jej nie dopuszcza, co anuluje umowę („Anulowana”).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.b2b_contract_generator import (
    _assert_generator_client_access,
    _reject_excel_row,
    _serialize_generated_contract,
    may_confirm_row_signature,
)
from app.api.b2b_esign import _assert_row_sender
from app.api.contract_access import B2BGeneratorAccess
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.user import User
from app.schemas.b2b_contract_generator import (
    B2BGeneratedContractItem,
    B2BKrzCheckIn,
    B2BKrzDecisionIn,
)
from app.services.b2b_contract_generator import krz

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

MSG_NOT_APPLICABLE = (
    "Sprawdzenie w KRZ dotyczy niepodpisanych umów B2B z Generatora "
    "(bez umów zlecenia i nowej umowy dla aktywnych kontraktorów)."
)
MSG_NOT_IN_PROGRESS = "Wynik KRZ zapisuje się przy umowie „W trakcie”."
MSG_MAY_NOT_RECORD = (
    "Wynik KRZ zapisuje osoba, która wysyła tę umowę do podpisu albo "
    "potwierdza jej podpis."
)
MSG_NOTHING_TO_DECIDE = "Ta umowa nie ma wpisu w KRZ, który czeka na decyzję."
MSG_MAY_NOT_DECIDE = (
    "Wpis w KRZ rozstrzyga Delivery Lead klienta, a bez niego Head of Recruitment."
)


async def _load(db: AsyncSession, generated_id: int) -> B2BGeneratedContract:
    row = await db.get(B2BGeneratedContract, generated_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    _reject_excel_row(row)
    return row


async def _locked(db: AsyncSession, generated_id: int) -> B2BGeneratedContract:
    row = await db.scalar(
        select(B2BGeneratedContract)
        .where(B2BGeneratedContract.id == generated_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    return row


async def _assert_may_record(
    db: AsyncSession, user: User, row: B2BGeneratedContract
) -> None:
    if await may_confirm_row_signature(db, user, row):
        return
    try:
        await _assert_row_sender(db, user, row)
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        raise HTTPException(status_code=403, detail=MSG_MAY_NOT_RECORD) from exc


async def _applies(db: AsyncSession, row: B2BGeneratedContract) -> bool:
    return krz.applies(
        row, from_mass_send=bool(await krz.mass_send_row_ids(db, [row.id]))
    )


@router.put("/generated/{generated_id}/krz", response_model=B2BGeneratedContractItem)
async def record_krz_check(
    generated_id: int,
    body: B2BKrzCheckIn,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> B2BGeneratedContractItem:
    row = await _load(db, generated_id)
    if not await _applies(db, row):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=MSG_NOT_APPLICABLE
        )
    if row.contract_status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=MSG_NOT_IN_PROGRESS
        )
    await _assert_may_record(db, current_user, row)

    row = await _locked(db, generated_id)
    check = krz.new_check(
        result=body.result,
        entry_kind=body.entry_kind,
        entry_note=body.entry_note,
        nip=row.partner_nip,
        actor_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    await krz.record_check(db, row, check, actor_id=current_user.id)
    await db.commit()
    await db.refresh(row)
    return await _serialize_generated_contract(db, row, current_user)


@router.post(
    "/generated/{generated_id}/krz/decision",
    response_model=B2BGeneratedContractItem,
)
async def decide_krz_entry(
    generated_id: int,
    body: B2BKrzDecisionIn,
    current_user: B2BGeneratorAccess,
    db: AsyncSession = Depends(get_db),
) -> B2BGeneratedContractItem:
    row = await _load(db, generated_id)
    await _assert_generator_client_access(db, current_user, row.client_id, write=False)
    if not krz.always_decides(current_user) and current_user.id not in (
        await krz.decider_ids(db, row)
    ):
        raise HTTPException(status_code=403, detail=MSG_MAY_NOT_DECIDE)

    row = await _locked(db, generated_id)
    check = krz.current_check(row)
    if (
        not await _applies(db, row)
        or row.contract_status != "in_progress"
        or check is None
        or check.get("result") != krz.RESULT_ENTRY
        or check.get("decision") is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=MSG_NOTHING_TO_DECIDE
        )

    row.krz_check = krz.with_decision(
        check,
        decision=body.decision,
        reason=body.reason,
        actor_id=current_user.id,
        now=datetime.now(timezone.utc),
    )
    old_status = row.contract_status
    if body.decision == krz.DECISION_REJECTED:
        # „Nie podpisujemy”: umowa nie dochodzi do skutku — ten sam stan co
        # „Zmień status → Anulowana” (numer zostaje w rejestrze).
        row.contract_status = "cancelled"
    krz.add_history(
        db,
        row,
        actor_id=current_user.id,
        label=krz.decision_label(row.krz_check),
        from_status=old_status,
    )
    if body.decision == krz.DECISION_ALLOWED:
        await krz.notify_allowed(db, row, actor_id=current_user.id)
    await db.commit()
    await db.refresh(row)
    return await _serialize_generated_contract(db, row, current_user)
