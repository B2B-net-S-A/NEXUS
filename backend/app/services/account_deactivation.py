"""Wyłączenie konta NEXUSA — jedno miejsce dla wszystkich ścieżek.

Robi to, co od początku robił ``DELETE /api/admin/users/{id}``: koniec sesji
(``authorization_version``, ``tokens_valid_after``), ``is_active=False``,
unieważnienie stałego linku kariery rekrutera (audyt 22.09 r2, SEC-06) i wpis
``activities`` z akcją ścieżki. Akcja powinna być w
``app.services.hr.account_profiles.DEACTIVATION_ACTIONS`` — z niej kartoteka
bierze dzień wyłączenia. Żywe pary kandydatów osoby przejmują Delivery Leadzi
rekrutacji (``departure_care``, decyzja Artura 28.10.2026).

Wołający blokuje wiersz konta (``SELECT … FOR UPDATE``), pilnuje ostatniego
admina (``protect_active_admin_membership``) i commituje.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.invite_link import CandidateInviteLink
from app.models.user import User


async def deactivate_account(
    db: AsyncSession,
    user: User,
    *,
    action: str,
    actor_id: Optional[int],
    details: dict[str, Any],
    now: Optional[datetime] = None,
) -> None:
    if user.is_active:
        user.authorization_version += 1
        user.tokens_valid_after = now or datetime.now(timezone.utc)
    user.is_active = False
    await db.execute(
        update(CandidateInviteLink)
        .where(
            CandidateInviteLink.created_by == user.id,
            CandidateInviteLink.kind == "recruiter",
        )
        .values(revoked=True)
    )
    db.add(
        Activity(
            entity_type="user",
            entity_id=user.id,
            action=action,
            user_id=actor_id,
            details=details,
        )
    )
    # Odejście z firmy: kandydaci osoby → Delivery Leadzi ich rekrutacji.
    # Awaria nie zatrzymuje wyłączenia — pętla triggerów nadrobi.
    from app.services.departure_care import hand_over_safely  # noqa: PLC0415

    await hand_over_safely(db, user, actor_id=actor_id)
