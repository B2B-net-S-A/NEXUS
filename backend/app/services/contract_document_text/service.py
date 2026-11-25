"""Odczyt treści dokumentów kontraktu dla asystenta prawnego, Jarvisa i pism (część F).

Funkcje nie sprawdzają uprawnień — robi to trasa (bramka pobrania pliku
dokumentu kontraktu, ``api/contract_document_text.py``). Zwracają cytaty
w kształcie ``SourcePassage`` fundamentu asystenta (``kind="contract"``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract_document import ContractDocument, ContractDocumentType
from app.services.contract_document_text import index
from app.services.contract_document_text.schema import STATUS_INDEXED
from app.services.contract_document_text.structure import (
    document_number,
    markers,
    range_ref,
)
from app.services.contract_document_text.termination import (
    TerminationRule,
    parse_termination,
)
from app.services.framework_contract_text import (
    ChunkRef,
    Passage,
    build_passages,
    query_stems,
    rank_by_keywords,
    read_in_order,
)
from app.services.hybrid_search import reciprocal_rank_fusion

RETRIEVAL_HYBRID = "hybrid"
RETRIEVAL_KEYWORDS = "keywords"
RETRIEVAL_NONE = "none"


# TODO(asystent-prawny A): podmienić na ``app.services.legal.SourcePassage``
# po scaleniu fundamentu — ten sam kształt (kind, ref, text, url, label).
@dataclass(frozen=True)
class SourcePassage:
    kind: str
    ref: str
    text: str
    url: Optional[str] = None
    label: Optional[str] = None


_TYPE_WORDS = {
    ContractDocumentType.contract.value: "umowa",
    ContractDocumentType.annex.value: "aneks",
    ContractDocumentType.termination_notice.value: "wypowiedzenie",
    ContractDocumentType.termination_agreement.value: "porozumienie",
}


@dataclass(frozen=True)
class DocumentReading:
    """Stan treści jednego dokumentu kontraktu."""

    id: int
    filename: str
    doc_type: str
    in_current_folder: bool
    readable: bool
    pages: Optional[int]
    total_chunks: Optional[int]
    note: Optional[str]


@dataclass(frozen=True)
class DocumentPassage:
    """Wycinek dokumentu z odnośnikiem i miejscem do doczytania dalej."""

    document_id: int
    first_chunk: int
    last_chunk: int
    source: SourcePassage


@dataclass(frozen=True)
class SearchResult:
    retrieval: str
    passages: list[DocumentPassage]
    documents: list[DocumentReading]
    note: Optional[str] = None


@dataclass(frozen=True)
class ReadResult:
    document: DocumentReading
    passage: Optional[DocumentPassage]
    next_chunk: Optional[int]
    note: Optional[str] = None


@dataclass(frozen=True)
class TerminationTerms:
    """Reguła wypowiedzenia z podpisanej umowy i cytaty, z których wynika."""

    document_id: int
    period_kind: str
    period_months: Optional[int]
    period_days: Optional[int]
    forms: tuple[str, ...]
    under_nullity: bool
    delivery: tuple[str, ...]
    sources: tuple[SourcePassage, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TerminationOutcome:
    terms: Optional[TerminationTerms]
    reason: Optional[str]
    document_id: Optional[int] = None


def document_url(document: ContractDocument) -> str:
    return f"/contracts/{document.contract_id}?tab=documents"


def _type_value(document: ContractDocument) -> str:
    return getattr(document.doc_type, "value", str(document.doc_type))


def _label(document: ContractDocument, number: Optional[str]) -> str:
    word = _TYPE_WORDS.get(_type_value(document), "dokument")
    return f"{word} {number}" if number else f"{word} „{document.filename}”"


def _reading(document: ContractDocument, total: Optional[int]) -> DocumentReading:
    return DocumentReading(
        id=int(document.id),
        filename=document.filename,
        doc_type=_type_value(document),
        in_current_folder=document.folder_id is None,
        readable=index.has_current_text(document),
        pages=document.text_pages,
        total_chunks=total,
        note=index.reading_note(document),
    )


def _passage(
    document: ContractDocument, passage: Passage, chunks: Sequence[ChunkRef]
) -> DocumentPassage:
    ordered = sorted(chunks, key=lambda c: c.index)
    whole = "".join(c.text for c in ordered)
    start = sum(len(c.text) for c in ordered if c.index < passage.first_chunk)
    label = _label(document, document_number(whole))
    section = range_ref(markers(whole), start, start + len(passage.text))
    return DocumentPassage(
        document_id=int(document.id),
        first_chunk=passage.first_chunk,
        last_chunk=passage.last_chunk,
        source=SourcePassage(
            kind="contract",
            ref=f"{label} {section}" if section else label,
            text=passage.text,
            url=document_url(document),
            label=document.filename,
        ),
    )


async def read_documents(db: AsyncSession, contract_id: int) -> list[ContractDocument]:
    """Dokumenty kontraktu z treścią umowy: najpierw „Aktualna umowa”, potem nowsze."""
    rows = await db.execute(
        select(ContractDocument)
        .where(
            ContractDocument.contract_id == contract_id,
            ContractDocument.doc_type.in_(index.READ_TYPES),
        )
        .order_by(
            ContractDocument.folder_id.is_not(None),
            ContractDocument.created_at.desc(),
            ContractDocument.id.desc(),
        )
    )
    return list(rows.scalars().all())


def _by_document(chunks: Sequence[ChunkRef]) -> dict[int, list[ChunkRef]]:
    grouped: dict[int, list[ChunkRef]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.contract_id, []).append(chunk)
    return grouped


async def search_contract_documents(
    db: AsyncSession, contract_id: int, query: str
) -> SearchResult:
    """Fragmenty dokumentów kontraktu pasujące do pytania: po znaczeniu i po słowach."""
    documents = await read_documents(db, contract_id)
    await index.ensure_indexed(db, documents)
    readable = [d for d in documents if index.has_current_text(d)]
    chunks = await index.load_chunks(db, [d.id for d in readable])
    grouped = _by_document(chunks)
    readings = [_reading(d, len(grouped.get(d.id, [])) or None) for d in documents]
    if not documents:
        return SearchResult(
            RETRIEVAL_NONE,
            [],
            readings,
            "Kontrakt nie ma w Dokumentach umowy, aneksu ani wypowiedzenia.",
        )
    if not chunks:
        return SearchResult(
            RETRIEVAL_NONE,
            [],
            readings,
            "Żaden dokument tego kontraktu nie ma treści do przeczytania — powody "
            "są przy dokumentach.",
        )
    keyword_ids = rank_by_keywords(query_stems(query), chunks)
    vector_ids = await index.vector_ranking(
        query, [d.id for d in readable if d.text_status == STATUS_INDEXED]
    )
    if vector_ids is None:
        retrieval, ranked = RETRIEVAL_KEYWORDS, keyword_ids
    else:
        known = {chunk.id for chunk in chunks}
        fused = reciprocal_rank_fusion(
            [[i for i in vector_ids if i in known], keyword_ids[: index.VECTOR_HITS]]
        )
        retrieval, ranked = RETRIEVAL_HYBRID, [chunk_id for chunk_id, _ in fused]
    by_id = {d.id: d for d in readable}
    passages = [
        _passage(by_id[p.contract_id], p, grouped[p.contract_id])
        for p in build_passages(ranked, chunks)
    ]
    note = (
        None
        if passages
        else "W dokumentach nie ma fragmentu pasującego do tych słów — zapytaj inaczej."
    )
    return SearchResult(retrieval, passages, readings, note)


async def read_contract_document(
    db: AsyncSession, document: ContractDocument, from_chunk: int = 0
) -> ReadResult:
    """Treść jednego dokumentu po kolei, od fragmentu ``from_chunk``."""
    await index.ensure_indexed(db, [document])
    chunks = (
        await index.load_chunks(db, [document.id])
        if index.has_current_text(document)
        else []
    )
    passage, next_chunk = read_in_order(chunks, from_chunk=from_chunk)
    note = None
    if chunks and passage is None:
        note = "Dokument nie ma dalszych fragmentów — to był koniec treści."
    return ReadResult(
        document=_reading(document, len(chunks) or None),
        passage=_passage(document, passage, chunks) if passage is not None else None,
        next_chunk=next_chunk,
        note=note,
    )


def _clause_source(
    document: ContractDocument, label: str, clause_text: str, ref: Optional[str]
) -> SourcePassage:
    return SourcePassage(
        kind="contract",
        ref=f"{label} {ref}" if ref else label,
        text=clause_text,
        url=document_url(document),
        label=document.filename,
    )


def _terms(
    document: ContractDocument, label: str, rule: TerminationRule
) -> TerminationTerms:
    clauses = [rule.period_clause, rule.form_clause, rule.delivery_clause]
    seen: set[str] = set()
    sources: list[SourcePassage] = []
    for clause in clauses:
        if clause is None or clause.text in seen:
            continue
        seen.add(clause.text)
        sources.append(_clause_source(document, label, clause.text, clause.ref))
    return TerminationTerms(
        document_id=int(document.id),
        period_kind=rule.period_kind,
        period_months=rule.period_months,
        period_days=rule.period_days,
        forms=rule.forms,
        under_nullity=rule.under_nullity,
        delivery=rule.delivery,
        sources=tuple(sources),
        notes=rule.notes,
    )


def _is_pdf(document: ContractDocument) -> bool:
    return (document.filename or "").lower().endswith(".pdf") or (
        document.content_type or ""
    ).lower() == "application/pdf"


async def termination_terms(db: AsyncSession, contract_id: int) -> TerminationOutcome:
    """Okres wypowiedzenia, forma i doręczenie z PODPISANEJ umowy kontraktu.

    Umowa = najnowszy plik typu „umowa” z sekcji „Aktualna umowa” (PDF przed
    DOCX — DOCX to zwykle robocza wersja z Generatora). Aneks z tej sekcji
    z własnym zapisem o wypowiedzeniu wygrywa (najnowszy pierwszy); daty
    wgrania nie porównujemy z umową, bo import z SharePointa wgrywa pliki
    w przypadkowej kolejności. Gdy zapisu nie da się odczytać
    jednoznacznie — ``terms=None`` z powodem.
    """
    documents = await read_documents(db, contract_id)
    contracts = sorted(
        (
            d
            for d in documents
            if _type_value(d) == ContractDocumentType.contract.value
            and d.folder_id is None
        ),
        key=lambda d: (not _is_pdf(d), -d.created_at.timestamp(), -d.id),
    )
    if not contracts:
        return TerminationOutcome(
            None,
            "W Dokumentach kontraktu (sekcja „Aktualna umowa”) nie ma pliku umowy.",
        )
    contract_doc = contracts[0]
    annexes = [
        d
        for d in documents
        if _type_value(d) == ContractDocumentType.annex.value and d.folder_id is None
    ]
    await index.ensure_indexed(db, [contract_doc, *annexes])
    if not index.has_current_text(contract_doc):
        return TerminationOutcome(
            None,
            index.reading_note(contract_doc) or "Treści umowy nie da się odczytać.",
            int(contract_doc.id),
        )
    readable = [contract_doc, *(a for a in annexes if index.has_current_text(a))]
    grouped = _by_document(await index.load_chunks(db, [d.id for d in readable]))

    def text_of(document: ContractDocument) -> str:
        return "".join(
            c.text for c in sorted(grouped.get(document.id, []), key=lambda c: c.index)
        )

    # Najnowszy aneks z rozpoznanym zapisem wygrywa z umową.
    for annex in sorted(annexes, key=lambda d: d.created_at, reverse=True):
        if annex not in readable:
            continue
        text = text_of(annex)
        parsed = parse_termination(text)
        if parsed.rule is not None:
            label = _label(annex, document_number(text))
            return TerminationOutcome(
                _terms(annex, label, parsed.rule), None, int(annex.id)
            )
    text = text_of(contract_doc)
    parsed = parse_termination(text)
    if parsed.rule is None:
        return TerminationOutcome(None, parsed.reason, int(contract_doc.id))
    label = _label(contract_doc, document_number(text))
    terms = _terms(contract_doc, label, parsed.rule)
    unreadable = [a for a in annexes if a not in readable]
    if unreadable:
        terms = replace(
            terms,
            notes=(
                *terms.notes,
                "Aneksu przy tej umowie nie da się odczytać — mógł zmienić zapis.",
            ),
        )
    return TerminationOutcome(terms, None, int(contract_doc.id))
