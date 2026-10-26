# UWAGA: bez `from __future__ import annotations` — `@limiter.limit` na
# module z PEP 563 zamienia ciało żądania w parametry query (slowapi #579).
"""Formularz CV klienta pary osoba × rekrutacja (0522, PR 2 z 3).

``/api/candidates/stages/{stage_id}/client-form`` — u klienta, który zamiast
CV firmowego przyjmuje własny formularz (``clients.cv_client_document``),
NEXUS wypełnia wzór z Plików rekrutacji danymi z CV, screeningu i notatek:

* ``GET`` — pola wzoru z wartościami, źródłami i brakami,
* ``POST …/fill`` — wypełnienie modelem (wartości wpisane przez rekrutera
  zostają),
* ``PUT`` — poprawki rekrutera,
* ``GET …/docx`` — plik Word w układzie wzoru klienta.

Dostęp jak do CV etapu (``candidate_stage_cv._load_csv_for_stage``): rola
czyta albo pisze dokumenty kandydata, a ``stage_id`` niesie rekrutację, więc
dostęp do pary wymaga dostępu do tej rekrutacji.
"""

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateDocumentAccess, CandidateWriteAccess
from app.api.deps import get_db
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.core.http_headers import content_disposition
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_client_form import CandidateClientForm
from app.models.job import Job
from app.models.job_file import JobFile
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import (
    client_form_fill,
    client_form_render,
    client_form_structure,
    job_files,
)
from app.services.client_form_schema import CLIENT_FORM
from app.services.cv_generator_b2b.standalone_service import (
    collect_screening_notes_text,
)

router = APIRouter()

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MSG_NO_TEMPLATE = (
    "Ta rekrutacja nie ma wzoru formularza — Delivery Lead dodaje go w Plikach "
    "rekrutacji."
)
MSG_NOT_FILLED = "Formularz nie jest jeszcze wypełniony."
MSG_UNKNOWN_FIELD = "Formularz nie ma takiego pola — odśwież okno."
VALUE_MAX = client_form_fill.VALUE_MAX


class ClientFormEdit(BaseModel):
    # id pola → wartość; pusta wartość = pole do uzupełnienia.
    fields: dict[str, str] = Field(default_factory=dict, max_length=500)


async def _pair(
    db: AsyncSession, stage_id: int, user: User, *, write: bool
) -> tuple[Job, Candidate, CandidateStage]:
    row = (
        await db.execute(
            select(CandidateStage, Job, Candidate)
            .join(Job, Job.id == CandidateStage.job_id)
            .join(Candidate, Candidate.id == CandidateStage.candidate_id)
            .where(CandidateStage.id == stage_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Stage nie znaleziony")
    stage, job, candidate = row
    if write:
        await ensure_job_membership(db, user, job.id)
    else:
        await ensure_job_read_access(db, user, job.id)
    return job, candidate, stage


async def _form(
    db: AsyncSession, job_id: int, candidate_id: int
) -> Optional[CandidateClientForm]:
    return await db.scalar(
        select(CandidateClientForm).where(
            CandidateClientForm.job_id == job_id,
            CandidateClientForm.candidate_id == candidate_id,
        )
    )


async def _template(
    db: AsyncSession, job_id: int
) -> tuple[Optional[JobFile], dict[str, Any]]:
    row = await job_files.client_form_of_job(db, job_id)
    if row is None:
        return None, {}
    try:
        return row, await job_files.current_structure(db, row)
    except job_files.JobFileRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _candidate_name(candidate: Candidate) -> str:
    return " ".join(
        part for part in (candidate.name, candidate.lastname) if part
    ).strip()


def _view(
    *,
    client_document: str,
    template: Optional[JobFile],
    structure: dict[str, Any],
    form: Optional[CandidateClientForm],
    template_sha: Optional[str] = None,
    message: Optional[str] = None,
) -> dict[str, Any]:
    values = (form.fields if form else None) or {}
    fields = [
        {
            **item,
            "value": (values.get(item["id"]) or {}).get("value"),
            "source": (values.get(item["id"]) or {}).get("source"),
            "quote": (values.get(item["id"]) or {}).get("quote"),
        }
        for item in structure.get("fields") or []
    ]
    if template is None:
        status = "no_template"
    elif form is None or form.filled_at is None and not values:
        status = "not_filled"
    else:
        status = "filled"
    return {
        "client_document": client_document,
        "status": status,
        "message": message,
        "template": (
            {
                "file_id": template.id,
                "filename": template.filename,
                "summary": client_form_structure.summary(structure),
            }
            if template is not None
            else None
        ),
        "template_changed": bool(
            form is not None
            and template is not None
            and (
                form.job_file_id != template.id
                or (template_sha is not None and form.template_sha256 != template_sha)
            )
        ),
        "fields": fields,
        "extra_rows": (form.extra_rows if form else None) or [],
        "missing": [item["id"] for item in fields if not item["value"]],
        "filled_at": form.filled_at if form else None,
        "updated_at": form.updated_at if form else None,
        "model": form.model if form else None,
    }


@router.get("/candidates/stages/{stage_id}/client-form")
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def get_client_form(
    request: Request,
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    job, candidate, _ = await _pair(db, stage_id, current_user, write=False)
    template, structure = await _template(db, job.id)
    return _view(
        client_document=await job_files.client_document_of_job(db, job.id),
        template=template,
        structure=structure,
        form=await _form(db, job.id, candidate.id),
    )


@router.post("/candidates/stages/{stage_id}/client-form/fill")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def fill_client_form(
    request: Request,
    stage_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Wypełnij formularz modelem. Wartości wpisane przez rekrutera zostają."""
    job, candidate, stage = await _pair(db, stage_id, current_user, write=True)
    template, structure = await _template(db, job.id)
    if template is None:
        raise HTTPException(status_code=409, detail=MSG_NO_TEMPLATE)
    try:
        template_sha = _sha(job_files.read_template(template))
    except job_files.JobFileRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    notes = await collect_screening_notes_text(
        db, candidate_id=candidate.id, stage=stage, job=job
    )
    sources = client_form_fill.Sources(
        cv=candidate.raw_cv_text or "", notes=notes or ""
    )
    # IDs zapamiętane przed modelem: `fill` commituje sesję (licznik AI).
    job_id, candidate_id, template_id = job.id, candidate.id, template.id
    name, user_id = _candidate_name(candidate), current_user.id
    result = await client_form_fill.fill(
        db,
        structure=structure,
        sources=sources,
        candidate_name=name,
        user_id=user_id,
    )
    form = await _form(db, job_id, candidate_id)
    if form is None:
        form = CandidateClientForm(candidate_id=candidate_id, job_id=job_id)
        db.add(form)
    kept = {
        field_id: value
        for field_id, value in (form.fields or {}).items()
        if (value or {}).get("source") == client_form_fill.SOURCE_RECRUITER
    }
    form.fields = {**result["fields"], **kept}
    form.extra_rows = result["extra_rows"]
    form.job_file_id = template_id
    form.template_sha256 = template_sha
    form.model = result["model"]
    form.filled_at = datetime.now(timezone.utc)
    form.filled_by = user_id
    form.updated_by = user_id
    form.missing_count = len(client_form_fill.missing_ids(structure, form.fields))
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="client_form_filled",
            user_id=user_id,
            details={
                "job_id": job_id,
                "file_id": template_id,
                "status": result["status"],
                "missing": form.missing_count,
            },
        )
    )
    await db.flush()
    await db.refresh(form)
    template = await db.get(JobFile, template_id)
    return _view(
        client_document=CLIENT_FORM,
        template=template,
        structure=structure,
        form=form,
        template_sha=template_sha,
        message=result["message"],
    )


@router.put("/candidates/stages/{stage_id}/client-form")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def save_client_form(
    request: Request,
    stage_id: int,
    payload: ClientFormEdit,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Poprawki rekrutera: wartość bez źródła, pusta = pole do uzupełnienia."""
    job, candidate, _ = await _pair(db, stage_id, current_user, write=True)
    template, structure = await _template(db, job.id)
    if template is None:
        raise HTTPException(status_code=409, detail=MSG_NO_TEMPLATE)
    known = {item["id"] for item in structure.get("fields") or []}
    if any(field_id not in known for field_id in payload.fields):
        raise HTTPException(status_code=422, detail=MSG_UNKNOWN_FIELD)
    form = await _form(db, job.id, candidate.id)
    if form is None:
        form = CandidateClientForm(
            candidate_id=candidate.id, job_id=job.id, job_file_id=template.id
        )
        db.add(form)
    fields = dict(form.fields or {})
    changed = 0
    for field_id, raw in payload.fields.items():
        value = client_form_fill._short(raw, VALUE_MAX)
        before = (fields.get(field_id) or {}).get("value")
        if value == before:
            continue
        changed += 1
        if value:
            fields[field_id] = {
                "value": value,
                "source": client_form_fill.SOURCE_RECRUITER,
                "quote": None,
            }
        else:
            fields.pop(field_id, None)
    form.fields = fields
    form.updated_by = current_user.id
    form.missing_count = len(client_form_fill.missing_ids(structure, fields))
    if changed:
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=candidate.id,
                action="client_form_saved",
                user_id=current_user.id,
                details={
                    "job_id": job.id,
                    "changed": changed,
                    "missing": form.missing_count,
                },
            )
        )
    await db.flush()
    await db.refresh(form)
    return _view(
        client_document=await job_files.client_document_of_job(db, job.id),
        template=template,
        structure=structure,
        form=form,
    )


def _download_name(template: JobFile, candidate: Candidate) -> str:
    stem = re.sub(r"\.docx$", "", template.filename, flags=re.IGNORECASE)
    name = _candidate_name(candidate).replace(" ", "_")
    return f"{stem}_{name}.docx" if name else f"{stem}.docx"


@router.get("/candidates/stages/{stage_id}/client-form/docx")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def download_client_form(
    request: Request,
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Plik Word: wzór klienta z wpisanymi wartościami (puste pola zostają puste)."""
    job, candidate, _ = await _pair(db, stage_id, current_user, write=False)
    template, structure = await _template(db, job.id)
    if template is None:
        raise HTTPException(status_code=409, detail=MSG_NO_TEMPLATE)
    form = await _form(db, job.id, candidate.id)
    if form is None or not form.fields:
        raise HTTPException(status_code=409, detail=MSG_NOT_FILLED)
    try:
        content = job_files.read_template(template)
        document = client_form_render.render(
            content, structure, form.fields, form.extra_rows
        )
    except job_files.JobFileRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except client_form_structure.FormRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=document,
        media_type=DOCX_TYPE,
        headers={
            "Content-Disposition": content_disposition(
                _download_name(template, candidate),
                "attachment",
                fallback="formularz.docx",
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
