"""Foldery w zakładce Dokumenty kontraktu (0494, ticket Ani 21.10.2026).

``GET    /api/contracts/{id}/document-folders`` — foldery, nazwa folderu
         „Zamówienia” i podpowiedzi „Poprzednia umowa”.
``POST   /api/contracts/{id}/document-folders`` — nowy folder (opcjonalnie
         od razu z zaznaczonymi plikami).
``PATCH  /api/contracts/{id}/document-folders/orders`` — nazwa „Zamówień”.
``PATCH  /api/contracts/{id}/document-folders/{folder_id}`` — zmiana nazwy.
``DELETE /api/contracts/{id}/document-folders/{folder_id}`` — pliki zostają.
``POST   /api/contracts/{id}/documents/move`` — przeniesienie plików.

Bramki jak dokumenty kontraktu: odczyt = podgląd kwot (pliki niosą stawki),
zapis = „Kontrakty i zamówienia”, a w obu zakres klienta Delivery Leada.
Logika: ``app.services.contract_document_folders``.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import _assert_contract, _assert_contract_document_client_access
from app.api.permission_access import AmountsViewUser, ContractsOrdersEditUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.user import User
from app.services import contract_document_folders as folders_service

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)


class FolderOut(BaseModel):
    id: int
    name: str
    created_at: datetime


class SuggestionOut(BaseModel):
    number: str
    folder_name: str
    folder_id: Optional[int] = None
    document_ids: list[int]


class FoldersOut(BaseModel):
    folders: list[FolderOut]
    orders_folder_name: str
    current_contract_number: Optional[str] = None
    suggestions: list[SuggestionOut]


class FolderCreate(BaseModel):
    name: str = Field(..., max_length=500)
    document_ids: list[int] = Field(default_factory=list, max_length=500)


class FolderRename(BaseModel):
    name: str = Field(..., max_length=500)


class DocumentsMove(BaseModel):
    document_ids: list[int] = Field(..., min_length=1, max_length=500)
    # NULL = „Aktualna umowa (bez folderu)”.
    folder_id: Optional[int] = None


class FolderCreated(BaseModel):
    folder: FolderOut
    moved: int


class MoveResult(BaseModel):
    moved: int


class OrdersFolderOut(BaseModel):
    orders_folder_name: str


class DeleteResult(BaseModel):
    released: int


def _activity(contract_id: int, user: User, action: str, details: dict) -> Activity:
    return Activity(
        entity_type="contract",
        entity_id=contract_id,
        action=action,
        user_id=user.id,
        details=details,
    )


async def _guard(db: AsyncSession, contract_id: int, user: User):
    contract = await _assert_contract(db, contract_id, user)
    await _assert_contract_document_client_access(contract, user, db)
    return contract


@router.get("/{contract_id}/document-folders", response_model=FoldersOut)
async def list_document_folders(
    contract_id: int,
    current_user: AmountsViewUser,
    db: AsyncSession = Depends(get_db),
):
    contract = await _guard(db, contract_id, current_user)
    folders, orders_name = await folders_service.list_folders(db, contract_id)
    current, suggestions = await folders_service.suggestions_for(db, contract, folders)
    return FoldersOut(
        folders=[
            FolderOut(id=f.id, name=f.name, created_at=f.created_at) for f in folders
        ],
        orders_folder_name=orders_name,
        current_contract_number=current,
        suggestions=[
            SuggestionOut(
                number=s.number,
                folder_name=s.folder_name,
                folder_id=s.folder_id,
                document_ids=s.document_ids,
            )
            for s in suggestions
        ],
    )


@router.post(
    "/{contract_id}/document-folders",
    response_model=FolderCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_folder(
    contract_id: int,
    data: FolderCreate,
    current_user: ContractsOrdersEditUser,
    db: AsyncSession = Depends(get_db),
):
    await _guard(db, contract_id, current_user)
    folder, moved = await folders_service.create_folder(
        db,
        contract_id,
        name=data.name,
        user_id=current_user.id,
        document_ids=data.document_ids,
    )
    db.add(
        _activity(
            contract_id,
            current_user,
            "document_folder_created",
            {"folder": folder.name, "moved": moved},
        )
    )
    await db.flush()
    await db.refresh(folder)
    return FolderCreated(
        folder=FolderOut(id=folder.id, name=folder.name, created_at=folder.created_at),
        moved=moved,
    )


# Przed ``/{folder_id}``: „orders” nie jest liczbą, ale kolejność tras
# rozstrzyga dopasowanie jawnie, zamiast liczyć na 422 walidacji.
@router.patch("/{contract_id}/document-folders/orders", response_model=OrdersFolderOut)
async def rename_orders_folder(
    contract_id: int,
    data: FolderRename,
    current_user: ContractsOrdersEditUser,
    db: AsyncSession = Depends(get_db),
):
    await _guard(db, contract_id, current_user)
    name = await folders_service.rename_orders_folder(
        db, contract_id, name=data.name, user_id=current_user.id
    )
    db.add(
        _activity(
            contract_id, current_user, "document_folder_renamed", {"folder": name}
        )
    )
    await db.flush()
    return OrdersFolderOut(orders_folder_name=name)


@router.patch("/{contract_id}/document-folders/{folder_id}", response_model=FolderOut)
async def rename_document_folder(
    contract_id: int,
    folder_id: int,
    data: FolderRename,
    current_user: ContractsOrdersEditUser,
    db: AsyncSession = Depends(get_db),
):
    await _guard(db, contract_id, current_user)
    folder = await folders_service.rename_folder(
        db, contract_id, folder_id, name=data.name
    )
    db.add(
        _activity(
            contract_id,
            current_user,
            "document_folder_renamed",
            {"folder": folder.name},
        )
    )
    await db.flush()
    await db.refresh(folder)
    return FolderOut(id=folder.id, name=folder.name, created_at=folder.created_at)


@router.delete(
    "/{contract_id}/document-folders/{folder_id}", response_model=DeleteResult
)
async def delete_document_folder(
    contract_id: int,
    folder_id: int,
    current_user: ContractsOrdersEditUser,
    db: AsyncSession = Depends(get_db),
):
    await _guard(db, contract_id, current_user)
    folder = await folders_service.get_user_folder(db, contract_id, folder_id)
    name = folder.name
    released = await folders_service.delete_folder(db, contract_id, folder_id)
    db.add(
        _activity(
            contract_id,
            current_user,
            "document_folder_deleted",
            {"folder": name, "released": released},
        )
    )
    await db.flush()
    return DeleteResult(released=released)


@router.post("/{contract_id}/documents/move", response_model=MoveResult)
async def move_contract_documents(
    contract_id: int,
    data: DocumentsMove,
    current_user: ContractsOrdersEditUser,
    db: AsyncSession = Depends(get_db),
):
    await _guard(db, contract_id, current_user)
    target_name = None
    if data.folder_id is not None:
        target_name = (
            await folders_service.get_user_folder(db, contract_id, data.folder_id)
        ).name
    moved = await folders_service.move_documents(
        db, contract_id, document_ids=data.document_ids, folder_id=data.folder_id
    )
    db.add(
        _activity(
            contract_id,
            current_user,
            "documents_moved",
            {"folder": target_name or "Aktualna umowa", "moved": moved},
        )
    )
    await db.flush()
    return MoveResult(moved=moved)
