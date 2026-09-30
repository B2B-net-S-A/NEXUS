"""Insights → Raporty → „Propozycje AI” (30.09.2026).

``GET /api/insights/proposals/outcomes?days=7`` — ile propozycji z bazy
zespół dodał, pominął (z powodem, 0405) i ile czeka. Dla admina, Head of
Recruitment i Delivery Leada; DL widzi wyłącznie rekrutacje, w których jest
Delivery Leadem, albo klientów ze swojego portfela (reguła „Delivery Lead widzi
tylko swoich klientów”). Bez kwot i bez nazwisk kandydatów.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import local_now
from app.models.user import User, UserRole
from app.services import proposal_outcomes

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

ProposalReportViewer = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin, UserRole.head_of_recruitment, UserRole.delivery_lead
        )
    ),
]


def sees_all_jobs(user: User) -> bool:
    """Admin i Head of Recruitment — cała firma; reszta (DL) — swój zakres."""
    return user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)


@router.get("/proposals/outcomes")
async def insights_proposal_outcomes(
    current_user: ProposalReportViewer,
    db: AsyncSession = Depends(get_db),
    days: int = Query(7, ge=1, le=proposal_outcomes.MAX_DAYS),
):
    from app.services.access_scope import (  # noqa: PLC0415
        resolve_delivery_lead_client_ids,
    )

    now = local_now()
    since = proposal_outcomes.window_start(now, days)
    if sees_all_jobs(current_user):
        rows = await proposal_outcomes.load_rows(db, since=since)
        scope = "organization"
    else:
        client_ids = await resolve_delivery_lead_client_ids(current_user, db)
        rows = await proposal_outcomes.load_rows(
            db,
            since=since,
            delivery_lead_id=current_user.id,
            client_ids=client_ids,
        )
        scope = "delivery_lead"
    return {
        "days": days,
        "since": since.isoformat(),
        "scope": scope,
        "reasons": list(proposal_outcomes.REASON_KEYS),
        **proposal_outcomes.summarize(rows),
    }
