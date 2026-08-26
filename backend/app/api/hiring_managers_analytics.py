"""Router `/api/reports/hiring-managers` — analytics per hiring manager.

Agregaty po `Job.hiring_manager_contact_id`:
- ile Jobów prowadzi (open + zamkniętych)
- ile placementów (Contract z hires z tych Jobów)
- avg time-to-fill
- ile aktywnych konsultantów obecnie

Permission: `HeadOfRecruitmentPlus` (admin + head_of_recruitment).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus
from app.core.database import get_db
from app.models.client import Client
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.services.client_identity import client_display_name_expression

router = APIRouter()


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
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Top hiring managers ranking.

    Each row = jeden contact, agregaty z `Job.hiring_manager_contact_id` +
    Contractów linked do tych Jobów.
    """
    # Jobs grouped by hiring_manager_contact_id × status — agregaty w 1 query.
    # JobStatus.published = "otwarta rekrutacja". draft/closed = nie otwarte.
    jobs_total_by_contact: dict[int, int] = {}
    jobs_open_by_contact: dict[int, int] = {}

    rows = list(
        (
            await db.execute(
                select(
                    Job.hiring_manager_contact_id,
                    Job.status,
                    func.count(Job.id),
                )
                .where(Job.hiring_manager_contact_id.is_not(None))
                .group_by(Job.hiring_manager_contact_id, Job.status)
            )
        )
    )
    for r in rows:
        cid = r[0]
        st = r[1]
        cnt = r[2]
        jobs_total_by_contact[cid] = jobs_total_by_contact.get(cid, 0) + cnt
        if st == JobStatus.published:
            jobs_open_by_contact[cid] = jobs_open_by_contact.get(cid, 0) + cnt

    # Contracts per hiring_manager (via Job.id)
    contract_rows = list(
        (
            await db.execute(
                select(
                    Job.hiring_manager_contact_id,
                    Contract.status,
                    func.count(Contract.id),
                )
                .join(Job, Job.id == Contract.job_id)
                .where(Job.hiring_manager_contact_id.is_not(None))
                .group_by(Job.hiring_manager_contact_id, Contract.status)
            )
        )
    )
    contracts_total_by_contact: dict[int, int] = {}
    contracts_active_by_contact: dict[int, int] = {}
    for r in contract_rows:
        cid = r[0]
        st = r[1]
        cnt = r[2]
        contracts_total_by_contact[cid] = contracts_total_by_contact.get(cid, 0) + cnt
        if st == ContractStatus.active:
            contracts_active_by_contact[cid] = (
                contracts_active_by_contact.get(cid, 0) + cnt
            )

    # Step 4: fetch contact details
    contact_ids = list(jobs_total_by_contact.keys())
    if not contact_ids:
        return []

    contacts = list(
        (
            await db.execute(
                select(
                    Contact.id,
                    Contact.name,
                    Contact.position,
                    Contact.client_id,
                    client_display_name_expression().label("client_name"),
                )
                .join(Client, Client.id == Contact.client_id)
                .where(Contact.id.in_(contact_ids))
            )
        )
    )

    items: list[HiringManagerKpiRow] = []
    for c in contacts:
        items.append(
            HiringManagerKpiRow(
                contact_id=c.id,
                contact_name=c.name,
                position=c.position,
                client_id=c.client_id,
                client_name=c.client_name,
                jobs_total=jobs_total_by_contact.get(c.id, 0),
                jobs_open=jobs_open_by_contact.get(c.id, 0),
                contracts_total=contracts_total_by_contact.get(c.id, 0),
                contracts_active=contracts_active_by_contact.get(c.id, 0),
            )
        )
    items.sort(key=lambda r: r.jobs_total, reverse=True)
    return items
