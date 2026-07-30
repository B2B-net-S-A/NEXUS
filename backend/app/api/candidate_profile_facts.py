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
    CandidateLanguagesPut,
    CandidateLanguagesResponse,
    CandidateProfileRatePatch,
    CandidateProfileRateResponse,
    CandidateRecentRecruitmentsResponse,
)
from app.services import candidate_profile_facts as facts

router = APIRouter()

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
