"""Restart-safe reconciliation for stuck signature dispatch (M5-P0.9).

Every signature sender — :mod:`app.services.autenti.sender` (contracts),
:mod:`app.services.autenti.client_contracts_sender` (framework contracts +
amendments) and :mod:`app.services.signing.sender` (in-house rail) — persists a
``document_signatures`` row in ``status=draft`` and hands the actual dispatch to
a background task (``asyncio.create_task`` / FastAPI ``BackgroundTasks``). A
container restart (Coolify rebuilds on every push) between the HTTP 202 and
completion orphans that row at ``draft``/``sending`` **forever**: the expiry
sweepers only touch ``sent``/``in_progress``, so nothing reconciles the
in-flight states. The admin engagement inventory *reports* the backlog
(``stuck_signature``) but never self-heals it.

This loop is the missing recovery. Any row stuck in ``draft``/``sending`` past a
short grace window (``SIGNATURE_RECONCILE_GRACE_SECONDS``, default 10 min — both
states are documented as transient, sub-second) is marked ``failed`` with an
actionable ``last_error``, an ``Activity`` row and a ``signature_failed``
notification to the sender, who resends from the UI (the sender's
``Idempotency-Key`` makes a fresh send safe).

We deliberately **mark-failed rather than re-dispatch**: a ``sending`` row may
already hold a partially-created provider process, and the senders' own
idempotency guard (``status != draft`` → skip) would no-op a re-dispatch anyway.
Marking failed surfaces reality in the UI and hands control back to the
recruiter uniformly for every rail.

Restart-safe: the only state is the DB row + its ``updated_at`` — a rebuild
never re-triggers work. Idempotent + cancellation-aware. Exits immediately
unless at least one signing rail is enabled; each row is gated by its own
provider's kill-switch (``AUTENTI_ENABLED`` for ``autenti`` rows,
``SIGNING_ENABLED`` for the rest).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.sql import ColumnElement

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.notification import NotificationType
from app.services.notification_triggers import emit as emit_notification

logger = logging.getLogger(__name__)

# In-flight states that must resolve within seconds. Anything older than the
# grace window has been orphaned by a mid-dispatch process death.
_STUCK_STATES = (SignatureStatus.draft, SignatureStatus.sending)


def _grace_seconds() -> int:
    """Grace before a draft/sending row is treated as orphaned (>=60s)."""
    raw = getattr(settings, "SIGNATURE_RECONCILE_GRACE_SECONDS", 600)
    return max(60, int(raw))


def _interval_seconds() -> int:
    """Loop cadence (clamped >=300s — recovery, not a hot path)."""
    raw = getattr(settings, "SIGNATURE_RECONCILE_INTERVAL_SECONDS", 600)
    return max(300, int(raw))


def _provider_filter() -> ColumnElement[bool] | None:
    """Restrict the sweep to rows whose provider rail is enabled.

    ``None`` means "no restriction" (both rails on). Only called when at least
    one rail is enabled — the neither-enabled case is short-circuited by the
    loop's top-level guard.
    """
    autenti_on = bool(settings.AUTENTI_ENABLED)
    signing_on = bool(settings.SIGNING_ENABLED)
    if autenti_on and signing_on:
        return None
    if autenti_on:
        return DocumentSignature.provider == "autenti"
    # signing_on only
    return DocumentSignature.provider != "autenti"


async def _reconcile_stuck() -> int:
    """Mark orphaned draft/sending rows failed + notify. Returns rows touched."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_grace_seconds())

    async with AsyncSessionLocal() as db:
        conditions = [
            DocumentSignature.status.in_(_STUCK_STATES),
            DocumentSignature.updated_at < cutoff,
        ]
        provider_clause = _provider_filter()
        if provider_clause is not None:
            conditions.append(provider_clause)

        result = await db.execute(select(DocumentSignature).where(*conditions))
        rows = list(result.scalars().all())
        if not rows:
            return 0

        for sig in rows:
            stuck_at = sig.status.value
            source = "autenti" if sig.provider == "autenti" else "signing"
            sig.status = SignatureStatus.failed
            sig.last_error = (
                f"Reconciler: wysyłka przerwana (restart usługi) — utknęła w "
                f"statusie '{stuck_at}' ponad {_grace_seconds() // 60} min. "
                "Wyślij ponownie."
            )
            sig.retry_count = (sig.retry_count or 0) + 1
            db.add(
                Activity(
                    entity_type="document_signature",
                    entity_id=sig.id,
                    action="signature_send_failed",
                    user_id=sig.sender_user_id,
                    external_source=source,
                    details={"reason": "reconciler_stuck", "stuck_at": stuck_at},
                )
            )
            try:
                await emit_notification(
                    db,
                    user_id=sig.sender_user_id,
                    title="Wysyłka umowy przerwana",
                    message=(
                        f"Wysyłka umowy do podpisu ({sig.signer_first_name} "
                        f"{sig.signer_last_name}) została przerwana i nie "
                        "dokończyła się. Wyślij ponownie."
                    ),
                    ntype=NotificationType.signature_failed,
                    related_entity_type="document_signature",
                    related_entity_id=sig.id,
                )
            except Exception:  # noqa: BLE001 — notification is best-effort
                logger.exception(
                    "signature_reconciler: notification failed sig=%d", sig.id
                )

        await db.commit()
        return len(rows)


async def signature_reconciler_loop() -> None:
    """Periodic recovery of dispatch orphaned by a mid-flight restart.

    No-op unless at least one signing rail is enabled. Registered in
    ``app.main:lifespan`` alongside the other background tasks.
    """
    if not (settings.AUTENTI_ENABLED or settings.SIGNING_ENABLED):
        logger.info(
            "signature_reconciler: both rails disabled "
            "(AUTENTI_ENABLED=false, SIGNING_ENABLED=false) — loop exiting"
        )
        return

    interval = _interval_seconds()
    logger.info("signature_reconciler: started (interval=%ds)", interval)

    while True:
        try:
            touched = await _reconcile_stuck()
            if touched:
                logger.warning(
                    "signature_reconciler: recovered %d stuck signature(s)", touched
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a recovery tick must never die
            logger.exception("signature_reconciler: tick failed")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
