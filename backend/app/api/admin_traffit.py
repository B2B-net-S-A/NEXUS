"""Admin endpoints for the scheduled Traffit → Nexus sync.

- ``POST /api/admin/traffit/sync?mode=delta|full`` — kick a run now (returns
  immediately; the import runs in the background). Used to activate / verify
  without waiting for the 02:00 UTC window.
- ``GET  /api/admin/traffit/sync/status`` — watermark + last-run stats per phase.

RBAC: admin z JWT **albo** konto serwisowe z odpowiednim scope'em
(``traffit:sync`` / ``traffit:read``) w nagłówku ``X-API-Key``.

To są endpointy odpalane operacyjnie poza przeglądarką — dokumentacja aktywacji
w CLAUDE.md każe „odpalić ``POST /api/admin/traffit/sync``", a pełny reconcile
domyka się przez kilkukrotne wywołanie. Robienie tego tokenem wyklikanym
w przeglądarce znaczyło, że automatyzacja podszywa się pod człowieka
poświadczeniem, które i tak umiera po 8 h. Scope'y są rozdzielone celowo:
klucz monitoringu czytający status nie ma prawa uruchomić pełnego importu.
"""

# UWAGA: bez `from __future__ import annotations` — PEP 563 zamienia adnotacje
# FastAPI w ForwardRef, a `@limiter.limit` (slowapi #579) rozwiązuje je już
# w SWOICH globalsach, więc `TraffitSyncCaller` przestaje być rozpoznawany
# i ląduje jako wymagany parametr QUERY. Ten sam trap co w
# `candidate_activity_summary.py`.

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TraffitReadCaller, TraffitSyncCaller
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.tasks import spawn
from app.tasks.traffit_sync import (
    run_traffit_sync,
    sync_is_running,
    validate_phases,
)

from app.services.traffit_status import read_traffit_status

router = APIRouter()


def _service_rate_limit() -> str:
    """Limit czytany przy KAŻDYM requeście, nie w chwili importu modułu.

    slowapi przyjmuje tu callable, więc zmiana ``SERVICE_ACCOUNT_RATE_LIMIT``
    w Coolify działa po restarcie procesu, a nie dopiero po przebudowie obrazu.
    """
    return settings.SERVICE_ACCOUNT_RATE_LIMIT


@router.post("/sync")
@limiter.limit(_service_rate_limit)
async def trigger_traffit_sync(
    request: Request,
    _caller: TraffitSyncCaller,
    mode: str = Query("delta", pattern="^(delta|full)$"),
    phases: Optional[str] = Query(
        None,
        description=(
            "Comma-separated phase names to run INSTEAD of the whole plan, "
            "e.g. `candidate_files,candidates_cv`. A partial run deliberately "
            "does NOT advance the __daily__/__full__ markers."
        ),
    ),
) -> Dict[str, Any]:
    """Trigger a Traffit sync run in the background. Admin JWT or ``traffit:sync``.

    ``request`` jest w sygnaturze, bo wymaga go slowapi (kubełek limitu per IP).
    """
    if not settings.TRAFFIT_SYNC_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Traffit sync disabled (TRAFFIT_SYNC_ENABLED=false)",
        )
    if sync_is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A Traffit sync is already running",
        )

    # Walidacja MUSI się wydarzyć tutaj, przed `create_task`. Bieg jest
    # fire-and-forget, więc `ValueError` rzucony w tasku poleciałby wyłącznie do
    # logów, a wywołujący dostałby 200 "started" za literówkę w nazwie fazy.
    #
    # Parsowanie po stronie ciała funkcji, nie przez `Annotated`/typ listy —
    # ten moduł ma `@limiter.limit`, a slowapi (#579) w połączeniu z PEP 563
    # potrafi wyprowadzić takie parametry jako WYMAGANE query i zwracać 422 na
    # poprawnym wywołaniu. Ten sam trap opisuje CLAUDE.md.
    selected: Optional[list[str]] = None
    if phases is not None:
        try:
            validated = validate_phases(
                [p.strip() for p in phases.split(",") if p.strip()]
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        # Z WALIDATORA, nie z surowego wejścia. Bieg i tak filtruje po zbiorze,
        # więc echo surowej listy pokazywałoby `?phases=a,a` jako dwie pozycje
        # przy jednym realnym przebiegu fazy — odpowiedź jest dla operatora
        # potwierdzeniem tego, co się uruchomi, i ma się z tym zgadzać.
        selected = sorted(validated)

    # Fire-and-forget: a full reconcile can take minutes/hours; don't block the
    # request. Progress is observable via GET /sync/status.
    spawn(run_traffit_sync(mode, phases=selected), f"traffit_sync(mode={mode})")
    out: Dict[str, Any] = {"status": "started", "mode": mode}
    if selected is not None:
        out["phases"] = selected
        out["markers_advanced"] = False
    return out


@router.get("/sync/status")
@limiter.limit(_service_rate_limit)
async def traffit_sync_status(
    request: Request,
    _caller: TraffitReadCaller,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    return await read_traffit_status(db)
