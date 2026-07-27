"""Belt-and-braces background loop for the Autenti integration.

Two responsibilities, both triggered every ``settings.AUTENTI_SWEEPER_INTERVAL_SECONDS``
(default 1h) when ``AUTENTI_ENABLED=true``:

1. **Expiry sweep**: any ``DocumentSignature`` with ``status in {sent, in_progress}``
   whose ``expires_at < now()`` is polled via ``GET /document-processes/{id}``.
   If Autenti confirms the process expired, we flip status to ``expired``,
   log an Activity row, and notify the sender. Guards against missed
   ``DOCUMENT_PROCESS_EXPIRED`` webhooks.

2. **Signed-PDF retry**: any ``DocumentSignature`` with
   ``status=completed AND signed_document_id IS NULL`` and
   ``retry_count < 3`` retries the download. Increments ``retry_count``
   on every attempt; gives up after 3 failures (manual recovery via UI).

Idempotent: no harm in running on tightly-spaced intervals. Cancellation-aware:
``asyncio.CancelledError`` exits cleanly during shutdown.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from io import BytesIO

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.notification import NotificationType
from app.services import storage_service
from app.services.autenti.client import (
    AutentiClient,
    AutentiConfig,
    AutentiError,
    AutentiNotFoundError,
)
from app.services.notification_triggers import emit as emit_notification

logger = logging.getLogger(__name__)

_AUTENTI_EXPIRED_STATUS_VALUES = {
    "EXPIRED",
    "DOCUMENT_PROCESS_EXPIRED",
}


def _interval_seconds() -> int:
    """Loop cadence (clamped to >=300s to avoid hammering the Autenti API)."""
    raw = getattr(settings, "AUTENTI_SWEEPER_INTERVAL_SECONDS", 3600)
    return max(300, int(raw))


async def _sweep_expired() -> int:
    """Confirm and finalize expired signatures. Returns rows touched."""
    config = AutentiConfig.from_settings()
    touched = 0
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DocumentSignature).where(
                DocumentSignature.status.in_(
                    [SignatureStatus.sent, SignatureStatus.in_progress]
                ),
                DocumentSignature.expires_at.is_not(None),
                DocumentSignature.expires_at < now,
                DocumentSignature.provider_ref.is_not(None),
            )
        )
        candidates = list(result.scalars().all())

        if not candidates:
            return 0

        async with AutentiClient(config) as client:
            for sig in candidates:
                try:
                    info = await client.get_process(sig.autenti_process_id or "")
                except AutentiNotFoundError:
                    # Autenti retired the process server-side — treat as expired.
                    info = {"status": "DOCUMENT_PROCESS_EXPIRED"}
                except AutentiError as exc:
                    logger.warning(
                        "Sweeper: get_process failed sig=%d err=%s", sig.id, exc
                    )
                    continue

                remote_status = str(info.get("status") or "").upper()
                if remote_status not in _AUTENTI_EXPIRED_STATUS_VALUES:
                    continue

                sig.status = SignatureStatus.expired
                db.add(
                    Activity(
                        entity_type="contract",
                        entity_id=sig.contract_id,
                        action="signature_expired",
                        user_id=sig.sender_user_id,
                        external_source="autenti",
                        external_id=sig.autenti_process_id,
                    )
                )
                try:
                    await emit_notification(
                        db,
                        user_id=sig.sender_user_id,
                        title="Umowa wygasła bez podpisu",
                        message=(
                            f"Wysyłka kontraktu #{sig.contract_id} do "
                            f"{sig.signer_first_name} {sig.signer_last_name} "
                            "wygasła. Wyślij ponownie z nowym terminem."
                        ),
                        ntype=NotificationType.signature_failed,
                        related_entity_type="document_signature",
                        related_entity_id=sig.id,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Sweeper: notification emit failed sig=%d", sig.id)
                touched += 1

        if touched:
            await db.commit()
    return touched


async def _retry_signed_downloads() -> int:
    """Retry signed PDF download for completed-but-unattached signatures.

    The PDF lands in object storage before the row that references it can be
    committed — there is no transaction spanning both, so that ordering is not
    something the code can eliminate. What it can do is make the gap harmless:

    * the storage key is **deterministic** per signature, so a retry after a
      crash overwrites the same object instead of stacking up a fresh orphan
      on every pass;
    * the DB write is committed **per signature**, so the window is one file
      wide instead of the whole batch; and
    * a failed DB write **deletes** the file it just wrote, so the exception
      path leaves nothing behind either.
    """
    config = AutentiConfig.from_settings()
    touched = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DocumentSignature.id).where(
                DocumentSignature.status == SignatureStatus.completed,
                DocumentSignature.signed_document_id.is_(None),
                DocumentSignature.provider_ref.is_not(None),
                DocumentSignature.retry_count < 3,
            )
        )
        # Iterate over ids and re-load each row: a per-signature rollback
        # expires everything in the session, so holding a batch of ORM objects
        # across it would break every later iteration with a lazy-load error.
        candidate_ids = list(result.scalars().all())
        if not candidate_ids:
            return 0

        async with AutentiClient(config) as client:
            for sig_id in candidate_ids:
                sig = await db.get(DocumentSignature, sig_id)
                if sig is None or sig.signed_document_id is not None:
                    # Gone, or a webhook attached the PDF while we were working.
                    continue
                contract_id = sig.contract_id
                try:
                    pdf_bytes = await client.download_signed_file(
                        sig.autenti_process_id or ""
                    )
                except AutentiError as exc:
                    sig.retry_count = (sig.retry_count or 0) + 1
                    sig.last_error = f"Sweeper download retry: {exc}"
                    logger.warning(
                        "Sweeper: download retry failed sig=%d count=%d err=%s",
                        sig_id,
                        sig.retry_count,
                        exc,
                    )
                    await db.commit()
                    continue

                if not pdf_bytes:
                    sig.retry_count = (sig.retry_count or 0) + 1
                    sig.last_error = "Sweeper download retry: empty PDF"
                    await db.commit()
                    continue

                filename = f"umowa_{contract_id}_signed_{sig_id}.pdf"
                # Stable key per signature: a crash between this write and the
                # commit below leaves an object that the next pass overwrites,
                # not a second copy alongside it.
                stored_name = f"autenti-signed-{sig_id}.pdf"
                # Sync file write — offload off the event loop.
                relative_path, size = await asyncio.to_thread(
                    storage_service.save_contract_document,
                    contract_id=contract_id,
                    upload_filename=filename,
                    source=BytesIO(pdf_bytes),
                    stored_name=stored_name,
                )
                try:
                    doc = ContractDocument(
                        contract_id=contract_id,
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
                    sig.last_error = None
                    # Commit per signature — the file on disk and the row that
                    # points at it become durable together, so a crash later in
                    # the batch cannot undo an attachment that already worked.
                    await db.commit()
                except Exception:
                    # DB refused the row: drop the file we just wrote so it does
                    # not linger unreferenced, and let the next pass start over.
                    await db.rollback()
                    await asyncio.to_thread(
                        storage_service.delete_contract_document, relative_path
                    )
                    logger.exception(
                        "Sweeper: attaching signed PDF failed sig=%d; file %s removed",
                        sig_id,
                        relative_path,
                    )
                    continue
                touched += 1

    return touched


async def autenti_sweeper_loop() -> None:
    """Top-level loop registered in ``main.py:lifespan`` when AUTENTI_ENABLED."""
    if not settings.AUTENTI_ENABLED:
        logger.info("AUTENTI_ENABLED=false — sweeper exiting at startup")
        return

    interval = _interval_seconds()
    logger.info("Autenti sweeper starting; interval=%ds", interval)

    while True:
        try:
            try:
                expired = await _sweep_expired()
                downloaded = await _retry_signed_downloads()
                if expired or downloaded:
                    logger.info(
                        "Autenti sweeper tick: expired=%d, downloaded=%d",
                        expired,
                        downloaded,
                    )
            except Exception:  # noqa: BLE001
                logger.exception("Autenti sweeper tick failed (continuing)")

            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("Autenti sweeper cancelled — exiting")
            return
