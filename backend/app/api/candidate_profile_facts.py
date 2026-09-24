"""Candidate profile facts: normalized languages, B2B rate and recent work."""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import (
    CandidateProfileFactsReadAccess,
    CandidateProfileFactsWriteAccess,
)
from app.core.database import get_db
from app.schemas.candidate_profile_facts import (
    CandidateCallFactsResponse,
    CandidateCallFactsUpdate,
    CandidateNotesFactApply,
    CandidateNotesFactsResponse,
    CandidateWorkModeResponse,
    CandidateWorkModeUpdate,
    CandidateLanguagesPut,
    CandidateLanguagesResponse,
    CandidateProfileRatePatch,
    CandidateProfileRateResponse,
    CandidateRecentRecruitmentsResponse,
)
from app.services import candidate_audit
from app.services import candidate_profile_facts as facts
from app.services.candidate_notes_facts import (
    NotesFactUnavailable,
    apply_notes_fact,
    build_notes_facts,
    profile_work_mode,
    set_profile_work_mode,
)

from app.api.section_access import SOURCING_SECTION_DEPENDENCIES

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

_ETAG_KINDS: tuple[Literal["languages", "profile-rate"], ...] = (
    "languages",
    "profile-rate",
)


def make_profile_fact_etag(
    kind: Literal["languages", "profile-rate"],
    candidate_id: int,
    version: int,
) -> str:
    if kind not in _ETAG_KINDS:  # pragma: no cover - typing already prevents it
        raise ValueError(f"unsupported profile-fact ETag kind: {kind}")
    return f'"candidate-{kind}-{candidate_id}-v{version}"'


def parse_if_match_version(
    if_match: str | None,
    *,
    kind: Literal["languages", "profile-rate"],
    candidate_id: int,
) -> int:
    if if_match is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "code": "if_match_required",
                "message": "Nagłówek If-Match jest wymagany dla tej operacji.",
            },
        )
    pattern = rf'^"candidate-{re.escape(kind)}-{candidate_id}-v([1-9][0-9]*)"$'
    match = re.fullmatch(pattern, if_match.strip())
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "code": "invalid_if_match",
                "message": "If-Match nie wskazuje bieżącej wersji tego zasobu.",
            },
        )
    return int(match.group(1))


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Candidate not found",
    )


def _version_conflict(
    *,
    kind: Literal["languages", "profile-rate"],
    candidate_id: int,
    current_version: int,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_412_PRECONDITION_FAILED,
        detail={
            "code": "profile_facts_version_conflict",
            "message": "Profil został zmieniony przez innego użytkownika.",
            "current_version": current_version,
            "current_etag": make_profile_fact_etag(
                kind,
                candidate_id,
                current_version,
            ),
        },
    )


def _set_etag(
    response: Response,
    *,
    kind: Literal["languages", "profile-rate"],
    candidate_id: int,
    version: int,
) -> None:
    response.headers["ETag"] = make_profile_fact_etag(kind, candidate_id, version)
    response.headers["Cache-Control"] = "private, no-cache"


@router.get(
    "/{candidate_id}/languages",
    response_model=CandidateLanguagesResponse,
)
async def get_candidate_languages(
    candidate_id: int,
    response: Response,
    current_user: CandidateProfileFactsReadAccess,
    db: AsyncSession = Depends(get_db),
) -> CandidateLanguagesResponse:
    del current_user  # role dependency is the complete read gate
    try:
        candidate, rows = await facts.get_candidate_with_languages(db, candidate_id)
    except facts.CandidateNotFoundError:
        raise _not_found() from None
    _set_etag(
        response,
        kind="languages",
        candidate_id=candidate_id,
        version=candidate.languages_version,
    )
    return CandidateLanguagesResponse(
        candidate_id=candidate_id,
        version=candidate.languages_version,
        languages=rows,
    )


@router.put(
    "/{candidate_id}/languages",
    response_model=CandidateLanguagesResponse,
)
async def put_candidate_languages(
    candidate_id: int,
    payload: CandidateLanguagesPut,
    response: Response,
    current_user: CandidateProfileFactsWriteAccess,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: AsyncSession = Depends(get_db),
) -> CandidateLanguagesResponse:
    expected_version = parse_if_match_version(
        if_match,
        kind="languages",
        candidate_id=candidate_id,
    )
    try:
        candidate, rows = await facts.replace_candidate_languages(
            db,
            candidate_id=candidate_id,
            languages=payload.languages,
            expected_version=expected_version,
            actor_id=current_user.id,
        )
    except facts.CandidateNotFoundError:
        raise _not_found() from None
    except facts.ProfileFactsVersionConflictError as exc:
        raise _version_conflict(
            kind="languages",
            candidate_id=candidate_id,
            current_version=exc.current_version,
        ) from None

    await db.commit()
    _set_etag(
        response,
        kind="languages",
        candidate_id=candidate_id,
        version=candidate.languages_version,
    )
    return CandidateLanguagesResponse(
        candidate_id=candidate_id,
        version=candidate.languages_version,
        languages=rows,
    )


def _profile_rate_response(candidate) -> CandidateProfileRateResponse:  # type: ignore[no-untyped-def]
    from app.services.candidate_profile_rate import canonical_profile_rate_amount

    amount = canonical_profile_rate_amount(
        candidate.expected_rate_hourly,
        candidate.expected_rate_currency,
    )
    return CandidateProfileRateResponse(
        candidate_id=candidate.id,
        amount=amount,
        version=candidate.profile_rate_version,
        updated_at=candidate.profile_rate_updated_at,
    )


@router.get(
    "/{candidate_id}/profile-rate",
    response_model=CandidateProfileRateResponse,
)
async def get_candidate_profile_rate(
    candidate_id: int,
    response: Response,
    current_user: CandidateProfileFactsReadAccess,
    db: AsyncSession = Depends(get_db),
) -> CandidateProfileRateResponse:
    del current_user
    try:
        candidate = await facts.get_candidate_profile_rate(db, candidate_id)
    except facts.CandidateNotFoundError:
        raise _not_found() from None
    _set_etag(
        response,
        kind="profile-rate",
        candidate_id=candidate_id,
        version=candidate.profile_rate_version,
    )
    return _profile_rate_response(candidate)


@router.patch(
    "/{candidate_id}/profile-rate",
    response_model=CandidateProfileRateResponse,
)
async def patch_candidate_profile_rate(
    candidate_id: int,
    payload: CandidateProfileRatePatch,
    response: Response,
    current_user: CandidateProfileFactsWriteAccess,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: AsyncSession = Depends(get_db),
) -> CandidateProfileRateResponse:
    expected_version = parse_if_match_version(
        if_match,
        kind="profile-rate",
        candidate_id=candidate_id,
    )
    try:
        candidate = await facts.update_candidate_profile_rate(
            db,
            candidate_id=candidate_id,
            amount=payload.amount,
            expected_version=expected_version,
            actor_id=current_user.id,
        )
    except facts.CandidateNotFoundError:
        raise _not_found() from None
    except facts.ProfileFactsVersionConflictError as exc:
        raise _version_conflict(
            kind="profile-rate",
            candidate_id=candidate_id,
            current_version=exc.current_version,
        ) from None

    await db.commit()
    _set_etag(
        response,
        kind="profile-rate",
        candidate_id=candidate_id,
        version=candidate.profile_rate_version,
    )
    return _profile_rate_response(candidate)


@router.get(
    "/{candidate_id}/recent-recruitments",
    response_model=CandidateRecentRecruitmentsResponse,
)
async def get_candidate_recent_recruitments(
    candidate_id: int,
    current_user: CandidateProfileFactsReadAccess,
    limit: int = Query(default=5, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
) -> CandidateRecentRecruitmentsResponse:
    try:
        items = await facts.get_recent_recruitments(
            db,
            candidate_id=candidate_id,
            current_user=current_user,
            limit=limit,
        )
    except facts.CandidateNotFoundError:
        raise _not_found() from None
    return CandidateRecentRecruitmentsResponse(
        candidate_id=candidate_id,
        items=items,
    )


# ── Fakty z notatek rekruterów + tryb pracy (22.09.2026) ───────────────────


async def _locked_candidate(db: AsyncSession, candidate_id: int):  # type: ignore[no-untyped-def]
    candidate = await facts.get_candidate_profile_rate(
        db, candidate_id, for_update=True
    )
    return candidate


@router.get(
    "/{candidate_id}/notes-facts",
    response_model=CandidateNotesFactsResponse,
)
async def get_candidate_notes_facts(
    candidate_id: int,
    current_user: CandidateProfileFactsReadAccess,
    db: AsyncSession = Depends(get_db),
) -> CandidateNotesFactsResponse:
    """Co notatki rekruterów mówią o kandydacie (czysty odczyt, bez modelu).

    Ta sama bramka co globalna stawka profilu: widok niesie stawkę z notatek.
    """
    del current_user
    try:
        candidate = await facts.get_candidate_profile_rate(db, candidate_id)
    except facts.CandidateNotFoundError:
        raise _not_found() from None
    return CandidateNotesFactsResponse(**build_notes_facts(candidate))


@router.post(
    "/{candidate_id}/notes-facts/apply",
    response_model=CandidateNotesFactsResponse,
)
async def apply_candidate_notes_fact(
    candidate_id: int,
    payload: CandidateNotesFactApply,
    current_user: CandidateProfileFactsWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CandidateNotesFactsResponse:
    """Zapisz w profilu wartość z notatek — wylicza ją serwer, nie przeglądarka."""
    try:
        candidate = await _locked_candidate(db, candidate_id)
    except facts.CandidateNotFoundError:
        raise _not_found() from None
    if payload.field == "rate":
        if payload.expected_profile_rate_version is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Brak wersji stawki profilu — odśwież profil i spróbuj ponownie.",
            )
        if candidate.profile_rate_version != payload.expected_profile_rate_version:
            raise _version_conflict(
                kind="profile-rate",
                candidate_id=candidate_id,
                current_version=candidate.profile_rate_version,
            )
    try:
        details = apply_notes_fact(candidate, payload.field)
    except NotesFactUnavailable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Notatki nie zawierają już wartości, którą da się zapisać w tym polu.",
        ) from None

    rate_audit = details.pop("rate_audit", None)
    if rate_audit is not None:
        candidate_audit.record_candidate_audit(
            db,
            action=candidate_audit.PROFILE_RATE_CHANGED,
            user_id=current_user.id,
            entity_id=candidate_id,
            details=rate_audit,
        )
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.NOTES_FACT_APPLIED,
        user_id=current_user.id,
        entity_id=candidate_id,
        details=details,
    )
    from app.services.match_score_cache import mark_stale_for_candidate

    await mark_stale_for_candidate(db, candidate_id)
    await db.commit()
    return CandidateNotesFactsResponse(**build_notes_facts(candidate))


@router.patch(
    "/{candidate_id}/work-mode",
    response_model=CandidateWorkModeResponse,
)
async def patch_candidate_work_mode(
    candidate_id: int,
    payload: CandidateWorkModeUpdate,
    current_user: CandidateProfileFactsWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CandidateWorkModeResponse:
    """Tryb pracy i dni w biurze z paska faktów profilu."""
    try:
        candidate = await _locked_candidate(db, candidate_id)
    except facts.CandidateNotFoundError:
        raise _not_found() from None
    change = set_profile_work_mode(
        candidate,
        modes=list(payload.remote_modes),
        max_onsite_days=payload.max_onsite_days_per_week,
    )
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.WORK_MODE_CHANGED,
        user_id=current_user.id,
        entity_id=candidate_id,
        details=change,
    )
    from app.services.match_score_cache import mark_stale_for_candidate

    await mark_stale_for_candidate(db, candidate_id)
    await db.commit()
    current = profile_work_mode(candidate)
    return CandidateWorkModeResponse(
        candidate_id=candidate_id,
        remote_modes=current["modes"],
        max_onsite_days_per_week=current["max_onsite_days"],
    )


# ── Korekta faktów z telefonu praktykanta (audyt 24.09.2026) ───────────────

_CALL_FACT_FIELDS = (
    "b2b_willingness",
    "work_time_preference",
    "accepts_below_min_rate",
    "accepts_more_office_days",
)


def _call_facts_response(candidate) -> CandidateCallFactsResponse:  # type: ignore[no-untyped-def]
    return CandidateCallFactsResponse(
        candidate_id=candidate.id,
        **{field: getattr(candidate, field) for field in _CALL_FACT_FIELDS},
    )


@router.patch(
    "/{candidate_id}/call-facts",
    response_model=CandidateCallFactsResponse,
)
async def patch_candidate_call_facts(
    candidate_id: int,
    payload: CandidateCallFactsUpdate,
    current_user: CandidateProfileFactsWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CandidateCallFactsResponse:
    """Popraw fakty z telefonu praktykanta z paska faktów profilu.

    Do audytu 24.09.2026 zapisywał je wyłącznie ekran praktykanta, więc jeden
    pomyłkowy „Tylko etat” ukrywał kandydata we wszystkich dopasowaniach bez
    drogi powrotu. Ta sama bramka co pozostałe fakty profilu; ślad w
    ``activities`` ze starą i nową wartością każdego zmienionego pola.
    """
    try:
        candidate = await _locked_candidate(db, candidate_id)
    except facts.CandidateNotFoundError:
        raise _not_found() from None
    changes: dict[str, dict[str, object]] = {}
    for field in _CALL_FACT_FIELDS:
        if field not in payload.model_fields_set:
            continue
        old = getattr(candidate, field)
        new = getattr(payload, field)
        if old == new:
            continue
        changes[field] = {"old": old, "new": new}
        setattr(candidate, field, new)
    if changes:
        candidate_audit.record_candidate_audit(
            db,
            action=candidate_audit.CALL_FACTS_CORRECTED,
            user_id=current_user.id,
            entity_id=candidate_id,
            details={"changes": changes},
        )
        from app.services.match_score_cache import mark_stale_for_candidate

        await mark_stale_for_candidate(db, candidate_id)
        await db.commit()
    return _call_facts_response(candidate)
