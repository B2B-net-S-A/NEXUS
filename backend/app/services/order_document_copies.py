"""PDF linii zamówienia zbiorczego a kopia PDF-u jej grupy w Dokumentach kontraktu.

Linia zamówienia zbiorczego może mieć własny PDF (``client_orders.file_path``),
a kontrakt dostaje też automatyczną kopię PDF-u grupy
(``contract_documents.source_order_group_id``). Bywa to ten sam plik: 19.11.2026
na produkcji 14 takich par w 13 kontraktach, a folder „Zamówienia” w zakładce
Dokumenty pokazywał oba wiersze. Trasa ``order-documents/by-contract`` oddaje
przy linii id kopii o identycznej treści (``same_file_document_id``), a front
pokazuje wtedy jeden wiersz — linię, bo kopia nie niesie nic więcej.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder
from app.models.contract_document import ContractDocument
from app.services import storage_service
from app.services.contract_folder_docs.store import file_sha256


def _order_file_sha256(file_path: str) -> str | None:
    try:
        return file_sha256(storage_service.get_client_order_po_path(file_path))
    except FileNotFoundError:
        return None


def _copy_sha256(copy: ContractDocument) -> str | None:
    # Z pliku, nie z kolumny: kopia grupy do 20.11.2026 była podmieniana
    # w miejscu bez zmiany skrótu (``store.same_content_documents``).
    try:
        return file_sha256(storage_service.get_contract_document_path(copy.file_path))
    except FileNotFoundError:
        return None


async def same_file_group_copies(
    db: AsyncSession, contract_id: int, orders: Sequence[ClientOrder]
) -> dict[int, int]:
    """``order_id`` → id kopii PDF-u grupy tej linii, gdy to ten sam plik.

    Treść (SHA-256) porównujemy tylko przy równym rozmiarze, więc pliki
    czytamy wyłącznie dla kandydatów na parę. Para innej treści zostaje
    dwoma wierszami."""
    group_ids = {
        order.order_group_id
        for order in orders
        if order.order_group_id is not None and order.file_path
    }
    if not group_ids:
        return {}
    copies = {
        copy.source_order_group_id: copy
        for copy in (
            await db.scalars(
                select(ContractDocument).where(
                    ContractDocument.contract_id == contract_id,
                    ContractDocument.source_order_group_id.in_(group_ids),
                )
            )
        ).all()
    }
    pairs: dict[int, int] = {}
    for order in orders:
        copy = copies.get(order.order_group_id)
        if (
            copy is None
            or not order.file_path
            or order.size_bytes is None
            or order.size_bytes != copy.size_bytes
        ):
            continue
        order_sha = _order_file_sha256(order.file_path)
        if order_sha is not None and order_sha == _copy_sha256(copy):
            pairs[order.id] = copy.id
    return pairs
