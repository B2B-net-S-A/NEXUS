"""In-house QES signing API router (provider-agnostic, drop Autenti).

Mounted under ``/api/signing`` unconditionally; write/IO endpoints call
:func:`_require_enabled` (503 when ``SIGNING_ENABLED=false``), read-only GETs
stay live. The public signing page lives in :mod:`app.api.public_signing`.

Plan: ``docs/in-house-qes-signature-plan.md`` §7.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, TacPlus
from app.core.config import settings
from app.core.database import get_db
from app.models.activity import Activity
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.schemas.document_signature import (
    DocumentSignatureDetailResponse,
    DocumentSignatureResponse,
    SignForSignatureRequest,
)
from app.services.signing.sender import (
    initiate_signing,
    mint_signature_link,
    prepare_send,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_enabled() -> None:
    if not settings.SIGNING_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="In-house signing is disabled (SIGNING_ENABLED=false)",
        )


@router.post(
    "/contracts/{contract_id}/send-for-signature",
    response_model=DocumentSignatureResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_for_signature(
    contract_id: int,
    payload: SignForSignatureRequest,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> DocumentSignature:
    """Create a signature row + schedule link minting. Returns 202."""
    _require_enabled()
    sig = await prepare_send(
        db, contract_id=contract_id, payload=payload, sender_user=current_user
    )
    asyncio.create_task(initiate_signing(sig.id))
    return sig


@router.get(
    "/contracts/{contract_id}/signatures",
    response_model=list[DocumentSignatureResponse],
)
async def list_signatures(
    contract_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentSignature]:
    """Most-recent-first signatures for a contract."""
    result = await db.execute(
        select(DocumentSignature)
        .where(DocumentSignature.contract_id == contract_id)
        .order_by(DocumentSignature.created_at.desc())
    )
    return list(result.scalars().all())


@router.get(
    "/signatures/{signature_id}",
    response_model=DocumentSignatureDetailResponse,
)
async def get_signature(
    signature_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DocumentSignature:
    sig = await db.scalar(
        select(DocumentSignature)
        .where(DocumentSignature.id == signature_id)
        .options(selectinload(DocumentSignature.events))
    )
    if sig is None:
        raise HTTPException(status_code=404, detail="Signature not found")
    return sig


@router.post(
    "/signatures/{signature_id}/withdraw",
    response_model=DocumentSignatureResponse,
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
    if sig.status not in (SignatureStatus.sent, SignatureStatus.in_progress):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot withdraw signature in status={sig.status.value}",
        )
    sig.status = SignatureStatus.withdrawn
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
    if sig.status not in (SignatureStatus.sent, SignatureStatus.in_progress):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot regenerate link for status={sig.status.value}",
        )
    link = mint_signature_link(db, sig)
    await db.commit()
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return {"sign_url": f"{base}/sign/{link.token}", "expires_at": sig.expires_at}


@router.get("/health")
async def signing_health(current_user: CurrentUser) -> dict:
    """Lightweight probe for the in-house signing rail."""
    return {
        "enabled": settings.SIGNING_ENABLED,
        "provider": settings.SIGNING_PROVIDER,
        "dss_configured": bool(settings.DSS_VALIDATION_URL),
        "now": datetime.now(timezone.utc).isoformat(),
    }
