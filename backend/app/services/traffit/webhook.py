"""Durable, idempotent ingestion for Traffit webhook signals."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traffit_integration import TraffitWebhookEvent
from app.services.traffit.merge import canonical_json


MAX_WEBHOOK_BODY_BYTES = 1024 * 1024


class InvalidWebhookSignature(ValueError):
    pass


def secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_webhook_secret(secret: str, expected_hash: str) -> bool:
    if not secret or not expected_hash:
        return False
    return hmac.compare_digest(secret_hash(secret), expected_hash.lower())


def verify_hmac_signature(
    raw_body: bytes,
    signature: str,
    signing_secret: str,
) -> bool:
    """Verify an optional sha256 HMAC if the tenant supports signed webhooks."""
    if not signature or not signing_secret:
        return False
    supplied = signature.strip()
    if supplied.lower().startswith("sha256="):
        supplied = supplied.split("=", 1)[1]
    expected = hmac.new(
        signing_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, supplied.lower())


def assert_webhook_authorized(
    *,
    url_secret: str,
    expected_secret_hash: str,
    raw_body: bytes,
    signature: Optional[str] = None,
    hmac_secret: Optional[str] = None,
) -> None:
    if not verify_webhook_secret(url_secret, expected_secret_hash):
        raise InvalidWebhookSignature("invalid webhook URL secret")
    if hmac_secret and not verify_hmac_signature(
        raw_body, signature or "", hmac_secret
    ):
        raise InvalidWebhookSignature("invalid webhook HMAC signature")


def _nested_id(value: Any) -> Optional[str]:
    if isinstance(value, Mapping) and value.get("id") is not None:
        return str(value["id"])
    if value is not None and not isinstance(value, (dict, list)):
        return str(value)
    return None


@dataclass(frozen=True)
class WebhookIdentity:
    event_type: str
    remote_entity_type: Optional[str]
    remote_entity_id: Optional[str]
    dedupe_key: str
    payload_hash: str


def identify_webhook(
    subscription_id: str,
    payload: Mapping[str, Any],
    *,
    request_id: Optional[str] = None,
    event_type: Optional[str] = None,
    received_at: Optional[datetime] = None,
) -> WebhookIdentity:
    body_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    normalized_event_type = str(
        event_type
        or payload.get("type")
        or payload.get("event_type")
        or payload.get("event")
        or "unknown"
    )[:100]
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    for key in ("employee", "candidate", "recruitment", "activity", "file"):
        candidate_id = _nested_id(payload.get(key))
        if candidate_id is not None:
            entity_type, entity_id = key, candidate_id
            break
    if entity_id is None:
        entity_id = _nested_id(
            payload.get("entity_id") or payload.get("employee_id") or payload.get("id")
        )
    if entity_type is None and payload.get("entity_type"):
        entity_type = str(payload["entity_type"])
    source_event_id = request_id or payload.get("event_id") or payload.get("uuid")
    # Without a source event id the payload is only a signal and can repeat for
    # later changes to the same employee. A short receipt bucket collapses
    # immediate delivery retries without deduplicating that signal forever.
    received = received_at or datetime.now(timezone.utc)
    bucket = int(received.timestamp() // 300)
    material = (
        str(source_event_id)
        if source_event_id
        else f"receipt:{body_hash}:{bucket}"
    )
    dedupe = hashlib.sha256(
        f"{subscription_id}:{material}".encode("utf-8")
    ).hexdigest()
    return WebhookIdentity(
        normalized_event_type, entity_type, entity_id, dedupe, body_hash
    )


async def ingest_webhook(
    db: AsyncSession,
    *,
    subscription_id: str,
    payload: Mapping[str, Any],
    request_id: Optional[str] = None,
    event_type: Optional[str] = None,
    received_at: Optional[datetime] = None,
    max_attempts: int = 8,
) -> tuple[TraffitWebhookEvent, bool]:
    """Persist a signal in the caller's transaction; return (event, created)."""
    identity = identify_webhook(
        subscription_id,
        payload,
        request_id=request_id,
        event_type=event_type,
        received_at=received_at,
    )
    existing = await db.scalar(
        select(TraffitWebhookEvent).where(
            TraffitWebhookEvent.dedupe_key == identity.dedupe_key
        )
    )
    if existing is not None:
        return existing, False
    event = TraffitWebhookEvent(
        subscription_id=subscription_id,
        dedupe_key=identity.dedupe_key,
        event_type=identity.event_type,
        remote_entity_type=identity.remote_entity_type,
        remote_entity_id=identity.remote_entity_id,
        payload=json.loads(canonical_json(payload)),
        payload_hash=identity.payload_hash,
        status="pending",
        attempts=0,
        max_attempts=max_attempts,
    )
    try:
        async with db.begin_nested():
            db.add(event)
            await db.flush()
    except IntegrityError:
        # Concurrent delivery with the same stable source id won the unique
        # constraint. The savepoint keeps the caller transaction usable.
        existing = await db.scalar(
            select(TraffitWebhookEvent).where(
                TraffitWebhookEvent.subscription_id == subscription_id,
                TraffitWebhookEvent.dedupe_key == identity.dedupe_key,
            )
        )
        if existing is None:
            raise
        return existing, False
    return event, True
