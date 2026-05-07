"""State-machine handler for Autenti webhook events.

Flow (plan §4):
1. Caller (FastAPI route) verifies the JWT via :mod:`webhook_verify` and
   passes the decoded claims here.
2. :func:`handle_event` looks up the ``DocumentSignature`` by
   ``autenti_process_id``. Missing → returns ``"ignored"`` (Autenti retries
   on 4xx; we 200 + log to break the retry loop on stale processes).
3. Inserts a row into ``document_signature_events``. The unique
   ``event_id`` constraint is the **only** dedup mechanism — replays cause
   IntegrityError, caught here, returning ``"duplicate"``.
4. Dispatches on ``event_type`` to a per-event handler that mutates
   ``document_signatures.status`` and fires notifications + Activity rows.
5. For ``SIGNING_PROCESS_COMPLETED``: also downloads the signed PDF via
   :class:`AutentiClient`, persists it via ``storage_service``, and links
   it on ``signed_document_id``. Failure-tolerant: status flips to
   ``completed`` even if download fails — Phase 5 sweeper retries.

Event taxonomy: see plan §1 (callbacks). Unknown event_type → log + 200.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Literal, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.document_signature_event import DocumentSignatureEvent
from app.models.notification import NotificationType
from app.schemas.document_signature import serialize_payload_safely
from app.services import storage_service
from app.services.autenti.client import AutentiClient, AutentiConfig, AutentiError
from app.services.notification_triggers import emit as emit_notification

logger = logging.getLogger(__name__)

HandlerOutcome = Literal["ok", "duplicate", "ignored"]


def _extract_process_id(claims: dict[str, Any]) -> Optional[str]:
    """Pull Autenti's process identifier from a webhook payload.

    Autenti has used several field names over time (``processId``,
    ``process_id``, ``documentProcessId``, sometimes nested under
    ``data.id``). Try them in order; first hit wins.
    """
    candidates: list[Any] = [
        claims.get("processId"),
        claims.get("process_id"),
        claims.get("documentProcessId"),
        (claims.get("data") or {}).get("id"),
        (claims.get("data") or {}).get("processId"),
    ]
    for value in candidates:
        if value:
            return str(value)
    return None


def _extract_event_id(claims: dict[str, Any]) -> Optional[str]:
    """Pull the event identifier (used as DB-level idempotency key)."""
    return claims.get("jti") or claims.get("eventId") or claims.get("event_id")


def _extract_event_type(claims: dict[str, Any]) -> str:
    """Best-effort event type. Always returns a non-empty string."""
    return (
        claims.get("eventType")
        or claims.get("event_type")
        or (claims.get("status") and f"STATUS:{claims['status']}")
        or "UNKNOWN"
    )


# ── State transitions ──────────────────────────────────────────────────────


def _terminal_status_for_event(
    event_type: str, status_field: Optional[str]
) -> Optional[SignatureStatus]:
    """Map an Autenti webhook event to a NEXUS signature status, if terminal.

    Returns None for non-terminal events (e.g. APPROVAL_PROCESS_CONSENTED on a
    multi-party flow that's not yet complete).
    """
    if event_type == "SIGNING_PROCESS_COMPLETED":
        return SignatureStatus.completed
    if status_field == "DOCUMENT_PROCESS_REJECTED":
        return SignatureStatus.rejected
    if status_field == "DOCUMENT_PROCESS_WITHDRAWN":
        return SignatureStatus.withdrawn
    if status_field == "DOCUMENT_PROCESS_EXPIRED":
        return SignatureStatus.expired
    if status_field == "COMPLETED":
        return SignatureStatus.completed
    return None


def _intermediate_status_for_event(event_type: str) -> Optional[SignatureStatus]:
    """Non-terminal transitions that bump status to ``in_progress``."""
    if event_type in {
        "APPROVAL_PROCESS_CONSENTED",
        "REVIEW_PROCESS_COMPLETED",
        "HANDED_OVER",
    }:
        return SignatureStatus.in_progress
    return None


# ── Public entry point ────────────────────────────────────────────────────


async def handle_event(db: AsyncSession, claims: dict[str, Any]) -> HandlerOutcome:
    """Idempotently process one decoded webhook payload.

    Returns:
        - ``"ok"`` on first-time processing.
        - ``"duplicate"`` when ``event_id`` is already in our table.
        - ``"ignored"`` when we don't recognise the ``process_id``
          (e.g. message for a process that isn't ours).
    """
    event_id = _extract_event_id(claims)
    if not event_id:
        logger.warning("Webhook claims missing event_id; ignoring")
        return "ignored"

    process_id = _extract_process_id(claims)
    if not process_id:
        logger.warning("Webhook claims missing process_id; ignoring event=%s", event_id)
        return "ignored"

    sig = await db.scalar(
        select(DocumentSignature).where(
            DocumentSignature.autenti_process_id == process_id
        )
    )
    if sig is None:
        logger.warning(
            "Webhook for unknown process_id=%s (event=%s) — ignoring",
            process_id,
            event_id,
        )
        return "ignored"

    event_type = _extract_event_type(claims)
    status_field = claims.get("status")

    # Try to insert the audit row. Unique index on event_id gives us
    # idempotency-by-DB — replays fail at INSERT time.
    event_row = DocumentSignatureEvent(
        signature_id=sig.id,
        event_id=event_id,
        event_type=event_type,
        status=str(status_field)[:32] if status_field else None,
        payload=serialize_payload_safely(claims),
    )
    try:
        async with db.begin_nested():
            db.add(event_row)
            await db.flush()
    except IntegrityError:
        logger.info(
            "Webhook duplicate event_id=%s (process=%s) — skipping",
            event_id,
            process_id,
        )
        return "duplicate"

    # Apply state transition.
    new_status = _terminal_status_for_event(event_type, status_field)
    if new_status is None:
        new_status = _intermediate_status_for_event(event_type)

    if new_status is not None and sig.status != new_status:
        sig.status = new_status
        if new_status == SignatureStatus.completed:
            sig.completed_at = datetime.now(timezone.utc)

    # Per-event side effects: notification + activity + (for completed)
    # signed PDF download.
    await _dispatch_side_effects(db, sig, event_type, status_field)

    event_row.processed_at = datetime.now(timezone.utc)
    await db.commit()
    return "ok"


# ── Side-effect dispatch ───────────────────────────────────────────────────


async def _dispatch_side_effects(
    db: AsyncSession,
    sig: DocumentSignature,
    event_type: str,
    status_field: Optional[str],
) -> None:
    if event_type == "SIGNING_PROCESS_COMPLETED" or status_field == "COMPLETED":
        await _on_signing_completed(db, sig)
    elif status_field == "DOCUMENT_PROCESS_REJECTED":
        await _on_rejected(db, sig)
    elif status_field == "DOCUMENT_PROCESS_WITHDRAWN":
        await _on_withdrawn(db, sig)


async def _on_signing_completed(db: AsyncSession, sig: DocumentSignature) -> None:
    # Download the signed PDF — best-effort. If download fails, the row stays
    # with status=completed, signed_document_id=NULL; the Phase 5 sweeper
    # retries the download.
    if sig.autenti_process_id and sig.signed_document_id is None:
        try:
            await _download_and_attach_signed_file(db, sig)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Signed PDF download failed: signature=%d process=%s err=%s",
                sig.id,
                sig.autenti_process_id,
                exc,
            )

    db.add(
        Activity(
            entity_type="contract",
            entity_id=sig.contract_id,
            action="signature_completed",
            user_id=sig.sender_user_id,
            external_source="autenti",
            external_id=sig.autenti_process_id,
            details={"signer_email": sig.signer_email},
        )
    )
    await emit_notification(
        db,
        user_id=sig.sender_user_id,
        title="Umowa podpisana",
        message=(
            f"{sig.signer_first_name} {sig.signer_last_name} podpisał(a) "
            f"umowę kontraktu #{sig.contract_id}."
        ),
        ntype=NotificationType.signature_signed,
        related_entity_type="document_signature",
        related_entity_id=sig.id,
        link=f"/candidates?contract={sig.contract_id}",
    )


async def _on_rejected(db: AsyncSession, sig: DocumentSignature) -> None:
    db.add(
        Activity(
            entity_type="contract",
            entity_id=sig.contract_id,
            action="signature_rejected",
            user_id=sig.sender_user_id,
            external_source="autenti",
            external_id=sig.autenti_process_id,
            details={"signer_email": sig.signer_email},
        )
    )
    await emit_notification(
        db,
        user_id=sig.sender_user_id,
        title="Kandydat odrzucił umowę",
        message=(
            f"{sig.signer_first_name} {sig.signer_last_name} odrzucił(a) "
            f"podpisanie umowy kontraktu #{sig.contract_id}. Skontaktuj się "
            "z kandydatem, aby ustalić dalsze kroki."
        ),
        ntype=NotificationType.signature_rejected,
        related_entity_type="document_signature",
        related_entity_id=sig.id,
        link=f"/candidates?contract={sig.contract_id}",
    )


async def _on_withdrawn(db: AsyncSession, sig: DocumentSignature) -> None:
    db.add(
        Activity(
            entity_type="contract",
            entity_id=sig.contract_id,
            action="signature_withdrawn",
            user_id=sig.sender_user_id,
            external_source="autenti",
            external_id=sig.autenti_process_id,
        )
    )
    # No notification — the user who clicked "Wycofaj" already saw the result
    # in their UI flow; an in-app notification would be noise.


async def _download_and_attach_signed_file(
    db: AsyncSession, sig: DocumentSignature
) -> None:
    """Pull the signed PDF from Autenti and persist it as ContractDocument.

    Mutates ``sig.signed_document_id``. Caller commits.
    """
    config = AutentiConfig.from_settings()
    async with AutentiClient(config) as client:
        pdf_bytes = await client.download_signed_file(sig.autenti_process_id or "")

    if not pdf_bytes:
        raise AutentiError(0, "Empty signed PDF from Autenti")

    filename = f"umowa_{sig.contract_id}_signed_{sig.id}.pdf"
    relative_path, size = storage_service.save_contract_document(
        contract_id=sig.contract_id,
        upload_filename=filename,
        source=BytesIO(pdf_bytes),
    )

    doc = ContractDocument(
        contract_id=sig.contract_id,
        filename=filename,
        file_path=relative_path,
        content_type="application/pdf",
        size_bytes=size,
        doc_type=ContractDocumentType.contract,
        uploaded_by=sig.sender_user_id,
    )
    db.add(doc)
    await db.flush()
    sig.signed_document_id = doc.id
    logger.info(
        "Signed PDF attached: signature=%d contract=%d document=%d size=%d",
        sig.id,
        sig.contract_id,
        doc.id,
        size,
    )
