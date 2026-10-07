"""Uzupełnienie historii: odpowiedzi z kart rekomendacji do arkuszy (07.10.2026).

``POST /api/admin/screening-note-backfill?dry_run=true`` liczy (bez zapisu
poza raportem), co stanie się z arkuszami screeningu par, które mają
odpowiedzi w karcie rekomendacji, i oddaje raport od razu.
``dry_run=false&expected=N`` (wymaga próby z ostatnich 7 dni, ``N`` = jej
``to_change``) zapisuje w tle. ``GET …/status`` pokazuje ostatnią próbę
i paragon zapisu. Reguły: ``app/services/screening_note_sync.py`` (zapis)
i ``app/services/screening_note_backfill.py`` (przebieg).
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.core.tasks import spawn
from app.services import screening_note_backfill as backfill

router = APIRouter()


@router.post("/screening-note-backfill")
async def screening_note_backfill(
    current_user: AdminUser,
    dry_run: bool = Query(True),
    expected: Optional[int] = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Odpowiedzi z kart rekomendacji → arkusze screeningu (``note_sync``)."""
    if backfill.is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Uzupełnianie arkuszy z notatek już trwa.",
        )
    if dry_run:
        started = datetime.now(timezone.utc)
        report = await backfill.plan(db)
        await backfill.finish_run(db, report, started=started)
        return report
    report = await backfill.fresh_dry_run(db)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Najpierw przebieg próbny (dry_run=true) — zapis wymaga raportu "
                "próbnego z ostatnich 7 dni."
            ),
        )
    to_change = int(report.get("to_change") or 0)
    if not to_change:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Próba nie znalazła żadnego arkusza do zmiany.",
        )
    if expected is None or expected != to_change:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Parametr expected musi być równy liczbie par do zmiany z próby "
                f"({to_change}). Przejrzyj raport próby i podaj tę liczbę."
            ),
        )
    if not backfill.reserve():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Uzupełnianie arkuszy z notatek już trwa.",
        )
    try:
        spawn(
            backfill.run_apply(actor_user_id=current_user.id),
            "screening_note_backfill(apply)",
        )
    except Exception:
        backfill.release()
        raise
    return {"status": "started", "dry_run": False, "expected": expected}


@router.get("/screening-note-backfill/status")
async def screening_note_backfill_status(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await backfill.read_status(db)
