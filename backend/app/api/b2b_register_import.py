"""Import rejestru umów z Excela działu — trasy admina.

Prefiks ``/api/b2b-generator`` (rejestracja w ``main.py``). Bez
``from __future__ import annotations`` — router nie ma dziś ``@limiter.limit``,
ale pułapka slowapi #579 (PEP 563 zamienia ``Annotated`` w parametry query)
dotyka każdego modułu, któremu ktoś kiedyś limit dołoży.

Wzór uploadu: import Nordea CSV (``admin_import.py``) — tylko ``.xlsx``,
odczyt ``read(LIMIT + 1)`` → 413.
"""

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.b2b_register_import import B2BRegisterImportRun
from app.models.user import User
from app.services.b2b_register_import.parser import RegisterParseError
from app.services.b2b_register_import.service import (
    RegisterImportConflict,
    payload_sha256,
    record_dry_run,
    rollback_run,
    run_import,
)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

MAX_REGISTER_IMPORT_BYTES = 10 * 1024 * 1024


@router.post("/register-import")
async def import_register(
    admin: AdminUser,
    dry_run: bool = Query(True),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Podgląd (domyślnie) albo zapis rejestru umów z Excela działu."""
    # Przed rollbackiem podglądu — po nim obiekt konta jest wygasły, a jego
    # doczytanie w async to `MissingGreenlet`.
    admin_id = admin.id
    filename = file.filename or "rejestr.xlsx"
    if not filename.casefold().endswith(".xlsx"):
        raise HTTPException(422, detail="Import wymaga pliku Excel .xlsx.")
    payload = await file.read(MAX_REGISTER_IMPORT_BYTES + 1)
    if len(payload) > MAX_REGISTER_IMPORT_BYTES:
        raise HTTPException(413, detail="Plik przekracza limit 10 MB.")
    try:
        report = await run_import(
            db, payload=payload, filename=filename, user_id=admin_id, dry_run=dry_run
        )
    except RegisterParseError as exc:
        await db.rollback()
        raise HTTPException(422, detail=str(exc)) from exc
    except RegisterImportConflict as exc:
        await db.rollback()
        raise HTTPException(409, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        raise
    if dry_run:
        # Ta sama ścieżka co zapis, zakończona rollbackiem. Zostaje tylko
        # ślad podglądu (same liczby) — on odblokowuje „Zastosuj”.
        await db.rollback()
        report["run_id"] = await record_dry_run(
            db,
            sha=payload_sha256(payload),
            filename=filename,
            user_id=admin_id,
            counters=report["counters"],
        )
    await db.commit()
    return report


@router.post("/register-import/runs/{run_id}/rollback")
async def rollback_register_import(
    run_id: int,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    admin_id = admin.id
    try:
        result = await rollback_run(db, run_id=run_id, user_id=admin_id)
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(404, detail="Przebieg importu nie istnieje.") from exc
    except RegisterImportConflict as exc:
        await db.rollback()
        raise HTTPException(409, detail=str(exc)) from exc
    await db.commit()
    return {"run_id": run_id, **result}


@router.get("/register-import/runs")
async def list_register_import_runs(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(B2BRegisterImportRun, User.name)
            .outerjoin(User, User.id == B2BRegisterImportRun.created_by)
            .order_by(B2BRegisterImportRun.id.desc())
            .limit(limit)
        )
    ).all()
    latest_applied = next((run.id for run, _ in rows if run.mode == "applied"), None)
    return [
        {
            "id": run.id,
            "mode": run.mode,
            "filename": run.source_filename,
            "sha256": run.source_sha256,
            "counters": run.counters or {},
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "created_by_name": author,
            "rolled_back_at": run.rolled_back_at.isoformat()
            if run.rolled_back_at
            else None,
            # Cofnąć można tylko ostatni zastosowany przebieg (serwer i tak to
            # sprawdza — flaga tylko chowa przycisk).
            "can_rollback": run.mode == "applied" and run.id == latest_applied,
        }
        for run, author in rows
    ]
