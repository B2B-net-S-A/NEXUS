"""Scalanie dwóch firm w kartotece sprzedaży (duplikaty po imporcie z Atlasa).

Wszystko, co wisi na firmie źródłowej, przechodzi na docelową: kontakty
(i ich powiązania z firmą), szanse, aktywności, pliki, leady, spółki zależne.
Tagi sumujemy, ``custom_fields`` łączymy (wygrywa firma docelowa), puste pola
docelowej uzupełniamy ze źródłowej. Źródłowej nie kasujemy — trafia do
archiwum z ``custom_fields.merged_into`` (ślad i droga powrotu). Jedna
transakcja: wywołujący robi ``commit`` dopiero po całości.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.sales import history
from app.services.sales_schema import OpportunityEventKind

from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
    SalesFile,
    SalesLead,
    SalesOpportunity,
)

#: Pola uzupełniane w docelowej, gdy są w niej puste.
FILLABLE_FIELDS: tuple[str, ...] = (
    "legal_name",
    "nip",
    "krs",
    "regon",
    "domain",
    "website_url",
    "linkedin_url",
    "industry",
    "size_range",
    "hq_city",
    "hq_country",
    "description",
    "tier",
    "source",
    "owner_user_id",
)


def _union_tags(target: list[Any], source: list[Any]) -> list[Any]:
    merged = list(target or [])
    for tag in source or []:
        if tag not in merged:
            merged.append(tag)
    return merged


async def merge_companies(
    db: AsyncSession,
    *,
    target: SalesCompany,
    source: SalesCompany,
    now: datetime,
    user_id: Optional[int] = None,
) -> None:
    source_id, target_id = source.id, target.id

    moved_contacts = list(
        (
            await db.execute(
                update(SalesContact)
                .where(SalesContact.company_id == source_id)
                .values(company_id=target_id)
                .returning(SalesContact.id)
            )
        ).scalars()
    )
    links = (
        await db.execute(
            select(SalesCompanyContact).where(
                SalesCompanyContact.company_id == source_id
            )
        )
    ).scalars()
    rows = [
        {
            "company_id": target_id,
            "contact_id": link.contact_id,
            "role": link.role,
            "title": link.title,
            "is_primary": link.is_primary,
            "is_current": link.is_current,
            "started_at": link.started_at,
            "ended_at": link.ended_at,
            "external_ref": link.external_ref,
        }
        for link in links
    ]
    if rows:
        # Osoba już powiązana z docelową zostaje przy swoim wierszu.
        await db.execute(
            insert(SalesCompanyContact).values(rows).on_conflict_do_nothing()
        )
        await db.execute(
            SalesCompanyContact.__table__.delete().where(
                SalesCompanyContact.company_id == source_id
            )
        )
    if moved_contacts:
        # Firma główna przeniesionych osób to teraz docelowa.
        await db.execute(
            update(SalesCompanyContact)
            .where(
                SalesCompanyContact.contact_id.in_(moved_contacts),
                SalesCompanyContact.company_id == target_id,
            )
            .values(is_primary=True)
        )

    moved_opportunities = (
        await db.execute(
            update(SalesOpportunity)
            .where(SalesOpportunity.company_id == source_id)
            .values(company_id=target_id)
            .returning(SalesOpportunity.id)
        )
    ).scalars()
    # Szansa zmieniła firmę — w jej historii widać, z której przyszła.
    for opportunity_id in moved_opportunities:
        history.record(
            db,
            opportunity_id=opportunity_id,
            user_id=user_id,
            kind=OpportunityEventKind.company_merged,
            field="company_id",
            old_value=str(source_id),
            new_value=str(target_id),
        )
    for model in (SalesActivity, SalesFile, SalesLead):
        await db.execute(
            update(model)
            .where(model.company_id == source_id)
            .values(company_id=target_id)
        )
    await db.execute(
        update(SalesCompany)
        .where(
            SalesCompany.parent_company_id == source_id,
            SalesCompany.id != target_id,
        )
        .values(parent_company_id=target_id)
    )
    if target.parent_company_id == source_id:
        parent = source.parent_company_id
        target.parent_company_id = parent if parent != target_id else None

    target.tags = _union_tags(target.tags, source.tags)
    target.custom_fields = {
        **(source.custom_fields or {}),
        **(target.custom_fields or {}),
    }
    for name in FILLABLE_FIELDS:
        if getattr(target, name) in (None, "") and getattr(source, name) not in (
            None,
            "",
        ):
            setattr(target, name, getattr(source, name))
    if target.owner_user_id is None and not target.owner_label:
        target.owner_label = source.owner_label
    if target.owner_user_id is not None:
        target.owner_label = None
    if target.client_id is None and source.client_id is not None:
        # ``ux_sales_companies_client``: najpierw zdejmij klienta ze źródłowej.
        client_id = source.client_id
        source.client_id = None
        await db.flush()
        target.client_id = client_id

    source.archived_at = now
    source.custom_fields = {**(source.custom_fields or {}), "merged_into": target_id}
    await db.flush()
