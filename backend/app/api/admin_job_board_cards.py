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

``job_ids=1,2,3`` (11.10.2026) zawęża próbę i zapis do wskazanych rekrutacji —
np. fali przeniesionej z Traffita; zapis wymaga próby TEGO SAMEGO zbioru.

``GET …/status`` pokazuje ostatnie próby i stan zapisów obu trybów. Reguły
wyboru i zapisu: ``app/services/job_board_cards_to_proposals.py``.
"""

from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Literal, Optional

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


def _job_ids(raw: Optional[str]) -> Optional[list[int]]:
    """``job_ids=1,2,3`` → zawężenie biegu; brak = cały zbiór."""
    parts = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if not all(part.isdigit() for part in parts):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="job_ids: lista id rekrutacji po przecinku.",
        )
    return conversion.normalize_job_ids(int(part) for part in parts)


@router.post("/proposals/convert-integration-cards")
async def convert_integration_cards(
    current_user: AdminUser,
    dry_run: bool = Query(True),
    mode: Literal["convert", "delete"] = Query("convert"),
    expected: Optional[int] = Query(None, ge=0),
    # ``Annotated``: wywołanie handlera wprost (testy, skrypty) dostaje
    # zwykłe ``None``, a nie obiekt ``Query``.
    job_ids: Annotated[Optional[str], Query(max_length=4000)] = None,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Karty auto-matcha z portali → propozycje ``job_board`` albo usunięcie."""
    scope = _job_ids(job_ids)
    if conversion.is_running(mode):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_ALREADY_RUNNING[mode]
        )
    if dry_run:
        started = datetime.now(timezone.utc)
        report = await conversion.plan(db, mode, job_ids=scope)
        await conversion.finish_run(db, report, started=started)
        return report
    if not await conversion.fresh_dry_run_exists(db, mode, job_ids=scope):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Najpierw przebieg próbny (dry_run=true) w tym trybie i dla tych "
                "samych rekrutacji — zapis wymaga próby z ostatnich 7 dni, "
                "zrobionej po ostatnim wdrożeniu."
            ),
        )
    targets = await conversion.count_targets(db, mode, job_ids=scope)
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
            conversion.run_apply(
                actor_user_id=current_user.id, mode=mode, job_ids=scope
            ),
            f"job_board_cards_to_proposals({mode})",
        )
    except Exception:
        conversion.release(mode)
        raise
    return {
        "status": "started",
        "dry_run": False,
        "mode": mode,
        "job_ids": scope,
        "targets": targets,
    }


@router.get("/proposals/convert-integration-cards/status")
async def convert_integration_cards_status(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await conversion.read_status(db)
