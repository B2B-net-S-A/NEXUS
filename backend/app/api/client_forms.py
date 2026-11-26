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
* ``GET …/docx`` — plik Word w układzie wzoru klienta (albo plik wgrany
  z dysku, gdy jest),
* ``POST …/upload`` / ``DELETE …/upload`` — wypełniony poza NEXUSEM plik
  pary (0756): idzie do QC i do klienta zamiast wypełnienia z NEXUSA.

Dostęp jak do CV etapu (``candidate_stage_cv._load_csv_for_stage``): rola
czyta albo pisze dokumenty kandydata, a ``stage_id`` niesie rekrutację, więc
dostęp do pary wymaga dostępu do tej rekrutacji.
"""

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateDocumentAccess, CandidateWriteAccess
from app.api.deps import get_db
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.core.http_headers import content_disposition
from app.core.scheduling import business_today
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_client_form import CandidateClientForm
from app.models.client import Client
from app.models.job import Job
from app.models.job_file import JobFile
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import (
    client_form_fill,
    client_form_render,
    client_form_structure,
    job_files,
    storage_service,
)
from app.services import client_form_scale, client_form_years, client_score_structure
from app.services.client_form_schema import CLIENT_FORM, KIND_FORM, KIND_SCORE
from app.services.cv_generator_b2b.standalone_service import (
    collect_screening_notes_text,
)

router = APIRouter()

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# 0525: „form” = formularz CV (Word), „score” = tabela punktowa (Excel).
DocumentKind = Literal["form", "score"]
KIND_QUERY = Query(
    "form", description="form — formularz CV (Word), score — tabela punktowa (Excel)"
)
MSG_NO_TEMPLATE = (
    "Ta rekrutacja nie ma wzoru formularza — Delivery Lead dodaje go w Plikach "
    "rekrutacji."
)
MSG_NOT_FILLED = "Formularz nie jest jeszcze wypełniony."
MSG_UNKNOWN_FIELD = "Formularz nie ma takiego pola — odśwież okno."
VALUE_MAX = client_form_fill.VALUE_MAX
PDF_TYPE = "application/pdf"
# 0756: plik wypełniony poza NEXUSEM — Word albo PDF formularza, Excel tabeli.
UPLOAD_TYPES: dict[str, dict[str, str]] = {
    KIND_FORM: {".docx": DOCX_TYPE, ".pdf": PDF_TYPE},
    KIND_SCORE: {".xlsx": XLSX_TYPE},
}
MSG_UPLOAD_TYPE = {
    KIND_FORM: "Wypełniony formularz wgraj jako plik Word (.docx) albo PDF.",
    KIND_SCORE: "Wypełnioną tabelę punktową wgraj jako plik Excel (.xlsx).",
}
MSG_UPLOAD_MACROS = (
    "Plik z makrami nie przejdzie — zapisz go jako zwykły plik bez makr."
)
MSG_UPLOAD_PDF = "Ten plik nie jest poprawnym PDF-em — zapisz go jeszcze raz."
MSG_NO_UPLOAD = "Ta osoba nie ma wgranego pliku."
MSG_UPLOAD_GONE = "Wgranego pliku nie ma już w magazynie — wgraj go jeszcze raz."


class ClientFormEdit(BaseModel):
    # id pola → wartość; pusta wartość = pole do uzupełnienia.
    fields: dict[str, str] = Field(default_factory=dict, max_length=500)


class ClientFormYearsEdit(BaseModel):
    # id pola lat → klucze stanowisk, które się liczą (reszta zdjęta w siatce).
    roles: dict[str, list[str]] = Field(default_factory=dict, max_length=200)
    # Pola, których braki idą do ściągi screeningu; ``None`` = bez zmiany.
    ask: Optional[list[str]] = Field(default=None, max_length=200)


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
    db: AsyncSession, job_id: int, candidate_id: int, kind: str = KIND_FORM
) -> Optional[CandidateClientForm]:
    return await db.scalar(
        select(CandidateClientForm).where(
            CandidateClientForm.job_id == job_id,
            CandidateClientForm.candidate_id == candidate_id,
            CandidateClientForm.kind == kind,
        )
    )


async def _template(
    db: AsyncSession, job_id: int, kind: str = KIND_FORM
) -> tuple[Optional[JobFile], dict[str, Any]]:
    row = await job_files.client_form_of_job(db, job_id, kind)
    if row is None:
        # Wzór dodany, zanim klient przeszedł na formularz CV (np. CEZ przed
        # 0521), nie został oznaczony przy dodaniu — NEXUS rozpoznaje go teraz.
        row = (await job_files.auto_mark_client_form(db, job_id)).get(kind)
    if row is None:
        return None, {}
    try:
        return row, await job_files.current_structure(db, row)
    except job_files.JobFileRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


async def _scale_rule_on(db: AsyncSession, job_id: int) -> bool:
    """Reguła klienta „doświadczenie = 10/10” w polach skali (0756)."""
    return bool(
        await db.scalar(
            select(Client.client_form_scale_full_on_experience)
            .join(Job, Job.client_id == Client.id)
            .where(Job.id == job_id)
        )
    )


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _candidate_name(candidate: Candidate) -> str:
    return " ".join(
        part for part in (candidate.name, candidate.lastname) if part
    ).strip()


def _points(structure: dict[str, Any], values: dict[str, Any]) -> dict[str, int]:
    """Suma wpisanych punktów tabeli punktowej i maksimum wierszy z punktami."""
    total = 0
    for item in structure.get("fields") or []:
        value = str((values.get(item["id"]) or {}).get("value") or "")
        if item.get("max_points") is not None and value.isdigit():
            total += int(value)
    return {"total": total, "max": client_score_structure.max_points_total(structure)}


def _view(
    *,
    kind: str = KIND_FORM,
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
            # Siatka lat: stanowiska z CV, z których kod policzył wartość.
            "years": (values.get(item["id"]) or {}).get("years"),
        }
        # Druga tabela „Doświadczenia” CEZ bez tytułu dostaje „— tabela 2”.
        for item in client_form_structure.with_table_titles(structure)
    ]
    uploaded = (
        {
            "filename": form.uploaded_filename,
            "content_type": form.uploaded_content_type,
            "size": form.uploaded_size,
            "uploaded_at": form.uploaded_at,
        }
        if form is not None and form.uploaded_file_key
        else None
    )
    # Wolne wiersze wzoru (23.11.2026) nie są brakiem — okno je zwija.
    missing = client_form_fill.missing_ids(structure, values)
    spare = client_form_structure.spare_ids(structure, values)
    if template is None:
        status = "no_template"
    elif form is None or form.filled_at is None and not values:
        status = "not_filled"
    else:
        status = "filled"
    summarize = (
        client_score_structure.summary
        if kind == KIND_SCORE
        else client_form_structure.summary
    )
    return {
        "kind": kind,
        "client_document": client_document,
        "status": status,
        "points": _points(structure, values) if kind == KIND_SCORE else None,
        # 0756: plik wgrany z dysku — gotowy do QC i do klienta niezależnie od pól.
        "uploaded": uploaded,
        "message": message,
        "template": (
            {
                "file_id": template.id,
                "filename": template.filename,
                "summary": summarize(structure),
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
        "missing": missing,
        "spare": [item["id"] for item in fields if item["id"] in spare],
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
    kind: DocumentKind = KIND_QUERY,
) -> dict:
    job, candidate, _ = await _pair(db, stage_id, current_user, write=False)
    template, structure = await _template(db, job.id, kind)
    return _view(
        kind=kind,
        client_document=await job_files.client_document_of_job(db, job.id),
        template=template,
        structure=structure,
        form=await _form(db, job.id, candidate.id, kind),
    )


@router.post("/candidates/stages/{stage_id}/client-form/fill")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def fill_client_form(
    request: Request,
    stage_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
    kind: DocumentKind = KIND_QUERY,
) -> dict:
    """Wypełnij formularz modelem. Wartości wpisane przez rekrutera zostają."""
    job, candidate, stage = await _pair(db, stage_id, current_user, write=True)
    template, structure = await _template(db, job.id, kind)
    if template is None:
        raise HTTPException(status_code=409, detail=MSG_NO_TEMPLATE)
    try:
        template_sha = _sha(job_files.read_template(template))
    except job_files.JobFileRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    notes = await collect_screening_notes_text(
        db, candidate_id=candidate.id, stage=stage, job=job
    )
    # Tabela punktowa liczy punkty według zasad oceny z Plików (zał. 5 CEZ);
    # formularz bierze z nich minimum stażu („ponad minimalne wymagania”).
    rules = await job_files.scoring_rules_text(
        db, job.id, score_legend=kind == KIND_SCORE
    )
    sources = client_form_fill.Sources(
        cv=candidate.raw_cv_text or "", notes=notes or "", rules=rules
    )
    # IDs zapamiętane przed modelem: `fill` commituje sesję (licznik AI).
    job_id, candidate_id, template_id = job.id, candidate.id, template.id
    name, user_id = _candidate_name(candidate), current_user.id
    scale_rule = await _scale_rule_on(db, job_id)
    city = (candidate.city or "").strip()
    result = await client_form_fill.fill(
        db,
        structure=structure,
        sources=sources,
        candidate_name=name,
        user_id=user_id,
        candidate_city=city,
    )
    form = await _form(db, job_id, candidate_id, kind)
    if form is None:
        form = CandidateClientForm(candidate_id=candidate_id, job_id=job_id, kind=kind)
        db.add(form)
    kept = {
        field_id: value
        for field_id, value in (form.fields or {}).items()
        if (value or {}).get("source") == client_form_fill.SOURCE_RECRUITER
    }
    asked = {
        field_id
        for field_id, value in (form.fields or {}).items()
        if ((value or {}).get("years") or {}).get("ask")
    }
    previous = dict(form.fields or {})
    form.fields = {**result["fields"], **kept}
    today = business_today()
    for field_id, entry in list(form.fields.items()):
        # Role zdjęte w siatce zostają zdjęte po „Wypełnij ponownie”.
        if field_id not in kept and (previous.get(field_id) or {}).get("years"):
            form.fields[field_id] = client_form_years.carry_selection(
                previous[field_id], entry, today
            )
    for field_id in asked & set(form.fields):
        years = form.fields[field_id].get("years")
        if years:
            form.fields[field_id] = {
                **form.fields[field_id],
                "years": {**years, "ask": True},
            }
    if scale_rule:
        form.fields = client_form_scale.apply(structure, form.fields, today)
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
                "kind": kind,
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
        kind=kind,
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
    kind: DocumentKind = KIND_QUERY,
) -> dict:
    """Poprawki rekrutera: wartość bez źródła, pusta = pole do uzupełnienia."""
    job, candidate, _ = await _pair(db, stage_id, current_user, write=True)
    template, structure = await _template(db, job.id, kind)
    if template is None:
        raise HTTPException(status_code=409, detail=MSG_NO_TEMPLATE)
    known = {item["id"] for item in structure.get("fields") or []}
    if any(field_id not in known for field_id in payload.fields):
        raise HTTPException(status_code=422, detail=MSG_UNKNOWN_FIELD)
    form = await _form(db, job.id, candidate.id, kind)
    if form is None:
        form = CandidateClientForm(
            candidate_id=candidate.id,
            job_id=job.id,
            job_file_id=template.id,
            kind=kind,
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
        # Siatka lat zostaje przy polu — rekruter może wrócić do wyliczenia.
        years = (fields.get(field_id) or {}).get("years")
        if value:
            fields[field_id] = {
                "value": value,
                "source": client_form_fill.SOURCE_RECRUITER,
                "quote": None,
                **({"years": years} if years else {}),
            }
        elif years:
            fields[field_id] = {
                "value": None,
                "source": None,
                "quote": None,
                "years": years,
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
        kind=kind,
        client_document=await job_files.client_document_of_job(db, job.id),
        template=template,
        structure=structure,
        form=form,
    )


MSG_NOT_YEARS = "To pole nie ma wyliczenia lat — wypełnij formularz ponownie."


@router.put("/candidates/stages/{stage_id}/client-form/years")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def save_client_form_years(
    request: Request,
    stage_id: int,
    payload: ClientFormYearsEdit,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
    kind: DocumentKind = KIND_QUERY,
) -> dict:
    """Siatka lat: które stanowiska się liczą i które braki idą do screeningu.

    Wartość liczy kod z zapisanych stanowisk (``client_form_years.recompute``) —
    przeglądarka nie przysyła liczby lat. Pole, które rekruter wpisał ręcznie,
    po zmianie ról dostaje wyliczenie z powrotem.
    """
    job, candidate, _ = await _pair(db, stage_id, current_user, write=True)
    template, structure = await _template(db, job.id, kind)
    if template is None:
        raise HTTPException(status_code=409, detail=MSG_NO_TEMPLATE)
    form = await _form(db, job.id, candidate.id, kind)
    fields = dict((form.fields if form else None) or {})
    touched = set(payload.roles) | set(payload.ask or [])
    if form is None or any(not (fields.get(f) or {}).get("years") for f in touched):
        raise HTTPException(status_code=422, detail=MSG_NOT_YEARS)
    today = business_today()
    for field_id, keys in payload.roles.items():
        fields[field_id] = client_form_years.recompute(
            fields[field_id], set(keys), today
        )
    if payload.ask is not None:
        wanted = set(payload.ask)
        for field_id, entry in fields.items():
            years = (entry or {}).get("years")
            if years and bool(years.get("ask")) != (field_id in wanted):
                fields[field_id] = {
                    **entry,
                    "years": {**years, "ask": field_id in wanted},
                }
    if await _scale_rule_on(db, job.id):
        fields = client_form_scale.apply(structure, fields, today)
    form.fields = fields
    form.updated_by = current_user.id
    form.missing_count = len(client_form_fill.missing_ids(structure, fields))
    await db.flush()
    await db.refresh(form)
    return _view(
        kind=kind,
        client_document=await job_files.client_document_of_job(db, job.id),
        template=template,
        structure=structure,
        form=form,
    )


def _download_name(
    template: JobFile, candidate: Candidate, extension: Optional[str] = None
) -> str:
    stem, dot, ext = template.filename.rpartition(".")
    stem, ext = (stem, ext.lower()) if dot else (template.filename, "docx")
    ext = extension or ext
    name = _candidate_name(candidate).replace(" ", "_")
    return f"{stem}_{name}.{ext}" if name else f"{stem}.{ext}"


@router.get("/candidates/stages/{stage_id}/client-form/docx")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def download_client_form(
    request: Request,
    stage_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
    kind: DocumentKind = KIND_QUERY,
) -> Response:
    """Plik klienta (Word albo Excel) z wpisanymi wartościami; puste pola zostają puste."""
    job, candidate, _ = await _pair(db, stage_id, current_user, write=False)
    template, structure = await _template(db, job.id, kind)
    if template is None:
        raise HTTPException(status_code=409, detail=MSG_NO_TEMPLATE)
    form = await _form(db, job.id, candidate.id, kind)
    if form is not None and form.uploaded_file_key:
        return _uploaded_response(form, template, candidate)
    if form is None or not form.fields:
        raise HTTPException(status_code=409, detail=MSG_NOT_FILLED)
    try:
        content = job_files.read_template(template)
        document = (
            client_form_render.render_score(content, structure, form.fields)
            if kind == KIND_SCORE
            else client_form_render.render(
                content, structure, form.fields, form.extra_rows
            )
        )
    except job_files.JobFileRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except client_form_structure.FormRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=document,
        media_type=XLSX_TYPE if kind == KIND_SCORE else DOCX_TYPE,
        headers={
            "Content-Disposition": content_disposition(
                _download_name(template, candidate),
                "attachment",
                fallback="tabela.xlsx" if kind == KIND_SCORE else "formularz.docx",
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


# ── 0756: plik wypełniony poza NEXUSEM, wgrany z dysku ─────────────────────
# Rekruterzy wypełniali formularz CEZ w Wordzie i wgrywali go przez „Wgraj CV”,
# więc lądował jako CV kandydata. Wgrany plik należy do pary osoba × rekrutacja:
# pobranie oddaje go zamiast wypełnienia z NEXUSA, a sam wiersz pary liczy się
# w bramce „QC CV” (`client_form_status.missing_before_qc`).


def _extension(filename: str) -> str:
    return filename.rpartition(".")[2].lower() if "." in filename else ""


def _check_upload(kind: str, extension: str, content: bytes) -> None:
    """Kontrola paczki jak przy wzorze: bez makr, z limitem części i rozmiaru."""
    if extension == "pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=422, detail=MSG_UPLOAD_PDF)
        return
    try:
        if kind == KIND_SCORE:
            client_score_structure.open_workbook(content)
        else:
            client_form_structure.open_document(content)
    except client_form_structure.FormRejected as exc:
        macros = str(exc) in (
            client_form_structure.MSG_MACROS,
            client_score_structure.MSG_MACROS,
        )
        raise HTTPException(
            status_code=422, detail=MSG_UPLOAD_MACROS if macros else str(exc)
        ) from exc


def _uploaded_response(
    form: CandidateClientForm, template: JobFile, candidate: Candidate
) -> Response:
    try:
        path = storage_service.get_client_form_file_path(form.uploaded_file_key or "")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=MSG_UPLOAD_GONE) from exc
    extension = _extension(form.uploaded_filename or "")
    return Response(
        content=path.read_bytes(),
        media_type=form.uploaded_content_type or DOCX_TYPE,
        headers={
            "Content-Disposition": content_disposition(
                _download_name(template, candidate, extension or None),
                "attachment",
                fallback=f"formularz.{extension or 'docx'}",
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/candidates/stages/{stage_id}/client-form/upload")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def upload_client_form(
    request: Request,
    stage_id: int,
    current_user: CandidateWriteAccess,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    kind: DocumentKind = KIND_QUERY,
) -> dict:
    """Wgraj wypełniony formularz (Word/PDF) albo tabelę punktową (Excel).

    Tworzy wiersz pary, gdy go nie ma; poprzedni wgrany plik znika z dysku po
    zapisie nowego. Wartości pól wypełnione w NEXUSIE zostają — po usunięciu
    pliku wracają do pobrania.
    """
    job, candidate, _ = await _pair(db, stage_id, current_user, write=True)
    template, structure = await _template(db, job.id, kind)
    if template is None:
        raise HTTPException(status_code=409, detail=MSG_NO_TEMPLATE)
    try:
        name, _ = job_files.checked_name(file.filename)
    except job_files.JobFileRefused as exc:
        raise HTTPException(status_code=415, detail=MSG_UPLOAD_TYPE[kind]) from exc
    extension = _extension(name)
    content_type = UPLOAD_TYPES[kind].get(f".{extension}")
    if content_type is None:
        raise HTTPException(status_code=415, detail=MSG_UPLOAD_TYPE[kind])
    try:
        content = await job_files.read_bounded(file)
    except job_files.JobFileRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    await run_in_threadpool(_check_upload, kind, extension, content)

    form = await _form(db, job.id, candidate.id, kind)
    if form is None:
        form = CandidateClientForm(
            candidate_id=candidate.id,
            job_id=job.id,
            job_file_id=template.id,
            kind=kind,
            fields={},
            extra_rows=[],
            missing_count=len(client_form_fill.missing_ids(structure, {})),
        )
        db.add(form)
    previous_key = form.uploaded_file_key
    key, size = storage_service.save_client_form_file(job.id, name, content)
    form.uploaded_file_key = key
    form.uploaded_filename = name
    form.uploaded_content_type = content_type
    form.uploaded_size = size
    form.uploaded_at = datetime.now(timezone.utc)
    form.uploaded_by = current_user.id
    form.updated_by = current_user.id
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="client_form_uploaded",
            user_id=current_user.id,
            details={
                "job_id": job.id,
                "kind": kind,
                "replaced": previous_key is not None,
            },
        )
    )
    try:
        await db.commit()
    except Exception:
        storage_service.delete_client_form_file(key)
        raise
    if previous_key and previous_key != key:
        storage_service.delete_client_form_file(previous_key)
    await db.refresh(form)
    return _view(
        kind=kind,
        client_document=await job_files.client_document_of_job(db, job.id),
        template=template,
        structure=structure,
        form=form,
    )


@router.delete("/candidates/stages/{stage_id}/client-form/upload")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def delete_uploaded_client_form(
    request: Request,
    stage_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
    kind: DocumentKind = KIND_QUERY,
) -> dict:
    """Usuń wgrany plik. Wiersz założony samym wgraniem znika — para wraca
    do „niewypełniony”, więc bramka „QC CV” znów go wymaga."""
    job, candidate, _ = await _pair(db, stage_id, current_user, write=True)
    template, structure = await _template(db, job.id, kind)
    form = await _form(db, job.id, candidate.id, kind)
    if form is None or not form.uploaded_file_key:
        raise HTTPException(status_code=404, detail=MSG_NO_UPLOAD)
    key = form.uploaded_file_key
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="client_form_upload_deleted",
            user_id=current_user.id,
            details={"job_id": job.id, "kind": kind},
        )
    )
    if form.filled_at is None and not form.fields:
        await db.delete(form)
        form = None
    else:
        form.uploaded_file_key = None
        form.uploaded_filename = None
        form.uploaded_content_type = None
        form.uploaded_size = None
        form.uploaded_at = None
        form.uploaded_by = None
        form.updated_by = current_user.id
    await db.commit()
    storage_service.delete_client_form_file(key)
    if form is not None:
        await db.refresh(form)
    return _view(
        kind=kind,
        client_document=await job_files.client_document_of_job(db, job.id),
        template=template,
        structure=structure,
        form=form,
    )
