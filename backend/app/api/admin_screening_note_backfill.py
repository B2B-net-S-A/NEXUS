"""Uzupełnienie historii: odpowiedzi z kart rekomendacji do arkuszy (07.10.2026).

``POST /api/admin/screening-note-backfill?dry_run=true`` liczy (bez zapisu
poza raportem), co stanie się z arkuszami screeningu par, które mają
odpowiedzi w karcie rekomendacji, i oddaje raport od razu.
``dry_run=false&expected=N`` (wymaga próby z ostatnich 7 dni, ``N`` = jej
``to_change``) zapisuje w tle. ``GET …/status`` pokazuje ostatnią próbę
i paragon zapisu. Reguły: ``app/services/screening_note_sync.py`` (zapis)
i ``app/services/screening_note_backfill.py`` (przebieg).

``include_other_notes=true`` (etap 1b) bierze także notatki innych rodzajów
niż karta. Zapis w tym trybie wymaga próby w tym samym trybie i włączonego
``SCREENING_NOTE_SYNC_OTHER_NOTES_ENABLED``.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.core.tasks import spawn
from app.services import screening_note_backfill as backfill
from app.services import screening_note_sync

router = APIRouter()


@router.post("/screening-note-backfill")
async def screening_note_backfill(
    current_user: AdminUser,
    dry_run: bool = Query(True),
    expected: Optional[int] = Query(None, ge=0),
    include_other_notes: bool = Query(False),
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
        report = await backfill.plan(db, include_other_notes=include_other_notes)
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
    other_notes = include_other_notes or screening_note_sync.other_notes_enabled()
    if bool(report.get("include_other_notes")) != other_notes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Ostatnia próba liczyła inny zakres notatek (karty / także inne "
                "notatki). Uruchom próbę w tym samym trybie co zapis."
            ),
        )
    if include_other_notes and not screening_note_sync.other_notes_enabled():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Zapis odpowiedzi z innych notatek wymaga włączonego "
                "SCREENING_NOTE_SYNC_OTHER_NOTES_ENABLED — inaczej przeliczenie "
                "karty wyczyściłoby te arkusze."
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
            backfill.run_apply(
                actor_user_id=current_user.id, include_other_notes=other_notes
            ),
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
