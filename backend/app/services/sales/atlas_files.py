"""Pliki z Atlasa (Supabase Storage) → magazyn NEXUSA, po imporcie danych.

Osobny krok, bo wymaga klucza storage Atlasa (``ATLAS_SUPABASE_URL``,
``ATLAS_SUPABASE_SERVICE_KEY``) i trwa dłużej niż import wierszy. Plik trafia
do tej firmy albo szansy, którą import założył z tego samego wiersza Atlasa
(``external_ref``); drugi bieg nie pobiera plików już przeniesionych, tylko
poprawia ich datę dodania i folder według Atlasa. Pobieranie jest
wstrzykiwane (``Fetch``), żeby test nie wychodził do sieci.

Oferty z modułu ofert Atlasa nie przechodzą do NEXUSA jako funkcja (decyzja
Artura), ale ich pliki tak: ostatnia wersja każdej oferty (DOCX i PDF) ląduje
w folderze ``OFFERS_FOLDER`` przy szansie (``offers.deal_id``), a bez szansy
przy firmie (``client_company_id``).
"""

from __future__ import annotations

import posixpath
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, NamedTuple, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesCompany, SalesFile, SalesOpportunity
from app.services import storage_service
from app.services.sales.atlas_import import ImportReport

DEAL_BUCKET = "deal-attachments"
COMPANY_BUCKET = "company-attachments"
OFFER_BUCKET = "offers"
OFFERS_FOLDER = "Oferty (Atlas)"

Fetch = Callable[[str, str], Awaitable[Optional[bytes]]]


class _Job(NamedTuple):
    """Jeden plik do przeniesienia (NamedTuple: test ładuje moduł poza ``sys.modules``)."""

    ref: str
    bucket: str
    storage_path: str
    filename: str
    folder: Optional[str]
    created_at: Optional[datetime]
    content_type: Optional[str]
    uploaded_by_email: str
    #: Właściciel w kolejności prób: (``opportunity``|``company``, external_ref).
    owners: tuple[tuple[str, str], ...]
    #: Prefiks klucza w raporcie (``files`` albo ``offer_files``).
    kind: str = "files"


async def _ids(db: AsyncSession, model: Any, refs: Sequence[str]) -> dict[str, int]:
    """``external_ref`` → id; firma scalona w NEXUSIE → jej firma docelowa."""

    if not refs:
        return {}
    rows = await db.execute(
        select(model.external_ref, model.id).where(model.external_ref.in_(list(refs)))
    )
    ids = dict(rows.all())
    if model is SalesCompany:
        from app.services.sales.atlas_import import company_merge_targets

        merged = await company_merge_targets(db)
        ids = {
            ref: merged.get(company_id, company_id) for ref, company_id in ids.items()
        }
    return ids


def _attachment_jobs(
    deal_attachments: Sequence[Mapping[str, Any]],
    company_attachments: Sequence[Mapping[str, Any]],
) -> list[_Job]:
    jobs = []
    for bucket, table, rows, owner, key in (
        (DEAL_BUCKET, "deal_attachments", deal_attachments, "opportunity", "deal_id"),
        (
            COMPANY_BUCKET,
            "company_attachments",
            company_attachments,
            "company",
            "company_id",
        ),
    ):
        owner_table = "deals" if owner == "opportunity" else "companies"
        for row in rows:
            jobs.append(
                _Job(
                    ref=f"atlas:{table}:{row['id']}",
                    bucket=bucket,
                    storage_path=str(row["storage_path"]),
                    filename=str(row.get("filename") or "plik")[:255],
                    folder=row.get("folder") or None,
                    created_at=row.get("created_at"),
                    content_type=row.get("content_type"),
                    uploaded_by_email=str(row.get("uploaded_by_email") or "")
                    .strip()
                    .lower(),
                    owners=((owner, f"atlas:{owner_table}:{row[key]}"),),
                )
            )
    return jobs


def _offer_jobs(
    offers: Sequence[Mapping[str, Any]],
    offer_versions: Sequence[Mapping[str, Any]],
) -> list[_Job]:
    """Ostatnia wersja każdej oferty: DOCX i PDF, nazwa ze statusem i datą wysłania."""

    versions: dict[str, list[Mapping[str, Any]]] = {}
    for version in offer_versions:
        versions.setdefault(str(version["offer_id"]), []).append(version)
    jobs = []
    for offer in offers:
        own = versions.get(str(offer["id"]), [])
        latest = next(
            (v for v in own if str(v["id"]) == str(offer.get("latest_version_id"))),
            None,
        ) or max(
            own,
            key=lambda v: (v.get("generated_at") is not None, v.get("generated_at")),
            default=None,
        )
        if latest is None:
            continue
        owners: list[tuple[str, str]] = []
        if offer.get("deal_id"):
            owners.append(("opportunity", f"atlas:deals:{offer['deal_id']}"))
        if offer.get("client_company_id"):
            owners.append(("company", f"atlas:companies:{offer['client_company_id']}"))
        sent = offer.get("sent_at")
        prefix = f"{offer.get('status') or 'draft'} " + (
            sent.strftime("%Y-%m-%d") if sent else "niewysłana"
        )
        for extension, column, content_type in (
            (
                "docx",
                "docx_storage_path",
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document",
            ),
            ("pdf", "pdf_storage_path", "application/pdf"),
        ):
            path = latest.get(column)
            if not path:
                continue
            name = posixpath.basename(str(path)) or f"oferta.{extension}"
            jobs.append(
                _Job(
                    ref=f"atlas:offer_versions:{latest['id']}:{extension}",
                    bucket=OFFER_BUCKET,
                    storage_path=str(path),
                    filename=f"{prefix} {name}"[:255],
                    folder=OFFERS_FOLDER,
                    created_at=latest.get("generated_at") or offer.get("created_at"),
                    content_type=content_type,
                    uploaded_by_email="",
                    owners=tuple(owners),
                    kind="offer_files",
                )
            )
    return jobs


async def copy_attachments(
    db: AsyncSession,
    *,
    deal_attachments: Sequence[Mapping[str, Any]],
    company_attachments: Sequence[Mapping[str, Any]],
    fetch: Fetch,
    users_by_email: Mapping[str, int],
    offers: Sequence[Mapping[str, Any]] = (),
    offer_versions: Sequence[Mapping[str, Any]] = (),
    dry_run: bool = False,
) -> ImportReport:
    """Przenieś pliki; zatwierdza wołający (każdy plik to osobny zapis na dysku)."""

    report = ImportReport()
    jobs = _attachment_jobs(deal_attachments, company_attachments) + _offer_jobs(
        offers, offer_versions
    )
    done = set(
        (
            await db.execute(
                select(SalesFile.external_ref).where(
                    SalesFile.external_ref.in_([job.ref for job in jobs] or ["-"])
                )
            )
        ).scalars()
    )
    owners = {
        "opportunity": await _ids(
            db,
            SalesOpportunity,
            [ref for job in jobs for kind, ref in job.owners if kind == "opportunity"],
        ),
        "company": await _ids(
            db,
            SalesCompany,
            [ref for job in jobs for kind, ref in job.owners if kind == "company"],
        ),
    }
    for job in jobs:
        if job.ref in done:
            # Bez ponownego pobierania: data dodania i folder z Atlasa (pierwszy
            # bieg zapisał datę przeniesienia). Brak wartości w Atlasie nie
            # czyści tego, co ustawiono w NEXUSIE.
            values = {
                key: value
                for key, value in (
                    ("created_at", job.created_at),
                    ("folder", job.folder),
                )
                if value is not None
            }
            if values:
                await db.execute(
                    update(SalesFile)
                    .where(SalesFile.external_ref == job.ref)
                    .values(**values)
                )
            report.add(f"{job.kind}_already_copied")
            continue
        owner = next(
            (
                (kind, owners[kind][ref])
                for kind, ref in job.owners
                if ref in owners[kind]
            ),
            None,
        )
        if owner is None:
            report.add(f"{job.kind}_skipped_owner_not_imported")
            continue
        if job.storage_path.startswith("pipedrive://files/"):
            # Historyczny import Atlasa zachował tu odwołanie, bez bajtów pliku.
            report.add("files_external_reference")
            continue
        if dry_run:
            # Na sucho: bez pobierania i bez zapisu na dysk — same liczby.
            report.add(f"{job.kind}_would_copy")
            continue
        data = await fetch(job.bucket, job.storage_path)
        if data is None:
            report.add(f"{job.kind}_missing_in_storage")
            continue
        kind, owner_id = owner
        owner_dir = "opportunities" if kind == "opportunity" else "companies"
        path, size = storage_service.save_sales_file(
            owner_dir, owner_id, job.filename, data
        )
        file = SalesFile(
            company_id=owner_id if kind == "company" else None,
            opportunity_id=owner_id if kind == "opportunity" else None,
            filename=job.filename,
            content_type=job.content_type,
            size_bytes=size,
            storage_key=path,
            folder=job.folder,
            uploaded_by_user_id=users_by_email.get(job.uploaded_by_email),
            external_ref=job.ref,
        )
        if job.created_at is not None:
            file.created_at = job.created_at
        db.add(file)
        await db.flush()
        report.add(f"{job.kind}_copied")
    return report
