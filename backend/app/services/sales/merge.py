"""Scalanie dwóch firm w kartotece sprzedaży (duplikaty po imporcie z Atlasa).

Wszystko, co wisi na firmie źródłowej, przechodzi na docelową: kontakty
(i ich powiązania z firmą), szanse, aktywności, pliki, leady, rekordy kolejki
dzwonienia, spółki zależne.
Tagi sumujemy, ``custom_fields`` łączymy (wygrywa firma docelowa), puste pola
docelowej uzupełniamy ze źródłowej. Źródłowej nie kasujemy — trafia do
archiwum z ``custom_fields.merged_into`` (ślad i droga powrotu). Jedna
transakcja: wywołujący robi ``commit`` dopiero po całości.

Nazwa i nazwa prawna źródłowej, których docelowa nie ma, zostają przy docelowej
jako nazwy dołączone („Inne nazwy z CV”), bo „Kogo znamy” dopasowuje osoby
dokładnie po nazwie. Punkty do rozmowy z bota to jeden wiersz na firmę: przy
docelowej zostaje nowszy z dwóch.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.company_names import normalize_company_name
from app.services.sales import history
from app.services.sales.company_aliases import JOINED, can_be_alias
from app.services.sales_schema import OpportunityEventKind

from app.models.sales import (
    SalesActivity,
    SalesCallRecord,
    SalesCompany,
    SalesCompanyAlias,
    SalesCompanyBriefing,
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


def names_to_join(
    covered: Iterable[str], names: Iterable[Optional[str]]
) -> list[tuple[str, str]]:
    """Nazwy wchłanianej karty do dopisania jako dołączone: (zapis, kanoniczna).

    „Kogo znamy” dopasowuje osoby dokładnie po nazwie kanonicznej, więc bez
    dopisku osoby z „Marka Group” w CV znikłyby z liczników po scaleniu tej
    karty w „Marka”. ``covered`` to nazwy kanoniczne, które docelowa już ma.
    """

    seen = set(covered)
    found = []
    for raw in names:
        canonical = normalize_company_name(raw or "")
        if not canonical or canonical in seen or not can_be_alias(canonical):
            continue
        seen.add(canonical)
        found.append(((raw or "").strip(), canonical))
    return found


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
    # Decyzje o nazwach z CV idą za firmą; docelowa zostaje przy swojej.
    aliases = (
        await db.execute(
            select(SalesCompanyAlias).where(SalesCompanyAlias.company_id == source_id)
        )
    ).scalars()
    alias_rows = [
        {
            "company_id": target_id,
            "alias": row.alias,
            "normalized_alias": row.normalized_alias,
            "status": row.status,
            "created_by_user_id": row.created_by_user_id,
        }
        for row in aliases
    ]
    # Nazwa wchłoniętej karty zostaje jako dołączona. Idzie po decyzjach źródła,
    # a wcześniejsza decyzja o tej nazwie (także „Nie ta firma”) wygrywa.
    alias_rows += [
        {
            "company_id": target_id,
            "alias": alias,
            "normalized_alias": canonical,
            "status": JOINED,
            "created_by_user_id": user_id,
        }
        for alias, canonical in names_to_join(
            {
                target.normalized_name,
                normalize_company_name(target.name),
                # Pustą nazwę prawną docelowej uzupełnia niżej nazwa źródłowej.
                normalize_company_name(target.legal_name or source.legal_name or ""),
            },
            (source.name, source.legal_name),
        )
    ]
    if alias_rows:
        await db.execute(
            insert(SalesCompanyAlias).values(alias_rows).on_conflict_do_nothing()
        )
        await db.execute(
            SalesCompanyAlias.__table__.delete().where(
                SalesCompanyAlias.company_id == source_id
            )
        )
    for model in (SalesActivity, SalesFile, SalesLead, SalesCallRecord):
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

    # Punkty do rozmowy to jeden wiersz na firmę: docelowa bierze punkty źródła,
    # gdy nie ma własnych albo ma starsze.
    briefing = insert(SalesCompanyBriefing).from_select(
        ["company_id", "mode", "points", "run_id", "generated_at"],
        select(
            literal(target_id),
            SalesCompanyBriefing.mode,
            SalesCompanyBriefing.points,
            SalesCompanyBriefing.run_id,
            SalesCompanyBriefing.generated_at,
        ).where(SalesCompanyBriefing.company_id == source_id),
    )
    await db.execute(
        briefing.on_conflict_do_update(
            index_elements=["company_id"],
            set_={
                name: briefing.excluded[name]
                for name in ("mode", "points", "run_id", "generated_at")
            },
            where=SalesCompanyBriefing.generated_at < briefing.excluded.generated_at,
        )
    )
    await db.execute(
        SalesCompanyBriefing.__table__.delete().where(
            SalesCompanyBriefing.company_id == source_id
        )
    )

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
