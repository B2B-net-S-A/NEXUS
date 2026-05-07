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

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, TacPlus
from app.core.database import get_db
from app.models.document_signature import DocumentSignature
from app.schemas.document_signature import (
    AutentiSendRequest,
    AutentiSendResponse,
    AutentiWebhookResponse,
    DocumentSignatureDetailResponse,
    DocumentSignatureResponse,
)
from app.services.autenti.sender import prepare_send, send_to_autenti
from app.services.autenti.webhook_handler import handle_event
from app.services.autenti.webhook_verify import (
    AutentiWebhookError,
    verify_jwt,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/contracts/{contract_id}/send",
    response_model=AutentiSendResponse,
    status_code=status.HTTP_202_ACCEPTED,
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
)
async def list_signatures_for_contract(
    contract_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentSignature]:
    """Most-recent-first list of every send attempt on this contract.

    A contract may have multiple rows: rejected → re-sent, withdrawn → re-sent,
    failed → "Wyślij ponownie" creates a new row. The UI renders them as a
    timeline so the recruiter can audit history.
    """
    result = await db.execute(
        select(DocumentSignature)
        .where(DocumentSignature.contract_id == contract_id)
        .order_by(DocumentSignature.created_at.desc())
    )
    return list(result.scalars().all())


@router.get(
    "/signatures/{signature_id}",
    response_model=DocumentSignatureDetailResponse,
)
async def get_signature_detail(
    signature_id: int,
    current_user: CurrentUser,
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
    return sig


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
    """
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
