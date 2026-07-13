"""Public (unauthenticated) signing page endpoints for ``/sign/{token}``.

The consultant opens a tokenized link, downloads the contract PDF, signs it
offline with their own qualified tool, and uploads the signed PAdES here. We
validate it (pyHanko local pre-check + EU DSS authoritative verdict) and, if a
qualified signature is confirmed, attach it and complete the signature row.

Auth = the opaque single-use :class:`SignatureLink` token (unguessable,
expiring). No-info-leak: every invalid/expired/used token → the same 404.
Rate-limited per IP via slowapi. Mounted under ``/api/public``.

Plan: ``docs/in-house-qes-signature-plan.md`` §7, §13.

NOTE: no ``from __future__ import annotations`` here — it turns ``UploadFile``
into a ForwardRef that FastAPI cannot resolve for the multipart ``file`` param.
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.signature_link import SignatureLink
from app.services.security_audit import record_sensitive_read
from app.services.signing.sender import finalize_signed_pdf, render_unsigned_pdf

logger = logging.getLogger(__name__)
router = APIRouter()

_GENERIC_404 = HTTPException(status_code=404, detail="Link nieprawidłowy lub wygasły")

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # mSzafir One Shot cap; comfortable for B2B PDFs


async def _load_valid_link(
    db: AsyncSession, token: str, *, require_unused: bool
) -> SignatureLink:
    """Load a usable link or raise the uniform 404 (no-info-leak)."""
    link = await db.scalar(select(SignatureLink).where(SignatureLink.token == token))
    now = datetime.now(timezone.utc)
    if (
        link is None
        or link.revoked
        or (link.expires_at is not None and link.expires_at < now)
        or (require_unused and link.used_at is not None)
    ):
        raise _GENERIC_404
    return link


async def _load_signature(db: AsyncSession, signature_id: int) -> DocumentSignature:
    sig = await db.scalar(
        select(DocumentSignature)
        .where(DocumentSignature.id == signature_id)
        .options(
            selectinload(DocumentSignature.contract_document),
            selectinload(DocumentSignature.contract),
        )
    )
    if sig is None:
        raise _GENERIC_404
    return sig


@router.get("/sign/{token}")
@limiter.limit("30/minute")
async def get_sign_page(
    token: str,
    request: Request,  # required by slowapi limiter
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Data for the public signing page (no PII beyond signer name)."""
    link = await _load_valid_link(db, token, require_unused=False)
    sig = await _load_signature(db, link.signature_id)
    await record_sensitive_read(
        db,
        user=None,
        entity_type="document_signature",
        entity_id=sig.id,
        action="public_data_viewed",
        details={
            "contract_id": sig.contract_id,
            "party": link.party,
            "access": "public_signing_page",
        },
    )
    return {
        "contract_id": sig.contract_id,
        "signer_name": f"{sig.signer_first_name} {sig.signer_last_name}",
        "signature_type": sig.signature_type,
        "provider": sig.provider,
        "party": link.party,
        "status": sig.status.value,
        "already_signed": sig.status == SignatureStatus.completed
        or link.used_at is not None,
        "expires_at": sig.expires_at.isoformat() if sig.expires_at else None,
    }


@router.get("/sign/{token}/pdf")
@limiter.limit("30/minute")
async def get_unsigned_pdf(
    token: str,
    request: Request,  # required by slowapi limiter
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render + return the unsigned contract PDF for the consultant to sign."""
    link = await _load_valid_link(db, token, require_unused=False)
    sig = await _load_signature(db, link.signature_id)
    try:
        pdf = await asyncio.to_thread(render_unsigned_pdf, sig)
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_unsigned_pdf: render failed sig=%d", sig.id)
        raise HTTPException(
            status_code=500, detail="Nie udało się wygenerować PDF"
        ) from exc
    await record_sensitive_read(
        db,
        user=None,
        entity_type="document_signature",
        entity_id=sig.id,
        action="document_downloaded",
        details={
            "contract_id": sig.contract_id,
            "party": link.party,
            "access": "public_signing_link",
        },
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="umowa_{sig.contract_id}.pdf"'
        },
    )


@router.post("/sign/{token}/submit")
@limiter.limit("5/minute; 30/hour")
async def submit_signed_pdf(
    token: str,
    request: Request,  # required by slowapi limiter
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept the consultant's signed PAdES, validate it, attach + complete."""
    link = await _load_valid_link(db, token, require_unused=True)
    sig = await _load_signature(db, link.signature_id)

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=422, detail="Pusty plik")
    if len(pdf_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Plik za duży (max 20 MB)")
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="To nie jest plik PDF")

    verdict = await finalize_signed_pdf(db, sig, pdf_bytes, moved_by=sig.sender_user_id)

    now = datetime.now(timezone.utc)
    link.used_at = now
    link.use_count = (link.use_count or 0) + 1
    link.last_used_at = now

    await db.commit()
    return verdict
