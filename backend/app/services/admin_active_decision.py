"""Ostatnia JAWNA decyzja admina o aktywności konta.

Runda 9 (R9-N13-2, decyzja Artura 27.09.2026): przy
``AAD_GROUP_RBAC_ENABLED`` logowanie SSO wyprowadza ``is_active`` z grup AAD
i do tej zmiany włączało każde konto obecne w grupie — także takie, które
admin świadomie wyłączył w panelu. Decyzja admina wygrywa.

Ta sama definicja „jawnej decyzji” co w ``services/compass_lifecycle.py``:
``active_changed`` zapisuje wyłącznie ``PUT /api/admin/users/{id}``,
``user_deactivated`` — ``DELETE /api/admin/users/{id}``. Logowanie SSO,
resync grup AAD i pętla Compassa przestawiają ``is_active`` bez tych wpisów,
więc nie są decyzją admina.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity

ADMIN_ACTIVE_DECISION_ACTIONS = ("active_changed", "user_deactivated")


async def latest_admin_active_decision(
    db: AsyncSession, user_id: int
) -> Optional[bool]:
    """``True`` = admin włączył, ``False`` = wyłączył, ``None`` = brak decyzji."""
    latest: Optional[Activity] = await db.scalar(
        select(Activity)
        .where(
            Activity.entity_type == "user",
            Activity.entity_id == user_id,
            Activity.action.in_(ADMIN_ACTIVE_DECISION_ACTIONS),
        )
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(1)
    )
    if latest is None:
        return None
    if latest.action == "user_deactivated":
        return False
    details = latest.details if isinstance(latest.details, dict) else {}
    to = details.get("to")
    if to is True:
        return True
    if to is False:
        return False
    return None
