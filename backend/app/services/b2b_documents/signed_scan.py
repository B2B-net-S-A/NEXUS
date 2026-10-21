"""Skan podpisanego aneksu w Dokumentach kontraktu.

Do 13.10.2026 po „Oznacz jako podpisany” do Dokumentów kontraktu trafiał
wygenerowany DOCX — plik bez podpisów — a przy aneksie z danymi wrażliwymi
(dane firmy, zlecenie) nie trafiało nic. Skan to faktycznie podpisany dokument:
ląduje jako dokument kontraktu typu „Aneks”, a aneksy kontraktu utworzone
przez ten dokument wskazują na niego. Wygenerowany DOCX zostaje obok — to
wersja robocza, z której powstał podpisany egzemplarz.

Skan aneksu danych firmy albo zlecenia zawiera PESEL, numer dowodu i adres
zamieszkania. NEXUS tych danych nie przechowuje w bazie (``strip_sensitive``),
ale podpisany egzemplarz należy do dokumentów kontraktu tak samo jak plik
dołączany tam ręcznie — okno podpisu od zawsze o to prosi
(``effects.describe``).
"""

from __future__ import annotations

import hashlib
import io
from pathlib import PurePath
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.upload_filename import fit_filename_column
from app.models.activity import Activity
from app.models.b2b_contract_document import B2BContractDocument
from app.models.contract_amendment import ContractAmendment
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.services import storage_service
from app.services.contract_folder_docs.store import requeue_replaced_content

MAX_SCAN_BYTES = 20 * 1024 * 1024

#: Rozszerzenie → (pierwsze bajty pliku, typ treści). Skan to PDF albo zdjęcie;
#: DOCX nie jest skanem podpisanego dokumentu.
_FORMATS: dict[str, tuple[bytes, str]] = {
    ".pdf": (b"%PDF-", "application/pdf"),
    ".jpg": (b"\xff\xd8\xff", "image/jpeg"),
    ".jpeg": (b"\xff\xd8\xff", "image/jpeg"),
    ".png": (b"\x89PNG\r\n\x1a\n", "image/png"),
}

MSG_FORMAT = "Skan podpisanego aneksu musi być plikiem PDF, JPG albo PNG."
MSG_CONTENT = (
    "Zawartość pliku nie odpowiada jego rozszerzeniu — wgraj skan w PDF, JPG albo PNG."
)
MSG_EMPTY = "Plik jest pusty."
MSG_TOO_BIG = "Plik jest za duży — skan może mieć najwyżej 20 MB."
MSG_NOT_SIGNED = "Skan dołączysz po oznaczeniu aneksu jako podpisany."
MSG_NO_CONTRACT = (
    "Aneks nie zmienił żadnego kontraktu, więc skan nie ma gdzie trafić — "
    "dołącz go ręcznie w zakładce Dokumenty właściwego kontraktu."
)


def check_scan(
    filename: str | None, data: bytes, *, format_msg: str = MSG_FORMAT
) -> tuple[str, str]:
    """(nazwa do zapisu, typ treści); odmowa, gdy plik nie jest skanem.

    Rozszerzenie i pierwsze bajty muszą się zgadzać — nazwa pochodzi
    z przeglądarki, więc sama nie mówi, co jest w środku. ``format_msg``
    nazywa dokument (aneks, umowa) w odmowie złego formatu."""
    name = fit_filename_column(filename or "skan.pdf")
    known = _FORMATS.get(PurePath(name).suffix.lower())
    if known is None:
        raise HTTPException(status_code=415, detail=format_msg)
    if not data:
        raise HTTPException(status_code=422, detail=MSG_EMPTY)
    if len(data) > MAX_SCAN_BYTES:
        raise HTTPException(status_code=413, detail=MSG_TOO_BIG)
    signature, content_type = known
    if not data.startswith(signature):
        raise HTTPException(status_code=415, detail=MSG_CONTENT)
    return name, content_type


async def read_scan(
    upload: UploadFile, *, format_msg: str = MSG_FORMAT
) -> tuple[str, str, bytes]:
    """(nazwa, typ treści, bajty) — nigdy więcej niż limit + 1 bajt w pamięci."""
    data = await upload.read(MAX_SCAN_BYTES + 1)
    name, content_type = check_scan(upload.filename, data, format_msg=format_msg)
    return name, content_type, data


def amendment_ids_of(doc: B2BContractDocument) -> list[int]:
    """Aneksy kontraktu, które utworzył podpis tego dokumentu."""
    summary: dict[str, Any] = doc.effect_summary or {}
    raw = summary.get("amendment_ids")
    if not isinstance(raw, list) or not raw:
        raw = [summary.get("amendment_id")]
    return [value for value in raw if isinstance(value, int)]


def signed_scan_id(doc: B2BContractDocument) -> int | None:
    value = (doc.effect_summary or {}).get("signed_scan_document_id")
    return value if isinstance(value, int) else None


async def existing_scan_ids(
    db: AsyncSession, docs: list[B2BContractDocument]
) -> set[int]:
    """Skany tych dokumentów, które nadal leżą w Dokumentach kontraktu.

    Zapis skutku trzyma id skanu na zawsze, a skan znika razem z kontraktem
    albo po „Usuń” w zakładce Dokumenty. Do 14.10.2026 rejestr pokazywał wtedy
    „Podmień skan” i „Nowy plik zastąpi skan…” przy skanie, którego nie ma
    (audyt 13.10.2026). Jedno zapytanie na stronę listy."""
    ids = {sid for doc in docs if (sid := signed_scan_id(doc)) is not None}
    if not ids:
        return set()
    found = await db.scalars(
        select(ContractDocument.id).where(ContractDocument.id.in_(ids))
    )
    return set(found.all())


async def attach(
    db: AsyncSession,
    *,
    doc: B2BContractDocument,
    filename: str,
    content_type: str,
    data: bytes,
    actor_id: int | None,
) -> str | None:
    """Zapisz skan przy kontrakcie i przepnij na niego aneksy tego dokumentu.

    Wołający trzyma blokadę dokumentu i sprawdził uprawnienia. Kontrakt
    bierzemy z aneksów, które podpis utworzył (albo z zapisu skutku) — umowa
    bazowa mogła po podpisie dostać inny kontrakt, a skan należy do tego,
    który aneks faktycznie zmienił. Kolejny skan PODMIENIA poprzedni.

    Zwraca ścieżkę podmienionego pliku (albo ``None``). Stary plik usuwa
    wołający PO commicie (``discard``): usunięty wcześniej zostawiałby po
    nieudanym commicie wiersz wskazujący plik, którego już nie ma."""
    if doc.signature_status != "signed_both" or doc.effect_applied_at is None:
        raise HTTPException(status_code=409, detail=MSG_NOT_SIGNED)
    amendments = list(
        (
            await db.scalars(
                select(ContractAmendment)
                .where(ContractAmendment.id.in_(amendment_ids_of(doc) or [-1]))
                .order_by(ContractAmendment.id)
                .with_for_update()
            )
        ).all()
    )
    contract_id = (
        amendments[0].contract_id
        if amendments
        else (doc.effect_summary or {}).get("contract_id")
    )
    if not isinstance(contract_id, int):
        raise HTTPException(status_code=409, detail=MSG_NO_CONTRACT)
    amendments = [a for a in amendments if a.contract_id == contract_id]

    suffix = PurePath(filename).suffix.lower()
    digest = hashlib.sha256(data).hexdigest()
    path, size = storage_service.save_contract_document(
        contract_id,
        filename,
        io.BytesIO(data),
        # Klucz z treści: ponowienie po awarii trafia w ten sam plik, a inny
        # skan zapisuje się obok — plik, na który wskazuje wiersz, zostaje
        # nietknięty do commitu.
        stored_name=f"b2b-document-{doc.id}-skan-{digest[:16]}{suffix}",
    )
    previous_id = signed_scan_id(doc)
    record = (
        await db.get(ContractDocument, previous_id) if previous_id is not None else None
    )
    if record is not None and record.contract_id != contract_id:
        record = None
    replaced_path: str | None = None
    if record is None:
        record = ContractDocument(
            contract_id=contract_id,
            doc_type=ContractDocumentType.annex,
            source="upload",
        )
        db.add(record)
    else:
        # Skan wysłany już do SharePointa wraca do wysyłki — synchronizacja
        # podmieni tam treść tego samego pliku.
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

    for amendment in amendments:
        amendment.document_id = record.id
    # Nowy słownik: zmiana w miejscu nie zostałaby zapisana w kolumnie JSONB.
    doc.effect_summary = {
        **(doc.effect_summary or {}),
        "signed_scan_document_id": record.id,
    }
    db.add(
        Activity(
            entity_type="b2b_contract_document",
            entity_id=doc.id,
            action="signed_scan_attached",
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
                "doc_type": ContractDocumentType.annex.value,
                "size_bytes": size,
            },
        )
    )
    return replaced_path


def discard(replaced_path: str | None) -> None:
    """Usuń plik podmienionego skanu — po udanym commicie."""
    if replaced_path is not None:
        storage_service.delete_contract_document(replaced_path)
