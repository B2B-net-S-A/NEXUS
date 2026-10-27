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

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cv_generator_b2b import _sniff_image_type
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


class QcSearch(BaseModel):
    """Gdzie QC szukało i czy znalazło (13.10.2026)."""

    source: Literal["cv", "original", "answers", "notes"]
    found: bool
    quote: Optional[str] = None


class QcDismissalInfo(BaseModel):
    """Kto, kiedy i dlaczego oznaczył uwagę jako nieprawdziwą (D5)."""

    id: int
    reason: str
    reason_label: str
    note: Optional[str] = None
    by_name: Optional[str] = None
    at: datetime


class QcItem(BaseModel):
    # Stały klucz pozycji (sprawdzenie | wymaganie | rola) — dla pominięć.
    key: Optional[str] = None
    requirement: Optional[str] = None
    role: Optional[str] = None
    detail: Optional[str] = None
    fix: Optional[str] = None
    term: Optional[str] = None
    role_index: Optional[int] = None
    # Fragment odczytu oryginału, na którym stoi „oryginał ma to w tej roli”.
    evidence: Optional[str] = None
    evidence_kind: Optional[Literal["description", "technologies", "title"]] = None
    searched: list[QcSearch] = []
    # Tylko w `QcCheck.dismissed_items`: pominięcie „To nieprawda”.
    dismissal: Optional[QcDismissalInfo] = None


class QcRoleState(BaseModel):
    requirement: str
    role: str
    state: Literal[
        "described", "missing", "listed_only", "not_in_original", "unverified"
    ]


class QcCheck(BaseModel):
    key: str
    label: str
    severity: Literal["blocking", "warning"]
    status: Literal["pass", "fail", "manual", "skip"]
    summary: str
    items: list[QcItem]
    # „Rola po roli” — przebiegi sprzed 12.10.2026 tego pola nie mają.
    roles: list[QcRoleState] = []
    # Informacje bez zadania (np. technologia tylko na liście roli) — nie
    # liczą się do uwag ani do bramki (13.10.2026).
    info: list[QcItem] = []
    # Pozycje oznaczone „To nieprawda” (D5) — z przywróceniem w oknie.
    dismissed_items: list[QcItem] = []
    # Uwaga wyciszona w „Jakość QC” (D6): widać ją, nie liczy się do uwag.
    muted: bool = False


class QcRun(BaseModel):
    t: str
    b: bool


class QcBlock(BaseModel):
    kind: Literal["h", "p", "li"]
    section: Optional[str] = None
    runs: list[QcRun]
    # Poziom nagłówka (1–4); śródtytuł h3/h4 nie kończy stanowiska.
    level: Optional[int] = None


class QcCv(BaseModel):
    source: Literal["branded_finalized", "branded_draft", "generated", "document"]
    editable: bool
    stage_id: Optional[int] = None
    generated_document_id: Optional[int] = None
    document_id: Optional[int] = None
    filename: Optional[str] = None
    bold_known: bool = True
    updated_at: Optional[datetime] = None
    # Wersja szkicu CV etapu, na której policzono QC (brak dla CV bez szkicu).
    edit_revision: Optional[int] = None
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
    source: Literal["original", "answers", "notes"]
    source_quote: str


class QcFixesResponse(BaseModel):
    status: Literal["ok", "unavailable", "no_cv", "not_editable"]
    cached: bool = False
    fixes: list[QcFix]


class QcApplyRequest(BaseModel):
    action: Literal["ai_fix", "bold_all", "remove_term", "spelling", "role_order"]
    fix_id: Optional[str] = Field(default=None, max_length=40)
    text: Optional[str] = Field(default=None, max_length=1000)
    scope: Optional[Literal["must", "nice"]] = None
    term: Optional[str] = Field(default=None, max_length=120)
    # Wersja szkicu z odpowiedzi QC; inna niż w bazie = 409 `CV_CHANGED`.
    # Opcjonalna: karty otwarte przed tą zmianą jej nie wysyłają.
    expected_revision: Optional[int] = Field(default=None, ge=0)


class QcTransformAction(BaseModel):
    # `years`, `title`, `strip_client_rules`, `remove_line` — tylko edytor CV
    # (panel „Do poprawy”, wariant A, PR 2); okno QC dalej `QcApplyRequest`.
    action: Literal[
        "ai_fix",
        "bold_all",
        "remove_term",
        "spelling",
        "role_order",
        "years",
        "title",
        "strip_client_rules",
        "remove_line",
    ]
    fix_id: Optional[str] = Field(default=None, max_length=40)
    text: Optional[str] = Field(default=None, max_length=1000)
    scope: Optional[Literal["must", "nice"]] = None
    term: Optional[str] = Field(default=None, max_length=120)


class QcTransformRequest(BaseModel):
    """Treść z edytora CV i poprawki do nałożenia na nią (bez zapisu szkicu)."""

    content_html: str = Field(min_length=1, max_length=500000)
    actions: list[QcTransformAction] = Field(min_length=1, max_length=20)
    # „Popraw wszystko”: serwer sam pomija poprawki spoza `cv_qc.BULK_ACTIONS`.
    bulk: bool = False


class QcTransformApplied(BaseModel):
    action: str
    fix_id: Optional[str] = None
    edited: Optional[bool] = None
    scope: Optional[str] = None
    term: Optional[str] = None
    count: Optional[int] = None


class QcTransformSkipped(BaseModel):
    action: str
    code: str
    message: str


class QcTransformResponse(BaseModel):
    content_html: str
    changed: bool
    applied: list[QcTransformApplied]
    skipped: list[QcTransformSkipped]


class QcConfirmRequest(BaseModel):
    """„Potwierdzone z kandydatem”: pozycja z listy QC i opcjonalny opis."""

    term: str = Field(min_length=1, max_length=120)
    text: Optional[str] = Field(default=None, max_length=1000)


class QcDismissRequest(BaseModel):
    """„To nieprawda”: która uwaga (klucz z odpowiedzi QC) i dlaczego."""

    check_key: str = Field(min_length=1, max_length=40)
    key: str = Field(min_length=1, max_length=400)
    reason: Literal[
        "in_cv", "other_name", "wrong_place", "not_needed", "other", "kept_order"
    ]
    note: Optional[str] = Field(default=None, max_length=500)
    quote: Optional[str] = Field(default=None, max_length=300)


class QcOverrideRequest(BaseModel):
    """Powód obejścia: gotowy (`reason_code`) z opcjonalnym opisem albo własny.

    Bez minimum znaków (02.10.2026) — wymuszone 10 znaków dawało wpisy
    w rodzaju „keksekqekndxjndxkqw”. Samo `reason` (front sprzed zmiany)
    działa jak „Inny powód”.
    """

    reason_code: Optional[str] = Field(default=None, max_length=40)
    reason: str = Field(default="", max_length=1000)
    # Blokady oznaczone w oknie „QC się myli” (D4, 17.10.2026) — klucze pozycji
    # z bieżącego przebiegu; serwer bierze tylko te, które QC nadal zgłasza.
    wrong_keys: list[str] = Field(
        default_factory=list, max_length=cv_qc.OVERRIDE_WRONG_MAX
    )

    @model_validator(mode="after")
    def _reason_given(self) -> "QcOverrideRequest":
        self.reason = " ".join(self.reason.split())
        self.wrong_keys = list(
            dict.fromkeys(key.strip()[:400] for key in self.wrong_keys if key.strip())
        )
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
    transient: bool = False,
) -> QcResponse:
    """QC CV firmowego pary (kandydat, rekrutacja) z wiersza etapu.

    Liczy świeżo i zapisuje przebieg (identyczny z poprzednim nie dostaje
    nowego wiersza) — tablica i bramka ruchu czytają ten sam stan.
    `transient=true` liczy bez zapisu: edytor CV odświeża listę po każdym
    autozapisie, a przebieg zapisuje raz, przy zamknięciu.
    """

    stage = await _stage(db, stage_id)
    await ensure_job_read_access(db, current_user, stage.job_id)
    return await _response(
        db,
        request,
        current_user,
        await cv_qc.run_qc(db, stage, user_id=current_user.id, persist=not transient),
    )


@router.get("/stages/{stage_id}/qc/consent-screenshot")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def get_stage_qc_consent_screenshot(
    request: Request,
    stage_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Zrzut zgody RODO przy CV z QC — miniatura przy uwadze `consent_matches`.

    Ta sama bramka co odczyt QC, bez integracji: obraz niesie adres e-mail
    kandydata, a token OAuth dostaje tylko „zgoda jest”. Nie trafia też do
    publicznego linku CV (`zrzut-zgody-rodo-na-koncu-cv-wymog-pko-bp.md`).
    """

    _ensure_person(request)
    stage = await _stage(db, stage_id)
    await ensure_job_read_access(db, current_user, stage.job_id)
    image = await cv_qc.consent_image(db, stage)
    media_type = _sniff_image_type(image) if image else None
    if media_type is None:
        raise HTTPException(status_code=404, detail="To CV nie ma zrzutu zgody.")
    return Response(
        content=image,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
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


@router.post("/stages/{stage_id}/qc/transform", response_model=QcTransformResponse)
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def transform_stage_cv_for_editor(
    request: Request,
    stage_id: int,
    payload: QcTransformRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> QcTransformResponse:
    """Poprawki z panelu „Do poprawy” policzone na treści z edytora CV.

    Niczego nie zapisuje w szkicu: edytor nakłada wynik jednym cofalnym
    krokiem i utrwala go autozapisem. Poprawka, której nie da się nałożyć,
    wraca w `skipped` z powodem (200, nie 422) — przy „Popraw wszystko”
    jedna nieudana nie zatrzymuje pozostałych.
    """

    stage = await _stage(db, stage_id)
    await ensure_job_membership(db, current_user, stage.job_id)
    result = await cv_qc.transform_for_editor(
        db,
        stage,
        payload.content_html,
        [action.model_dump(exclude_none=True) for action in payload.actions],
        bulk=payload.bulk,
        user_id=current_user.id,
    )
    await db.commit()
    return QcTransformResponse(**result)


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
        note=payload.reason,
        wrong_keys=payload.wrong_keys,
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


@router.post("/stages/{stage_id}/qc/dismiss", response_model=QcResponse)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def dismiss_stage_qc_item(
    request: Request,
    stage_id: int,
    payload: QcDismissRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> QcResponse:
    """„To nieprawda” — pomiń uwagę QC dla pary i zwróć świeże QC (D5).

    Uwagę blokującą pomija ten, kto może przesunąć kartę mimo uwag
    (`_can_override`); Delivery Lead dostaje dzwonek. Brak CV i reguł klienta
    nie da się pominąć (422). Integracje — 403.
    """

    from app.services.cv_finding_dismissals import DismissError

    _ensure_person(request)
    stage = await _stage(db, stage_id)
    await ensure_job_membership(db, current_user, stage.job_id)
    try:
        result = await cv_qc.dismiss_finding(
            db,
            stage,
            check_key=payload.check_key,
            key=payload.key,
            reason=payload.reason,
            note=payload.note,
            quote=payload.quote,
            user_id=current_user.id,
            may_dismiss_blocking=await _can_override(
                db, request, current_user, stage.job_id
            ),
        )
    except cv_qc.DismissForbidden as exc:
        raise HTTPException(
            status_code=403,
            detail="Uwagę blokującą pomija osoba, która może przepuścić CV mimo QC.",
        ) from exc
    except DismissError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "CV_QC_DISMISS_FAILED", "message": str(exc)},
        ) from exc
    await db.commit()
    return await _response(db, request, current_user, result)


@router.post(
    "/stages/{stage_id}/qc/dismissals/{dismissal_id}/restore",
    response_model=QcResponse,
)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def restore_stage_qc_item(
    request: Request,
    stage_id: int,
    current_user: RecruiterPlus,
    dismissal_id: int = Path(ge=1, le=9_223_372_036_854_775_807),
    db: AsyncSession = Depends(get_db),
) -> QcResponse:
    """Przywróć pominiętą uwagę QC pary i zwróć świeże QC."""

    from app.services.cv_finding_dismissals import DismissError

    _ensure_person(request)
    stage = await _stage(db, stage_id)
    await ensure_job_membership(db, current_user, stage.job_id)
    try:
        result = await cv_qc.restore_finding(
            db, stage, dismissal_id=dismissal_id, user_id=current_user.id
        )
    except DismissError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "CV_QC_RESTORE_FAILED", "message": str(exc)},
        ) from exc
    await db.commit()
    return await _response(db, request, current_user, result)
