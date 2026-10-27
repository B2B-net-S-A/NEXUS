"""Sprzedaż → Pliki przy firmie albo szansie.

Prefiks ``/api/sales/files`` (wpięty w ``app/main.py``). Lista i pobranie:
„Sprzedaż: podgląd”; wgranie: „Sprzedaż: edycja”; usuwa autor albo admin.
Plik do 20 MB, tylko typy dokumentów biurowych i obrazów — to załączniki
handlowe (oferty klienta, notatki ze spotkań), nie archiwum.
"""

from datetime import datetime
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.sales_gates import SalesEditUser, SalesViewUser, is_admin
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.models.sales import SalesCompany, SalesFile, SalesOpportunity
from app.models.user import User
from app.services import storage_service

router = APIRouter()

MAX_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".txt",
        ".csv",
        ".png",
        ".jpg",
        ".jpeg",
        ".eml",
        ".msg",
    }
)
NOT_FOUND_DETAIL = "Nie ma takiego pliku."


class FileOut(BaseModel):
    id: int
    filename: str
    content_type: Optional[str]
    size_bytes: Optional[int]
    folder: Optional[str]
    company_id: Optional[int]
    opportunity_id: Optional[int]
    uploaded_by: Optional[str]
    uploaded_by_user_id: Optional[int]
    created_at: datetime


def _extension(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot >= 0 else ""


@router.get("", response_model=list[FileOut])
async def list_files(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    company_id: Optional[int] = None,
    opportunity_id: Optional[int] = None,
) -> list[FileOut]:
    if company_id is None and opportunity_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Podaj firmę albo szansę."
        )
    author = aliased(User)
    query = select(SalesFile, author.name).outerjoin(
        author, author.id == SalesFile.uploaded_by_user_id
    )
    if opportunity_id is not None:
        query = query.where(SalesFile.opportunity_id == opportunity_id)
    else:
        # Karta firmy pokazuje też pliki jej szans — tam handlowcy je wgrywają.
        opportunity_ids = select(SalesOpportunity.id).where(
            SalesOpportunity.company_id == company_id
        )
        query = query.where(
            (SalesFile.company_id == company_id)
            | SalesFile.opportunity_id.in_(opportunity_ids)
        )
    rows = (await db.execute(query.order_by(SalesFile.created_at.desc()))).all()
    return [
        FileOut(
            id=row.SalesFile.id,
            filename=row.SalesFile.filename,
            content_type=row.SalesFile.content_type,
            size_bytes=row.SalesFile.size_bytes,
            folder=row.SalesFile.folder,
            company_id=row.SalesFile.company_id,
            opportunity_id=row.SalesFile.opportunity_id,
            uploaded_by=row.name,
            uploaded_by_user_id=row.SalesFile.uploaded_by_user_id,
            created_at=row.SalesFile.created_at,
        )
        for row in rows
    ]


@router.post("", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    current_user: SalesEditUser,
    file: UploadFile = File(...),
    company_id: Optional[int] = Form(default=None),
    opportunity_id: Optional[int] = Form(default=None),
    folder: Optional[str] = Form(default=None, max_length=120),
    db: AsyncSession = Depends(get_db),
) -> FileOut:
    if (company_id is None) == (opportunity_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Plik dodajesz do firmy albo do szansy.",
        )
    owner_model = SalesOpportunity if opportunity_id is not None else SalesCompany
    owner_id = opportunity_id if opportunity_id is not None else company_id
    if await db.get(owner_model, owner_id) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Nie ma takiej firmy ani szansy."
        )
    name = (file.filename or "").strip() or "plik"
    if _extension(name) not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dozwolone są PDF, dokumenty Office, CSV, TXT, obrazy i maile.",
        )
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Plik może mieć najwyżej 20 MB.",
        )
    if not data:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Plik jest pusty."
        )
    owner = "opportunities" if opportunity_id is not None else "companies"
    path, size = storage_service.save_sales_file(owner, owner_id, name, data)
    row = SalesFile(
        company_id=company_id,
        opportunity_id=opportunity_id,
        filename=name[:255],
        content_type=(file.content_type or None),
        size_bytes=size,
        storage_key=path,
        folder=(folder or "").strip() or None,
        uploaded_by_user_id=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return FileOut(
        id=row.id,
        filename=row.filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        folder=row.folder,
        company_id=row.company_id,
        opportunity_id=row.opportunity_id,
        uploaded_by=current_user.name,
        uploaded_by_user_id=current_user.id,
        created_at=row.created_at,
    )


@router.get("/{file_id}/download")
async def download_file(
    file_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    inline: bool = Query(default=False),
) -> Response:
    row = await db.get(SalesFile, file_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    try:
        data = storage_service.read_sales_file(row.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Pliku nie ma w magazynie (jeszcze nie przeniesiony z Atlasa?).",
        ) from exc
    preview = inline and _extension(row.filename) in (".pdf", ".png", ".jpg", ".jpeg")
    return Response(
        content=data,
        media_type=row.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(
                row.filename, "inline" if preview else "attachment"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await db.get(SalesFile, file_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if row.uploaded_by_user_id != current_user.id and not is_admin(current_user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Plik usuwa osoba, która go dodała, albo administrator.",
        )
    key = row.storage_key
    await db.delete(row)
    await db.commit()
    storage_service.delete_sales_file(key)
