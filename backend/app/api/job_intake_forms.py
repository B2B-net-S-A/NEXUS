# UWAGA: bez `from __future__ import annotations` — `@limiter.limit` na
# module z PEP 563 zamienia `Annotated` guardy w parametry query (slowapi #579).
"""Niedokończone formularze „Nowa rekrutacja” na koncie autora (0416).

``/api/job-intake/forms`` — lista, odczyt, zapis i usunięcie. Widzi
i zmienia WYŁĄCZNIE autor: cudzy albo nieistniejący formularz = 404, żeby
odpowiedź nie mówiła, czy taki numer istnieje. Bramka ta sama co odczyt maila
klienta na ``/jobs/new`` (``RecruitmentManageUser`` + sekcja Pipeline), bo
formularz to dokładnie ta praca, tylko przerwana.

Treść formularza i maila nie trafia do logów.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.permission_access import RecruitmentManageUser
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.client import Client
from app.models.job_intake_form import JobIntakeForm
from app.services import job_files
from app.services import job_intake_forms as forms
from app.services.job_file_schema import SOURCE_UPLOAD

router = APIRouter(
    prefix="/job-intake/forms", dependencies=PIPELINE_SECTION_DEPENDENCIES
)


class IntakeFormBody(BaseModel):
    label: str = Field("", max_length=255)
    client_id: Optional[int] = Field(None, gt=0)
    # Skąd zaczął się formularz: „text” (wklejony mail), „file” (plik),
    # „manual” (wpisany ręcznie). Pole opisowe — serwer go nie interpretuje.
    source: str = Field("manual", min_length=1, max_length=20, pattern=r"^[a-z_]+$")
    request_text: Optional[str] = Field(None, max_length=forms.MAX_REQUEST_TEXT_CHARS)
    form: dict[str, Any] = Field(default_factory=dict)

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: str) -> str:
        return value.strip()

    @field_validator("form")
    @classmethod
    def _form_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        if forms.form_size_bytes(value) > forms.MAX_FORM_BYTES:
            raise ValueError(
                "Formularz jest za duży do zapisania (najwyżej 200 KB). "
                "Skróć opis albo usuń wklejone załączniki."
            )
        return value


async def _client_name(db: AsyncSession, client_id: Optional[int]) -> Optional[str]:
    if client_id is None:
        return None
    return await db.scalar(select(Client.name).where(Client.id == client_id))


async def _assert_client_exists(db: AsyncSession, client_id: Optional[int]) -> None:
    if client_id is None:
        return
    exists = await db.scalar(select(Client.id).where(Client.id == client_id))
    if exists is None:
        raise HTTPException(422, "Nie znaleziono klienta wybranego w formularzu.")


async def _own_form(db: AsyncSession, user_id: int, form_id: int) -> JobIntakeForm:
    row = await db.scalar(
        select(JobIntakeForm).where(
            JobIntakeForm.id == form_id, JobIntakeForm.user_id == user_id
        )
    )
    if row is None:
        raise HTTPException(404, "Nie znaleziono formularza.")
    return row


@router.get("")
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def list_intake_forms(
    request: Request,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Moje niedokończone formularze, od ostatnio zmienianego."""
    items = await forms.list_forms(db, current_user.id)
    return {
        "items": [
            {
                "id": item.id,
                "label": item.label,
                "client_id": item.client_id,
                "client_name": item.client_name,
                "source": item.source,
                "updated_at": item.updated_at,
                "expires_at": forms.expires_at(item.updated_at),
            }
            for item in items
        ]
    }


@router.get("/{form_id}")
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def get_intake_form(
    request: Request,
    form_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _own_form(db, current_user.id, form_id)
    return {
        "id": row.id,
        "label": row.label,
        "client_id": row.client_id,
        "client_name": await _client_name(db, row.client_id),
        "source": row.source,
        "request_text": row.request_text,
        "form": row.form or {},
        "updated_at": row.updated_at,
    }


@router.post("", status_code=201)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def create_intake_form(
    request: Request,
    body: IntakeFormBody,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client_exists(db, body.client_id)
    await forms.lock_user_forms(db, current_user.id)
    if await forms.count_forms(db, current_user.id) >= forms.MAX_FORMS_PER_USER:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "forms_limit",
                    "message": forms.FORMS_LIMIT_MESSAGE,
                }
            },
        )
    now = datetime.now(timezone.utc)
    row = JobIntakeForm(
        user_id=current_user.id,
        client_id=body.client_id,
        label=body.label,
        source=body.source,
        request_text=body.request_text,
        form=body.form,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    return {"id": row.id, "updated_at": now}


@router.put("/{form_id}")
@limiter.limit("240/minute", key_func=user_or_ip_key)
async def update_intake_form(
    request: Request,
    form_id: int,
    body: IntakeFormBody,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _own_form(db, current_user.id, form_id)
    await _assert_client_exists(db, body.client_id)
    now = datetime.now(timezone.utc)
    row.client_id = body.client_id
    row.label = body.label
    row.source = body.source
    row.request_text = body.request_text
    row.form = body.form
    # Jawnie, nie `onupdate` — wartość wraca w odpowiedzi bez doczytywania.
    row.updated_at = now
    await db.flush()
    return {"id": row.id, "updated_at": now}


@router.delete("/{form_id}", status_code=204)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def delete_intake_form(
    request: Request,
    form_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not await forms.delete_own_form(db, user_id=current_user.id, form_id=form_id):
        raise HTTPException(404, "Nie znaleziono formularza.")
    return Response(status_code=204)


# ── Pliki formularza (0427) ──────────────────────────────────────────────────
#
# Rekrutacja powstaje dopiero przy „Utwórz i przekaż”, więc plik dodany na
# `/jobs/new` wisi na niedokończonym formularzu autora. `POST /api/jobs`
# przepina go na rekrutację (`job_files.attach_intake_files`). Reguły przyjęcia
# pliku i odpowiedź pobrania są wspólne z plikami rekrutacji.


def _file_refused(exc: job_files.JobFileRefused) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


@router.get("/{form_id}/files")
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def list_intake_form_files(
    request: Request,
    form_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _own_form(db, current_user.id, form_id)
    return {
        "items": await job_files.list_files(db, form_id=form_id),
        "max_files": job_files.MAX_FILES,
        "max_file_bytes": job_files.MAX_FILE_BYTES,
    }


@router.post("/{form_id}/files", status_code=201)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def upload_intake_form_file(
    request: Request,
    form_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    source: str = Form(SOURCE_UPLOAD),
) -> dict:
    await _own_form(db, current_user.id, form_id)
    try:
        row = await job_files.add_file(
            db,
            upload=file,
            user_id=current_user.id,
            source=source,
            form_id=form_id,
        )
    except job_files.JobFileRefused as exc:
        raise _file_refused(exc) from exc
    await db.refresh(row)
    return job_files.serialize(row, current_user.name)


@router.get("/{form_id}/files/{file_id}/content")
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def download_intake_form_file(
    request: Request,
    form_id: int,
    file_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
    disposition: Literal["attachment", "inline"] = Query("attachment"),
) -> FileResponse:
    from app.api.job_files import MSG_FILE_MISSING, file_response

    await _own_form(db, current_user.id, form_id)
    row = await job_files.get_file(db, file_id, form_id=form_id)
    if row is None:
        raise HTTPException(404, MSG_FILE_MISSING)
    return file_response(row, disposition)


@router.delete("/{form_id}/files/{file_id}", status_code=204)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def delete_intake_form_file(
    request: Request,
    form_id: int,
    file_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    from app.api.job_files import MSG_FILE_MISSING

    await _own_form(db, current_user.id, form_id)
    row = await job_files.get_file(db, file_id, form_id=form_id)
    if row is None:
        raise HTTPException(404, MSG_FILE_MISSING)
    path = row.file_path
    await db.delete(row)
    # Plik znika PO udanym commicie — nieudana transakcja nie zostawia
    # wiersza bez pliku.
    await db.commit()
    job_files.delete_stored([path])
    return Response(status_code=204)
