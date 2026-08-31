"""Router `/api/my-relationships` — DL widzi swoje key contacts cross-client.

DL który zaznaczył kontakty u różnych klientów jako `is_key_relationship=True`
(plus `key_relationship_owner_id=current_user.id`) tu widzi je w jednym widoku
posortowane po `last_personal_touchpoint_at` (najstarsze najpierw — do
follow-up planning).

Admin/HoR/Finance widzi wszystkie key relationships (bez filtra po owner_id).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.client import Client
from app.models.contact import Contact, RelationshipStrength
from app.models.user import UserRole

router = APIRouter()


class MyRelationshipRow(BaseModel):
    contact_id: int
    name: str
    position: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    client_id: int
    client_name: str
    is_decision_maker: bool = False
    relationship_strength: Optional[RelationshipStrength] = None
    relationship_notes: Optional[str] = None
    last_personal_touchpoint_at: Optional[datetime] = None
    last_contacted_at: Optional[datetime] = None
    days_since_personal_touchpoint: Optional[int] = None
    """`None` jeśli nigdy nie było personal touchpoint (do follow-up priorytet)."""

    model_config = {"from_attributes": True}


@router.get("", response_model=list[MyRelationshipRow])
async def list_my_key_relationships(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Lista key contactów DL'a cross-client, posortowane po stalności touchpoint'u.

    Admin/HoR/Finance widzi wszystkie key contacts (management read view).
    """
    # Multi-role aware (M1-RBAC-02) — patrz my_clients.py.
    is_organization_reader = user.has_any_role(
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.finance,
    )

    stmt = (
        select(
            Contact.id,
            Contact.name,
            Contact.position,
            Contact.email,
            Contact.phone,
            Contact.client_id,
            Client.name.label("client_name"),
            Contact.is_decision_maker,
            Contact.relationship_strength,
            Contact.relationship_notes,
            Contact.last_personal_touchpoint_at,
            Contact.last_contacted_at,
        )
        .join(Client, Client.id == Contact.client_id)
        .where(Contact.is_key_relationship.is_(True))
    )

    if not is_organization_reader:
        # DL widzi tylko swoje (gdzie sam zaznaczył jako owner)
        stmt = stmt.where(Contact.key_relationship_owner_id == user.id)

    # Sort: NULLs first (nigdy nie było — pilna potrzeba), potem najstarsze
    stmt = stmt.order_by(Contact.last_personal_touchpoint_at.asc().nullsfirst())

    rows = (await db.execute(stmt)).all()

    now = datetime.now()
    items: list[MyRelationshipRow] = []
    for r in rows:
        days = None
        if r.last_personal_touchpoint_at is not None:
            # Make timezone-naive for diff calc
            ts = r.last_personal_touchpoint_at
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            days = (now - ts).days
        items.append(
            MyRelationshipRow(
                contact_id=r.id,
                name=r.name,
                position=r.position,
                email=r.email,
                phone=r.phone,
                client_id=r.client_id,
                client_name=r.client_name,
                is_decision_maker=r.is_decision_maker or False,
                relationship_strength=r.relationship_strength,
                relationship_notes=r.relationship_notes,
                last_personal_touchpoint_at=r.last_personal_touchpoint_at,
                last_contacted_at=r.last_contacted_at,
                days_since_personal_touchpoint=days,
            )
        )
    return items
