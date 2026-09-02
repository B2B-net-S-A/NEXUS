"""In-house QES signing API router (provider-agnostic, drop Autenti).

Mounted under ``/api/signing`` unconditionally; write/IO endpoints call
:func:`_require_enabled` (503 when ``SIGNING_ENABLED=false``), read-only GETs
stay live. The public signing page lives in :mod:`app.api.public_signing`.

Plan: ``docs/in-house-qes-signature-plan.md`` §7.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.contract_access import assert_contract_legal_contract_access
from app.api.deps import CurrentUser, TacPlus, require_roles
from app.api.section_access import ProductSection, require_section_access
from app.core.config import settings
from app.core.database import get_db
from app.models.activity import Activity
from app.models.contract import Contract
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.signature_link import SignatureLink
from app.models.user import User, UserRole
from app.schemas.document_signature import (
    DocumentSignatureDetailResponse,
    DocumentSignatureResponse,
    SignForSignatureRequest,
    SignForSignatureResponse,
)
from app.services.signing.pipeline_hook import STAGE_SENT, move_candidate_for_signing
from app.services.signing.sender import (
    finalize_signed_pdf,
    mint_signature_link,
    prepare_and_send,
    prepare_send,
)

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024

logger = logging.getLogger(__name__)
router = APIRouter()

_DELIVERY_SECTION_DEPENDENCIES = [
    Depends(require_section_access(ProductSection.delivery))
]


ContractSignatureReadUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.finance,
        )
    ),
]


def _require_enabled() -> None:
    if not settings.SIGNING_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="In-house signing is disabled (SIGNING_ENABLED=false)",
        )


@router.post(
    "/contracts/{contract_id}/send-for-signature",
    response_model=SignForSignatureResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=_DELIVERY_SECTION_DEPENDENCIES,
)
async def send_for_signature(
    contract_id: int,
    payload: SignForSignatureRequest,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> SignForSignatureResponse:
    """Create the signature, mint the link, return the shareable URL. 202."""
    _require_enabled()
    await assert_contract_legal_contract_access(
        db, current_user, contract_id, write=True
    )
    sig, sign_url = await prepare_and_send(
        db, contract_id=contract_id, payload=payload, sender_user=current_user
    )
    return SignForSignatureResponse(
        signature_id=sig.id,
        contract_id=sig.contract_id,
        status=sig.status,
        sign_url=sign_url,
    )


@router.post(
    "/contracts/{contract_id}/mark-sent-offline",
    response_model=DocumentSignatureResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_DELIVERY_SECTION_DEPENDENCIES,
)
async def mark_sent_offline(
    contract_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> DocumentSignature:
    """Offline (e-mail) flow: record the contract as sent → 'Umowa wysłana'.

    For recruiters who send the contract by e-mail instead of the public link,
    but still want the pipeline to advance. No /sign link is minted.
    """
    _require_enabled()
    await assert_contract_legal_contract_access(
        db, current_user, contract_id, write=True
    )
    sig = await prepare_send(
        db,
        contract_id=contract_id,
        payload=SignForSignatureRequest(
            provider="upload_validate", signature_type="QES"
        ),
        sender_user=current_user,
    )
    sig.status = SignatureStatus.sent
    sig.sent_at = datetime.now(timezone.utc)
    try:
        contract = await db.get(Contract, contract_id)
        await move_candidate_for_signing(
            db, contract, stage_name=STAGE_SENT, moved_by=current_user.id
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "mark_sent_offline: pipeline move failed contract=%d", contract_id
        )
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="signature_sent",
            user_id=current_user.id,
            external_source="signing",
            details={"channel": "offline_email"},
        )
    )
    await db.commit()
    await db.refresh(sig)
    return sig


@router.post(
    "/contracts/{contract_id}/upload-signed",
    status_code=status.HTTP_201_CREATED,
    dependencies=_DELIVERY_SECTION_DEPENDENCIES,
)
async def upload_signed_offline(
    contract_id: int,
    current_user: TacPlus,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Offline (e-mail) flow: recruiter uploads a signed PDF received by e-mail.

    Validates it (pyHanko, same as the consultant flow), attaches it, completes
    the signature and advances the candidate to 'Umowa podpisana'.
    """
    _require_enabled()
    await assert_contract_legal_contract_access(
        db, current_user, contract_id, write=True
    )
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=422, detail="Pusty plik")
    if len(pdf_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Plik za duży (max 20 MB)")
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="To nie jest plik PDF")

    sig = await prepare_send(
        db,
        contract_id=contract_id,
        payload=SignForSignatureRequest(
            provider="upload_validate", signature_type="QES"
        ),
        sender_user=current_user,
    )
    verdict = await finalize_signed_pdf(db, sig, pdf_bytes, moved_by=current_user.id)
    await db.commit()
    return verdict


@router.get(
    "/contracts/{contract_id}/signatures",
    response_model=list[DocumentSignatureResponse],
    dependencies=_DELIVERY_SECTION_DEPENDENCIES,
)
async def list_signatures(
    contract_id: int,
    current_user: ContractSignatureReadUser,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentSignature]:
    """Most-recent-first signatures for a contract."""
    await assert_contract_legal_contract_access(db, current_user, contract_id)
    result = await db.execute(
        select(DocumentSignature)
        .where(DocumentSignature.contract_id == contract_id)
        .order_by(DocumentSignature.created_at.desc())
    )
    return list(result.scalars().all())


@router.get(
    "/signatures/{signature_id}",
    response_model=DocumentSignatureDetailResponse,
    dependencies=_DELIVERY_SECTION_DEPENDENCIES,
)
async def get_signature(
    signature_id: int,
    current_user: ContractSignatureReadUser,
    db: AsyncSession = Depends(get_db),
) -> DocumentSignature:
    sig = await db.scalar(
        select(DocumentSignature)
        .where(DocumentSignature.id == signature_id)
        .options(selectinload(DocumentSignature.events))
    )
    if sig is None:
        raise HTTPException(status_code=404, detail="Signature not found")
    await assert_contract_legal_contract_access(db, current_user, sig.contract_id)
    return sig


@router.post(
    "/signatures/{signature_id}/withdraw",
    response_model=DocumentSignatureResponse,
    dependencies=_DELIVERY_SECTION_DEPENDENCIES,
)
async def withdraw_signature(
    signature_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> DocumentSignature:
    """Withdraw a pending signature (revokes the public link via expiry)."""
    _require_enabled()
    sig = await db.scalar(
        select(DocumentSignature).where(DocumentSignature.id == signature_id)
    )
    if sig is None:
        raise HTTPException(status_code=404, detail="Signature not found")
    await assert_contract_legal_contract_access(
        db, current_user, sig.contract_id, write=True
    )
    if sig.status not in (SignatureStatus.sent, SignatureStatus.in_progress):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot withdraw signature in status={sig.status.value}",
        )
    sig.status = SignatureStatus.withdrawn
    # Revoke every still-open link for this signature. Setting sig.status alone
    # did NOT stop an already-handed-out link: _load_valid_link only checks
    # link.revoked/expiry/used_at, not sig.status — so a party who received the
    # URL before the withdraw could still submit and complete the signature
    # (M5-P0.2). Revoking flips those links to revoked=True → uniform 404.
    await db.execute(
        update(SignatureLink)
        .where(
            SignatureLink.signature_id == sig.id,
            SignatureLink.used_at.is_(None),
        )
        .values(revoked=True)
    )
    db.add(
        Activity(
            entity_type="contract",
            entity_id=sig.contract_id,
            action="signature_withdrawn",
            user_id=current_user.id,
            external_source="signing",
        )
    )
    await db.commit()
    await db.refresh(sig)
    return sig


@router.post(
    "/signatures/{signature_id}/regenerate-link",
    response_model=dict,
    dependencies=_DELIVERY_SECTION_DEPENDENCIES,
)
async def regenerate_link(
    signature_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mint a fresh single-use link for a still-pending signature."""
    _require_enabled()
    sig = await db.scalar(
        select(DocumentSignature).where(DocumentSignature.id == signature_id)
    )
    if sig is None:
        raise HTTPException(status_code=404, detail="Signature not found")
    await assert_contract_legal_contract_access(
        db, current_user, sig.contract_id, write=True
    )
    if sig.status not in (SignatureStatus.sent, SignatureStatus.in_progress):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot regenerate link for status={sig.status.value}",
        )
    # Revoke prior outstanding links BEFORE minting the replacement, so an old
    # URL cannot coexist with the fresh one (M5-P0.2). The new link is added
    # after this UPDATE, so it stays revoked=False.
    await db.execute(
        update(SignatureLink)
        .where(
            SignatureLink.signature_id == sig.id,
            SignatureLink.used_at.is_(None),
        )
        .values(revoked=True)
    )
    _link, raw_token = mint_signature_link(db, sig)
    await db.commit()
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return {"sign_url": f"{base}/sign/{raw_token}", "expires_at": sig.expires_at}


@router.get("/health")
async def signing_health(current_user: CurrentUser) -> dict:
    """Lightweight probe for the in-house signing rail."""
    return {
        "enabled": settings.SIGNING_ENABLED,
        "provider": settings.SIGNING_PROVIDER,
        "dss_configured": bool(settings.DSS_VALIDATION_URL),
        "now": datetime.now(timezone.utc).isoformat(),
    }
