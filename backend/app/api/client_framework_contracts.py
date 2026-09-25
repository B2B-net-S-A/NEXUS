"""Router `/api/clients/{client_id}/framework-contracts` — MSA per klient.

Reads (GET) — admin/Finance i Delivery Lead globalnie.
Talent Community Manager ma bezpieczny odczyt Delivery, ale nie dostaje
nieprzezroczystych dokumentów prawnych, które mogą zawierać stawki.
Writes (POST/PATCH/DELETE) — `DlAssignedOrAdmin` (admin globalnie albo DL
przypisany do klienta). Bramka sekcji odcina HoR/TAC i zapis TCM.

Pattern multipart upload — zaczerpnięte z `client_materials.py` (one-pagers).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    DlAssignedOrAdmin,
    get_current_user,
)
from app.api.delivery_client_scope import DELIVERY_CLIENT_SCOPE_DEPENDENCIES
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.services.client_access import (
    assert_client_writable,
    deny,
    resolve_client_access,
)
from app.services.critical_events import audited_deletion
from app.services.autenti.client_contracts_sender import ClientDocSendRequest
from app.core.database import get_db
from app.models.activity import Activity
from app.models.client import Client
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.client_contract_terms import ClientContractTerms
from app.models.client_executive_contract import ClientExecutiveContract
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractSignedVia,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder
from app.schemas.client_framework_contract import (
    ClientFrameworkContractListResponse,
    ClientFrameworkContractRead,
    ClientFrameworkContractUpdate,
)
from app.services import storage_service
from app.core.scheduling import business_today

router = APIRouter(
    dependencies=[*DELIVERY_SECTION_DEPENDENCIES, *DELIVERY_CLIENT_SCOPE_DEPENDENCIES]
)


MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB — MSA bywa duży

_ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/octet-stream",
}
_ALLOWED_EXT_RE = (".pdf", ".docx", ".doc")


async def _assert_client(db: AsyncSession, client_id: int) -> None:
    client = (
        await db.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()
    # Klient usunięty z profilu (0307) nie ma już profilu ani zakładki Umowy.
    if client is None or client.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Client not found")


async def _validate_references(
    db: AsyncSession,
    client_id: int,
    *,
    fc_id: Optional[int],
    parent_contract_id: Optional[int],
    contract_terms_id: Optional[int],
) -> None:
    """Powiązania umowy ramowej muszą wskazywać rekordy TEGO klienta.

    Do 24.09.2026 nieistniejące id kończyło się 500 z bazy (FK), a id
    z innego klienta — cichym zapisem cudzej umowy jako „poprzedniej wersji”
    (audyt S3).
    """
    if parent_contract_id is not None:
        if fc_id is not None and parent_contract_id == fc_id:
            raise HTTPException(
                422, detail="Umowa nie może być poprzednią wersją samej siebie."
            )
        parent_client = await db.scalar(
            select(ClientFrameworkContract.client_id).where(
                ClientFrameworkContract.id == parent_contract_id
            )
        )
        if parent_client != client_id:
            raise HTTPException(
                422,
                detail="Poprzednia wersja musi być umową ramową tego samego klienta.",
            )
    if contract_terms_id is not None:
        terms_client = await db.scalar(
            select(ClientContractTerms.client_id).where(
                ClientContractTerms.id == contract_terms_id
            )
        )
        if terms_client != client_id:
            raise HTTPException(
                422,
                detail="Warunki umowy muszą należeć do tego samego klienta.",
            )


def _validate_text_fields(
    *, name: Optional[str], currency: Optional[str], filename: Optional[str]
) -> None:
    """Lustro długości kolumn — 422 po polsku zamiast 500 z bazy (audyt S3)."""
    if name is not None:
        if not name.strip():
            raise HTTPException(422, detail="Podaj nazwę umowy ramowej.")
        if len(name) > 255:
            raise HTTPException(422, detail="Nazwa umowy: najwyżej 255 znaków.")
    if currency is not None and len(currency) > 3:
        raise HTTPException(422, detail="Waluta to trzyliterowy kod, np. PLN albo EUR.")
    if filename is not None and len(filename) > 255:
        raise HTTPException(
            422, detail="Nazwa pliku jest za długa (najwyżej 255 znaków). Skróć ją."
        )


async def _require_legal_docs_reader(
    client_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Odczyt umów ramowych (MSA) = dokumenty prawne klienta."""
    await _assert_client(db, client_id)
    access = await resolve_client_access(db, current_user, client_id)
    if not access.can_view_legal_documents:
        raise deny("umowy ramowe klienta wymagają dostępu prawnego do klienta")
    return current_user


LegalDocsReader = Depends(_require_legal_docs_reader)


def _validate_upload(file: UploadFile) -> None:
    filename = file.filename or "file"
    mime = (file.content_type or "").lower()
    ext_ok = filename.lower().endswith(_ALLOWED_EXT_RE)
    if mime not in _ALLOWED_MIME and not ext_ok:
        raise HTTPException(status_code=415, detail="Tylko pliki PDF/DOCX/DOC")
    if not ext_ok:
        raise HTTPException(
            status_code=415,
            detail="Nazwa pliku musi mieć rozszerzenie .pdf/.docx/.doc",
        )


def _days_to(target: Optional[date]) -> Optional[int]:
    if target is None:
        return None
    return (target - business_today()).days


async def _amendment_counts(db: AsyncSession, fc_ids: list[int]) -> dict[int, int]:
    """Liczba aneksów per umowa — jedno zapytanie dla całej listy (audyt N14)."""
    if not fc_ids:
        return {}
    rows = await db.execute(
        select(ClientContractAmendment.framework_contract_id, func.count())
        .where(ClientContractAmendment.framework_contract_id.in_(fc_ids))
        .group_by(ClientContractAmendment.framework_contract_id)
    )
    return {int(fc_id): int(count) for fc_id, count in rows}


async def _to_read(
    db: AsyncSession,
    fc: ClientFrameworkContract,
    amendments_count: Optional[int] = None,
) -> ClientFrameworkContractRead:
    if amendments_count is None:
        amendments_count = (await _amendment_counts(db, [fc.id])).get(fc.id, 0)
    return ClientFrameworkContractRead(
        id=fc.id,
        client_id=fc.client_id,
        name=fc.name,
        status=fc.status,
        effective_date=fc.effective_date,
        expiry_date=fc.expiry_date,
        signed_via=fc.signed_via,
        currency=fc.currency,
        parent_contract_id=fc.parent_contract_id,
        contract_terms_id=fc.contract_terms_id,
        filename=fc.filename,
        has_file=fc.file_path is not None,
        content_type=fc.content_type,
        size_bytes=fc.size_bytes,
        uploaded_by=fc.uploaded_by,
        uploaded_at=fc.uploaded_at,
        notes=fc.notes,
        source_system=fc.source_system,
        source_key=fc.source_key,
        import_run_id=fc.import_run_id,
        created_at=fc.created_at,
        updated_at=fc.updated_at,
        amendments_count=amendments_count or 0,
        days_to_expiry=_days_to(fc.expiry_date),
    )


# ── List + read ─────────────────────────────────────────────────────────────


@router.get(
    "/{client_id}/framework-contracts",
    response_model=ClientFrameworkContractListResponse,
)
async def list_framework_contracts(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[FrameworkContractStatus] = None,
    _user=LegalDocsReader,
):
    stmt = select(ClientFrameworkContract).where(
        ClientFrameworkContract.client_id == client_id
    )
    if status_filter is not None:
        stmt = stmt.where(ClientFrameworkContract.status == status_filter)
    stmt = stmt.order_by(ClientFrameworkContract.effective_date.desc().nullslast())
    rows = list((await db.execute(stmt)).scalars().all())
    counts = await _amendment_counts(db, [fc.id for fc in rows])
    items = [await _to_read(db, fc, counts.get(fc.id, 0)) for fc in rows]
    return ClientFrameworkContractListResponse(items=items, total=len(items))


@router.get(
    "/{client_id}/framework-contracts/{fc_id}",
    response_model=ClientFrameworkContractRead,
)
async def get_framework_contract(
    client_id: int,
    fc_id: int,
    db: AsyncSession = Depends(get_db),
    _user=LegalDocsReader,
):
    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == fc_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if fc is None:
        raise HTTPException(404, detail="Framework contract not found")
    return await _to_read(db, fc)


# ── Create + update + delete ────────────────────────────────────────────────


@router.post(
    "/{client_id}/framework-contracts",
    response_model=ClientFrameworkContractRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_framework_contract(
    client_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
    file: Optional[UploadFile] = File(None),
    name: str = Form(...),
    contract_status: FrameworkContractStatus = Form(FrameworkContractStatus.draft),
    effective_date: Optional[date] = Form(None),
    expiry_date: Optional[date] = Form(None),
    signed_via: FrameworkContractSignedVia = Form(FrameworkContractSignedVia.upload),
    currency: Optional[str] = Form(None),
    parent_contract_id: Optional[int] = Form(None),
    contract_terms_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
):
    # Zapis tylko na widocznym kliencie (usunięty/scalony/ukryty → 404, S1).
    await assert_client_writable(db, client_id)
    _validate_text_fields(
        name=name,
        currency=currency,
        filename=file.filename if file is not None else None,
    )
    await _validate_references(
        db,
        client_id,
        fc_id=None,
        parent_contract_id=parent_contract_id,
        contract_terms_id=contract_terms_id,
    )
    if (
        effective_date is not None
        and expiry_date is not None
        and expiry_date < effective_date
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expiry_date cannot be earlier than effective_date",
        )

    relative_path = None
    size = None
    content_type = None
    filename = None
    if file is not None:
        _validate_upload(file)
        filename = file.filename
        content_type = file.content_type
        relative_path, size = storage_service.save_client_framework_contract(
            client_id=client_id,
            upload_filename=filename or "msa.pdf",
            source=file.file,
        )
        if size > MAX_UPLOAD_BYTES:
            storage_service.delete_client_framework_contract(relative_path)
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
            )

    fc = ClientFrameworkContract(
        client_id=client_id,
        name=name,
        status=contract_status,
        effective_date=effective_date,
        expiry_date=expiry_date,
        signed_via=signed_via,
        currency=currency,
        parent_contract_id=parent_contract_id,
        contract_terms_id=contract_terms_id,
        filename=filename,
        file_path=relative_path,
        content_type=content_type,
        size_bytes=size,
        uploaded_by=user.id if file is not None else None,
        uploaded_at=datetime.now(timezone.utc) if file is not None else None,
        notes=notes,
    )
    db.add(fc)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="framework_contract_created",
            user_id=user.id,
            details={"name": name, "status": contract_status.value},
        )
    )
    await db.flush()
    await db.refresh(fc)
    await db.commit()
    return await _to_read(db, fc)


@router.patch(
    "/{client_id}/framework-contracts/{fc_id}",
    response_model=ClientFrameworkContractRead,
)
async def update_framework_contract(
    client_id: int,
    fc_id: int,
    payload: ClientFrameworkContractUpdate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await assert_client_writable(db, client_id)
    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == fc_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if fc is None:
        raise HTTPException(404, detail="Framework contract not found")

    data = payload.model_dump(exclude_unset=True)
    await _validate_references(
        db,
        client_id,
        fc_id=fc_id,
        parent_contract_id=data.get("parent_contract_id"),
        contract_terms_id=data.get("contract_terms_id"),
    )
    next_effective_date = data.get("effective_date", fc.effective_date)
    next_expiry_date = data.get("expiry_date", fc.expiry_date)
    if (
        next_effective_date is not None
        and next_expiry_date is not None
        and next_expiry_date < next_effective_date
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expiry_date cannot be earlier than effective_date",
        )
    for field, value in data.items():
        setattr(fc, field, value)

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="framework_contract_updated",
            user_id=user.id,
            details={"fc_id": fc_id, "changed": list(data.keys())},
        )
    )
    await db.commit()
    await db.refresh(fc)
    return await _to_read(db, fc)


async def _draft_delete_blockers(db: AsyncSession, fc_id: int) -> list[str]:
    """Rekordy trzymające umowę ramową kluczem RESTRICT — opis po polsku."""
    blockers: list[str] = []
    order_count = (
        await db.scalar(
            select(func.count())
            .select_from(ClientOrder)
            .where(ClientOrder.framework_contract_id == fc_id)
        )
    ) or 0
    if order_count:
        blockers.append(f"zamówienia: {order_count}")
    executive = list(
        await db.scalars(
            select(ClientExecutiveContract.number)
            .where(ClientExecutiveContract.framework_contract_id == fc_id)
            .order_by(ClientExecutiveContract.number)
        )
    )
    if executive:
        blockers.append("umowy wykonawcze: " + ", ".join(executive))
    return blockers


@router.delete(
    "/{client_id}/framework-contracts/{fc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_framework_contract(
    client_id: int,
    fc_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete: status → `superseded`. Hard delete tylko gdy `draft`.

    Każda próba — wykonana i zablokowana — trafia do Historii zdarzeń.
    """
    async with audited_deletion(
        db,
        actor=user,
        event_type="framework_contract.delete",
        entity_type="agreement",
        entity_id=fc_id,
        client_id=client_id,
    ) as audit:
        await assert_client_writable(db, client_id)
        fc = await db.scalar(
            select(ClientFrameworkContract).where(
                ClientFrameworkContract.id == fc_id,
                ClientFrameworkContract.client_id == client_id,
            )
        )
        if fc is None:
            raise HTTPException(404, detail="Framework contract not found")
        audit.describe(label=fc.name, status=fc.status.value)

        files_to_delete: list[str] = []
        amendment_files: list[str] = []
        if fc.status == FrameworkContractStatus.draft:
            # Zamówienia i umowy wykonawcze trzymają umowę ramową kluczem
            # RESTRICT — do 24.09.2026 plik znikał z dysku, a potem DELETE
            # padał na FK jako 500 i szkic zostawał bez pliku (audyt W3).
            # Odmowa 409 z listą PRZED jakąkolwiek zmianą.
            blockers = await _draft_delete_blockers(db, fc.id)
            if blockers:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "framework_contract_in_use",
                        "message": (
                            "Szkicu nie da się usunąć — wskazują na niego: "
                            + "; ".join(blockers)
                            + ". Odepnij je albo oznacz umowę jako zastąpioną."
                        ),
                        "blockers": blockers,
                    },
                )
            if fc.file_path:
                files_to_delete.append(fc.file_path)
            amendment_files = [
                path
                for path in (
                    await db.scalars(
                        select(ClientContractAmendment.file_path).where(
                            ClientContractAmendment.framework_contract_id == fc.id,
                            ClientContractAmendment.file_path.is_not(None),
                        )
                    )
                )
                if path
            ]
            await db.delete(fc)
            audit.result_note = "Szkic umowy ramowej usunięty trwale."
        else:
            fc.status = FrameworkContractStatus.superseded
            audit.result_note = (
                "Umowa ramowa oznaczona jako zastąpiona — rekord zostaje w historii."
            )

        db.add(
            Activity(
                entity_type="client",
                entity_id=client_id,
                action="framework_contract_deleted",
                user_id=user.id,
                details={"fc_id": fc_id, "hard_delete": fc.status.value == "draft"},
            )
        )
        await db.commit()
    # Pliki kasujemy PO udanym commicie — nieudana transakcja nie może
    # zostawić rekordu bez pliku (audyt W3).
    for path in files_to_delete:
        storage_service.delete_client_framework_contract(path)
    for path in amendment_files:
        storage_service.delete_client_contract_amendment(path)


# ── File upload (replace) + download ────────────────────────────────────────


@router.put(
    "/{client_id}/framework-contracts/{fc_id}/file",
    response_model=ClientFrameworkContractRead,
)
async def replace_framework_contract_file(
    client_id: int,
    fc_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    await assert_client_writable(db, client_id)
    _validate_text_fields(name=None, currency=None, filename=file.filename)
    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == fc_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if fc is None:
        raise HTTPException(404, detail="Framework contract not found")

    _validate_upload(file)
    new_path, size = storage_service.save_client_framework_contract(
        client_id=client_id,
        upload_filename=file.filename or "msa.pdf",
        source=file.file,
    )
    if size > MAX_UPLOAD_BYTES:
        storage_service.delete_client_framework_contract(new_path)
        raise HTTPException(413, detail="File too large")

    old_path = fc.file_path
    fc.filename = file.filename
    fc.file_path = new_path
    fc.content_type = file.content_type
    fc.size_bytes = size
    fc.uploaded_by = user.id
    fc.uploaded_at = datetime.now(timezone.utc)

    await db.commit()
    # Stary plik dopiero po udanym commicie (audyt W3).
    if old_path:
        storage_service.delete_client_framework_contract(old_path)
    await db.refresh(fc)
    return await _to_read(db, fc)


@router.post(
    "/{client_id}/framework-contracts/{fc_id}/send-autenti",
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_framework_contract_to_autenti(
    client_id: int,
    fc_id: int,
    payload: ClientDocSendRequest,
    user: DlAssignedOrAdmin,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Initiate Autenti signing flow for a framework contract.

    Tworzy `DocumentSignature` row, ustawia FC status na `pending_signature`,
    schedules background `send_pdf_to_autenti` (PDF już istnieje na storage).
    """
    from app.services.autenti.client_contracts_sender import (
        prepare_send_framework_contract,
        send_pdf_to_autenti,
    )

    await assert_client_writable(db, client_id)
    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == fc_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if fc is None:
        raise HTTPException(404, detail="Framework contract not found")

    sig = await prepare_send_framework_contract(
        db, framework_contract_id=fc_id, payload=payload, sender_user=user
    )
    background_tasks.add_task(send_pdf_to_autenti, sig.id)
    return {"signature_id": sig.id, "status": sig.status.value}


@router.get("/{client_id}/framework-contracts/{fc_id}/file")
async def download_framework_contract(
    client_id: int,
    fc_id: int,
    db: AsyncSession = Depends(get_db),
    _user=LegalDocsReader,
):
    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == fc_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if fc is None or fc.file_path is None:
        raise HTTPException(404, detail="File not found")
    abs_path = storage_service.get_client_framework_contract_path(fc.file_path)
    return FileResponse(
        path=str(abs_path),
        filename=fc.filename or "msa.pdf",
        media_type=fc.content_type or "application/pdf",
    )
