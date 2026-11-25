"""Liczniki źródeł asystenta prawnego poza korpusem prawa (część H).

Karta „Źródła asystenta prawnego” w Przepisach → „Źródła i boty” czyta
``GET /api/legal/sources``: korpus (``corpus.sources_status``) i te liczniki.
Same liczby — bez nazw klientów, osób i wzorów.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.legal import template_review

#: Umowa ramowa albo aneks, których tekst asystent (i Jarvis) może czytać.
READABLE_TEXT_STATUSES: tuple[str, ...] = ("indexed", "text_only")


async def db_counts(db: AsyncSession) -> dict[str, Any]:
    from app.models.client_contract_amendment import ClientContractAmendment
    from app.models.client_framework_contract import ClientFrameworkContract
    from app.models.custom_document_template import (
        CustomDocumentTemplate,
        CustomDocumentTemplateVersion,
    )
    from app.models.legal_case_law import LegalCase

    case_count, case_latest = (
        await db.execute(select(func.count(), func.max(LegalCase.fetched_at)))
    ).one()
    custom = await db.scalar(
        select(func.count())
        .select_from(CustomDocumentTemplate)
        .join(
            CustomDocumentTemplateVersion,
            CustomDocumentTemplateVersion.id
            == CustomDocumentTemplate.active_version_id,
        )
        .where(
            CustomDocumentTemplate.withdrawn_at.is_(None),
            CustomDocumentTemplateVersion.status == "approved",
        )
    )
    contracts = await db.scalar(
        select(func.count()).where(
            ClientFrameworkContract.text_status.in_(READABLE_TEXT_STATUSES)
        )
    )
    amendments = await db.scalar(
        select(func.count()).where(
            ClientContractAmendment.text_status.in_(READABLE_TEXT_STATUSES)
        )
    )
    return {
        "case_law": int(case_count or 0),
        "case_law_latest": case_latest.isoformat() if case_latest else None,
        "custom_templates": int(custom or 0),
        "framework_contracts": int(contracts or 0),
        "framework_amendments": int(amendments or 0),
    }


async def documents_status(db: AsyncSession) -> dict[str, Any]:
    counts = await db_counts(db)
    return {
        "case_law": {
            "count": counts["case_law"],
            "latest_fetched_at": counts["case_law_latest"],
        },
        "templates": {
            "repo": len(template_review.repo_templates()),
            "client_clauses": len(template_review.clause_sources()),
            "custom_approved": counts["custom_templates"],
        },
        "framework_contracts": {
            "contracts": counts["framework_contracts"],
            "amendments": counts["framework_amendments"],
        },
    }
