"""Zapis pliku z SharePointa jako dokumentu kontraktu — jedna droga dla
pierwszego pobrania i synchronizacji (ticket 9).

„Jeśli kontrakt ma już dany dokument, pomiń plik” = ten sam skrót SHA-256
treści na tym kontrakcie albo ten sam plik SharePointa (``sharepoint_item_id``).
Dokumenty sprzed 0402 nie mają skrótu — liczymy go z pliku na dysku przy
pierwszym dotknięciu kontraktu i zapisujemy.
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.log_safety import safe_storage_key
from app.core.upload_filename import fit_filename_column
from app.models.activity import Activity
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.services import storage_service
from app.services.contract_folder_docs.classify import CONTENT_TYPES, extension

logger = logging.getLogger(__name__)

SOURCE_IMPORT = "sharepoint_import"
SOURCE_SYNC = "sharepoint"
SOURCE_UPLOAD = "upload"
# Źródła, które przyszły Z SharePointa — nigdy nie wysyłamy ich z powrotem.
FROM_SHAREPOINT = (SOURCE_IMPORT, SOURCE_SYNC)

# Blokada doradcza per kontrakt: dwa procesy (przebieg z panelu i pętla po
# deployu) nie mogą jednocześnie sprawdzić „brak skrótu” i dopisać tego samego.
_LOCK_NAMESPACE = 4020402


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def _backfill_missing_hashes(db: AsyncSession, contract_id: int) -> None:
    docs = (
        await db.execute(
            select(ContractDocument).where(
                ContractDocument.contract_id == contract_id,
                ContractDocument.content_sha256.is_(None),
            )
        )
    ).scalars()
    for doc in docs:
        try:
            path = storage_service.get_contract_document_path(doc.file_path)
            doc.content_sha256 = sha256_hex(path.read_bytes())
        except (FileNotFoundError, OSError):
            # Wiersz bez pliku na dysku zostaje bez skrótu — nie blokuje importu.
            logger.warning(
                "contract_docs_sp: brak pliku dokumentu %s (%s)",
                doc.id,
                safe_storage_key(doc.file_path),
            )


@dataclass(frozen=True)
class AttachResult:
    document_id: Optional[int]
    status: str  # done | skipped_existing


async def attach_file(
    db: AsyncSession,
    *,
    contract_id: int,
    content: bytes,
    filename: str,
    doc_type: str,
    source: str,
    item_id: str,
    user_id: Optional[int],
    run_id: Optional[int] = None,
    stored_key: str,
) -> AttachResult:
    """Zapisz plik na kontrakcie albo pomiń, gdy kontrakt już go ma.

    ``stored_key`` jest stały dla (przebieg/plik, kontrakt) — ponowienie po
    deployu nadpisuje ten sam plik na dysku zamiast zostawiać sierotę. Klucz
    NIE niesie nazwy pliku: ta bywa ścieżką z podfolderu („2023/umowa.pdf”),
    a zapis zostawia z niej tylko ostatni człon, więc dwa pliki „umowa.pdf”
    z różnych podfolderów nadpisywałyby się na dysku.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :id)"),
        {"ns": _LOCK_NAMESPACE, "id": contract_id},
    )
    digest = sha256_hex(content)
    await _backfill_missing_hashes(db, contract_id)
    # Sesje mają `autoflush=False` — bez tego zapytanie niżej nie widzi
    # skrótów policzonych przed chwilą.
    await db.flush()
    existing = await db.scalar(
        select(ContractDocument)
        .where(
            ContractDocument.contract_id == contract_id,
            (ContractDocument.content_sha256 == digest)
            | (ContractDocument.sharepoint_item_id == item_id),
        )
        .order_by(ContractDocument.id)
        .limit(1)
    )
    if existing is not None:
        # Ten sam plik już jest na kontrakcie (np. wgrany ręcznie pod inną
        # nazwą) — wiążemy go z plikiem SharePointa, inaczej synchronizacja
        # wysłałaby go z powrotem jako drugą kopię.
        if existing.sharepoint_item_id is None:
            existing.sharepoint_item_id = item_id
            existing.sharepoint_push_status = "done"
            existing.sharepoint_push_error = None
            await db.flush()
        return AttachResult(existing.id, "skipped_existing")

    display_name = fit_filename_column(filename.rsplit("/", 1)[-1] or "dokument")
    relative_path, size = storage_service.save_contract_document(
        contract_id=contract_id,
        upload_filename=display_name,
        source=io.BytesIO(content),
        stored_name=stored_key.replace("/", "_") + extension(display_name),
    )
    doc = ContractDocument(
        contract_id=contract_id,
        filename=display_name,
        file_path=relative_path,
        content_type=CONTENT_TYPES.get(extension(display_name)),
        size_bytes=size,
        doc_type=ContractDocumentType(doc_type),
        uploaded_by=user_id,
        content_sha256=digest,
        source=source,
        import_run_id=run_id,
        sharepoint_item_id=item_id,
        # Przyszedł z SharePointa — nie ma czego wysyłać z powrotem.
        sharepoint_push_status="done",
    )
    db.add(doc)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="document_uploaded",
            user_id=user_id,
            details={
                "filename": display_name,
                "doc_type": doc_type,
                "size_bytes": size,
                "via": source,
            },
        )
    )
    try:
        await db.flush()
    except Exception:
        storage_service.delete_contract_document(relative_path)
        raise
    return AttachResult(doc.id, "done")
