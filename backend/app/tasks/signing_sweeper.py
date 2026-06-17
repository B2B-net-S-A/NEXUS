"""Background sweeper for the in-house signing rail.

Expires pending signatures past their deadline (the public link's
single-use/TTL handles the link itself; this flips the row to ``expired`` and
notifies the recruiter so the UI reflects reality). Unlike the Autenti sweeper
there is no provider polling — for the upload-and-validate pas there is no
remote process to reconcile; completion is driven synchronously by the public
``/submit`` endpoint.

Exits immediately when ``SIGNING_ENABLED=false`` (rolling-rollback safe).
Interval clamped to >=300s.

Plan: ``docs/in-house-qes-signature-plan.md`` §7.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.notification import NotificationType
from app.services.notification_triggers import emit as emit_notification

logger = logging.getLogger(__name__)


async def _expire_overdue() -> int:
    """Flip overdue ``sent``/``in_progress`` rows to ``expired``."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DocumentSignature).where(
                DocumentSignature.provider != "autenti",
                DocumentSignature.status.in_(
                    [SignatureStatus.sent, SignatureStatus.in_progress]
                ),
                DocumentSignature.expires_at.is_not(None),
                DocumentSignature.expires_at < now,
            )
        )
        rows = list(result.scalars().all())
        if not rows:
            return 0
        for sig in rows:
            sig.status = SignatureStatus.expired
            db.add(
                Activity(
                    entity_type="contract",
                    entity_id=sig.contract_id,
                    action="signature_expired",
                    user_id=sig.sender_user_id,
                    external_source="signing",
                )
            )
            try:
                await emit_notification(
                    db,
                    user_id=sig.sender_user_id,
                    title="Umowa wygasła bez podpisu",
                    message=(
                        f"Link do podpisu umowy kontraktu #{sig.contract_id} dla "
                        f"{sig.signer_first_name} {sig.signer_last_name} wygasł. "
                        "Wyślij ponownie."
                    ),
                    ntype=NotificationType.signature_failed,
                    related_entity_type="document_signature",
                    related_entity_id=sig.id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("signing_sweeper: notification failed sig=%d", sig.id)
        await db.commit()
        return len(rows)


async def signing_sweeper_loop() -> None:
    """Periodic expiry sweep. No-op when the kill-switch is off."""
    if not settings.SIGNING_ENABLED:
        logger.info("signing_sweeper: SIGNING_ENABLED=false — loop exiting")
        return
    interval = max(300, settings.SIGNING_SWEEPER_INTERVAL_SECONDS)
    logger.info("signing_sweeper: started (interval=%ds)", interval)
    while True:
        try:
            touched = await _expire_overdue()
            if touched:
                logger.info("signing_sweeper: expired %d signature(s)", touched)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("signing_sweeper: tick failed")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
