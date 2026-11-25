"""Treść podpisanych dokumentów kontraktu — wyszukiwanie, odczyt, reguła wypowiedzenia.

Bramka jest ta sama co pobranie pliku dokumentu kontraktu
(``download_contract_document``): fragment umowy niesie to samo co PDF,
w tym stawki, więc „Stawki i kwoty: podgląd”, a konto z rolą Delivery Leada
tylko u klienta z przypisania. Opis: ``docs/claude/asystent-prawny/``.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import _assert_contract, _assert_contract_document_client_access
from app.api.permission_access import AmountsViewUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.contract_document import ContractDocument
from app.services.contract_document_text import index, service

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)


class SourcePassageOut(BaseModel):
    kind: str
    ref: str
    text: str
    url: Optional[str] = None
    label: Optional[str] = None


class DocumentReadingOut(BaseModel):
    id: int
    filename: str
    doc_type: str
    in_current_folder: bool
    readable: bool
    pages: Optional[int] = None
    total_chunks: Optional[int] = None
    note: Optional[str] = None


class DocumentPassageOut(BaseModel):
    document_id: int
    first_chunk: int
    last_chunk: int
    ref: str
    text: str
    url: Optional[str] = None
    filename: Optional[str] = None


class ContractDocumentSearchResponse(BaseModel):
    contract_id: int
    query: str
    retrieval: str
    passages: list[DocumentPassageOut]
    documents: list[DocumentReadingOut]
    note: Optional[str] = None


class ContractDocumentTextResponse(BaseModel):
    contract_id: int
    document: DocumentReadingOut
    passage: Optional[DocumentPassageOut] = None
    next_chunk: Optional[int] = None
    note: Optional[str] = None


class TerminationTermsOut(BaseModel):
    document_id: int
    period_kind: str
    period_months: Optional[int] = None
    period_days: Optional[int] = None
    forms: list[str]
    under_nullity: bool
    delivery: list[str]
    sources: list[SourcePassageOut]
    notes: list[str]


class TerminationTermsResponse(BaseModel):
    contract_id: int
    document_id: Optional[int] = None
    terms: Optional[TerminationTermsOut] = None
    reason: Optional[str] = None


def _passage_out(passage: service.DocumentPassage) -> DocumentPassageOut:
    return DocumentPassageOut(
        document_id=passage.document_id,
        first_chunk=passage.first_chunk,
        last_chunk=passage.last_chunk,
        ref=passage.source.ref,
        text=passage.source.text,
        url=passage.source.url,
        filename=passage.source.label,
    )


def _reading_out(reading: service.DocumentReading) -> DocumentReadingOut:
    return DocumentReadingOut(**reading.__dict__)


async def _readable_contract(db: AsyncSession, contract_id: int, user) -> None:
    contract = await _assert_contract(db, contract_id, user)
    await _assert_contract_document_client_access(contract, user, db)


@router.get(
    "/contracts/{contract_id}/documents/search",
    response_model=ContractDocumentSearchResponse,
)
async def search_contract_documents(
    contract_id: int,
    current_user: AmountsViewUser,
    q: str = Query(..., min_length=2, max_length=300),
    db: AsyncSession = Depends(get_db),
):
    """Fragmenty umowy, aneksów i wypowiedzeń kontraktu pasujące do pytania."""
    await _readable_contract(db, contract_id, current_user)
    result = await service.search_contract_documents(db, contract_id, q)
    return ContractDocumentSearchResponse(
        contract_id=contract_id,
        query=q,
        retrieval=result.retrieval,
        passages=[_passage_out(p) for p in result.passages],
        documents=[_reading_out(d) for d in result.documents],
        note=result.note,
    )


@router.get(
    "/contracts/{contract_id}/documents/termination-terms",
    response_model=TerminationTermsResponse,
)
async def contract_termination_terms(
    contract_id: int,
    current_user: AmountsViewUser,
    db: AsyncSession = Depends(get_db),
):
    """Okres wypowiedzenia, forma i doręczenie odczytane z podpisanej umowy."""
    await _readable_contract(db, contract_id, current_user)
    outcome = await service.termination_terms(db, contract_id)
    terms = outcome.terms
    return TerminationTermsResponse(
        contract_id=contract_id,
        document_id=outcome.document_id,
        reason=outcome.reason,
        terms=(
            TerminationTermsOut(
                document_id=terms.document_id,
                period_kind=terms.period_kind,
                period_months=terms.period_months,
                period_days=terms.period_days,
                forms=list(terms.forms),
                under_nullity=terms.under_nullity,
                delivery=list(terms.delivery),
                sources=[SourcePassageOut(**s.__dict__) for s in terms.sources],
                notes=list(terms.notes),
            )
            if terms is not None
            else None
        ),
    )


@router.get(
    "/contract-documents/{document_id}/text",
    response_model=ContractDocumentTextResponse,
)
async def read_contract_document_text(
    document_id: int,
    current_user: AmountsViewUser,
    from_chunk: int = Query(0, ge=0, le=index.MAX_CHUNKS),
    db: AsyncSession = Depends(get_db),
):
    """Treść jednego dokumentu kontraktu po kolei, od fragmentu ``from_chunk``."""
    document = await db.scalar(
        select(ContractDocument).where(ContractDocument.id == document_id)
    )
    if document is None:
        raise HTTPException(404, detail="Nie ma takiego dokumentu kontraktu.")
    await _readable_contract(db, document.contract_id, current_user)
    if not index.is_read_type(document.doc_type):
        raise HTTPException(
            422,
            detail="NEXUS czyta treść tylko umowy, aneksu, wypowiedzenia i porozumienia.",
        )
    result = await service.read_contract_document(db, document, from_chunk)
    return ContractDocumentTextResponse(
        contract_id=document.contract_id,
        document=_reading_out(result.document),
        passage=_passage_out(result.passage) if result.passage else None,
        next_chunk=result.next_chunk,
        note=result.note,
    )
