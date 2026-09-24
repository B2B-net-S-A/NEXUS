"""Scalanie duplikatów kandydatów — podgląd i wykonanie (admin + Head of Recruitment).

``GET  /api/candidates/{id}/merge-preview?other=`` — plan z odciskiem (``{id}`` = ocalały).
``POST /api/candidates/{id}/merge`` — ``{other, fingerprint, choices}``.

Logika i powody: ``app.services.candidate_merge``. Wpis Historii zdarzeń nie
niesie imion i nazwisk (``Kandydat #id``) — przeżywa usunięcie osoby.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.services import critical_events
from app.services.candidate_merge import (
    MergeError,
    build_plan,
    drop_duplicate_vector,
    execute_merge,
)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

EVENT_TYPE = "candidate.merge"


class CandidateMergeRequest(BaseModel):
    other: int = Field(..., gt=0, description="Duplikat, który zostanie usunięty.")
    fingerprint: str = Field(..., min_length=64, max_length=64)
    choices: Optional[dict[str, Literal["survivor", "duplicate"]]] = None


def _http(exc: MergeError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/{candidate_id}/merge-preview")
async def candidate_merge_preview(
    candidate_id: int,
    current_user: HeadOfRecruitmentPlus,
    other: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Co zostanie przeniesione z ``other`` na ``candidate_id``. Nic nie zapisuje."""

    try:
        plan = await build_plan(db, candidate_id, other)
    except MergeError as exc:
        raise _http(exc) from exc
    return plan.as_dict()


@router.post("/{candidate_id}/merge")
async def candidate_merge(
    candidate_id: int,
    body: CandidateMergeRequest,
    current_user: HeadOfRecruitmentPlus,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = await execute_merge(
            db,
            survivor_id=candidate_id,
            duplicate_id=body.other,
            fingerprint=body.fingerprint,
            choices=body.choices,
            user_id=current_user.id,
        )
    except MergeError as exc:
        # Bez `db.rollback()`: wygasiłby `current_user` (MissingGreenlet
        # w `record_blocked`). Niezatwierdzone zmiany wycofa `get_db`.
        if exc.code == "merge_blocked":
            await critical_events.record_blocked(
                actor=current_user,
                event_type=EVENT_TYPE,
                entity_type="contractor",
                entity_id=candidate_id,
                entity_label=f"Kandydat #{candidate_id}",
                reason_code="blocked",
                reason=", ".join(b["code"] for b in exc.extra.get("blockers", [])),
                details={"duplicate_id": body.other},
            )
        raise _http(exc) from exc

    await critical_events.record_executed(
        db,
        actor=current_user,
        event_type=EVENT_TYPE,
        entity_type="contractor",
        entity_id=candidate_id,
        entity_label=f"Kandydat #{candidate_id}",
        reason=(
            f"Scalono duplikat Kandydat #{body.other} z Kandydat #{candidate_id}; "
            "duplikat usunięty."
        ),
        details={
            "duplicate_id": body.other,
            "moved_rows": result["moved_rows"],
            "replaced_rows": result["replaced_rows"],
            "fields_from_duplicate": result["fields_from_duplicate"],
        },
    )
    await db.commit()
    background_tasks.add_task(drop_duplicate_vector, body.other)
    return result
