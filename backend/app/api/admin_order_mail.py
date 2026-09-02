"""Admin: pobieranie zamówień z maila — ręczny bieg, stan pętli, dziennik.

- ``POST /api/admin/order-mail/sync`` — bieg teraz (w tle); 503 gdy wyłączone,
  409 gdy bieg trwa. ``since_days`` = głębszy backfill z jawnym zakresem.
- ``GET  /api/admin/order-mail/status`` — watermark + statystyki ostatniego biegu.
- ``GET  /api/admin/order-mail/documents`` — dziennik (także wpisy ignorowane
  i nierozpoznane, których kolejka operatora nie pokazuje).

Walidacja PRZED ``create_task``: fire-and-forget znaczy, że błąd w tasku trafia
tylko do logów, a wołający dostałby 200 „started" na literówkę.
"""

# Bez `from __future__ import annotations` — patrz admin_traffit.py (PEP 563).
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.config import settings
from app.core.database import get_db
from app.models.order_mail import OUTCOMES, OrderMailDocument
from app.services.order_mail_ingest import (
    find_orders_connection,
    ingest_is_running,
    read_state,
    run_order_mail_ingest,
)

router = APIRouter()


@router.post("/sync")
async def trigger_order_mail_sync(
    _admin: AdminUser,
    since_days: Optional[int] = Query(None, ge=1, le=365),
) -> Dict[str, Any]:
    if not settings.ORDER_MAIL_INGEST_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pobieranie zamówień z maila wyłączone (ORDER_MAIL_INGEST_ENABLED=false)",
        )
    if ingest_is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Bieg już trwa"
        )
    since = (
        datetime.now(timezone.utc) - timedelta(days=since_days) if since_days else None
    )
    asyncio.create_task(run_order_mail_ingest(reason="manual", since=since))
    return {"status": "started", "since_days": since_days}


@router.get("/status")
async def order_mail_status(
    _admin: AdminUser, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    state = await read_state(db)
    conn = await find_orders_connection(db) if settings.ORDER_MAIL_UPN else None
    counts = await db.execute(
        select(OrderMailDocument.outcome, func.count()).group_by(
            OrderMailDocument.outcome
        )
    )
    return {
        "enabled": settings.ORDER_MAIL_INGEST_ENABLED,
        "upn_configured": bool(settings.ORDER_MAIL_UPN),
        "connection": {"id": conn.id, "upn": conn.mailbox_upn, "purpose": conn.purpose}
        if conn
        else None,
        "running": ingest_is_running(),
        "slots_local": settings.ORDER_MAIL_SLOTS_LOCAL,
        "autoapply_enabled": settings.ORDER_MAIL_AUTOAPPLY_ENABLED,
        "state": {
            k: (v.isoformat() if isinstance(v, datetime) else v)
            for k, v in (state or {}).items()
        },
        "outcomes": {row[0]: row[1] for row in counts.all()},
    }


@router.get("/documents")
async def list_order_mail_documents(
    _admin: AdminUser,
    outcome: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    if outcome is not None and outcome not in OUTCOMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Nieznany wynik {outcome!r}; dozwolone: {', '.join(OUTCOMES)}",
        )
    stmt = select(OrderMailDocument).order_by(
        OrderMailDocument.received_at.desc().nullslast(), OrderMailDocument.id.desc()
    )
    count_stmt = select(func.count()).select_from(OrderMailDocument)
    if outcome:
        stmt = stmt.where(OrderMailDocument.outcome == outcome)
        count_stmt = count_stmt.where(OrderMailDocument.outcome == outcome)
    total = await db.scalar(count_stmt)
    rows = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    return {
        "total": total or 0,
        "items": [
            {
                "id": r.id,
                "received_at": r.received_at.isoformat() if r.received_at else None,
                "sender_email": r.sender_email,
                "subject": r.subject,
                "attachment_name": r.attachment_name,
                "attachment_sha256": r.attachment_sha256,
                "outcome": r.outcome,
                "client_id": r.client_id,
                "client_key": r.client_key,
                "identification_method": r.identification_method,
                "identification_reason": r.identification_reason,
                "client_policy": r.client_policy,
                "gate_verdict": r.gate_verdict,
                "gate_reasons": r.gate_reasons,
                "document_meta": r.document_meta,
                "title": (r.extraction or {}).get("title"),
                "rows": len((r.extraction or {}).get("consultant_rows") or []),
                "error": r.error,
                "duplicate_of_id": r.duplicate_of_id,
            }
            for r in rows
        ],
    }
