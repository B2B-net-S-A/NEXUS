"""Pliki z Atlasa (Supabase Storage) → magazyn NEXUSA, po imporcie danych.

Osobny krok, bo wymaga klucza storage Atlasa (``ATLAS_SUPABASE_URL``,
``ATLAS_SUPABASE_SERVICE_KEY``) i trwa dłużej niż import wierszy. Plik trafia
do tej firmy albo szansy, którą import założył z tego samego wiersza Atlasa
(``external_ref``); drugi bieg pomija pliki już przeniesione. Pobieranie jest
wstrzykiwane (``Fetch``), żeby test nie wychodził do sieci.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesCompany, SalesFile, SalesOpportunity
from app.services import storage_service
from app.services.sales.atlas_import import ImportReport

logger = logging.getLogger(__name__)

DEAL_BUCKET = "deal-attachments"
COMPANY_BUCKET = "company-attachments"

Fetch = Callable[[str, str], Awaitable[Optional[bytes]]]


async def _ids(db: AsyncSession, model: Any, refs: Sequence[str]) -> dict[str, int]:
    if not refs:
        return {}
    rows = await db.execute(
        select(model.external_ref, model.id).where(model.external_ref.in_(list(refs)))
    )
    return dict(rows.all())


async def copy_attachments(
    db: AsyncSession,
    *,
    deal_attachments: Sequence[Mapping[str, Any]],
    company_attachments: Sequence[Mapping[str, Any]],
    fetch: Fetch,
    users_by_email: Mapping[str, int],
    dry_run: bool = False,
) -> ImportReport:
    """Przenieś pliki; zatwierdza wołający (każdy plik to osobny zapis na dysku)."""

    report = ImportReport()
    jobs: list[tuple[str, str, Mapping[str, Any], str]] = [
        (DEAL_BUCKET, "deal_attachments", row, f"atlas:deals:{row['deal_id']}")
        for row in deal_attachments
    ] + [
        (
            COMPANY_BUCKET,
            "company_attachments",
            row,
            f"atlas:companies:{row['company_id']}",
        )
        for row in company_attachments
    ]
    done = set(
        (
            await db.execute(
                select(SalesFile.external_ref).where(
                    SalesFile.external_ref.in_(
                        [f"atlas:{table}:{row['id']}" for _, table, row, _ in jobs]
                        or ["-"]
                    )
                )
            )
        ).scalars()
    )
    opportunities = await _ids(
        db,
        SalesOpportunity,
        [owner for _, table, _, owner in jobs if table == "deal_attachments"],
    )
    companies = await _ids(
        db,
        SalesCompany,
        [owner for _, table, _, owner in jobs if table == "company_attachments"],
    )
    for bucket, table, row, owner_ref in jobs:
        ref = f"atlas:{table}:{row['id']}"
        if ref in done:
            report.add("files_already_copied")
            continue
        owner_id = (opportunities if table == "deal_attachments" else companies).get(
            owner_ref
        )
        if owner_id is None:
            report.add("files_skipped_owner_not_imported")
            continue
        if dry_run:
            # Na sucho: bez pobierania i bez zapisu na dysk — same liczby.
            report.add("files_would_copy")
            continue
        try:
            data = await fetch(bucket, str(row["storage_path"]))
        except Exception:  # noqa: BLE001 — jeden plik nie zatrzymuje reszty
            logger.warning("[atlas-files] pobranie nieudane: %s", ref)
            data = None
        if not data:
            report.add("files_missing_in_storage")
            continue
        name = str(row.get("filename") or "plik")[:255]
        owner_dir = "opportunities" if table == "deal_attachments" else "companies"
        path, size = storage_service.save_sales_file(owner_dir, owner_id, name, data)
        email = str(row.get("uploaded_by_email") or "").strip().lower()
        db.add(
            SalesFile(
                company_id=owner_id if table == "company_attachments" else None,
                opportunity_id=owner_id if table == "deal_attachments" else None,
                filename=name,
                content_type=row.get("content_type"),
                size_bytes=size,
                storage_key=path,
                folder=(row.get("folder") or None),
                uploaded_by_user_id=users_by_email.get(email),
                external_ref=ref,
            )
        )
        await db.flush()
        report.add("files_copied")
    return report
