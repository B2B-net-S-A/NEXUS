"""Router QC CV — `/api/pipeline/stages/{stage_id}/qc…` (Rekrutacja v5, 0361).

Kontrola jakości CV firmowego przed wysłaniem do klienta zastępuje ręczny
przegląd DZ. Odczyt QC ma każda rola z odczytem rekrutacji; poprawki nakłada
ten, kto może ruszać kartą w pipeline; obejście — z powodem, osoba
z uprawnieniem „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta”
(domyślnie Delivery Lead i admin), a w trybie doradczym (`CV_QC_ADVISORY`,
12.10.2026) każdy, kto może przesuwać karty. Logika: `app/services/cv_qc.py`.

Bez ``from __future__ import annotations`` — slowapi #579 (PEP 563 zamienia
guardy `Annotated` w parametry QUERY).
"""

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, RecruiterPlus
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.recruitment_pipeline import CandidateStage
from app.services import cv_qc
from app.services.action_permissions import ProductAction, has_permission
from app.services.candidate_claim import is_integration_request
from app.services.permission_denial import ensure_permission

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class QcItem(BaseModel):
    requirement: Optional[str] = None
    role: Optional[str] = None
    detail: Optional[str] = None
    fix: Optional[str] = None
    term: Optional[str] = None
    role_index: Optional[int] = None
    # Fragment odczytu oryginału, na którym stoi „oryginał ma to w tej roli”.
    evidence: Optional[str] = None
    evidence_kind: Optional[Literal["description", "technologies", "title"]] = None


class QcRoleState(BaseModel):
    requirement: str
    role: str
    state: Literal["described", "missing", "not_in_original", "unverified"]


class QcCheck(BaseModel):
    key: str
    label: str
    severity: Literal["blocking", "warning"]
    status: Literal["pass", "fail", "manual", "skip"]
    summary: str
    items: list[QcItem]
    # „Rola po roli” — przebiegi sprzed 12.10.2026 tego pola nie mają.
    roles: list[QcRoleState] = []


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
    # Umiejętności krytyczne (podzbiór `must`) i skąd pochodzą: wybór Delivery
    # Leada, podpowiedź z historii albo brak (wtedy QC nie blokuje na
    # umiejętnościach).
    critical: list[str] = []
    critical_source: Literal["dl", "suggested", "none"] = "none"


class QcOverride(BaseModel):
    reason: str
    by_name: Optional[str] = None
    at: datetime


class QcConfirmation(BaseModel):
    text: str
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
    # Tryb doradczy i to, czy TA osoba może przesunąć kartę mimo uwag QC.
    advisory: bool = False
    can_override: bool = False
    confirmations: list[QcConfirmation] = []
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


class QcConfirmRequest(BaseModel):
    """„Potwierdzone z kandydatem”: pozycja z listy QC i opcjonalny opis."""

    term: str = Field(min_length=1, max_length=120)
    text: Optional[str] = Field(default=None, max_length=1000)


class QcOverrideRequest(BaseModel):
    """Powód obejścia: gotowy (`reason_code`) z opcjonalnym opisem albo własny.

    Bez minimum znaków (02.10.2026) — wymuszone 10 znaków dawało wpisy
    w rodzaju „keksekqekndxjndxkqw”. Samo `reason` (front sprzed zmiany)
    działa jak „Inny powód”.
    """

    reason_code: Optional[str] = Field(default=None, max_length=40)
    reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _reason_given(self) -> "QcOverrideRequest":
        self.reason = " ".join(self.reason.split())
        if (
            self.reason_code is not None
            and self.reason_code not in cv_qc.OVERRIDE_REASONS
        ):
            raise ValueError("Nieznany powód obejścia QC.")
        if self.reason_code in (None, "other") and not self.reason:
            raise ValueError("Opisz powód obejścia QC.")
        return self


async def _stage(db: AsyncSession, stage_id: int) -> CandidateStage:
    stage = await db.get(CandidateStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego etapu kandydata.")
    return stage


def _ensure_person(request: Request) -> None:
    """Decyzje QC „mimo uwag” i potwierdzenia z rozmowy podejmuje człowiek.

    Token klienta OAuth (scraper, n8n) działa jako konto z rolą operacyjną,
    więc przeszedłby tę samą bramkę co rekruter — a dzwonek do Delivery Leada
    i notatka „potwierdzone z kandydatem” mają sens tylko z prawdziwym autorem.
    """

    if is_integration_request(request):
        raise HTTPException(
            status_code=403,
            detail="Tę decyzję w QC CV podejmuje osoba, nie integracja.",
        )


async def _can_override(
    db: AsyncSession, request: Request, user: Any, job_id: int
) -> bool:
    """Kto może przesunąć kartę mimo uwag QC.

    Zawsze osoba z uprawnieniem wysyłki CV do klienta; w trybie doradczym
    każdy, kto może przesuwać karty tej rekrutacji (ta sama bramka co ruch
    i poprawki — od 23.09.2026 rekrutacje są wspólne dla ról wewnętrznych),
    poza integracjami (`_ensure_person`).
    """

    if has_permission(user, ProductAction.recruitment_manage):
        return True
    if not cv_qc.advisory_mode() or is_integration_request(request):
        return False
    try:
        await ensure_job_membership(db, user, job_id)
    except HTTPException:
        return False
    return True


async def _response(
    db: AsyncSession, request: Request, user: Any, result: dict[str, Any]
) -> QcResponse:
    return QcResponse(
        **result,
        can_override=await _can_override(db, request, user, result["job_id"]),
    )


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
    return await _response(
        db,
        request,
        current_user,
        await cv_qc.run_qc(db, stage, user_id=current_user.id),
    )


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
    return await _response(db, request, current_user, result)


@router.post("/stages/{stage_id}/qc/override", response_model=QcResponse)
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def override_stage_qc(
    request: Request,
    stage_id: int,
    payload: QcOverrideRequest,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> QcResponse:
    """Przepuść parę mimo QC — z powodem.

    Decyzja tego, kto wysyła CV do klienta; w trybie doradczym także osoby,
    która przesuwa kartę — wtedy Delivery Lead dostaje dzwonek i może ją cofnąć.
    """

    reviewer = has_permission(current_user, ProductAction.recruitment_manage)
    if not reviewer:
        # Odmowa pada PRZED odczytem etapu — poza trybem doradczym po nazwie
        # uprawnienia, w nim tylko dla integracji.
        if not cv_qc.advisory_mode():
            ensure_permission(current_user, ProductAction.recruitment_manage)
        _ensure_person(request)
    stage = await _stage(db, stage_id)
    if reviewer:
        await ensure_job_read_access(db, current_user, stage.job_id)
    else:
        await ensure_job_membership(db, current_user, stage.job_id)
    result = await cv_qc.record_override(
        db,
        stage,
        user_id=current_user.id,
        reason=cv_qc.override_reason_text(payload.reason_code, payload.reason),
        reason_code=payload.reason_code,
        notify_reviewers=not reviewer,
    )
    await db.commit()
    return await _response(db, request, current_user, result)


@router.post("/stages/{stage_id}/qc/confirm", response_model=QcResponse)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def confirm_stage_qc_item(
    request: Request,
    stage_id: int,
    payload: QcConfirmRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> QcResponse:
    """„Potwierdzone z kandydatem” — zapisz potwierdzenie pozycji „spoza
    oryginału” jako notatkę pary i zwróć świeże QC.

    422, gdy QC tej pozycji już nie zgłasza (CV albo notatki zmieniły się
    w innym oknie).
    """

    _ensure_person(request)
    stage = await _stage(db, stage_id)
    await ensure_job_membership(db, current_user, stage.job_id)
    try:
        result = await cv_qc.confirm_with_candidate(
            db,
            stage,
            term=payload.term,
            text=payload.text,
            user_id=current_user.id,
        )
    except cv_qc.ApplyError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "CV_QC_CONFIRM_FAILED", "message": str(exc)},
        ) from exc
    await db.commit()
    return await _response(db, request, current_user, result)
