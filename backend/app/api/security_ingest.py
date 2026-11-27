"""Wejście źródeł dla ekranu Bezpieczeństwo (0799): CrowdSec, Falco, Wazuh, CI.

Wyłącznie klucz konta serwisowego ze scope'em ``security:ingest``
(``allow_admin_jwt=False`` — przeglądarka nie ma tu czego szukać), limit
``SECURITY_INGEST_RATE_LIMIT`` na konto. Klucz nie czyta niczego z NEXUSA:
odpowiedź to same liczniki. Kontrakt formatów: ``docs/claude/ui/ekran-bezpieczenstwo.md``.

Bez ``from __future__ import annotations`` — moduł ma ``@limiter.limit``
(slowapi #579: ciało żądania ląduje wtedy jako parametr query → 422).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, require_service_scope
from app.api.integrations_v1.common import principal_rate_key
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.service_account import ServiceScope
from app.services.security_ingest import (
    FalcoEvent,
    IngestBatch,
    IngestResult,
    SourceOwnedByOtherAccount,
    WazuhAlert,
    falco_to_event,
    ingest_batch,
    wazuh_to_event,
)

router = APIRouter()

IngestCaller = Annotated[
    Caller,
    Depends(require_service_scope(ServiceScope.security_ingest, allow_admin_jwt=False)),
]


def _rate_limit() -> str:
    return settings.SECURITY_INGEST_RATE_LIMIT


def _account_id(caller: Caller) -> int | None:
    return caller.service.account_id if caller.service else None


async def _ingest(db: AsyncSession, batch: IngestBatch, caller: Caller) -> IngestResult:
    try:
        return await ingest_batch(db, batch, service_account_id=_account_id(caller))
    except SourceOwnedByOtherAccount:
        await db.rollback()
        raise HTTPException(
            status_code=403,
            detail={
                "error": "source_owned_by_other_account",
                "message": (
                    f"Źródło „{batch.source}” wysyła inne konto serwisowe. "
                    "Każde źródło ma własne konto."
                ),
            },
        ) from None


@router.post("/ingest", status_code=202)
@limiter.limit(_rate_limit, key_func=principal_rate_key)
async def ingest(
    request: Request,
    body: IngestBatch,
    caller: IngestCaller,
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Format ogólny: zdarzenia i znaleziska jednego źródła."""
    result = await _ingest(db, body, caller)
    return result.as_dict()


@router.post("/ingest/falco", status_code=202)
@limiter.limit(_rate_limit, key_func=principal_rate_key)
async def ingest_falco(
    request: Request,
    body: FalcoEvent,
    caller: IngestCaller,
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Zdarzenie Falco z Falcosidekicka (webhook)."""
    batch = IngestBatch(source="falco", events=[falco_to_event(body)])
    result = await _ingest(db, batch, caller)
    return result.as_dict()


@router.post("/ingest/wazuh", status_code=202)
@limiter.limit(_rate_limit, key_func=principal_rate_key)
async def ingest_wazuh(
    request: Request,
    body: WazuhAlert,
    caller: IngestCaller,
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Alert Wazuha z integracji."""
    batch = IngestBatch(source="wazuh", events=[wazuh_to_event(body)])
    result = await _ingest(db, batch, caller)
    return result.as_dict()
