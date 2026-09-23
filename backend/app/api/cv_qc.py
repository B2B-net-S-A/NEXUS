"""Router QC CV — `/api/pipeline/stages/{stage_id}/qc…` (Rekrutacja v5, 0361).

Kontrola jakości CV firmowego przed wysłaniem do klienta zastępuje ręczny
przegląd DZ. Odczyt QC ma każda rola z odczytem rekrutacji; poprawki nakłada
ten, kto może ruszać kartą w pipeline; obejście — Delivery Lead albo admin
z powodem. Logika: `app/services/cv_qc.py`.

Bez ``from __future__ import annotations`` — slowapi #579 (PEP 563 zamienia
guardy `Annotated` w parametry QUERY).
"""

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, RecruiterPlus
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import UserRole
from app.services import cv_qc

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class QcItem(BaseModel):
    requirement: Optional[str] = None
    role: Optional[str] = None
    detail: Optional[str] = None
    fix: Optional[str] = None
    term: Optional[str] = None
    role_index: Optional[int] = None


class QcCheck(BaseModel):
    key: str
    label: str
    severity: Literal["blocking", "warning"]
    status: Literal["pass", "fail", "manual", "skip"]
    summary: str
    items: list[QcItem]


class QcRun(BaseModel):
    t: str
    b: bool


class QcBlock(BaseModel):
    kind: Literal["h", "p", "li"]
    section: Optional[str] = None
    runs: list[QcRun]


class QcCv(BaseModel):
    source: Literal["branded_finalized", "branded_draft", "generated", "document"]
    editable: bool
    stage_id: Optional[int] = None
    generated_document_id: Optional[int] = None
    document_id: Optional[int] = None
    filename: Optional[str] = None
    bold_known: bool = True
    updated_at: Optional[datetime] = None
    blocks: list[QcBlock]


class QcOriginal(BaseModel):
    source: Optional[Literal["snapshot", "profile_text"]] = None
    filename: Optional[str] = None
    text: Optional[str] = None


class QcClientRequest(BaseModel):
    must: list[str]
    nice: list[str]


class QcOverride(BaseModel):
    reason: str
    by_name: Optional[str] = None
    at: datetime


class QcResponse(BaseModel):
    stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: Optional[str] = None
    client_name: Optional[str] = None
    passed: bool
    blocking_failed: int
    warnings_count: int
    override: Optional[QcOverride] = None
    run_id: Optional[int] = None
    computed_at: datetime
    cv: Optional[QcCv] = None
    original_cv: QcOriginal
    client_request: QcClientRequest
    checks: list[QcCheck]


class QcFix(BaseModel):
    id: str
    check_key: str
    requirement: str
    role: str
    role_index: Optional[int] = None
    cv_role_label: Optional[str] = None
    current_text: Optional[str] = None
    proposed_text: str
    source: Literal["original", "notes"]
    source_quote: str


class QcFixesResponse(BaseModel):
    status: Literal["ok", "unavailable", "no_cv", "not_editable"]
    cached: bool = False
    fixes: list[QcFix]


class QcApplyRequest(BaseModel):
    action: Literal["ai_fix", "bold_all", "remove_term", "spelling"]
    fix_id: Optional[str] = Field(default=None, max_length=40)
    text: Optional[str] = Field(default=None, max_length=1000)
    scope: Optional[Literal["must", "nice"]] = None
    term: Optional[str] = Field(default=None, max_length=120)


class QcOverrideRequest(BaseModel):
    reason: str = Field(max_length=1000)

    @field_validator("reason")
    @classmethod
    def _reason_long_enough(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 10:
            raise ValueError("Podaj powód obejścia QC (co najmniej 10 znaków).")
        return value


async def _stage(db: AsyncSession, stage_id: int) -> CandidateStage:
    stage = await db.get(CandidateStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego etapu kandydata.")
    return stage


def _response(result: dict[str, Any]) -> QcResponse:
    return QcResponse(**result)


@router.get("/stages/{stage_id}/qc", response_model=QcResponse)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def get_stage_qc(
    request: Request,
    stage_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> QcResponse:
    """QC CV firmowego pary (kandydat, rekrutacja) z wiersza etapu.

    Liczy świeżo i zapisuje przebieg (identyczny z poprzednim nie dostaje
    nowego wiersza) — tablica i bramka ruchu czytają ten sam stan.
    """

    stage = await _stage(db, stage_id)
    await ensure_job_read_access(db, current_user, stage.job_id)
    return _response(await cv_qc.run_qc(db, stage, user_id=current_user.id))


@router.post("/stages/{stage_id}/qc/fixes", response_model=QcFixesResponse)
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def get_stage_qc_fixes(
    request: Request,
    stage_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> QcFixesResponse:
    """Propozycje zdań GPT-6 Luny dla braków w rolach. Nigdy 5xx.

    POST, bo pierwsze wywołanie dla danej treści płaci za model i zapisuje
    wynik; kolejne z tą samą treścią czytają zapamiętany.
    """

    stage = await _stage(db, stage_id)
    await ensure_job_membership(db, current_user, stage.job_id)
    return QcFixesResponse(
        **await cv_qc.generate_fixes(db, stage, user_id=current_user.id)
    )


@router.post("/stages/{stage_id}/qc/apply", response_model=QcResponse)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def apply_stage_qc_fix(
    request: Request,
    stage_id: int,
    payload: QcApplyRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> QcResponse:
    """Nałóż poprawkę na szkic CV firmowego pary i zwróć świeże QC.

    Zmianę wybiera rekruter; zatwierdzone CV wraca do szkicu jako nowa wersja
    (linki klienta zachowują zatwierdzoną treść). 409 `CV_NOT_EDITABLE` dla
    CV spoza NEXUSA, 422 dla poprawki, której nie da się nałożyć.
    """

    stage = await _stage(db, stage_id)
    await ensure_job_membership(db, current_user, stage.job_id)
    try:
        result = await cv_qc.apply_action(
            db,
            stage,
            payload.model_dump(exclude_none=True),
            user_id=current_user.id,
        )
    except cv_qc.ApplyError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "CV_QC_FIX_FAILED", "message": str(exc)}
        ) from exc
    await db.commit()
    return _response(result)


@router.post("/stages/{stage_id}/qc/override", response_model=QcResponse)
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def override_stage_qc(
    request: Request,
    stage_id: int,
    payload: QcOverrideRequest,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> QcResponse:
    """Przepuść parę mimo QC — tylko Delivery Lead i admin, z powodem."""

    if not current_user.has_any_role(UserRole.admin, UserRole.delivery_lead):
        raise HTTPException(
            status_code=403,
            detail="QC może obejść tylko Delivery Lead albo admin.",
        )
    stage = await _stage(db, stage_id)
    await ensure_job_read_access(db, current_user, stage.job_id)
    result = await cv_qc.record_override(
        db, stage, user_id=current_user.id, reason=payload.reason
    )
    await db.commit()
    return _response(result)
