"""Karty z portali: przeniesienie do „Do przejrzenia” albo usunięcie.

``POST /api/admin/proposals/convert-integration-cards?dry_run=true`` liczy
(bez zapisu poza raportem) nietknięte karty auto-matcha z JJIT/RocketJobs
i oddaje raport od razu. ``mode=convert`` (domyślnie) — opublikowane
rekrutacje z NEXUSA, karta → propozycja ``job_board``; ``mode=delete``
(06.10.2026) — rekrutacje ZAMKNIĘTE (z Traffita i z NEXUSA), karta znika
drogą „Usuń z rekrutacji”, bez propozycji.

``dry_run=false`` przenosi/usuwa w tle i wymaga:

* próby tego trybu z ostatnich 7 dni, zrobionej PO starcie tego procesu
  (po deployu — nowa próba; reguły mogły się zmienić);
* ``expected`` równego liczbie par, które zapis wziąłby teraz — inna liczba
  albo zero = 409 i nic się nie zapisuje.

``GET …/status`` pokazuje ostatnie próby i stan zapisów obu trybów. Reguły
wyboru i zapisu: ``app/services/job_board_cards_to_proposals.py``.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.core.tasks import spawn
from app.services import job_board_cards_to_proposals as conversion

router = APIRouter()

_ALREADY_RUNNING = {
    conversion.MODE_CONVERT: "Przeniesienie kart z portali już trwa.",
    conversion.MODE_DELETE: "Usuwanie kart z zamkniętych rekrutacji już trwa.",
}


@router.post("/proposals/convert-integration-cards")
async def convert_integration_cards(
    current_user: AdminUser,
    dry_run: bool = Query(True),
    mode: Literal["convert", "delete"] = Query("convert"),
    expected: Optional[int] = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Karty auto-matcha z portali → propozycje ``job_board`` albo usunięcie."""
    if conversion.is_running(mode):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_ALREADY_RUNNING[mode]
        )
    if dry_run:
        started = datetime.now(timezone.utc)
        report = await conversion.plan(db, mode)
        await conversion.finish_run(db, report, started=started)
        return report
    if not await conversion.fresh_dry_run_exists(db, mode):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Najpierw przebieg próbny (dry_run=true) w tym trybie — zapis "
                "wymaga próby z ostatnich 7 dni, zrobionej po ostatnim wdrożeniu."
            ),
        )
    targets = await conversion.count_targets(db, mode)
    if targets == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nie ma kart, które spełniają warunki — nic do zapisania.",
        )
    if expected is None or expected != targets:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Liczba kart różni się od podanej (teraz {targets}). Uruchom "
                "próbę (dry_run=true) jeszcze raz i podaj jej wynik w parametrze "
                "expected."
            ),
        )
    # Rezerwacja synchronicznie w handlerze: `spawn` startuje zadanie dopiero
    # w kolejnej iteracji pętli, więc dwa szybkie POST-y przeszłyby oba.
    if not conversion.reserve(mode):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_ALREADY_RUNNING[mode]
        )
    try:
        spawn(
            conversion.run_apply(actor_user_id=current_user.id, mode=mode),
            f"job_board_cards_to_proposals({mode})",
        )
    except Exception:
        conversion.release(mode)
        raise
    return {"status": "started", "dry_run": False, "mode": mode, "targets": targets}


@router.get("/proposals/convert-integration-cards/status")
async def convert_integration_cards_status(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await conversion.read_status(db)
