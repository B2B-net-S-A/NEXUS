"""Trasy meta API integracyjnego v1: test połączenia i specyfikacja.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

import copy
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import Caller, require_service_scope_any
from app.api.integrations_v1.common import (
    PREFIX,
    IntegrationRoute,
    principal_of,
    principal_rate_key,
    read_rate_limit,
)
from app.core.rate_limit import limiter
from app.models.service_account import SCOPE_LABELS, ServiceScope
from app.services.service_account_health import EXPIRY_WARNING_DAYS

router = APIRouter(route_class=IntegrationRoute)

AnyKey = Annotated[Caller, Depends(require_service_scope_any())]

API_KEY_HEADER_SCHEME = {
    "type": "apiKey",
    "in": "header",
    "name": "X-API-Key",
    "description": "Klucz konta serwisowego (Ustawienia → Klucze API).",
}


class ScopeOut(BaseModel):
    value: str
    label: str


class MeOut(BaseModel):
    account: str
    name: str
    key_id: str
    scopes: list[ScopeOut]
    key_expires_at: Optional[datetime]
    key_expires_in_days: Optional[int]
    key_expires_soon: bool


@router.get("/me", response_model=MeOut, summary="Konto i uprawnienia klucza")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def me(request: Request, caller: AnyKey) -> MeOut:
    """Test połączenia: które konto, jakie scope'y i kiedy wygasa klucz."""
    principal = principal_of(caller)
    labels = {scope.value: SCOPE_LABELS[scope] for scope in ServiceScope}
    days: Optional[int] = None
    if principal.key_expires_at is not None:
        days = (principal.key_expires_at - datetime.now(timezone.utc)).days
    return MeOut(
        account=principal.slug,
        name=principal.name,
        key_id=principal.key_id,
        scopes=[
            ScopeOut(value=value, label=labels.get(value, value))
            for value in sorted(principal.scopes)
        ],
        key_expires_at=principal.key_expires_at,
        key_expires_in_days=days,
        key_expires_soon=days is not None and days <= EXPIRY_WARNING_DAYS,
    )


def integrations_openapi(full: dict) -> dict:
    """Specyfikacja WYŁĄCZNIE tras v1 z pełnej specyfikacji aplikacji.

    Pełny ``/openapi.json`` jest na produkcji wyłączony (inwentarz całej
    powierzchni ataku, ``main.py``). Tu wychodzą tylko ścieżki v1 i schematy,
    do których się odwołują, plus schemat bezpieczeństwa ``X-API-Key``.
    """
    paths = {
        path: item
        for path, item in full.get("paths", {}).items()
        if path.startswith(PREFIX)
    }
    schemas = full.get("components", {}).get("schemas", {})
    needed: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                if name not in needed and name in schemas:
                    needed.add(name)
                    walk(schemas[name])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(paths)
    spec = {
        "openapi": full.get("openapi", "3.1.0"),
        "info": {
            "title": "NEXUS — API integracyjne",
            "version": "1.0.0",
            "description": (
                "API dla automatyzacji procesów firmy (na start rozliczanie klientów). "
                "Uwierzytelnienie: nagłówek X-API-Key. Zapisy wymagają nagłówka "
                "Idempotency-Key (UUID). Wdrożenia NEXUSA odbywają się 18:00–08:00 "
                "(Europe/Warsaw) — w tym oknie możliwa ~2-minutowa przerwa; ponawiaj "
                "502/503 z odstępem."
            ),
        },
        "paths": copy.deepcopy(paths),
        "components": {
            "schemas": {name: schemas[name] for name in sorted(needed)},
            "securitySchemes": {"ApiKeyHeader": API_KEY_HEADER_SCHEME},
        },
        "security": [{"ApiKeyHeader": []}],
    }
    # Zależności czytają klucz z nagłówka ręcznie (nie przez `APIKeyHeader`),
    # więc FastAPI nie zna schematu — wycinamy jego domyślny `HTTPBearer`.
    for item in spec["paths"].values():
        for operation in item.values():
            if isinstance(operation, dict):
                operation.pop("security", None)
    return spec


@router.get("/openapi.json", include_in_schema=False)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def openapi_spec(request: Request, caller: AnyKey) -> JSONResponse:
    """Specyfikacja OpenAPI tras v1 (do importu w n8n, Power Automate, Postman)."""
    principal_of(caller)
    return JSONResponse(integrations_openapi(request.app.openapi()))
