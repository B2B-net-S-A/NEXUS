# UWAGA: bez `from __future__ import annotations` — `@limiter.limit` na
# module z PEP 563 zamienia `Annotated` guardy w parametry query (slowapi #579).
"""Pliki rekrutacji — menu „⋯” → „Pliki” na stronie rekrutacji (0427).

``/api/jobs/{job_id}/files``: lista, pobranie, dodanie i usunięcie. Pliki
widzi każdy, kto czyta Profil Championa tej rekrutacji (każda rola
wewnętrzna); dodaje i usuwa ten, kto ją redaguje (``ensure_job_editor``).
Pliki dodane przy zakładaniu rekrutacji trafiają tu z niedokończonego
formularza (``job_files.attach_intake_files`` w ``POST /api/jobs``).

Reguły przyjęcia pliku i magazyn: ``app/services/job_files.py``.
"""

from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, get_db
from app.api.recruitment_access import (
    ensure_champion_job_reader,
    ensure_job_editor,
    job_edit_level,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.http_headers import content_disposition, safe_document_disposition
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.activity import Activity
from app.models.job import Job
from app.models.job_file import JobFile
from app.models.user import User
from app.services import job_files, storage_service

router = APIRouter(prefix="/jobs", dependencies=PIPELINE_SECTION_DEPENDENCIES)

MSG_FILE_MISSING = "Nie znaleziono pliku."
MSG_FILE_GONE = "Pliku nie ma już w magazynie."


def refused(exc: job_files.JobFileRefused) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def file_response(
    row: JobFile, disposition: Literal["attachment", "inline"]
) -> FileResponse:
    """Plik z dysku. W karcie przeglądarki otwierają się tylko PDF i obrazy —
    reszta zawsze do pobrania (``safe_document_disposition``)."""
    try:
        path = storage_service.get_job_file_path(row.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=MSG_FILE_GONE) from exc
    media_type = row.content_type or "application/octet-stream"
    return FileResponse(
        path=str(path),
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition(
                row.filename,
                safe_document_disposition(media_type, disposition),
                fallback="plik",
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _job(db: AsyncSession, job_id: int) -> Job:
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _readable_job(db: AsyncSession, user: User, job_id: int) -> Job:
    job = await _job(db, job_id)
    await ensure_champion_job_reader(job, user, db)
    return job


@router.get("/{job_id}/files")
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def list_job_files(
    request: Request,
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await _readable_job(db, current_user, job_id)
    return {
        "items": await job_files.list_files(db, job_id=job_id),
        "can_edit": await job_edit_level(db, current_user, job) is not None,
        "max_files": job_files.MAX_FILES,
        "max_file_bytes": job_files.MAX_FILE_BYTES,
    }


@router.get("/{job_id}/files/{file_id}/content")
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def download_job_file(
    request: Request,
    job_id: int,
    file_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    disposition: Literal["attachment", "inline"] = Query("attachment"),
) -> FileResponse:
    await _readable_job(db, current_user, job_id)
    row = await job_files.get_file(db, file_id, job_id=job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=MSG_FILE_MISSING)
    return file_response(row, disposition)


@router.post("/{job_id}/files", status_code=201)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def upload_job_file(
    request: Request,
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
) -> dict:
    job = await _readable_job(db, current_user, job_id)
    await ensure_job_editor(db, current_user, job)
    try:
        row = await job_files.add_file(
            db, upload=file, user_id=current_user.id, job_id=job_id
        )
    except job_files.JobFileRefused as exc:
        raise refused(exc) from exc
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="job_file_added",
            user_id=current_user.id,
            details={"file_id": row.id, "filename": row.filename},
        )
    )
    await db.flush()
    await db.refresh(row)
    return job_files.serialize(row, current_user.name)


@router.delete("/{job_id}/files/{file_id}", status_code=204)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def delete_job_file(
    request: Request,
    job_id: int,
    file_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    job = await _readable_job(db, current_user, job_id)
    await ensure_job_editor(db, current_user, job)
    row = await job_files.get_file(db, file_id, job_id=job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=MSG_FILE_MISSING)
    path = row.file_path
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="job_file_removed",
            user_id=current_user.id,
            details={"file_id": row.id, "filename": row.filename},
        )
    )
    await db.delete(row)
    # Plik znika PO udanym commicie — nieudana transakcja nie zostawia
    # wiersza bez pliku (wzorzec z materiałów klienta, audyt W3).
    await db.commit()
    job_files.delete_stored([path])
    return Response(status_code=204)
