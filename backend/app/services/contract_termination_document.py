"""Wypowiedzenie albo porozumienie leżące w Dokumentach kontraktu (22.11.2026).

Przypomnienie „umowa B2B nie jest rozwiązana” czyta tylko
``contracts.agreement_termination_*``. Dokument dodany do zakładki Dokumenty
(ręcznie albo z SharePointa, ``source = sharepoint_import``) tych pól nie
wypełnia, więc zespół widział „nierozwiązana” mimo wypowiedzenia w aktach
(kontrakt #605; na kopii z 19.11 38 z 75 zakończonych i kończących się umów
B2B bez zapisanego rozwiązania miało taki dokument).

Ten moduł tylko WSKAZUJE dokument — najnowszy ``termination_notice`` albo
``termination_agreement`` kontraktu. Pól rozwiązania z niego nie wypełniamy:
ostatni dzień umowy przesuwa okres wypowiedzenia i zakaz konkurencji, więc
wpisuje go człowiek przez ``PUT /api/contracts/{id}/agreement-termination``.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import ContractType
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.schemas.contract import ContractTerminationDocument

__all__ = [
    "TERMINATION_DOC_TYPES",
    "attach_termination_documents",
    "termination_documents",
]

TERMINATION_DOC_TYPES: tuple[ContractDocumentType, ...] = (
    ContractDocumentType.termination_notice,
    ContractDocumentType.termination_agreement,
)


async def termination_documents(
    db: AsyncSession, contract_ids: Iterable[int]
) -> dict[int, ContractTerminationDocument]:
    """Najnowszy dokument rozwiązania na kontrakt (po dacie dodania, potem id)."""
    ids = sorted({cid for cid in contract_ids if cid is not None})
    if not ids:
        return {}
    rows = await db.execute(
        select(
            ContractDocument.contract_id,
            ContractDocument.id,
            ContractDocument.doc_type,
            ContractDocument.filename,
            ContractDocument.content_type,
            ContractDocument.source,
            ContractDocument.created_at,
        )
        .where(
            ContractDocument.contract_id.in_(ids),
            ContractDocument.doc_type.in_(TERMINATION_DOC_TYPES),
        )
        .order_by(
            ContractDocument.contract_id,
            ContractDocument.created_at.desc(),
            ContractDocument.id.desc(),
        )
    )
    found: dict[int, ContractTerminationDocument] = {}
    for row in rows.all():
        if row.contract_id in found:
            continue
        found[row.contract_id] = ContractTerminationDocument(
            id=row.id,
            doc_type=getattr(row.doc_type, "value", row.doc_type),
            filename=row.filename,
            content_type=row.content_type,
            source=row.source,
            created_at=row.created_at,
        )
    return found


def _needs_hint(item: Any) -> bool:
    """Tylko umowa B2B bez zapisanego rozwiązania — reszty przypomnienie nie dotyczy."""
    # ``ContractType`` to str-enum: porównanie działa i dla enuma, i dla "b2b".
    return getattr(item, "contract_type", None) == ContractType.b2b and not getattr(
        item, "agreement_termination_mode", None
    )


async def attach_termination_documents(db: AsyncSession, items: Sequence[Any]) -> None:
    """Wpisz ``termination_document`` w wiersze listy i w członków grup.

    Jedno zapytanie na stronę listy. Wiersz zgrupowany po osobie ma dokument
    per umowa (``group_members``), bo „+ Rozwiązanie” stoi przy każdej umowie.
    """
    targets: list[Any] = []
    for item in items:
        if _needs_hint(item):
            targets.append(item)
        for member in getattr(item, "group_members", None) or []:
            if _needs_hint(member):
                targets.append(member)
    if not targets:
        return
    docs = await termination_documents(db, (t.id for t in targets))
    for target in targets:
        doc: Optional[ContractTerminationDocument] = docs.get(target.id)
        if doc is not None:
            target.termination_document = doc
