"""Aneksy z Generatora aneksów widziane od strony kontraktu.

Zakładka „Aneksy” kontraktu pokazuje aneks od wygenerowania („czeka na
podpis”), a nie dopiero po podpisie. Wiersz czekającego aneksu jest RZUTEM
dokumentu — nie wpisem w ``contract_amendments``: tę tabelę czytają jako zmiany
już zastosowane analityka kontraktów, fakty zamówień, naprawa dat końca
i Finanse → Zamówienia PDF, więc aneks bez podpisu liczyłby się tam jako
obowiązujący.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.b2b_contract_document import B2BContractDocument
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.contract_amendment import ContractAmendment
from app.services.b2b_documents import effects, signed_scan
from app.services.b2b_documents.registry import TYPES

ANNEX_TYPE_KEYS: tuple[str, ...] = tuple(
    key for key, doc_type in TYPES.items() if doc_type.family == "annex"
)

AnnexDocument = tuple[B2BContractDocument, "B2BGeneratedContract | None"]


def belongs_to_contract(
    doc: B2BContractDocument,
    parent: B2BGeneratedContract | None,
    contract_id: int,
) -> bool:
    """Czy aneks jest aneksem TEGO kontraktu.

    Podpisany: kontrakt, który podpis faktycznie zmienił (zapis skutku) —
    umowa bazowa mogła potem dostać inny kontrakt, a aneks nie przenosi się
    za nią. Niepodpisany: kontrakt, na który podpis zadziała dziś."""
    if doc.effect_applied_at is not None:
        return (doc.effect_summary or {}).get("contract_id") == contract_id
    return effects.current_contract_id(doc, parent) == contract_id


async def annex_documents_for_contract(
    db: AsyncSession, contract_id: int
) -> list[AnnexDocument]:
    """Aneksy z generatora należące do kontraktu, od najnowszego."""
    found = await db.execute(
        select(B2BContractDocument, B2BGeneratedContract)
        .outerjoin(
            B2BGeneratedContract,
            B2BGeneratedContract.id == B2BContractDocument.parent_generated_contract_id,
        )
        .where(
            B2BContractDocument.document_type.in_(ANNEX_TYPE_KEYS),
            or_(
                B2BGeneratedContract.contract_id == contract_id,
                and_(
                    B2BContractDocument.parent_generated_contract_id.is_(None),
                    B2BContractDocument.contract_id == contract_id,
                ),
                B2BContractDocument.effect_summary["contract_id"].astext
                == str(contract_id),
            ),
        )
        .order_by(B2BContractDocument.id.desc())
    )
    return [
        (doc, parent)
        for doc, parent in found.all()
        if belongs_to_contract(doc, parent, contract_id)
    ]


def documents_by_amendment(
    documents: list[AnnexDocument],
) -> dict[int, B2BContractDocument]:
    """Aneks kontraktu → dokument z generatora, którego podpis go utworzył."""
    out: dict[int, B2BContractDocument] = {}
    for doc, _parent in documents:
        if doc.effect_applied_at is None:
            continue
        for amendment_id in signed_scan.amendment_ids_of(doc):
            out[amendment_id] = doc
    return out


def without_amendment(
    documents: list[AnnexDocument], amendment_ids: set[int]
) -> list[AnnexDocument]:
    """Aneksy, których w historii kontraktu nie reprezentuje żaden wpis:
    czekające na podpis, anulowane i podpisane bez zmiany w kontrakcie."""
    return [
        (doc, parent)
        for doc, parent in documents
        if doc.effect_applied_at is None
        or not (set(signed_scan.amendment_ids_of(doc)) & amendment_ids)
    ]


async def document_for_amendment(
    db: AsyncSession, amendment: ContractAmendment
) -> B2BContractDocument | None:
    documents = await annex_documents_for_contract(db, amendment.contract_id)
    return documents_by_amendment(documents).get(amendment.id)


def values_of(doc: B2BContractDocument) -> dict[str, Any]:
    return dict((doc.render_payload or {}).get("values") or {})


def effective_date_of(
    doc: B2BContractDocument, *, contract_client_id: int | None
) -> date | None:
    """Dzień wejścia aneksu w życie: zapisany przy podpisie, a wcześniej —
    ta sama reguła, którą podpis zastosuje (``effects.annex_effective_date``)."""
    stored = (doc.effect_summary or {}).get("effective_date")
    if isinstance(stored, str):
        try:
            return date.fromisoformat(stored[:10])
        except ValueError:
            pass
    return effects.annex_effective_date(
        doc.document_type,
        values_of(doc),
        doc.document_date,
        contract_client_id=contract_client_id,
    )
