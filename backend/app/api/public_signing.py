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
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.activity import Activity
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.notification import NotificationType
from app.models.signature_link import SignatureLink
from app.services import storage_service
from app.services.notification_triggers import emit as emit_notification
from app.services.signing.registry import get_provider
from app.services.signing.sender import render_unsigned_pdf

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
        .options(selectinload(DocumentSignature.contract_document))
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

    provider = get_provider(sig.provider)
    report = await provider.validate(pdf_bytes)

    if report.indication == "NO_SIGNATURE":
        raise HTTPException(
            status_code=422, detail="Plik nie zawiera podpisu elektronicznego"
        )
    # If DSS gave an authoritative verdict and it's NOT qualified, reject —
    # an IP-transferring B2B contract needs QES.
    if settings.DSS_VALIDATION_URL and not report.is_qes:
        raise HTTPException(
            status_code=422,
            detail=(
                "Podpis nie jest kwalifikowany (wymagany QES). "
                f"Werdykt walidacji: {report.indication or 'nieokreślony'}"
            ),
        )

    # Persist the signed PDF.
    rel_path, size = storage_service.save_contract_document(
        sig.contract_id, f"signed_umowa_{sig.contract_id}.pdf", BytesIO(pdf_bytes)
    )
    signed_doc = ContractDocument(
        contract_id=sig.contract_id,
        filename=f"signed_umowa_{sig.contract_id}.pdf",
        file_path=rel_path,
        content_type="application/pdf",
        size_bytes=size,
        doc_type=ContractDocumentType.contract,
    )
    db.add(signed_doc)
    await db.flush()

    now = datetime.now(timezone.utc)
    sig.signed_document_id = signed_doc.id
    sig.validation_report = report.as_db_report()
    sig.signature_level = report.signature_level
    sig.status = SignatureStatus.completed
    sig.completed_at = now

    link.used_at = now
    link.use_count = (link.use_count or 0) + 1
    link.last_used_at = now

    db.add(
        Activity(
            entity_type="contract",
            entity_id=sig.contract_id,
            action="signature_signed",
            user_id=sig.sender_user_id,
            external_source="signing",
            details={
                "is_qes": report.is_qes,
                "signature_level": report.signature_level,
                "signed_by": report.signed_by,
            },
        )
    )
    try:
        await emit_notification(
            db,
            user_id=sig.sender_user_id,
            title="Umowa podpisana",
            message=(
                f"Konsultant {sig.signer_first_name} {sig.signer_last_name} "
                f"podpisał umowę kontraktu #{sig.contract_id}."
            ),
            ntype=NotificationType.signature_signed,
            related_entity_type="document_signature",
            related_entity_id=sig.id,
            link=f"/candidates?contract={sig.contract_id}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("submit_signed_pdf: notification emit failed sig=%d", sig.id)

    await db.commit()
    return {
        "status": "ok",
        "is_qes": report.is_qes,
        "signature_level": report.signature_level,
        "signed_by": report.signed_by,
        "indication": report.indication,
        "dss_verified": bool(settings.DSS_VALIDATION_URL),
    }
