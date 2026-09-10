"""Jednorazowe czyszczenie zakładki „Nieaktywni klienci" — trasy administratora.

Przepływ: podgląd (tylko odczyt) → zatwierdzenie konkretnej listy przez
administratora → wykonanie → raport z dwiema listami (A: usunięci,
B: wstrzymani z powodem). Wykonanie jest jednorazowe: drugie wywołanie
dostaje 409 z datą pierwszego. Logika: ``services/inactive_client_cleanup`` (ocena)
i ``services/inactive_client_cleanup_run`` (wykonanie, raport).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.schemas.client_cleanup import (
    CleanupExecuteRequest,
    CleanupPreviewResponse,
    CleanupReport,
    CleanupStatusResponse,
)
from app.services.inactive_client_cleanup import (
    SOURCE_LABELS,
    CleanupAlreadyExecutedError,
    evaluate_inactive_clients,
)
from app.services.inactive_client_cleanup_run import (
    execute_inactive_client_cleanup,
    get_cleanup_run,
    load_cleanup_report,
)

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)


def _already_executed(executed_at) -> HTTPException:
    when = executed_at.strftime("%d.%m.%Y %H:%M") if executed_at else "wcześniej"
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"Czyszczenie listy nieaktywnych klientów zostało już wykonane ({when}). "
            "To operacja jednorazowa — raport z obiema listami jest dostępny."
        ),
    )


@router.get("/directory/inactive-cleanup", response_model=CleanupStatusResponse)
async def get_inactive_cleanup_status(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    report = await load_cleanup_report(db)
    return CleanupStatusResponse(
        report=CleanupReport(**report) if report is not None else None,
        source_labels=SOURCE_LABELS,
    )


@router.get(
    "/directory/inactive-cleanup/preview", response_model=CleanupPreviewResponse
)
async def preview_inactive_cleanup(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Co zrobiłoby czyszczenie — bez żadnego zapisu."""

    existing = await get_cleanup_run(db)
    if existing is not None:
        raise _already_executed(existing.executed_at)
    plan = await evaluate_inactive_clients(db)
    return CleanupPreviewResponse(**plan.as_dict(), source_labels=SOURCE_LABELS)


@router.post("/directory/inactive-cleanup/execute", response_model=CleanupReport)
async def execute_inactive_cleanup(
    payload: CleanupExecuteRequest,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    existing = await get_cleanup_run(db)
    if existing is not None:
        raise _already_executed(existing.executed_at)
    if not payload.confirmed_client_ids:
        # Operacja jest jednorazowa — zapis raportu bez usunięcia kogokolwiek
        # zablokowałby ją na zawsze, zanim ktokolwiek rozstrzygnie listę B.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Brak klientów zatwierdzonych do usunięcia — nic nie zapisano.",
        )
    try:
        await execute_inactive_client_cleanup(
            db,
            actor=current_user,
            confirmed_client_ids=payload.confirmed_client_ids,
        )
    except CleanupAlreadyExecutedError as exc:
        raise _already_executed(exc.run.executed_at) from exc
    await db.commit()
    report = await load_cleanup_report(db)
    if report is None:  # pragma: no cover — właśnie zapisany
        raise HTTPException(status_code=500, detail="Brak raportu po wykonaniu")
    return CleanupReport(**report)
