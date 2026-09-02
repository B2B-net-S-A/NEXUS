"""Autenti e-signature API router.

Mounted under ``/api/autenti`` from ``app.main`` ONLY when
``settings.AUTENTI_ENABLED`` is True. With the kill-switch off the router
is silently absent (404 from the framework) — no behavioural change.

Endpoints implemented in Phase 2:

- ``POST /contracts/{contract_id}/send`` — async dispatch (202 + bg task).
- ``GET  /contracts/{contract_id}/signatures`` — list of all sends.
- ``GET  /signatures/{signature_id}`` — single signature + timeline.

Phase 3 adds ``POST /webhook``; Phase 4 adds ``/withdraw`` + ``/remind``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.contract_access import assert_contract_legal_contract_access
from app.api.deps import CurrentUser, TacPlus, require_roles
from app.api.section_access import ProductSection, require_section_access
from app.core.config import settings
from app.core.database import get_db
from app.models.activity import Activity
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.user import User, UserRole
from app.schemas.document_signature import (
    AutentiSendRequest,
    AutentiSendResponse,
    AutentiWebhookResponse,
    DocumentSignatureDetailResponse,
    DocumentSignatureResponse,
)
from app.services.autenti.client import AutentiClient, AutentiConfig, AutentiError
from app.services.autenti.sender import prepare_send, send_to_autenti
from app.services.autenti.webhook_handler import handle_event
from app.services.autenti.webhook_verify import (
    AutentiWebhookError,
    verify_jwt,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_DELIVERY_SECTION_DEPENDENCIES = [
    Depends(require_section_access(ProductSection.delivery))
]


ContractSignatureReadUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.finance,
        )
    ),
]


def _require_enabled() -> None:
    """Guard for write/IO endpoints. Read-only endpoints stay live."""
    if not settings.AUTENTI_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Autenti integration is disabled (AUTENTI_ENABLED=false)",
        )


@router.post(
    "/contracts/{contract_id}/send",
    response_model=AutentiSendResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=_DELIVERY_SECTION_DEPENDENCIES,
)
async def send_contract_for_signature(
    contract_id: int,
    payload: AutentiSendRequest,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> AutentiSendResponse:
    """Validate and dispatch a contract to Autenti.

    Returns 202 immediately with the new ``document_signatures.id``.
    The actual API call happens in :func:`send_to_autenti` background task,
    which transitions ``status=draft → sending → sent`` (or ``failed``).
    """
    _require_enabled()
    await assert_contract_legal_contract_access(
        db, current_user, contract_id, write=True
    )
    sig = await prepare_send(
        db,
        contract_id=contract_id,
        payload=payload,
        sender_user=current_user,
    )
    # Schedule async send AFTER commit. Detached from request lifecycle —
    # owns its own DB session via AsyncSessionLocal in the function.
    asyncio.create_task(send_to_autenti(sig.id))
    return AutentiSendResponse(
        signature_id=sig.id,
        contract_id=sig.contract_id,
        status=sig.status,
    )


@router.get(
    "/contracts/{contract_id}/signatures",
    response_model=list[DocumentSignatureResponse],
    dependencies=_DELIVERY_SECTION_DEPENDENCIES,
)
async def list_signatures_for_contract(
    contract_id: int,
    current_user: ContractSignatureReadUser,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentSignature]:
    """Most-recent-first list of every send attempt on this contract.

    A contract may have multiple rows: rejected → re-sent, withdrawn → re-sent,
    failed → "Wyślij ponownie" creates a new row. The UI renders them as a
    timeline so the recruiter can audit history.
    """
    await assert_contract_legal_contract_access(db, current_user, contract_id)
    result = await db.execute(
        select(DocumentSignature)
        .where(DocumentSignature.contract_id == contract_id)
        .order_by(DocumentSignature.created_at.desc())
    )
    return list(result.scalars().all())


@router.get(
    "/signatures/{signature_id}",
    response_model=DocumentSignatureDetailResponse,
    dependencies=_DELIVERY_SECTION_DEPENDENCIES,
)
async def get_signature_detail(
    signature_id: int,
    current_user: ContractSignatureReadUser,
    db: AsyncSession = Depends(get_db),
) -> DocumentSignature:
    """Single signature + chronological event timeline (Phase 3 webhooks)."""
    sig = await db.scalar(
        select(DocumentSignature)
        .where(DocumentSignature.id == signature_id)
        .options(selectinload(DocumentSignature.events))
    )
    if sig is None:
        raise HTTPException(status_code=404, detail="Signature not found")
    await assert_contract_legal_contract_access(db, current_user, sig.contract_id)
    return sig


@router.post(
    "/signatures/{signature_id}/withdraw",
    response_model=DocumentSignatureResponse,
    dependencies=_DELIVERY_SECTION_DEPENDENCIES,
)
async def withdraw_signature(
    signature_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> DocumentSignature:
    """Cancel a sent process. Calls Autenti `withdraw` action."""
    _require_enabled()
    sig = await db.scalar(
        select(DocumentSignature).where(DocumentSignature.id == signature_id)
    )
    if sig is None:
        raise HTTPException(status_code=404, detail="Signature not found")
    await assert_contract_legal_contract_access(
        db, current_user, sig.contract_id, write=True
    )
    if sig.status not in (
        SignatureStatus.sent,
        SignatureStatus.in_progress,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot withdraw signature in status={sig.status.value}; "
                "only `sent` or `in_progress` can be withdrawn."
            ),
        )
    if not sig.autenti_process_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Signature has no Autenti process_id (still sending?).",
        )

    try:
        config = AutentiConfig.from_settings()
        async with AutentiClient(config) as client:
            await client.withdraw(sig.autenti_process_id)
    except AutentiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Autenti withdraw failed: {exc}",
        )

    sig.status = SignatureStatus.withdrawn
    db.add(
        Activity(
            entity_type="contract",
            entity_id=sig.contract_id,
            action="signature_withdrawn",
            user_id=current_user.id,
            external_source="autenti",
            external_id=sig.autenti_process_id,
        )
    )
    await db.commit()
    await db.refresh(sig)
    return sig


@router.post(
    "/signatures/{signature_id}/remind",
    response_model=DocumentSignatureResponse,
    dependencies=_DELIVERY_SECTION_DEPENDENCIES,
)
async def remind_signer(
    signature_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
) -> DocumentSignature:
    """Trigger Autenti `remind` action. Throttled at 1 reminder / hour."""
    _require_enabled()
    sig = await db.scalar(
        select(DocumentSignature).where(DocumentSignature.id == signature_id)
    )
    if sig is None:
        raise HTTPException(status_code=404, detail="Signature not found")
    await assert_contract_legal_contract_access(
        db, current_user, sig.contract_id, write=True
    )
    if sig.status not in (
        SignatureStatus.sent,
        SignatureStatus.in_progress,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot remind signature in status={sig.status.value}; "
                "only `sent` or `in_progress` are pending signature."
            ),
        )
    if not sig.autenti_process_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Signature has no Autenti process_id (still sending?).",
        )

    # Throttle: refuse if a remind Activity exists for this signature
    # within the last hour.
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = await db.scalar(
        select(Activity)
        .where(
            Activity.entity_type == "contract",
            Activity.entity_id == sig.contract_id,
            Activity.action == "signature_remind_sent",
            Activity.external_id == sig.autenti_process_id,
            Activity.created_at >= one_hour_ago,
        )
        .limit(1)
    )
    if recent is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Reminder already sent within the last hour. Wait before retrying.",
        )

    try:
        config = AutentiConfig.from_settings()
        async with AutentiClient(config) as client:
            await client.remind(sig.autenti_process_id)
    except AutentiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Autenti remind failed: {exc}",
        )

    db.add(
        Activity(
            entity_type="contract",
            entity_id=sig.contract_id,
            action="signature_remind_sent",
            user_id=current_user.id,
            external_source="autenti",
            external_id=sig.autenti_process_id,
        )
    )
    await db.commit()
    await db.refresh(sig)
    return sig


@router.get("/health")
async def autenti_health(
    current_user: CurrentUser,
) -> dict:
    """Lightweight health probe for the Autenti integration.

    Returns ``{healthy, has_credentials, last_token_refresh_seconds_ago}``.
    Useful for the on-call playbook (see docs/autenti-integration.md).
    """
    from app.services.autenti.webhook_verify import _jwks_fetched_at

    has_creds = bool(
        getattr(
            __import__("app.core.config", fromlist=["settings"]), "settings"
        ).AUTENTI_CLIENT_ID
    )
    age = None
    if _jwks_fetched_at:
        age = int(datetime.now(timezone.utc).timestamp() - _jwks_fetched_at)

    return {
        "enabled": True,  # Router only mounts when enabled, so this is implicit.
        "has_credentials": has_creds,
        "jwks_cache_age_seconds": age,
    }


@router.post("/webhook", response_model=AutentiWebhookResponse)
async def receive_autenti_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AutentiWebhookResponse:
    """Receive a JWT-signed webhook from Autenti.

    No FastAPI auth dependency — the JWT signature IS the auth. Body is the
    raw JWT (Autenti uses a compact JWS over JSON).

    Returns 200 with ``status: "ok" | "duplicate" | "ignored"``. Always 200
    (or 401 on bad signature) — Autenti retries 4xx/5xx, so unknown
    process_id MUST 200 to break the retry loop.

    503 when AUTENTI_ENABLED=false (Autenti will retry 5xx — webhook
    payload isn't lost during a rolling rollback).
    """
    _require_enabled()
    raw = await request.body()
    token = raw.decode("utf-8", errors="replace").strip()
    # Some Autenti deployments wrap the JWT in JSON: {"jwt": "..."}
    if token.startswith("{"):
        try:
            import json

            parsed = json.loads(token)
            token = parsed.get("jwt") or parsed.get("token") or token
        except json.JSONDecodeError:
            pass

    if not token:
        logger.warning("Empty Autenti webhook body")
        raise HTTPException(status_code=400, detail="Empty body")

    try:
        claims = await verify_jwt(token)
    except AutentiWebhookError as exc:
        logger.warning("Autenti webhook JWT verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Webhook signature invalid: {exc}",
        )

    outcome = await handle_event(db, claims)
    return AutentiWebhookResponse(status=outcome)
