"""Send a B2B contract for in-house QES signature (provider-agnostic).

Two-step flow mirroring the Autenti sender, but provider-neutral and KIR-free
for the upload-and-validate pas:

1. :func:`prepare_send` — validates contract/candidate/content, creates a
   ``document_signatures`` row in ``status=draft``.
2. :func:`prepare_and_send` — wraps it: mints a single-use
   :class:`SignatureLink`, flips ``draft → sent``, notifies the recruiter, and
   returns the public ``/sign/{token}`` URL synchronously so it can be shared.

The consultant opens the link, downloads the contract PDF, signs it with their
own qualified tool, and uploads the signed PAdES — which the public endpoint
validates (pyHanko + EU DSS). No KIR dependency for this pas.

Plan: ``docs/in-house-qes-signature-plan.md`` §3, §7.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.notification import NotificationType
from app.models.signature_link import SignatureLink
from app.models.user import User
from app.schemas.document_signature import SignForSignatureRequest
from app.services import storage_service
from app.services.notification_triggers import emit as emit_notification
from app.services.signing.pdf_renderer import render_contract_pdf
from app.services.signing.pipeline_hook import (
    STAGE_HIRED,
    STAGE_SENT,
    STAGE_SIGNED,
    move_candidate_for_signing,
)
from app.services.signing.registry import get_provider

logger = logging.getLogger(__name__)


def _require_enabled() -> None:
    if not settings.SIGNING_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="In-house signing is disabled (SIGNING_ENABLED=false)",
        )


def _validate_signer(candidate: Candidate) -> tuple[str, str, str, Optional[str]]:
    """Denormalized signer snapshot from the candidate, or 422 with hint."""
    email = (candidate.email or "").strip()
    first = (candidate.name or "").strip()
    last = (candidate.lastname or "").strip()
    missing = []
    if not email:
        missing.append("candidate.email")
    if not first:
        missing.append("candidate.name")
    if not last:
        missing.append("candidate.lastname")
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Candidate is missing signer fields",
                "missing": missing,
            },
        )
    phone = (candidate.phone or "").strip() or None
    return email, first, last, phone


async def prepare_send(
    db: AsyncSession,
    *,
    contract_id: int,
    payload: SignForSignatureRequest,
    sender_user: User,
) -> DocumentSignature:
    """Validate + persist a new ``document_signatures`` row (status=draft)."""
    _require_enabled()

    contract = await db.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(selectinload(Contract.candidate))
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.status not in (
        ContractStatus.draft,
        ContractStatus.active,
        ContractStatus.ending,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Umowa ma status={contract.status.value}; do podpisu można "
                "wysłać umowę `draft`, `active` lub `ending` (nie `ended`)."
            ),
        )
    if contract.candidate is None:
        raise HTTPException(
            status_code=422, detail="Contract has no candidate attached"
        )

    signer_email, first_name, last_name, signer_phone = _validate_signer(
        contract.candidate
    )

    snapshot = await db.scalar(
        select(ContractDocument)
        .where(
            ContractDocument.contract_id == contract.id,
            ContractDocument.doc_type == "contract",
        )
        .order_by(ContractDocument.created_at.desc())
        .limit(1)
    )
    # Signable content: prefer a finalized snapshot (immutable reviewed HTML),
    # else fall back to the contract's rendered draft HTML (produced by the
    # B2B generator's /generate bridge — prod contracts have no snapshots).
    if snapshot is None and not (contract.draft_content_html or "").strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Umowa nie ma treści do podpisu — wygeneruj ją w Generatorze "
                "Umów B2B (lub sfinalizuj draft), a potem wyślij do podpisu."
            ),
        )

    expires_days = payload.expires_in_days or settings.SIGNING_LINK_EXPIRY_DAYS
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    sig = DocumentSignature(
        contract_id=contract.id,
        contract_document_id=snapshot.id if snapshot else None,
        provider=payload.provider,
        signature_type=payload.signature_type,
        status=SignatureStatus.draft,
        sender_user_id=sender_user.id,
        signer_email=signer_email,
        signer_first_name=first_name,
        signer_last_name=last_name,
        signer_phone=signer_phone,
        expires_at=expires_at,
    )
    db.add(sig)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="signature_initiated",
            user_id=sender_user.id,
            external_source="signing",
            details={
                "provider": payload.provider,
                "signature_type": payload.signature_type,
                "signer_email": signer_email,
            },
        )
    )
    await db.commit()
    await db.refresh(sig)
    return sig


def render_unsigned_pdf(sig: DocumentSignature) -> bytes:
    """Render the contract snapshot HTML → unsigned PDF (sync; to_thread it).

    Reused by the public ``GET /sign/{token}/pdf`` endpoint so the consultant
    can download exactly the document they're about to sign.
    """
    html: Optional[str] = None
    if sig.contract_document_id and sig.contract_document is not None:
        abs_path = storage_service.get_contract_document_path(
            sig.contract_document.file_path
        )
        html = abs_path.read_bytes().decode("utf-8", errors="replace")
    elif sig.contract is not None and sig.contract.draft_content_html:
        html = sig.contract.draft_content_html
    if not html:
        raise RuntimeError(
            f"No signable content for signature {sig.id} "
            "(no snapshot and empty draft_content_html)"
        )
    return render_contract_pdf(html, title=f"Umowa #{sig.contract_id}")


def mint_signature_link(
    db: AsyncSession, sig: DocumentSignature, *, party: str = "consultant"
) -> SignatureLink:
    """Create a single-use signing link tied to ``sig``."""
    purpose = "upload_signed" if sig.provider == "upload_validate" else "qes_signing"
    link = SignatureLink(
        token=secrets.token_urlsafe(36),
        signature_id=sig.id,
        party=party,
        purpose=purpose,
        created_by=sig.sender_user_id,
        expires_at=sig.expires_at
        or (
            datetime.now(timezone.utc)
            + timedelta(days=settings.SIGNING_LINK_EXPIRY_DAYS)
        ),
    )
    db.add(link)
    return link


async def prepare_and_send(
    db: AsyncSession,
    *,
    contract_id: int,
    payload: SignForSignatureRequest,
    sender_user: User,
) -> tuple[DocumentSignature, str]:
    """Validate, create the signature, mint the link, return the shareable URL.

    Synchronous so the recruiter gets the ``/sign/{token}`` link back
    immediately. Flips ``draft → sent`` and notifies the recruiter in-app.
    """
    sig = await prepare_send(
        db, contract_id=contract_id, payload=payload, sender_user=sender_user
    )
    link = mint_signature_link(db, sig)
    sig.status = SignatureStatus.sent
    sig.sent_at = datetime.now(timezone.utc)

    base = settings.PUBLIC_BASE_URL.rstrip("/")
    sign_url = f"{base}/sign/{link.token}"

    db.add(
        Activity(
            entity_type="contract",
            entity_id=sig.contract_id,
            action="signature_sent",
            user_id=sig.sender_user_id,
            external_source="signing",
            details={"provider": sig.provider},
        )
    )
    try:
        await emit_notification(
            db,
            user_id=sig.sender_user_id,
            title="Link do podpisu gotowy",
            message=(
                f"Umowa kontraktu #{sig.contract_id} dla "
                f"{sig.signer_first_name} {sig.signer_last_name}. "
                f"Wyślij konsultantowi link do podpisu: {sign_url}"
            ),
            ntype=NotificationType.signature_sent,
            related_entity_type="document_signature",
            related_entity_id=sig.id,
            link=f"/candidates?contract={sig.contract_id}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("prepare_and_send: notification emit failed sig=%d", sig.id)

    # Advance the candidate to "Umowa wysłana" (best-effort).
    try:
        contract = await db.get(Contract, sig.contract_id)
        await move_candidate_for_signing(
            db, contract, stage_name=STAGE_SENT, moved_by=sender_user.id
        )
    except Exception:  # noqa: BLE001
        logger.exception("prepare_and_send: pipeline move failed sig=%d", sig.id)

    await db.commit()
    await db.refresh(sig)
    logger.info("prepare_and_send: link minted sig=%d", sig.id)
    return sig, sign_url


async def finalize_signed_pdf(
    db: AsyncSession,
    sig: DocumentSignature,
    pdf_bytes: bytes,
    *,
    moved_by: int,
) -> dict[str, Any]:
    """Validate a signed PAdES, attach it, complete the signature, advance pipeline.

    Shared by the public ``/submit`` (consultant web upload) and the recruiter
    ``/upload-signed`` (offline e-mail) endpoints — identical validation +
    storage + completion. Advances the candidate to "Umowa podpisana", or to
    "Zatrudniony" when the PDF is signed by BOTH parties (consultant + our
    company side, i.e. ``>= 2`` approval signatures). Does NOT commit (caller
    owns the transaction). Returns the validation verdict dict for the response.
    """
    provider = get_provider(sig.provider)
    report = await provider.validate(pdf_bytes)

    if report.indication == "NO_SIGNATURE":
        raise HTTPException(
            status_code=422, detail="Plik nie zawiera podpisu elektronicznego"
        )
    if settings.DSS_VALIDATION_URL and not report.is_qes:
        raise HTTPException(
            status_code=422,
            detail=(
                "Podpis nie jest kwalifikowany (wymagany QES). "
                f"Werdykt walidacji: {report.indication or 'nieokreślony'}"
            ),
        )

    # Both parties signed (consultant + our company side) ⇒ the contract is
    # fully executed ⇒ the candidate is hired. Detected via the approval-
    # signature count (>= 2); conservative on an unknown count → "Umowa
    # podpisana" (never falsely promotes to "Zatrudniony"). See
    # ``ValidationReport.both_parties_signed``.
    both_signed = report.both_parties_signed
    target_stage = STAGE_HIRED if both_signed else STAGE_SIGNED

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
                "signature_count": report.signature_count,
                "both_parties_signed": both_signed,
                "pipeline_stage": target_stage,
            },
        )
    )

    # Advance the candidate: "Zatrudniony" if fully executed (both parties),
    # else "Umowa podpisana" (best-effort — a pipeline move must never break
    # signing). The direct CandidateStage insert sets moved_by + stage_def_id,
    # which is what the "U klienta"/placements/KPI read-time queries key off.
    # We deliberately do NOT replicate the normal hired hook's draft-Contract
    # auto-creation (a contract already exists here) nor activate the contract.
    try:
        contract = sig.contract or await db.get(Contract, sig.contract_id)
        await move_candidate_for_signing(
            db, contract, stage_name=target_stage, moved_by=moved_by
        )
    except Exception:  # noqa: BLE001
        logger.exception("finalize_signed_pdf: pipeline move failed sig=%d", sig.id)

    try:
        title = (
            "Umowa podpisana przez obie strony" if both_signed else "Umowa podpisana"
        )
        if both_signed:
            message = (
                f"Umowa kontraktu #{sig.contract_id} dla "
                f"{sig.signer_first_name} {sig.signer_last_name} została podpisana "
                "przez obie strony — kandydat przeszedł na etap „Zatrudniony”."
            )
        else:
            message = (
                f"Umowa kontraktu #{sig.contract_id} dla "
                f"{sig.signer_first_name} {sig.signer_last_name} została podpisana."
            )
        await emit_notification(
            db,
            user_id=sig.sender_user_id,
            title=title,
            message=message,
            ntype=NotificationType.signature_signed,
            related_entity_type="document_signature",
            related_entity_id=sig.id,
            link=f"/candidates?contract={sig.contract_id}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("finalize_signed_pdf: notification emit failed sig=%d", sig.id)

    return {
        "status": "ok",
        "is_qes": report.is_qes,
        "signature_level": report.signature_level,
        "signed_by": report.signed_by,
        "indication": report.indication,
        "dss_verified": bool(settings.DSS_VALIDATION_URL),
        "signature_count": report.signature_count,
        "signers": report.signers,
        "both_parties_signed": both_signed,
        "pipeline_stage": target_stage,
    }
