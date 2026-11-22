"""Stawka z dokumentu na liście kontraktów (0739): filtr i pole wiersza."""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract_document_rate_read import ContractDocumentRateRead
from app.services.contract_rate_documents import reader


def _open_clause():
    read = ContractDocumentRateRead
    return (
        read.reader_version == reader.READER_VERSION,
        read.has_finding.is_(True),
        or_(read.decision.is_(None), read.decision == "undone"),
    )


def open_rate_document_contracts():
    """Podzapytanie: kontrakty z otwartą różnicą stawki z dokumentu."""

    return select(ContractDocumentRateRead.contract_id).where(*_open_clause())


async def attach_rate_document_changes(db: AsyncSession, items: Sequence[Any]) -> None:
    """Wpisz w wiersze listy pierwszy krok otwartej różnicy (przed redakcją kwot)."""

    ids = [item.id for item in items if getattr(item, "id", None) is not None]
    if not ids:
        return
    rows = (
        await db.execute(
            select(ContractDocumentRateRead)
            .where(ContractDocumentRateRead.contract_id.in_(ids), *_open_clause())
            .order_by(ContractDocumentRateRead.id)
        )
    ).scalars()
    by_contract: dict[int, dict[str, Any]] = {}
    for row in rows:
        finding = row.finding or {}
        steps = [s for s in finding.get("steps") or [] if s.get("from")]
        if not steps or row.contract_id in by_contract:
            continue
        first = min(steps, key=lambda s: s["from"])
        by_contract[row.contract_id] = {
            "from": first["from"],
            "rate": first.get("rate"),
            "kind": (row.result or {}).get("kind"),
            "category": finding.get("category"),
            "count": len(steps),
        }
    for item in items:
        change = by_contract.get(getattr(item, "id", None))
        if change is not None:
            item.rate_document_change = change
