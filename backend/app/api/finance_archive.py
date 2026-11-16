"""Archiwum dokumentów z eBI24 (E5) — Finanse.

Prefiks ``/api/finance/archive-ebi24``, sekcja Finanse i uprawnienie „Moduł
Finanse” na każdej trasie; moduł „Księgowość” wyłączony = 404 (admin widzi),
jak kolejka kosztów i kartoteka kontrahentów.

* ``GET /summary`` — liczby dokumentów per rok i rodzaj, ostatni import,
* ``GET ""`` — lista z wyszukiwaniem (numer, kontrahent, NIP, numer KSeF),
  filtrem rodzaju i miesiąca/roku,
* ``GET /{id}/file`` — plik oryginalny (PDF/HTML) albo podgląd faktury
  wystawionej w eBI24 (HTML z danych), ``GET /{id}/raw`` — dane eBI24 (JSON),
* ``POST /import`` — paczka ZIP ze ``scripts/pack_ebi24_archive.py``
  (idempotentna po id eBI24; tylko admin — jednorazowe przeniesienie archiwum).
"""

from __future__ import annotations

import json
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.finance_archive import FinanceArchiveDocument
from app.models.user import User
from app.services.finance_ledger import archive
from app.services.finance_ledger import settings as module_settings

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)


async def _open(db: AsyncSession, user: User) -> None:
    enabled = await module_settings.is_enabled(db)
    if not module_settings.open_for(user, enabled):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, module_settings.MODULE_DISABLED_DETAIL
        )


async def _document(db: AsyncSession, document_id: int) -> FinanceArchiveDocument:
    doc = await db.get(FinanceArchiveDocument, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego dokumentu.")
    return doc


@router.get("/summary")
async def archive_summary(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    return await archive.summary(db)


@router.get("")
async def archive_list(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(None, max_length=120),
    kind: Optional[Literal["sale", "cost", "other"]] = Query(None),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
) -> dict[str, Any]:
    await _open(db, current_user)
    if month is not None and year is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Miesiąc tylko z rokiem."
        )
    return await archive.listing(
        db,
        archive.Filters(q=q, kind=kind, year=year, month=month),
        limit=limit,
        offset=offset,
    )


def _read(doc: FinanceArchiveDocument) -> bytes:
    try:
        return archive.read_file(doc)
    except FileNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Plik dokumentu nie jest wgrany na serwer."
        ) from None


@router.get("/{document_id}/file")
async def archive_file(
    document_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _open(db, current_user)
    doc = await _document(db, document_id)
    content = _read(doc)
    if doc.file_type == "ebi":
        try:
            data = json.loads(content)
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Dane dokumentu są nieczytelne."
            ) from None
        return Response(
            archive.render_html(doc, data if isinstance(data, dict) else {}),
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"
            },
        )
    headers = {
        "Content-Disposition": f'inline; filename="ebi24-{doc.source_id}.{doc.file_path.rpartition(".")[2]}"'
    }
    if doc.file_type == "html":
        # HTML z obcego systemu: bez skryptów i zasobów z zewnątrz.
        headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
        )
    return Response(content, media_type=archive.MIME[doc.file_type], headers=headers)


@router.get("/{document_id}/raw")
async def archive_raw(
    document_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    doc = await _document(db, document_id)
    payload: dict[str, Any] = {"meta": doc.meta}
    if doc.file_type == "ebi":
        try:
            payload["document"] = json.loads(_read(doc))
        except ValueError:
            payload["document"] = None
    return payload


@router.post("/import")
async def archive_import(
    current_user: AdminUser,
    file: UploadFile = File(..., description="Paczka ZIP z pack_ebi24_archive.py"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    content = await file.read(archive.MAX_PACKAGE_BYTES + 1)
    try:
        result = await archive.import_package(db, content, actor_id=current_user.id)
    except archive.ArchiveError as exc:
        await db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from exc
    await db.commit()
    return result.as_dict()
