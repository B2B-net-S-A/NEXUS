# UWAGA: bez `from __future__ import annotations` — `@limiter.limit` na
# module z PEP 563 zamienia `Annotated` guardy w parametry query (slowapi #579).
"""Odczyt requestu klienta przed założeniem rekrutacji (strona /jobs/new).

Dwie trasy, obie tylko do odczytu — niczego nie zapisują w bazie poza
telemetrią AI (`ai_feature`). Rekrutację zakłada potem zwykłe `POST /api/jobs`,
a przekazanie do searchu zwykłe `POST /api/jobs/{id}/handoff`, więc ta
powierzchnia nie ma własnych reguł uprawnień do rekrutacji.
"""

import logging
import os
import tempfile
from typing import Annotated, Any, Literal, Optional

import anthropic
from fastapi.concurrency import run_in_threadpool
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DeliveryLeadPlus, get_db
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.ai_feature import AIFeatureKey
from app.models.client import Client
from app.services import job_request_intake as intake
from app.services.ai_quota import AIQuotaExceeded, ai_feature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/job-intake", dependencies=PIPELINE_SECTION_DEPENDENCIES)

MAX_FILE_BYTES = 10 * 1024 * 1024
_ALLOWED_EXTENSIONS = (".docx", ".pdf", ".txt")


class ReadRequestBody(BaseModel):
    client_id: int = Field(..., gt=0)
    text: str = Field(
        ..., min_length=intake.MIN_REQUEST_CHARS, max_length=intake.MAX_REQUEST_CHARS
    )


async def _assert_client(db: AsyncSession, client_id: int) -> None:
    exists = await db.scalar(select(Client.id).where(Client.id == client_id))
    if exists is None:
        raise HTTPException(404, "Nie znaleziono klienta.")


async def _read(db: AsyncSession, user_id: int, client_id: int, text: str) -> dict:
    try:
        async with ai_feature(db, AIFeatureKey.champion_draft, user_id=user_id):
            await db.commit()
            result = await intake.read_request(
                db, client_id=client_id, request_text=text
            )
    except AIQuotaExceeded as exc:
        await db.rollback()
        raise HTTPException(503, {"message": exc.reason}) from exc
    except anthropic.APIError as exc:
        raise HTTPException(
            503, "Model AI chwilowo niedostępny — spróbuj za chwilę."
        ) from exc
    except (ValueError, RuntimeError) as exc:
        logger.warning("job_request_intake: read failed: %s", type(exc).__name__)
        raise HTTPException(
            502,
            "Nie udało się odczytać requestu — spróbuj ponownie albo uzupełnij pola ręcznie.",
        ) from exc
    return result.as_dict()


@router.post("/read")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def read_request(
    request: Request,
    body: ReadRequestBody,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _assert_client(db, body.client_id)
    return {
        "text": body.text,
        "intake": await _read(db, current_user.id, body.client_id, body.text),
    }


@router.post("/read-file")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def read_request_file(
    request: Request,
    current_user: DeliveryLeadPlus,
    client_id: Annotated[int, Form(gt=0)],
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _assert_client(db, client_id)
    name = (file.filename or "").lower()
    if not name.endswith(_ALLOWED_EXTENSIONS):
        raise HTTPException(422, "Obsługiwane pliki: .docx, .pdf, .txt.")
    data = await file.read(MAX_FILE_BYTES + 1)
    if not data:
        raise HTTPException(422, "Plik jest pusty.")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Plik jest za duży (maks. 10 MB).")

    from app.services.cv_text_extractor import extract_text

    suffix = os.path.splitext(name)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            text = await run_in_threadpool(extract_text, tmp.name, name)
        except Exception as exc:  # noqa: BLE001 — każdy błąd odczytu = 422
            raise HTTPException(422, "Nie udało się odczytać tekstu z pliku.") from exc
    text = (text or "").strip()
    if len(text) < intake.MIN_REQUEST_CHARS:
        raise HTTPException(
            422, "W pliku nie ma tekstu do odczytania (skan bez tekstu?)."
        )
    text = text[: intake.MAX_REQUEST_CHARS]
    return {"text": text, "intake": await _read(db, current_user.id, client_id, text)}


class PublicDraftRequest(BaseModel):
    """Pola rekrutacji z ekranu ``/jobs/new`` — przed zapisem rekrutacji."""

    title: str = Field(..., min_length=1, max_length=255)
    client_id: Optional[int] = Field(default=None, gt=0)
    description: Optional[str] = Field(
        default=None, max_length=intake.MAX_REQUEST_CHARS
    )
    must_skills: list[str] = Field(default_factory=list, max_length=40)
    nice_skills: list[str] = Field(default_factory=list, max_length=40)
    location: Optional[str] = Field(default=None, max_length=255)
    remote_policy: Optional[Literal["onsite", "hybrid", "remote"]] = None
    onsite_days_per_week: Optional[int] = Field(default=None, ge=0, le=5)
    champion_profile: Optional[dict[str, Any]] = None


@router.post("/public-draft")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def public_draft(
    request: Request,
    body: PublicDraftRequest,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Szkic ogłoszenia na portale (0381) — tytuł bez klienta, opis, uwagi kontroli.

    Nic nie zapisuje. Publikacja idzie po utworzeniu rekrutacji zwykłą
    ścieżką strony kariery (zapis opisu → zatwierdzenie → link → portal).
    """
    from types import SimpleNamespace

    from app.models.job import RemotePolicy
    from app.services.job_public_profile import (
        PublicDraftUnavailable,
        draft_for_request,
    )

    if body.client_id is not None:
        await _assert_client(db, body.client_id)
    request_job = SimpleNamespace(
        id=None,
        title=body.title,
        client_id=body.client_id,
        description=body.description,
        requirements=None,
        must_skills=[s for s in body.must_skills if s.strip()],
        nice_skills=[s for s in body.nice_skills if s.strip()],
        location=body.location,
        remote_policy=RemotePolicy(body.remote_policy) if body.remote_policy else None,
        onsite_days_per_week=body.onsite_days_per_week,
        seniority=None,
        champion_profile=body.champion_profile or {},
    )
    try:
        return await draft_for_request(db, request_job, user_id=current_user.id)
    except PublicDraftUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
