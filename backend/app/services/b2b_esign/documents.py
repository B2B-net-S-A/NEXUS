"""Paczka do podpisu: dokumenty z listy klienta obok umowy B2B (0687).

Decyzja Artura 13.11.2026: kontraktor dostaje jeden link i podpisuje za
jednym razem umowę, NDA, oświadczenie o niekaralności i każdy inny wzór
z listy klienta „Dokumenty do startu”. Do paczki trafia każda pozycja pary
z wgranym wzorem (DOCX albo PDF), której jeszcze nie ma; nadawca może ją
odznaczyć w oknie wysyłki.

Dokument podpisuje tylko kontraktor (podpis kwalifikowany z jego nazwiskiem
w certyfikacie), na PDF-ie zamrożonym przy wysyłce. Umowa przechodzi do
reprezentanta B2B Network dopiero, gdy kontraktor podpisze wszystko
(``service.finish_contractor_if_complete``).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Mapping, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_signing_document import B2BSigningDocument
from app.models.b2b_signing_request import B2BSigningRequest
from app.models.job import Job
from app.models.start_document import ClientStartDocument, PlacementStartDocument
from app.services import start_documents as start_docs
from app.services import start_documents_fill as fill
from app.services import storage_service
from app.services.b2b_esign import service
from app.services.b2b_esign.verdict import Fingerprint, judge, upload_problem
from app.services.cv_pdf_preview import pdf_from_docx

logger = logging.getLogger(__name__)

MSG_DOC_NOT_FOUND = "Tego dokumentu nie ma w paczce do podpisu."
MSG_DOC_SIGNED = "Ten dokument jest już przez Ciebie podpisany."
MSG_DOC_CHOICE = (
    "Do paczki dodasz tylko dokumenty z listy klienta, których jeszcze brakuje."
)


def doc_pdf_problem(title: str) -> str:
    return (
        f"Nie udało się zrobić PDF-a z dokumentu „{title}”. Odznacz go w oknie "
        "wysyłki albo spróbuj za chwilę."
    )


async def candidates(
    db: AsyncSession, row: B2BGeneratedContract
) -> list[ClientStartDocument]:
    """Pozycje listy klienta, które mogą wejść do paczki tej umowy: wzór do
    pobrania jest wgrany, a para jeszcze tej pozycji nie ma. Klient bez listy
    albo umowa bez rekrutacji = pusta paczka (droga jak dotąd)."""
    if not row.candidate_id or not row.job_id:
        return []
    job = await db.get(Job, row.job_id)
    if job is None:
        return []
    state = await start_docs.pair_state(db, row.candidate_id, job)
    if state is None:
        return []
    return [
        item.document
        for item in state.items
        if item.document.kind == start_docs.KIND_FILE
        and item.document.template_path
        and not item.done
    ]


def choose(
    found: list[ClientStartDocument], wanted_ids: Optional[list[int]]
) -> list[ClientStartDocument]:
    """``None`` = wszystkie z listy; lista = wybór z okna (spoza listy = 422)."""
    if wanted_ids is None:
        return found
    by_id = {d.id: d for d in found}
    if not set(wanted_ids) <= set(by_id):
        raise HTTPException(status_code=422, detail=MSG_DOC_CHOICE)
    return [d for d in found if d.id in set(wanted_ids)]


async def render_pdf(
    document: ClientStartDocument, payload: Optional[Mapping[str, Any]]
) -> bytes:
    """PDF wzoru do podpisu: PDF bez zmian, DOCX (z danymi z umowy, gdy pozycja
    tak mówi) przez ten sam konwerter co umowa. Awaria = ``PdfPreviewUnavailable``
    albo ``FileNotFoundError``; wołający mówi, którego dokumentu."""
    data = storage_service.read_start_document_file(document.template_path or "")
    if data.startswith(b"%PDF-"):
        return data
    if document.fill_from_agreement:
        data = fill.fill_template(data, fill.values_from_payload(payload))
    return await pdf_from_docx(data)


async def attach(
    db: AsyncSession,
    request: B2BSigningRequest,
    prepared: list[tuple[ClientStartDocument, bytes]],
) -> list[B2BSigningDocument]:
    """Zamroź PDF-y dokumentów przy wniosku (po ``service.send``)."""
    out: list[B2BSigningDocument] = []
    for position, (document, pdf) in enumerate(prepared, start=1):
        source = Fingerprint.of(pdf)
        path, _ = storage_service.save_b2b_signing_pdf(
            request.id, f"dokument_{position}.pdf", pdf
        )
        item = B2BSigningDocument(
            request_id=request.id,
            start_document_id=document.id,
            position=position,
            title=document.name[:200],
            source_pdf_path=path,
            source_sha256=source.sha256,
            source_size=source.size,
        )
        db.add(item)
        out.append(item)
    await db.flush()
    return out


async def for_request(db: AsyncSession, request_id: int) -> list[B2BSigningDocument]:
    return list(
        (
            await db.scalars(
                select(B2BSigningDocument)
                .where(B2BSigningDocument.request_id == request_id)
                .order_by(B2BSigningDocument.position, B2BSigningDocument.id)
            )
        ).all()
    )


async def get_in_request(
    db: AsyncSession, request_id: int, document_id: int
) -> B2BSigningDocument:
    item = await db.get(B2BSigningDocument, document_id)
    if item is None or item.request_id != request_id:
        raise HTTPException(status_code=404, detail=MSG_DOC_NOT_FOUND)
    return item


async def contractor_submit(
    db: AsyncSession,
    *,
    request: B2BSigningRequest,
    document_id: int,
    data: bytes,
    validator: service.Validator,
    now: datetime,
) -> tuple[B2BSigningRequest, B2BSigningDocument]:
    """Podpisany dokument z linku. Wołać po ``service.contractor_precheck``.

    Ta sama kolejność co umowa: plik zaczyna się bajtami wydanego PDF-a,
    walidacja bez blokady, potem blokada wiersza rejestru, wniosku i dokumentu."""
    request_id = request.id
    row_id = request.generated_contract_id
    contractor_name = request.contractor_name
    item = await get_in_request(db, request_id, document_id)
    if item.signed_pdf_path:
        raise HTTPException(status_code=409, detail=MSG_DOC_SIGNED)
    source = Fingerprint(item.source_sha256, item.source_size)
    service.check_pdf_upload(data)
    problem = upload_problem(data, source)
    if problem:
        await service.count_failed_attempt(db, request_id)
        raise HTTPException(status_code=422, detail=problem)
    await db.commit()  # bez transakcji na czas walidacji (jak umowa)
    report = await validator.validate(data)
    verdict = judge(
        report,
        authoritative=validator.authoritative,
        required_signers=[contractor_name],
    )
    if not verdict.accepted:
        if verdict.code != "no_validator":
            await service.count_failed_attempt(db, request_id)
        raise HTTPException(status_code=422, detail=verdict.message)

    row, locked = await service.lock_row_then_request(db, row_id, request_id)
    if not service.row_still_signable(row):
        raise HTTPException(status_code=409, detail=service.MSG_CLOSED)
    if not service.is_link_live(locked, now):
        raise HTTPException(status_code=409, detail=service.MSG_RACE)
    item = await db.scalar(
        select(B2BSigningDocument)
        .where(B2BSigningDocument.id == document_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if item is None or item.signed_pdf_path or item.source_sha256 != source.sha256:
        raise HTTPException(status_code=409, detail=service.MSG_RACE)
    path, _ = storage_service.save_b2b_signing_pdf(
        locked.id, f"dokument_{item.position}_podpisany.pdf", data
    )
    item.signed_pdf_path = path
    item.signed_sha256 = Fingerprint.of(data).sha256
    item.signed_at = now
    item.validation = report.as_db_report()
    service.push_event(locked, "document_signed", now, title=item.title)
    await db.flush()
    await service.finish_contractor_if_complete(db, locked, now)
    return locked, item


def pair_file_name(item: B2BSigningDocument) -> str:
    """Nazwa pliku w „Dokumentach do startu”: DL widzi, skąd przyszedł."""
    return f"{item.title} (podpis w NEXUSIE).pdf"[:255]


async def deliver_to_pair(
    db: AsyncSession,
    *,
    row: B2BGeneratedContract,
    item: B2BSigningDocument,
    data: bytes,
    now: datetime,
) -> tuple[Optional[str], Optional[str]]:
    """Podpisany dokument jako plik pozycji pary w „Dokumentach do startu”
    (liczy się od razu, Delivery Lead może go zwrócić — jak plik wgrany
    ręcznie). Zwraca (nowa ścieżka, poprzednia ścieżka); wołający robi commit,
    kasuje poprzedni plik, a przy błędzie nowy."""
    if not item.start_document_id or not row.candidate_id or not row.job_id:
        return None, None
    name = pair_file_name(item)
    path, _ = storage_service.save_start_document_file(
        f"pairs/{row.candidate_id}-{row.job_id}", name, data
    )
    await db.execute(
        pg_insert(PlacementStartDocument)
        .values(
            document_id=item.start_document_id,
            candidate_id=row.candidate_id,
            job_id=row.job_id,
            status=start_docs.STATUS_DELIVERED,
        )
        .on_conflict_do_nothing(constraint="uq_placement_start_documents_pair")
    )
    pair_row = await db.scalar(
        select(PlacementStartDocument)
        .where(
            PlacementStartDocument.document_id == item.start_document_id,
            PlacementStartDocument.candidate_id == row.candidate_id,
            PlacementStartDocument.job_id == row.job_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if pair_row is None:  # wstawiony wyżej albo przez równoległe żądanie
        storage_service.delete_start_document_file(path)
        return None, None
    previous = pair_row.file_path
    pair_row.status = start_docs.STATUS_DELIVERED
    pair_row.delivered_at = now
    # Wgrał kontraktor z linku, nie konto NEXUSA.
    pair_row.delivered_by = None
    pair_row.checked_at = None
    pair_row.checked_by = None
    pair_row.reason = None
    pair_row.reason_at = None
    pair_row.reason_by = None
    pair_row.file_path = path
    pair_row.file_name = name
    pair_row.file_content_type = "application/pdf"
    return path, previous
