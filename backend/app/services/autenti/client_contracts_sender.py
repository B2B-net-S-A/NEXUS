"""Autenti send dla klient-poziomowych dokumentów (framework contract / amendment).

Różnica vs `sender.py` (kandydackie contracts):
- target = `ClientFrameworkContract` lub `ClientContractAmendment` (nie `Contract`)
- nie ma HTML snapshot — PDF jest uploadowany przez DL/admin bezpośrednio
- signer (kontrahent klienta) podawany przez DL w request body

Flow:
1. ``prepare_and_send_client_doc`` (sync) — waliduje, tworzy
   `DocumentSignature` row z FK = framework / amendment, ustawia source PDF,
   commituje, schedules background.
2. ``send_pdf_to_autenti`` (async background) — czyta PDF z storage, uploaduje
   do Autenti, transition `draft → sending → sent`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.notification import NotificationType
from app.models.user import User
from app.services import storage_service
from app.services.autenti.client import (
    AutentiClient,
    AutentiConfig,
    AutentiError,
)
from app.services.notification_triggers import emit as emit_notification

logger = logging.getLogger(__name__)


class ClientDocSendRequest(BaseModel):
    """Body dla `POST /send-autenti` na framework contract / amendment."""

    signer_email: EmailStr
    signer_first_name: str
    signer_last_name: str
    signer_phone: Optional[str] = None
    signature_type: Literal["SES", "AdES", "QES"] = "SES"
    expires_in_days: Optional[int] = None


def _validate_signer(payload: ClientDocSendRequest) -> None:
    if payload.signature_type == "AdES" and not payload.signer_phone:
        raise HTTPException(
            422,
            detail={
                "message": "AdES requires signer phone for SMS verification",
                "missing": ["signer_phone"],
            },
        )


async def prepare_send_framework_contract(
    db: AsyncSession,
    *,
    framework_contract_id: int,
    payload: ClientDocSendRequest,
    sender_user: User,
) -> DocumentSignature:
    if not settings.AUTENTI_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Autenti integration is disabled (AUTENTI_ENABLED=false)",
        )
    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == framework_contract_id
        )
    )
    if fc is None:
        raise HTTPException(404, detail="Framework contract not found")
    if fc.file_path is None:
        raise HTTPException(
            409,
            detail="Cannot send for signature — upload the PDF first",
        )
    if fc.status not in (
        FrameworkContractStatus.draft,
        FrameworkContractStatus.pending_signature,
    ):
        raise HTTPException(
            409,
            detail=(
                f"Framework contract is in status={fc.status.value}; "
                "only `draft` or `pending_signature` can be sent"
            ),
        )
    _validate_signer(payload)

    expires_at: Optional[datetime] = None
    if payload.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=payload.expires_in_days
        )

    sig = DocumentSignature(
        contract_id=None,
        client_framework_contract_id=fc.id,
        contract_document_id=None,
        autenti_signature_type=payload.signature_type,
        status=SignatureStatus.draft,
        sender_user_id=sender_user.id,
        signer_email=payload.signer_email,
        signer_first_name=payload.signer_first_name,
        signer_last_name=payload.signer_last_name,
        signer_phone=payload.signer_phone,
        expires_at=expires_at,
    )
    db.add(sig)
    fc.status = FrameworkContractStatus.pending_signature

    db.add(
        Activity(
            entity_type="client",
            entity_id=fc.client_id,
            action="framework_contract_signature_initiated",
            user_id=sender_user.id,
            external_source="autenti",
            details={
                "framework_contract_id": fc.id,
                "signature_type": payload.signature_type,
                "signer_email": payload.signer_email,
            },
        )
    )
    await db.flush()
    await db.commit()
    await db.refresh(sig)
    return sig


async def prepare_send_amendment(
    db: AsyncSession,
    *,
    amendment_id: int,
    payload: ClientDocSendRequest,
    sender_user: User,
) -> DocumentSignature:
    if not settings.AUTENTI_ENABLED:
        raise HTTPException(
            503, detail="Autenti integration is disabled (AUTENTI_ENABLED=false)"
        )
    a = await db.scalar(
        select(ClientContractAmendment).where(
            ClientContractAmendment.id == amendment_id
        )
    )
    if a is None:
        raise HTTPException(404, detail="Amendment not found")
    if a.file_path is None:
        raise HTTPException(
            409, detail="Cannot send — upload the amendment PDF first"
        )
    _validate_signer(payload)

    expires_at: Optional[datetime] = None
    if payload.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=payload.expires_in_days
        )

    sig = DocumentSignature(
        contract_id=None,
        client_contract_amendment_id=a.id,
        contract_document_id=None,
        autenti_signature_type=payload.signature_type,
        status=SignatureStatus.draft,
        sender_user_id=sender_user.id,
        signer_email=payload.signer_email,
        signer_first_name=payload.signer_first_name,
        signer_last_name=payload.signer_last_name,
        signer_phone=payload.signer_phone,
        expires_at=expires_at,
    )
    db.add(sig)
    db.add(
        Activity(
            entity_type="client",
            entity_id=a.framework_contract_id,
            action="amendment_signature_initiated",
            user_id=sender_user.id,
            external_source="autenti",
            details={
                "amendment_id": a.id,
                "signature_type": payload.signature_type,
                "signer_email": payload.signer_email,
            },
        )
    )
    await db.flush()
    await db.commit()
    await db.refresh(sig)
    return sig


# ── Background send ────────────────────────────────────────────────────────


def _build_create_payload(*, signature: DocumentSignature, title: str) -> dict:
    """Minimal Autenti payload — single signer SES/AdES/QES."""
    constraints: list[dict] = []
    if signature.autenti_signature_type == "AdES":
        constraints.append({"type": "BIOMETRIC_SMS_CONSTRAINT"})
    elif signature.autenti_signature_type == "QES":
        constraints.append({"type": "QUALIFIED_SIGNATURE_CONSTRAINT"})

    signer_block: dict = {
        "email": signature.signer_email,
        "firstName": signature.signer_first_name,
        "lastName": signature.signer_last_name,
        "constraints": constraints,
    }
    if signature.signer_phone:
        signer_block["phoneNumber"] = signature.signer_phone

    return {
        "title": title,
        "signers": [signer_block],
    }


async def _mark_failed(
    db: AsyncSession, sig: DocumentSignature, err: str
) -> None:
    sig.status = SignatureStatus.failed
    sig.last_error = err[:1000]
    sig.retry_count = (sig.retry_count or 0) + 1

    if sig.client_framework_contract_id:
        fc = await db.scalar(
            select(ClientFrameworkContract).where(
                ClientFrameworkContract.id == sig.client_framework_contract_id
            )
        )
        # Cofnij status z pending_signature → draft
        if fc and fc.status == FrameworkContractStatus.pending_signature:
            fc.status = FrameworkContractStatus.draft

    db.add(
        Activity(
            entity_type="document_signature",
            entity_id=sig.id,
            action="signature_send_failed",
            user_id=sig.sender_user_id,
            external_source="autenti",
            details={"error": err[:500]},
        )
    )
    await emit_notification(
        db,
        user_id=sig.sender_user_id,
        title="Wysyłka do Autenti nie powiodła się",
        message=err[:500],
        ntype=NotificationType.signature_failed,
        related_entity_type="document_signature",
        related_entity_id=sig.id,
    )
    await db.commit()


async def send_pdf_to_autenti(signature_id: int) -> None:
    """Background task: PDF już istnieje → upload do Autenti → send.

    W przeciwieństwie do `send_to_autenti` (kandydackie contracts) tutaj nie
    renderujemy HTML→PDF — PDF został wgrany przez DL/admin bezpośrednio.
    """
    async with AsyncSessionLocal() as db:
        sig = await db.scalar(
            select(DocumentSignature).where(DocumentSignature.id == signature_id)
        )
        if sig is None:
            logger.error("send_pdf_to_autenti: signature %d not found", signature_id)
            return
        if sig.status != SignatureStatus.draft:
            logger.warning(
                "send_pdf_to_autenti id=%d: status=%s — skipping",
                signature_id,
                sig.status.value,
            )
            return

        # Resolve PDF path + title
        if sig.client_framework_contract_id:
            fc = await db.scalar(
                select(ClientFrameworkContract).where(
                    ClientFrameworkContract.id == sig.client_framework_contract_id
                )
            )
            if fc is None or fc.file_path is None:
                await _mark_failed(db, sig, "Framework contract or file missing")
                return
            try:
                pdf_path = storage_service.get_client_framework_contract_path(
                    fc.file_path
                )
            except FileNotFoundError as exc:
                await _mark_failed(db, sig, f"PDF not found on disk: {exc}")
                return
            title = f"MSA: {fc.name}"
        elif sig.client_contract_amendment_id:
            a = await db.scalar(
                select(ClientContractAmendment).where(
                    ClientContractAmendment.id == sig.client_contract_amendment_id
                )
            )
            if a is None or a.file_path is None:
                await _mark_failed(db, sig, "Amendment or file missing")
                return
            try:
                pdf_path = storage_service.get_client_contract_amendment_path(
                    a.file_path
                )
            except FileNotFoundError as exc:
                await _mark_failed(db, sig, f"PDF not found on disk: {exc}")
                return
            title = f"Aneks: {a.name}"
        else:
            await _mark_failed(db, sig, "No framework_contract / amendment FK set")
            return

        sig.status = SignatureStatus.sending
        await db.commit()

        try:
            with pdf_path.open("rb") as fh:
                pdf_bytes = fh.read()
        except Exception as exc:  # noqa: BLE001
            await _mark_failed(db, sig, f"PDF read failed: {exc}")
            return

        try:
            config = AutentiConfig.from_settings()
        except Exception as exc:  # noqa: BLE001
            await _mark_failed(db, sig, f"Autenti config: {exc}")
            return

        idempotency_key = f"client-doc-sig-{sig.id}"
        try:
            async with AutentiClient(config) as client:
                process = await client.create_document_process(
                    _build_create_payload(signature=sig, title=title),
                    idempotency_key=idempotency_key,
                )
                process_id = process.get("id") or process.get("uuid")
                if not process_id:
                    raise AutentiError(
                        500, f"Missing id in create response: {process!r}"
                    )

                sig.autenti_process_id = str(process_id)
                await db.commit()

                await client.upload_file(
                    str(process_id),
                    pdf_bytes=pdf_bytes,
                    filename=pdf_path.name,
                    idempotency_key=f"{idempotency_key}-upload",
                )
                await client.send(
                    str(process_id), idempotency_key=f"{idempotency_key}-send"
                )

            sig.status = SignatureStatus.sent
            sig.sent_at = datetime.now(timezone.utc)
            db.add(
                Activity(
                    entity_type="document_signature",
                    entity_id=sig.id,
                    action="client_doc_signature_sent",
                    user_id=sig.sender_user_id,
                    external_source="autenti",
                    external_id=str(process_id),
                    details={"signature_type": sig.autenti_signature_type},
                )
            )
            await emit_notification(
                db,
                user_id=sig.sender_user_id,
                title="Dokument wysłany do podpisu",
                message=(
                    f"Dokument klienta wysłany do {sig.signer_first_name} "
                    f"{sig.signer_last_name} (Autenti)."
                ),
                ntype=NotificationType.signature_sent,
                related_entity_type="document_signature",
                related_entity_id=sig.id,
            )
            await db.commit()
        except AutentiError as exc:
            await _mark_failed(db, sig, f"Autenti API: {exc}")
        except Exception as exc:  # noqa: BLE001
            await _mark_failed(db, sig, f"Unhandled: {exc}")
