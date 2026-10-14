"""Wspólne elementy API integracyjnego v1 (``/api/integrations/v1``, 0442).

Decyzja Artura 14.10.2026: procesy firmy (na start rozliczanie klientów)
podpinane pod NEXUSA przez stabilne, udokumentowane API dla automatyzacji.
Trasy ekranów zmieniają się kilka razy dziennie — v1 jest osobną warstwą
z umową: dodanie pola jest zgodne, usunięcie albo zmiana znaczenia = v2
(pilnuje snapshot ``tests/data/integrations_v1_openapi.json``).

UWAGA: moduły v1 NIE MOGĄ mieć ``from __future__ import annotations`` —
PEP 563 + slowapi #579 zamieniają guard ``Annotated`` w parametr QUERY
(422 na poprawnym żądaniu). Pilnuje ``tests/test_public_surface_hardening.py``.
"""

import logging
from decimal import Decimal
from typing import Annotated, Any, Awaitable, Callable, Generic, Optional, TypeVar

from fastapi import Depends, HTTPException, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, PlainSerializer
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import Caller, require_service_scope
from app.core.config import settings
from app.core.rate_limit import client_ip_key
from app.models.service_account import ServiceScope
from app.services import integration_receipts
from app.services.integration_actor import IntegrationActor, actor_for
from app.services.oauth_route_scopes import route_template
from app.services.service_account_auth import ServicePrincipal

logger = logging.getLogger(__name__)

PREFIX = "/api/integrations/v1"
MAX_PAGE_SIZE = 500
# Id w ścieżce i numer strony w zakresie int4 Postgresa — wartość spoza
# zakresu dawała 500 (przepełnienie parametru asyncpg) zamiast 422.
INT4_MAX = 2_147_483_647
MAX_PAGE = 100_000
IdPath = Annotated[int, Path(ge=1, le=INT4_MAX)]
PageQuery = Annotated[int, Query(ge=1, le=MAX_PAGE)]
PageSizeQuery = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]

# ── Koperta błędu ────────────────────────────────────────────────────────────

_DEFAULT_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    410: "gone",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    503: "unavailable",
}


def error_response(
    status_code: int,
    detail: Any,
    headers: Optional[dict] = None,
) -> JSONResponse:
    """``{"error": {"code", "message", "details"}}`` — jeden kształt dla v1.

    Szczegóły z ``HTTPException(detail={...})`` (np. ``insufficient_scope``
    z brakującymi scope'ami) trafiają do ``details`` bez zmian.
    """
    code = _DEFAULT_CODES.get(status_code, "error")
    message = "Błąd żądania."
    details: Any = None
    if isinstance(detail, dict):
        code = str(detail.get("error") or detail.get("code") or code)
        message = str(detail.get("message") or detail.get("detail") or message)
        rest = {
            k: v
            for k, v in detail.items()
            if k not in {"error", "code", "message", "detail"}
        }
        details = rest or None
    elif isinstance(detail, str) and detail:
        message = detail
    elif detail is not None:
        details = detail
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {"error": {"code": code, "message": message, "details": details}}
        ),
        headers=headers,
    )


class IntegrationApiError(Exception):
    """Błąd trasy v1 niosący gotową odpowiedź w kopercie v1.

    Celowo WYJĄTEK, a nie zwrócona odpowiedź: musi przejść przez stos
    zależności żądania, żeby ``get_db`` zrobił ROLLBACK. Zwrócenie odpowiedzi
    z wnętrza handlera trasy kończyło zależności normalnie, więc ``get_db``
    robił COMMIT — paragon idempotencji zostawał ``pending`` na zawsze,
    a import MD przerwany konfliktem zostawiał zatwierdzoną partię (przegląd
    PR 2A, 14.10.2026; ``tests/test_integrations_v1_transactions.py``).
    """

    def __init__(self, response: JSONResponse) -> None:
        super().__init__(response.status_code)
        self.response = response


async def integration_error_handler(_request: Request, exc: Exception) -> Response:
    """Handler aplikacji (``main.py``) — oddaje odpowiedź z ``IntegrationApiError``."""
    assert isinstance(exc, IntegrationApiError)
    return exc.response


class IntegrationRoute(APIRoute):
    """Trasa v1: każdy błąd (także z zależności i walidacji) w kopercie v1.

    Globalne handlery (`main.py`) zostają bez zmian dla reszty aplikacji —
    ekrany czytają ``detail`` i tak ma zostać.
    """

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                errors = [
                    {
                        "loc": list(err.get("loc", ())),
                        "msg": err.get("msg"),
                        "type": err.get("type"),
                    }
                    for err in exc.errors()
                ]
                raise IntegrationApiError(
                    error_response(
                        422,
                        {
                            "error": "validation_error",
                            "message": "Nieprawidłowe dane żądania.",
                            "errors": errors,
                        },
                    )
                ) from exc
            except RateLimitExceeded as exc:
                raise IntegrationApiError(
                    error_response(
                        429,
                        {
                            "error": "rate_limited",
                            "message": f"Za dużo zapytań ({exc.detail}). Spróbuj za minutę.",
                        },
                        headers={"Retry-After": "60"},
                    )
                ) from exc
            except StarletteHTTPException as exc:
                raise IntegrationApiError(
                    error_response(
                        exc.status_code,
                        exc.detail,
                        headers=getattr(exc, "headers", None),
                    )
                ) from exc

        return handler


# ── Limity tempa (per konto serwisowe, nie per IP) ───────────────────────────


def principal_rate_key(request: Request) -> str:
    """Klucz limitu: konto serwisowe (ustawione przy uwierzytelnieniu)."""
    principal = getattr(request.state, "service_principal", None)
    if principal is not None:
        return f"service_account:{principal.account_id}"
    return client_ip_key(request)


def read_rate_limit() -> str:
    """Callable — czytany przy każdym żądaniu, zmiana env bez deployu kodu."""
    return settings.INTEGRATIONS_V1_READ_RATE_LIMIT


def write_rate_limit() -> str:
    return settings.INTEGRATIONS_V1_WRITE_RATE_LIMIT


# ── Zależności scope'ów (tylko klucz API, bez JWT) ───────────────────────────


def _scoped(*scopes: ServiceScope):
    return Depends(require_service_scope(*scopes, allow_admin_jwt=False))


ClientsRead = Annotated[Caller, _scoped(ServiceScope.clients_read)]
ContractsRead = Annotated[Caller, _scoped(ServiceScope.contracts_read)]
OrdersRead = Annotated[Caller, _scoped(ServiceScope.orders_read)]
MdRead = Annotated[Caller, _scoped(ServiceScope.md_read)]
MdWrite = Annotated[Caller, _scoped(ServiceScope.md_write)]
FinanceRead = Annotated[Caller, _scoped(ServiceScope.finance_read)]
FinanceWrite = Annotated[Caller, _scoped(ServiceScope.finance_write)]
InvoicesRead = Annotated[Caller, _scoped(ServiceScope.invoices_read)]
InvoicesWrite = Annotated[Caller, _scoped(ServiceScope.invoices_write)]


def principal_of(caller: Caller) -> ServicePrincipal:
    if caller.service is None:  # pragma: no cover - zależności v1 nie dają JWT
        raise HTTPException(401, detail="Wymagany klucz API")
    return caller.service


def can_see_amounts(caller: Caller) -> bool:
    """Stawki i kwoty w zamówieniach/kontraktach — osobny scope ``amounts:read``."""
    return ServiceScope.amounts_read.value in principal_of(caller).scopes


def integration_actor(caller: Caller) -> IntegrationActor:
    return actor_for(principal_of(caller))


# ── Kwoty i stronicowanie ────────────────────────────────────────────────────


def _money(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    return format(Decimal(value).quantize(Decimal("0.01")), "f")


#: Kwota jako napis dziesiętny ``"1234.50"`` — float gubi grosze.
Money = Annotated[
    Optional[Decimal],
    PlainSerializer(_money, return_type=Optional[str], when_used="json"),
]

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
    has_more: bool


def page_of(items: list, *, page: int, page_size: int, total: int) -> dict:
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": page * page_size < total,
    }


# ── Zapis idempotentny ───────────────────────────────────────────────────────


async def idempotent_write(
    request: Request,
    db: AsyncSession,
    caller: Caller,
    *,
    payload: Any,
    run: Callable[[], Awaitable[tuple[int, Any]]],
) -> Response:
    """Paragon → zapis → odpowiedź w paragonie → commit (jedna transakcja).

    ``run`` wykonuje zapis BEZ commita i zwraca ``(status, ciało)``.
    """
    principal = principal_of(caller)
    route = route_template(request) or request.url.path
    receipt, replay = await integration_receipts.begin(
        db,
        principal,
        raw_key=request.headers.get(integration_receipts.IDEMPOTENCY_HEADER),
        method=request.method,
        route=route,
        payload=payload,
    )
    if replay is not None:
        return JSONResponse(
            status_code=replay.status_code,
            content=replay.body,
            headers={integration_receipts.REPLAYED_HEADER: "true"},
        )
    status_code, body = await run()
    encoded = jsonable_encoder(body)
    await integration_receipts.finish(
        db, receipt, status_code=status_code, body=encoded
    )
    await db.commit()
    return JSONResponse(status_code=status_code, content=encoded)


async def dry_run_response(
    db: AsyncSession, run: Callable[[], Awaitable[tuple[int, Any]]]
) -> Response:
    """Próba: pełne przeliczenie, odpowiedź zbudowana PRZED wycofaniem.

    Zawsze 200 — nic nie powstało, więc „201 Created” byłoby nieprawdą.
    """
    try:
        _status_code, body = await run()
        encoded = jsonable_encoder(body)
    finally:
        await db.rollback()
    if isinstance(encoded, dict):
        encoded = {**encoded, "dry_run": True}
    return JSONResponse(status_code=200, content=encoded)
