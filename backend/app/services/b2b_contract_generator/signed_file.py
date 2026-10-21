"""Podpisany egzemplarz umowy B2B w Dokumentach kontraktu (0496, 21.10.2026).

„Oznacz jako podpisaną” zakłada kontrakt i zamówienie, ale do 21.10.2026 nie
zostawiało pliku: podpisany PDF krążył mailem (kontraktor → Olaf → rekruter →
Administracja) i lądował na dysku „b2b all”, a w NEXUSIE go nie było
(zgłoszenie Administracji). Plik jest dobrowolny — droga bez niego działa
jak dotąd. Dołącza się go w oknie podpisu albo później z wiersza rejestru;
trafia do Dokumentów kontraktu jako „Umowa”, a wiersz rejestru na niego
wskazuje (``signed_document_id``). Kolejny plik PODMIENIA poprzedni.

Format i limity jak przy skanie podpisanego aneksu (``signed_scan.check_scan``).
"""

from __future__ import annotations

import hashlib
import io
from pathlib import PurePath

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.services import storage_service
from app.services.contract_folder_docs.store import requeue_replaced_content

MSG_FORMAT = "Podpisana umowa musi być plikiem PDF, JPG albo PNG."
MSG_NOT_SIGNED = "Plik dołączysz po oznaczeniu umowy jako podpisanej."
MSG_NO_CONTRACT = (
    "Umowa nie ma powiązanego kontraktu, więc plik nie ma gdzie trafić — "
    "dołącz go ręcznie w zakładce Dokumenty właściwego kontraktu."
)


async def existing_document_ids(
    db: AsyncSession, rows: list[B2BGeneratedContract]
) -> set[int]:
    """Podpisane pliki tych wierszy, które nadal leżą w Dokumentach.

    Kolumna zeruje się przy usunięciu dokumentu (``ON DELETE SET NULL``), ale
    lista czyta wiersze z tej samej sesji, więc pyta wprost — jedno zapytanie
    na stronę listy, jak ``signed_scan.existing_scan_ids``."""
    ids = {row.signed_document_id for row in rows if row.signed_document_id}
    if not ids:
        return set()
    found = await db.scalars(
        select(ContractDocument.id).where(ContractDocument.id.in_(ids))
    )
    return set(found.all())


async def attach(
    db: AsyncSession,
    *,
    row: B2BGeneratedContract,
    filename: str,
    content_type: str,
    data: bytes,
    actor_id: int | None,
) -> str | None:
    """Zapisz plik przy kontrakcie wiersza i wskaż go z wiersza.

    Wołający trzyma blokadę wiersza i sprawdził uprawnienia. Zwraca ścieżkę
    podmienionego pliku (albo ``None``); stary plik usuwa wołający PO commicie
    (``discard``), żeby nieudany commit nie zostawił wiersza bez pliku."""
    if row.signature_status != "signed_both":
        raise HTTPException(status_code=409, detail=MSG_NOT_SIGNED)
    contract_id = row.contract_id
    if contract_id is None:
        raise HTTPException(status_code=409, detail=MSG_NO_CONTRACT)

    suffix = PurePath(filename).suffix.lower()
    digest = hashlib.sha256(data).hexdigest()
    path, size = storage_service.save_contract_document(
        contract_id,
        filename,
        io.BytesIO(data),
        # Klucz z treści: ponowienie po awarii trafia w ten sam plik, a inny
        # plik zapisuje się obok — ten, na który wskazuje wiersz, zostaje
        # nietknięty do commitu.
        stored_name=f"b2b-generated-{row.id}-podpisana-{digest[:16]}{suffix}",
    )
    record = (
        await db.get(ContractDocument, row.signed_document_id)
        if row.signed_document_id is not None
        else None
    )
    if record is not None and record.contract_id != contract_id:
        record = None
    replaced_path: str | None = None
    if record is None:
        record = ContractDocument(
            contract_id=contract_id,
            doc_type=ContractDocumentType.contract,
            source="upload",
        )
        db.add(record)
    else:
        requeue_replaced_content(record, content_sha256=digest, filename=filename)
        if record.file_path != path:
            replaced_path = record.file_path
    record.filename = filename
    record.file_path = path
    record.content_type = content_type
    record.size_bytes = size
    record.content_sha256 = digest
    record.uploaded_by = actor_id
    await db.flush()

    row.signed_document_id = record.id
    db.add(
        Activity(
            entity_type="b2b_generated_contract",
            entity_id=row.id,
            action="signed_file_attached",
            user_id=actor_id,
            details={"contract_id": contract_id, "contract_document_id": record.id},
        )
    )
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="document_uploaded",
            user_id=actor_id,
            details={
                "filename": filename,
                "doc_type": ContractDocumentType.contract.value,
                "size_bytes": size,
            },
        )
    )
    return replaced_path


def discard(replaced_path: str | None) -> None:
    """Usuń plik podmienionego egzemplarza — po udanym commicie."""
    if replaced_path is not None:
        storage_service.delete_contract_document(replaced_path)
