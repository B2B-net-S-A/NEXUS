"""Router `/api/reports/hiring-managers` — analytics per hiring manager.

Agregaty po `Job.hiring_manager_contact_id`:
- ile Jobów prowadzi (open + zamkniętych)
- ile placementów (Contract z hires z tych Jobów)
- avg time-to-fill
- ile aktywnych konsultantów obecnie

Permission: organization read for admin, head_of_recruitment and Finance.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services.insights_hiring_managers import compute_hiring_manager_kpis

router = APIRouter()

HiringManagersReadUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.head_of_recruitment,
            UserRole.finance,
        )
    ),
]


class HiringManagerKpiRow(BaseModel):
    contact_id: int
    contact_name: str
    position: Optional[str] = None
    client_id: int
    client_name: str
    jobs_total: int = 0
    jobs_open: int = 0
    contracts_total: int = 0
    contracts_active: int = 0

    model_config = {"from_attributes": True}


@router.get("", response_model=list[HiringManagerKpiRow])
async def hiring_managers_kpi(
    _user: HiringManagersReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Top hiring managers ranking.

    Each row = jeden contact, agregaty z `Job.hiring_manager_contact_id` +
    Contractów linked do tych Jobów.

    Liczenie mieszka w `app/services/insights_hiring_managers.py` — ten sam
    ranking pokazuje `/api/insights/clients/hiring-managers` (D7). Wołane BEZ
    okna, czyli po całej historii: tak liczy ta powierzchnia od zawsze
    i przycięcie jej oknem zmieniłoby liczby konsumentom, którzy o to nie
    prosili.
    """
    rows = await compute_hiring_manager_kpis(db)
    return [
        HiringManagerKpiRow(
            contact_id=r.contact_id,
            contact_name=r.contact_name,
            position=r.position,
            client_id=r.client_id,
            client_name=r.client_name,
            jobs_total=r.jobs_total,
            jobs_open=r.jobs_open,
            contracts_total=r.contracts_total,
            contracts_active=r.contracts_active,
        )
        for r in rows
    ]
