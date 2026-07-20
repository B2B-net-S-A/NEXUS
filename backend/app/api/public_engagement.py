"""Public (auth-less) endpoints for self-service engagement declaration.

Phase „Otwartość na dodatkowe projekty" Faza 2.6 — magic-link flow.

Rekruter generuje token przez `POST /api/candidates/{id}/engagement-declaration-link`
(auth required). Kandydat klika link `https://<app>/engagement/{token}` i przez
ten public router aktualizuje swoje preferencje engagement bez logowania.

Bezpieczeństwo:
- Token jednokrotny (`used_at` set on first successful POST → ponowne POST → 410).
- TTL 30 dni (`expires_at` < now → 410).
- Brak auth, ale ekspozycja jest minimalna: zwracamy tylko imię kandydata.
- Rate-limit przez globalny slowapi (limit per IP).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.engagement_token import EngagementDeclarationToken


router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────


class PublicEngagementView(BaseModel):
    """Bezpieczna projekcja kandydata + jego flag — bez emaila/telefonu/itp."""

    candidate_first_name: str
    open_to_side_projects: bool
    open_to_sales_support: bool
    open_to_expert_consult: bool
    expires_at: datetime


class PublicEngagementSubmit(BaseModel):
    open_to_side_projects: bool
    open_to_sales_support: bool
    open_to_expert_consult: bool
    notes: Optional[str] = None


class PublicEngagementSubmitResponse(BaseModel):
    success: bool
    candidate_first_name: str
    saved_at: datetime


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _resolve_token(token: str, db: AsyncSession) -> EngagementDeclarationToken:
    row = await db.scalar(
        select(EngagementDeclarationToken).where(
            EngagementDeclarationToken.token == token
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Link nieprawidłowy lub wygasł.")
    now = datetime.now(timezone.utc)
    if row.expires_at < now:
        raise HTTPException(status_code=410, detail="Link wygasł.")
    if row.used_at is not None:
        raise HTTPException(status_code=410, detail="Link już został użyty.")
    return row


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/public/engagement-declaration/{token}",
    response_model=PublicEngagementView,
)
async def get_engagement_form(token: str, db: AsyncSession = Depends(get_db)):
    """Public read — zwraca obecne wartości flag + imię kandydata.

    Nie zwracamy emaila/telefonu/skilli — żeby enumeracja tokenów nie dała
    wycieku PII.
    """
    row = await _resolve_token(token, db)
    candidate = row.candidate
    return PublicEngagementView(
        candidate_first_name=candidate.name or "",
        open_to_side_projects=candidate.open_to_side_projects,
        open_to_sales_support=candidate.open_to_sales_support,
        open_to_expert_consult=candidate.open_to_expert_consult,
        expires_at=row.expires_at,
    )


@router.post(
    "/public/engagement-declaration/{token}",
    response_model=PublicEngagementSubmitResponse,
)
async def submit_engagement_form(
    token: str,
    data: PublicEngagementSubmit,
    db: AsyncSession = Depends(get_db),
):
    """Public submit — kandydat ustawia 3 flagi + opcjonalną notatkę.

    Token zostaje oznaczony jako `used_at = now` (jednokrotny). Backend
    aktualizuje też 3 timestampy `*_updated_at` zgodnie z Fazą 2.2.
    """
    row = await _resolve_token(token, db)
    candidate = row.candidate

    now = datetime.now(timezone.utc)
    # Atomic single-use claim BEFORE any side effect. _resolve_token already
    # rejected a used token, but two concurrent submits could both pass that
    # read and then both append a duplicate note / double-write the flags. The
    # guarded UPDATE lets exactly one win; the loser gets 410 and touches
    # nothing. Same transaction, so a later failure rolls the claim back.
    claimed = (
        await db.execute(
            update(EngagementDeclarationToken)
            .where(
                EngagementDeclarationToken.token == token,
                EngagementDeclarationToken.used_at.is_(None),
            )
            .values(used_at=now)
            .returning(EngagementDeclarationToken.token)
        )
    ).first()
    if claimed is None:
        raise HTTPException(status_code=410, detail="Link już został użyty.")

    # Update flagi + per-flag timestamps (replikacja logiki z PATCH /engagement)
    candidate.open_to_side_projects = data.open_to_side_projects
    candidate.open_to_sales_support = data.open_to_sales_support
    candidate.open_to_expert_consult = data.open_to_expert_consult
    candidate.open_to_side_projects_updated_at = now
    candidate.open_to_sales_support_updated_at = now
    candidate.open_to_expert_consult_updated_at = now
    if data.notes:
        # Append, nie nadpisuj — rekruter mógł mieć tam już swoje notatki.
        prev = (candidate.engagement_notes or "").strip()
        suffix = f"\n[deklaracja kandydata, {now:%Y-%m-%d}]: {data.notes.strip()}"
        candidate.engagement_notes = (prev + suffix).strip() if prev else suffix.strip()

    await db.commit()

    return PublicEngagementSubmitResponse(
        success=True,
        candidate_first_name=candidate.name or "",
        saved_at=now,
    )
