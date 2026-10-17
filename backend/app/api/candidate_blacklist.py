"""Okno „Czarna lista…” — jedno wejście dla obu zakresów (17.10.2026).

* ``POST /api/candidates/{id}/blacklist`` — ``scope: global`` ustawia status
  ``blacklisted`` z osobą, datą i powodem; ``scope: client`` dopisuje wpis
  „Czarna lista klienta” do rejestru konfliktów (ostrzeżenie, nie blokada).
  Dodaje każdy z zapisem kandydata — także rekruter: globalną listę mógł
  ustawić i wcześniej (pole „Status”), a wpis u klienta niczego nie blokuje.
* ``POST /api/candidates/{id}/blacklist/remove`` — zdjęcie czarnej listy
  „u nas”, z powodem; tylko admin, Delivery Lead i Head of Recruitment.
  Wpis u klienta zdejmuje się jak każdy konflikt (``/conflicts/{id}/deactivate``).

``PATCH /api/candidates/{id}`` nie zmienia już statusu na ani z
``blacklisted`` (422) — inaczej powód i autor dałyby się ominąć.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AfterValidator, BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import require_candidate_write
from app.api.candidate_conflicts import ConflictCreate, add_conflict
from app.api.deps import require_roles
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_conflict import ConflictType
from app.models.user import User
from app.services.candidate_blacklist import (
    REASON_MAX_LENGTH,
    REASON_MIN_LENGTH,
    REMOVER_ROLES,
    blacklist_info,
    clear_blacklist,
    mark_blacklisted,
)
from app.services.candidate_identity_ownership import (
    lock_changed_traffit_synced_fields,
)
from app.services.match_score_cache import mark_stale_for_candidate

router = APIRouter()

ALREADY_BLACKLISTED_DETAIL = {
    "code": "already_blacklisted",
    "message": "Osoba jest już na czarnej liście u nas.",
}
NOT_BLACKLISTED_DETAIL = {
    "code": "not_blacklisted",
    "message": "Osoba nie jest na czarnej liście u nas.",
}
REASON_TOO_SHORT = f"Wpisz powód (co najmniej {REASON_MIN_LENGTH} znaków)."


def _reason(value: str) -> str:
    stripped = value.strip()
    if len(stripped) < REASON_MIN_LENGTH:
        raise ValueError(REASON_TOO_SHORT)
    return stripped


Reason = Annotated[str, Field(max_length=REASON_MAX_LENGTH), AfterValidator(_reason)]


class BlacklistAdd(BaseModel):
    scope: Literal["global", "client"]
    client_id: Optional[int] = None
    reason: Reason

    @model_validator(mode="after")
    def _client_needs_id(self) -> "BlacklistAdd":
        if self.scope == "client" and self.client_id is None:
            raise ValueError("Wybierz klienta.")
        return self


class BlacklistRemove(BaseModel):
    reason: Reason


async def _locked_candidate(db: AsyncSession, candidate_id: int) -> Candidate:
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@router.post("/candidates/{candidate_id}/blacklist")
async def add_to_blacklist(
    candidate_id: int,
    data: BlacklistAdd,
    current_user: User = Depends(require_candidate_write),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if data.scope == "client":
        conflict = await add_conflict(
            db,
            candidate_id=candidate_id,
            data=ConflictCreate(
                client_id=data.client_id,
                type=ConflictType.blacklist,
                reason=data.reason,
            ),
            user=current_user,
        )
        return {"scope": "client", "conflict": conflict}

    candidate = await _locked_candidate(db, candidate_id)
    if candidate.status == CandidateStatus.blacklisted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ALREADY_BLACKLISTED_DETAIL
        )
    # Status ręcznie poprawiony w NEXUSIE — import nie może go cofnąć.
    lock_changed_traffit_synced_fields(
        candidate, {"status": CandidateStatus.blacklisted}, user_id=current_user.id
    )
    mark_blacklisted(
        candidate,
        user_id=current_user.id,
        reason=data.reason,
        at=datetime.now(timezone.utc),
    )
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="candidate_blacklisted",
            user_id=current_user.id,
            details={"scope": "global", "reason": data.reason},
        )
    )
    # Ocena dopasowania zeruje osobę z czarnej listy — cache musi się przeliczyć.
    await mark_stale_for_candidate(db, candidate.id)
    info = blacklist_info(candidate, current_user.name)
    await db.commit()
    return {
        "scope": "global",
        "status": CandidateStatus.blacklisted.value,
        "blacklist": info.model_dump(mode="json") if info else None,
    }


@router.post(
    "/candidates/{candidate_id}/blacklist/remove",
    dependencies=[Depends(require_candidate_write)],
)
async def remove_from_blacklist(
    candidate_id: int,
    data: BlacklistRemove,
    current_user: User = Depends(require_roles(*REMOVER_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    candidate = await _locked_candidate(db, candidate_id)
    if candidate.status != CandidateStatus.blacklisted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=NOT_BLACKLISTED_DETAIL
        )
    added_reason = candidate.blacklist_reason
    lock_changed_traffit_synced_fields(
        candidate, {"status": CandidateStatus.active}, user_id=current_user.id
    )
    clear_blacklist(candidate)
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="candidate_blacklist_removed",
            user_id=current_user.id,
            details={
                "scope": "global",
                "reason": data.reason,
                "added_reason": added_reason,
            },
        )
    )
    await mark_stale_for_candidate(db, candidate.id)
    await db.commit()
    return {"status": CandidateStatus.active.value, "blacklist": None}
