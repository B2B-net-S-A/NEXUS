"""Zapis orzeczeń: wiersz na (źródło, id w źródle), tematy się sumują."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.legal_case_law import LegalCase
from app.services.help_search import fold
from app.services.legal_case_law.saos import CaseRecord

#: tsvector ma limit 1 MB; tyle znaków tekstu złożonego wystarcza z zapasem.
SEARCH_TEXT_MAX = 400_000


def search_text(record: CaseRecord) -> str:
    """Sygnatura, sąd, teza i treść bez polskich znaków — wejście ``to_tsvector``."""
    body = "\n".join(
        part
        for part in (record.signature, record.court, record.summary, record.text)
        if part
    )
    return fold(body)[:SEARCH_TEXT_MAX]


@dataclass(frozen=True)
class StoreResult:
    inserted: int
    updated: int
    unchanged: int


async def store_records(
    db: AsyncSession, records: Sequence[CaseRecord]
) -> StoreResult:
    """Dopisuje albo odświeża orzeczenia; commit robi wołający."""
    unique: dict[tuple[str, str], CaseRecord] = {}
    for record in records:
        key = (record.source, record.source_id)
        previous = unique.get(key)
        if previous is not None:
            merged = tuple(dict.fromkeys((*previous.topics, *record.topics)))
            record = replace(record, topics=merged)
        unique[key] = record
    if not unique:
        return StoreResult(0, 0, 0)
    existing = {
        (row.source, row.source_id): row
        for row in (
            await db.execute(
                select(LegalCase).where(
                    tuple_(LegalCase.source, LegalCase.source_id).in_(list(unique))
                )
            )
        ).scalars()
    }
    inserted = updated = unchanged = 0
    for key, record in unique.items():
        row = existing.get(key)
        digest = record.content_sha256
        if row is None:
            db.add(
                LegalCase(
                    source=record.source,
                    source_id=record.source_id,
                    signature=record.signature,
                    court=record.court,
                    court_type=record.court_type,
                    judgment_date=record.judgment_date,
                    kind=record.kind,
                    url=record.url,
                    summary=record.summary,
                    text=record.text,
                    content_sha256=digest,
                    topics=list(record.topics),
                    search_tsv=func.to_tsvector("simple", search_text(record)),
                )
            )
            inserted += 1
            continue
        topics = list(dict.fromkeys([*(row.topics or []), *record.topics]))
        if row.content_sha256 == digest and topics == list(row.topics or []):
            unchanged += 1
            continue
        if row.content_sha256 != digest:
            row.signature = record.signature
            row.court = record.court
            row.court_type = record.court_type
            row.judgment_date = record.judgment_date
            row.kind = record.kind
            row.url = record.url
            row.summary = record.summary
            row.text = record.text
            row.content_sha256 = digest
            row.search_tsv = func.to_tsvector("simple", search_text(record))
            row.fetched_at = func.now()
        row.topics = topics
        row.updated_at = func.now()
        updated += 1
    await db.flush()
    return StoreResult(inserted, updated, unchanged)
