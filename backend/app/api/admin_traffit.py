"""Status archiwum Traffita — ``GET /api/admin/traffit/sync/status``.

Watermark i statystyki ostatniego biegu per faza, czytane z bazy NEXUSA
(kafelek „Traffit (archiwum)” w Ustawieniach, konta serwisowe).

RBAC: admin z JWT **albo** konto serwisowe ze scope'em ``traffit:read``
w nagłówku ``X-API-Key``.

Traffit jest wyłączony na stałe od 14.10.2026 (``traffit_retired.py``), a kod
importu i pozostałe trasy tego modułu usunięto 08.11.2026 (audyt 07.11, D1).
"""

# UWAGA: bez `from __future__ import annotations` — PEP 563 zamienia adnotacje
# FastAPI w ForwardRef, a `@limiter.limit` (slowapi #579) rozwiązuje je już
# w SWOICH globalsach, więc `TraffitReadCaller` przestaje być rozpoznawany
# i ląduje jako wymagany parametr QUERY. Ten sam trap co w
# `candidate_activity_summary.py`.

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TraffitReadCaller
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.services.traffit_status import read_traffit_status

router = APIRouter()


def _service_rate_limit() -> str:
    """Limit czytany przy KAŻDYM requeście, nie w chwili importu modułu.

    slowapi przyjmuje tu callable, więc zmiana ``SERVICE_ACCOUNT_RATE_LIMIT``
    w Coolify działa po restarcie procesu, a nie dopiero po przebudowie obrazu.
    """
    return settings.SERVICE_ACCOUNT_RATE_LIMIT


@router.get("/sync/status")
@limiter.limit(_service_rate_limit)
async def traffit_sync_status(
    request: Request,
    _caller: TraffitReadCaller,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await read_traffit_status(db)
