"""Skrzynka leadów: dopasowanie firmy, klient NEXUSA poza sprzedażą, zamiana na szansę."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import (
    SalesCompany,
    SalesLead,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
)
from app.services import sales_schema as schema
from app.services.client_duplicates import find_same_name_clients
from app.services.company_names import normalize_company_name
from app.services.sales import history
from app.services.sales.lifecycle import apply_stage


async def is_existing_client(db: AsyncSession, company_name: str) -> bool:
    """Czy firma jest już klientem NEXUSA (ta sama reguła co ostrzeżenie o duplikacie
    klienta: nazwa, nazwa wyświetlana albo prawna i aktywne aliasy)."""

    return bool(await find_same_name_clients(db, company_name))


async def match_company(db: AsyncSession, company_name: str) -> Optional[int]:
    """Firma z kartoteki sprzedaży o tej samej nazwie kanonicznej (najstarsza)."""

    canonical = normalize_company_name(company_name)
    if not canonical:
        return None
    return (
        await db.execute(
            select(SalesCompany.id)
            .where(
                SalesCompany.normalized_name == canonical,
                SalesCompany.archived_at.is_(None),
            )
            .order_by(SalesCompany.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def convert(
    db: AsyncSession,
    lead: SalesLead,
    *,
    owner_user_id: int,
    title: Optional[str] = None,
) -> SalesOpportunity:
    """Lead → firma (istniejąca albo nowa) → szansa na pierwszym otwartym etapie."""

    now = datetime.now(timezone.utc)
    company_id = lead.company_id or await match_company(db, lead.company_name or "")
    if company_id is None:
        name = (lead.company_name or "").strip() or lead.title[:500]
        company = SalesCompany(
            name=name,
            normalized_name=normalize_company_name(name) or name.lower(),
            source=f"lead:{lead.source}"[:60],
            owner_user_id=owner_user_id,
            created_by_user_id=owner_user_id,
        )
        db.add(company)
        await db.flush()
        company_id = company.id

    pipeline = (
        await db.execute(
            select(SalesPipeline).where(
                SalesPipeline.key == schema.DEFAULT_PIPELINE_KEY
            )
        )
    ).scalar_one()
    stages = list(
        (
            await db.execute(
                select(SalesPipelineStage)
                .where(SalesPipelineStage.pipeline_id == pipeline.id)
                .order_by(SalesPipelineStage.position)
            )
        ).scalars()
    )
    stage = next(s for s in stages if s.outcome == "open")
    opportunity = SalesOpportunity(
        company_id=company_id,
        pipeline_id=pipeline.id,
        stage_id=stage.id,
        title=((title or "").strip() or lead.title)[:255],
        description=lead.summary,
        source=f"lead:{lead.source}"[:60],
        owner_user_id=owner_user_id,
        created_by_user_id=owner_user_id,
    )
    apply_stage(opportunity, stage, stages, now=now)
    db.add(opportunity)
    await db.flush()
    history.record_created(db, opportunity, user_id=owner_user_id)
    lead.company_id = company_id
    lead.opportunity_id = opportunity.id
    lead.status = "converted"
    return opportunity
