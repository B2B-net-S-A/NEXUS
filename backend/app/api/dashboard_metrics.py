"""Własna metryka pulpitu — katalog źródeł i liczenie (kreator + kafelki).

`POST /evaluate` jest odczytem (definicja jest zbyt złożona na query string),
więc stoi w `READ_ONLY_POST_ROUTE_TEMPLATES`. Router wymaga odczytu
którejkolwiek sekcji z danymi; o dostępie do KONKRETNEGO źródła decyduje
silnik (`services/custom_metrics/engine.py`) przy każdym zapytaniu.

Moduł celowo BEZ `from __future__ import annotations` — ma `@limiter.limit`
(PEP 563 + slowapi #579 zamienia body w parametr query, czyli 422).
"""

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.section_access import require_section_access_any_read
from app.core.cache import cache_get, cache_set
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.scheduling import business_today
from app.services.access_scope import resolve_dashboard_scope
from app.services.custom_metrics.definition import MetricDefinition
from app.services.custom_metrics.engine import (
    MetricAccessDenied,
    access_fingerprint,
    evaluate_metric,
    metric_catalog,
)
from app.services.section_permissions import ProductSection

router = APIRouter(
    dependencies=[
        Depends(
            require_section_access_any_read(
                ProductSection.pipeline,
                ProductSection.sourcing,
                ProductSection.delivery,
                ProductSection.insights,
                ProductSection.finance,
            )
        )
    ]
)

_CACHE_TTL_SECONDS = 120
_CACHE_PREFIX = "dashboard_metric:v2"


def _denied(exc: MetricAccessDenied) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "metric_scope_denied", "message": str(exc)},
    )


@router.get("/catalog")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def get_metric_catalog(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Źródła, miary i zakresy, które TO konto może policzyć."""
    return await metric_catalog(db, current_user)


@router.post("/evaluate")
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def evaluate(
    request: Request,
    definition: MetricDefinition,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Liczy metrykę. 403 `metric_scope_denied` = brak dostępu, nie zero."""
    today = business_today()
    scope = await resolve_dashboard_scope(current_user, db)
    try:
        # Uprawnienia do źródła i granica klientów liczone PRZED cache
        # (runda 8, R8-N10-4) — odebrana sekcja albo klient nie przeżywa
        # w wyniku zapamiętanym na 2 minuty.
        access = await access_fingerprint(db, current_user, definition)
    except MetricAccessDenied as exc:
        raise _denied(exc) from exc
    # Klucz obejmuje zakres konta, granicę klientów i dzień: dwie osoby
    # o różnych uprawnieniach nigdy nie dzielą wyniku, a „teraz" nie
    # przeżywa północy.
    raw = json.dumps(
        {
            "d": definition.model_dump(mode="json"),
            "u": current_user.id,
            "s": scope.cache_token(),
            "a": access,
            "t": today.isoformat(),
        },
        sort_keys=True,
    )
    key = f"{_CACHE_PREFIX}:{hashlib.sha256(raw.encode()).hexdigest()}"
    cached = await cache_get(key)
    if cached is not None:
        return cached
    try:
        result = await evaluate_metric(
            db, current_user, definition, today=today, scope=scope
        )
    except MetricAccessDenied as exc:
        raise _denied(exc) from exc
    payload = result.as_payload()
    await cache_set(key, payload, ttl_seconds=_CACHE_TTL_SECONDS)
    return payload
