"""Zapis pliku z SharePointa jako dokumentu kontraktu — jedna droga dla
pierwszego pobrania i synchronizacji (ticket 9).

„Jeśli kontrakt ma już dany dokument, pomiń plik” = ten sam skrót SHA-256
treści na tym kontrakcie albo ten sam plik SharePointa (``sharepoint_item_id``).
Dokumenty sprzed 0402 nie mają skrótu — liczymy go z pliku na dysku przy
pierwszym dotknięciu kontraktu i zapisujemy.

Ten sam test „kontrakt ma już ten plik” (``same_content_documents``) stoi od
20.11.2026 przed ręcznym uploadem, kopią PDF-u zamówienia zbiorczego i skanem
podpisanego aneksu (decyzja Artura 19.11: blokada uploadu + jedna kopia).
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy import or_, select, text
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


def requeue_replaced_content(
    doc: ContractDocument, *, content_sha256: str, filename: str
) -> None:
    """Treść dokumentu podmieniono w NEXUSIE — kopia w SharePoincie jest stara.

    Dokument wysłany wcześniej (``sharepoint_item_id``) wraca na „czeka na
    wysyłkę”; synchronizacja podmieni treść TEGO pliku (``sync._replace_one``)
    zamiast dokładać drugi. Bez tego wiersz z ``sharepoint_item_id`` nie wracał
    do wysyłki wcale i w SharePoincie zostawał stary skan aneksu (przegląd
    kodu 13.10.2026). Wołaj PRZED nadpisaniem pól dokumentu. Plik, który
    przyszedł z SharePointa, nie wraca tam z NEXUSA."""
    if doc.sharepoint_item_id is None or doc.source in FROM_SHAREPOINT:
        return
    if doc.content_sha256 == content_sha256 and doc.filename == filename:
        return
    doc.sharepoint_push_status = None
    doc.sharepoint_push_attempts = 0
    doc.sharepoint_push_error = None


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def lock_contract_documents(db: AsyncSession, contract_id: int) -> None:
    """Blokada doradcza dokumentów jednego kontraktu do końca transakcji.

    Ta sama co w ``attach_file``: dwa zapisy tego samego pliku naraz (podwójne
    kliknięcie, plik z SharePointa w tej samej chwili) nie mogą oba uznać, że
    kontrakt go jeszcze nie ma. Bierz ją, ZANIM transakcja zablokuje wiersz
    kontraktu: wstawienie dokumentu czeka na ten wiersz (klucz obcy), więc
    odwrotna kolejność może się zakleszczyć z importem z SharePointa."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :id)"),
        {"ns": _LOCK_NAMESPACE, "id": contract_id},
    )


def file_sha256(path: Path) -> Optional[str]:
    """SHA-256 pliku czytanego po 64 KB; ``None``, gdy pliku nie da się czytać."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 64), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _document_sha256(file_path: str) -> Optional[str]:
    try:
        return file_sha256(storage_service.get_contract_document_path(file_path))
    except FileNotFoundError:
        return None


async def same_content_documents(
    db: AsyncSession,
    contract_id: int,
    content_sha256: str,
    *,
    size_bytes: Optional[int] = None,
) -> list[ContractDocument]:
    """Dokumenty kontraktu z tym samym plikiem, od najstarszego (20.11.2026).

    „Kontrakt ma już ten plik” = ten sam SHA-256 treści, jak przy imporcie
    z SharePointa. Skrót w bazie tylko zawęża szukanie, a rozstrzyga plik na
    dysku. Kopia PDF-u zamówienia zbiorczego do 20.11.2026 nie dostawała
    skrótu przy zapisie, więc import z SharePointa dopisywał go
    (``_backfill_missing_hashes``), a zamówienie podmieniało potem plik
    w miejscu i skrót zostawał stary. Dlatego kopie grup i wiersze bez skrótu
    porównujemy z plikiem zawsze. Wiersz, którego pliku nie ma na dysku, się
    nie liczy, bo zgubiony plik musi dać się wgrać z powrotem.

    Skrótów tu NIE zapisujemy. Skan aneksu i zapis linii zamówienia trzymają
    już blokadę wiersza kontraktu, a aktualizacja innych wierszy dokumentów
    mogłaby się wtedy zakleszczyć z ``attach_file``. ``size_bytes`` pomija
    czytanie plików o innym rozmiarze."""
    candidates = (
        await db.scalars(
            select(ContractDocument)
            .where(
                ContractDocument.contract_id == contract_id,
                or_(
                    ContractDocument.content_sha256 == content_sha256,
                    ContractDocument.content_sha256.is_(None),
                    ContractDocument.source_order_group_id.is_not(None),
                ),
            )
            .order_by(ContractDocument.id)
        )
    ).all()
    return [
        doc
        for doc in candidates
        if (size_bytes is None or doc.size_bytes in (None, size_bytes))
        and _document_sha256(doc.file_path) == content_sha256
    ]


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
    await lock_contract_documents(db, contract_id)
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
