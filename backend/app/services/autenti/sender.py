"""Send a contract draft to Autenti for e-signature.

Two-step flow:

1. :func:`prepare_send` — synchronous part called from the FastAPI handler.
   Validates inputs (contract status, candidate fields, AUTENTI_ENABLED),
   creates a ``document_signatures`` row in ``status=draft``, returns 202.
2. :func:`send_to_autenti` — background task scheduled via
   ``asyncio.create_task``. Loads the contract, renders HTML→PDF, calls
   Autenti API (create_document_process → upload_file → send), persists
   ``autenti_process_id``, transitions ``draft → sending → sent``.

Failure handling: any exception in the background path sets
``status=failed``, ``last_error`` to the exception text, logs an
``Activity(action="signature_send_failed")``. UI surfaces the error and
offers a "Resend" CTA — the recruiter explicitly creates a new row
(no automatic retries; idempotent retries via ``Idempotency-Key`` header).

Plan: §4 (API contracts), §5 Phase 2.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.models.contract_document import ContractDocument
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.notification import NotificationType
from app.models.user import User
from app.schemas.document_signature import AutentiSendRequest
from app.services import storage_service
from app.services.autenti.client import (
    AutentiClient,
    AutentiConfig,
    AutentiError,
)
from app.services.autenti.pdf_renderer import render_contract_pdf
from app.services.notification_triggers import emit as emit_notification

logger = logging.getLogger(__name__)


# ── Validation helpers ─────────────────────────────────────────────────────


def _candidate_full_name_parts(candidate: Candidate) -> tuple[str, str]:
    """Return ``(first_name, last_name)`` — both NEVER empty.

    Candidate model splits ``name`` (first) and ``lastname``. Both are
    required by Autenti. Raises 422 if blank.
    """
    first = (candidate.name or "").strip()
    last = (candidate.lastname or "").strip()
    if not first or not last:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Candidate is missing first/last name",
                "missing": ["candidate.name" if not first else "candidate.lastname"],
            },
        )
    return first, last


def _validate_signer_fields(
    candidate: Candidate, signature_type: str
) -> tuple[str, str, str, Optional[str]]:
    """Pull denormalized signer snapshot or raise 422 with field-level hint.

    SES → email, first/last required.
    AdES → above + phone (SMS verification).
    QES → email, first/last (kandydat sam się autoryzuje przez profil zaufany).
    """
    email = (candidate.email or "").strip()
    if not email:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Candidate has no email",
                "missing": ["candidate.email"],
            },
        )
    first, last = _candidate_full_name_parts(candidate)

    phone: Optional[str] = (candidate.phone or "").strip() or None
    if signature_type == "AdES" and not phone:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "AdES requires the candidate's phone for SMS verification",
                "missing": ["candidate.phone"],
            },
        )
    return email, first, last, phone


# ── Synchronous prep ───────────────────────────────────────────────────────


async def prepare_send(
    db: AsyncSession,
    *,
    contract_id: int,
    payload: AutentiSendRequest,
    sender_user: User,
) -> DocumentSignature:
    """Validate + persist the new ``document_signatures`` row.

    Caller (FastAPI handler) commits the session, then schedules
    :func:`send_to_autenti` as a background task and returns 202.
    """
    if not settings.AUTENTI_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Autenti integration is disabled (AUTENTI_ENABLED=false)",
        )

    contract = await db.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(selectinload(Contract.candidate))
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")

    if contract.status not in (ContractStatus.active, ContractStatus.ending):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Contract is in status={contract.status.value}; "
                "only `active` or `ending` contracts can be sent for signature"
            ),
        )

    if contract.candidate is None:
        raise HTTPException(
            status_code=422, detail="Contract has no candidate attached"
        )

    signer_email, first_name, last_name, signer_phone = _validate_signer_fields(
        contract.candidate, payload.signature_type
    )

    # Pick the unsigned HTML snapshot we want signed. Plan §3: every
    # send references the most recent ContractDocument(doc_type=contract)
    # for this contract — that's the immutable HTML produced by
    # /draft/finalize. If none exists yet, the recruiter must finalize
    # the draft first.
    snapshot = await db.scalar(
        select(ContractDocument)
        .where(
            ContractDocument.contract_id == contract.id,
            ContractDocument.doc_type == "contract",
        )
        .order_by(ContractDocument.created_at.desc())
        .limit(1)
    )
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Contract has no finalized snapshot yet — open the draft "
                "editor, click 'Finalizuj' first, then send for signature."
            ),
        )

    expires_at: Optional[datetime] = None
    if payload.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=payload.expires_in_days
        )

    sig = DocumentSignature(
        contract_id=contract.id,
        contract_document_id=snapshot.id,
        autenti_signature_type=payload.signature_type,
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
            external_source="autenti",
            details={
                "signature_type": payload.signature_type,
                "expires_in_days": payload.expires_in_days,
                "signer_email": signer_email,
            },
        )
    )

    await db.flush()
    await db.commit()
    await db.refresh(sig)
    logger.info(
        "Autenti signature row created: id=%d contract=%d type=%s",
        sig.id,
        contract.id,
        payload.signature_type,
    )
    return sig


# ── Payload builder ────────────────────────────────────────────────────────


def _signature_constraints(signature_type: str) -> list[dict]:
    """Map our SES|AdES|QES Literal to Autenti participant constraints.

    Autenti API uses a generic ``constraints`` array on each party with
    ``classifiers`` + ``attributes.requiredClassifiers`` to demand a
    specific signature provider/type. Reference:
    developers.autenti.com/docs/.../requesting-e-idas-qualified-electronic-signature
    """
    base_constraint = {
        "constrainedActions": ["ACTION:SIGNATURE_APPLICATION"],
        "classifiers": ["CONSTRAINT-UNIQUE_TYPE:SIGNATURE_TYPE"],
    }
    if signature_type == "QES":
        return [
            {
                **base_constraint,
                "attributes": {
                    "requiredClassifiers": [
                        "SIGNATURE_PROVIDER-SIGNATURE_TYPE:QUALIFIED"
                    ]
                },
            }
        ]
    if signature_type == "AdES":
        return [
            {
                **base_constraint,
                "attributes": {
                    "requiredClassifiers": [
                        "SIGNATURE_PROVIDER-SIGNATURE_TYPE:ADVANCED_AUTENTI"
                    ]
                },
            }
        ]
    # SES default
    return [
        {
            **base_constraint,
            "attributes": {
                "requiredClassifiers": [
                    "SIGNATURE_PROVIDER-SIGNATURE_TYPE:BASIC_AUTENTI"
                ]
            },
        }
    ]


def _build_create_payload(
    *,
    signature: DocumentSignature,
    message_pl: Optional[str],
    return_url: Optional[str],
) -> dict:
    """Shape the ``POST /document-processes`` body.

    Single-signer flow per plan MVP — multi-party support arrives in
    Phase 6. Custom message / return_url are optional.
    """
    party: dict = {
        "role": "SIGNER",
        "ordering": 1,
        "person": {
            "email": signature.signer_email,
            "firstName": signature.signer_first_name,
            "lastName": signature.signer_last_name,
        },
        "constraints": _signature_constraints(signature.autenti_signature_type),
    }
    if signature.signer_phone:
        party["person"]["phone"] = signature.signer_phone
    if return_url:
        party["returnUrl"] = return_url

    title = f"Umowa B2B — {signature.signer_first_name} {signature.signer_last_name}"
    body: dict = {"title": title, "parties": [party]}

    if message_pl:
        body["message"] = {
            "subject": title,
            "body": message_pl,
            "language": "pl",
        }

    return body


# ── Background task ────────────────────────────────────────────────────────


async def send_to_autenti(signature_id: int) -> None:
    """Background coroutine: HTML→PDF → upload → send. Owns its own session.

    Schedule via ``asyncio.create_task(send_to_autenti(sig.id))`` AFTER the
    handler has committed :func:`prepare_send`. Failures are persisted on
    the same row (status=failed, last_error) — never raised back.
    """
    async with AsyncSessionLocal() as db:
        sig = await db.scalar(
            select(DocumentSignature)
            .where(DocumentSignature.id == signature_id)
            .options(
                selectinload(DocumentSignature.contract_document),
                selectinload(DocumentSignature.contract).selectinload(
                    Contract.candidate
                ),
            )
        )
        if sig is None:
            logger.error("send_to_autenti: signature %d not found", signature_id)
            return

        # Idempotency guard — only send when row is in 'draft'.
        if sig.status != SignatureStatus.draft:
            logger.warning(
                "send_to_autenti id=%d: status=%s (expected draft) — skipping",
                signature_id,
                sig.status.value,
            )
            return

        # Load the snapshot HTML. ContractDocument stores the printable HTML
        # blob as a file; we read it back and convert to PDF.
        try:
            html_bytes = _read_snapshot_html(sig.contract_document.file_path)
        except Exception as exc:  # noqa: BLE001
            await _mark_failed(db, sig, f"Snapshot load failed: {exc}")
            return

        sig.status = SignatureStatus.sending
        await db.commit()

        try:
            pdf = await asyncio.to_thread(
                render_contract_pdf,
                html_bytes.decode("utf-8", errors="replace"),
                title=f"Umowa #{sig.contract_id}",
            )
        except Exception as exc:  # noqa: BLE001
            await _mark_failed(db, sig, f"PDF render failed: {exc}")
            return

        try:
            config = AutentiConfig.from_settings()
        except Exception as exc:  # noqa: BLE001
            await _mark_failed(db, sig, f"Autenti config error: {exc}")
            return

        idempotency_key = f"sig-{sig.id}"
        try:
            async with AutentiClient(config) as client:
                process = await client.create_document_process(
                    _build_create_payload(
                        signature=sig,
                        message_pl=None,  # FE reserved for Phase 2 dialog
                        return_url=None,
                    ),
                    idempotency_key=idempotency_key,
                )
                process_id = process.get("id") or process.get("uuid")
                if not process_id:
                    raise AutentiError(
                        500, f"Missing id in create response: {process!r}"
                    )

                # Persist process_id in the SAME transaction as state move.
                sig.autenti_process_id = str(process_id)
                await db.commit()

                await client.upload_file(
                    str(process_id),
                    pdf_bytes=pdf,
                    filename=f"umowa_{sig.contract_id}.pdf",
                    idempotency_key=f"{idempotency_key}-upload",
                )
                await client.send(
                    str(process_id), idempotency_key=f"{idempotency_key}-send"
                )

            sig.status = SignatureStatus.sent
            sig.sent_at = datetime.now(timezone.utc)
            db.add(
                Activity(
                    entity_type="contract",
                    entity_id=sig.contract_id,
                    action="signature_sent",
                    user_id=sig.sender_user_id,
                    external_source="autenti",
                    external_id=str(process_id),
                    details={"signature_type": sig.autenti_signature_type},
                )
            )
            await emit_notification(
                db,
                user_id=sig.sender_user_id,
                title="Umowa wysłana do podpisu",
                message=(
                    f"Wysłałeś umowę kontraktu #{sig.contract_id} do podpisu "
                    f"({sig.signer_first_name} {sig.signer_last_name})."
                ),
                ntype=NotificationType.signature_sent,
                related_entity_type="document_signature",
                related_entity_id=sig.id,
                link=f"/candidates?contract={sig.contract_id}",
            )
            await db.commit()
            logger.info(
                "Autenti signature sent: id=%d process=%s",
                sig.id,
                process_id,
            )

        except AutentiError as exc:
            await _mark_failed(db, sig, f"Autenti API: {exc}")
        except Exception as exc:  # noqa: BLE001
            await _mark_failed(db, sig, f"Unhandled error: {exc}")


def _read_snapshot_html(relative_path: str) -> bytes:
    """Load the printable HTML snapshot saved by /draft/finalize."""
    abs_path = storage_service.get_contract_document_path(relative_path)
    return abs_path.read_bytes()


async def _mark_failed(
    db: AsyncSession, sig: DocumentSignature, error_msg: str
) -> None:
    """Persist failure + Activity + notification. Always called in bg task."""
    logger.warning(
        "Autenti send failed: signature=%d contract=%d error=%s",
        sig.id,
        sig.contract_id,
        error_msg,
    )
    sig.status = SignatureStatus.failed
    sig.last_error = error_msg[:2000]  # Truncate to avoid bloating the row
    sig.retry_count = (sig.retry_count or 0) + 1
    db.add(
        Activity(
            entity_type="contract",
            entity_id=sig.contract_id,
            action="signature_send_failed",
            user_id=sig.sender_user_id,
            external_source="autenti",
            details={"error": error_msg[:500]},
        )
    )
    try:
        await emit_notification(
            db,
            user_id=sig.sender_user_id,
            title="Wysyłka umowy nie powiodła się",
            message=(
                f"Nie udało się wysłać umowy kontraktu #{sig.contract_id} "
                "do Autenti. Spróbuj ponownie lub sprawdź konfigurację."
            ),
            ntype=NotificationType.signature_failed,
            related_entity_type="document_signature",
            related_entity_id=sig.id,
        )
    except Exception:  # noqa: BLE001
        # Notification dispatch is best-effort — do not block the failure path.
        logger.exception("Notification emit failed for signature=%d", sig.id)
    await db.commit()
