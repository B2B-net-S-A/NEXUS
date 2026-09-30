"""Jednorazowe przeniesienie kart z portali do „Do przejrzenia” (30.09.2026).

``POST /api/admin/proposals/convert-integration-cards?dry_run=true`` liczy
(bez zapisu poza raportem) nietknięte karty auto-matcha z JJIT/RocketJobs
i oddaje raport od razu; ``dry_run=false`` (wymaga próby z ostatnich 7 dni)
przenosi je w tle. ``GET …/status`` pokazuje ostatnią próbę i stan zapisu.
Reguły wyboru i zapisu: ``app/services/job_board_cards_to_proposals.py``.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.core.tasks import spawn
from app.services import job_board_cards_to_proposals as conversion

router = APIRouter()


@router.post("/proposals/convert-integration-cards")
async def convert_integration_cards(
    current_user: AdminUser,
    dry_run: bool = Query(True),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Karty auto-matcha z portali → propozycje ``job_board``."""
    if conversion.is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Przeniesienie kart z portali już trwa.",
        )
    if dry_run:
        started = datetime.now(timezone.utc)
        report = await conversion.plan(db)
        await conversion.finish_run(db, report, started=started)
        return report
    if not await conversion.fresh_dry_run_exists(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Najpierw przebieg próbny (dry_run=true) — zapis wymaga raportu "
                "próbnego z ostatnich 7 dni."
            ),
        )
    spawn(
        conversion.run_apply(actor_user_id=current_user.id),
        "job_board_cards_to_proposals(apply)",
    )
    return {"status": "started", "dry_run": False}


@router.get("/proposals/convert-integration-cards/status")
async def convert_integration_cards_status(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await conversion.read_status(db)
