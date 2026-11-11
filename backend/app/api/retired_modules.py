"""Adresy usuniętych modułów odpowiadają 410 z komunikatem zamiast 404.

D1 z audytu 07.11.2026: Akademia, Praktykant, Traffit, telefonia i Analytics v1
zniknęły z kodu, tabele zostały. 410 mówi klientowi (stara karta przeglądarki,
skrypt, klucz API), że adresu nie będzie, i podaje powód po polsku.

Handler działa tylko wtedy, gdy żadna trasa nie pasuje do adresu. Trasa, która
nadal istnieje pod takim prefiksem (np. ``GET /api/admin/traffit/sync/status``),
odpowiada normalnie, także własnym 404.
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

_ACADEMY = "Akademia została usunięta z NEXUSA (decyzja z 08.11.2026)."
_TRAINEE = "Program praktykantów został usunięty z NEXUSA (decyzja z 08.11.2026)."
_ANALYTICS = "Analytics v1 zostało usunięte z NEXUSA. Statystyki są w Insights."
_CLOUDTALK = "Integracja CloudTalk została usunięta z NEXUSA."
_TRAFFIT = (
    "Traffit jest wyłączony od 14.10.2026 — NEXUS nie importuje już danych z Traffita."
)

RETIRED_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/api/academy", _ACADEMY),
    ("/api/integrations/v1/academy", _ACADEMY),
    ("/api/trainee", _TRAINEE),
    ("/api/analytics/v1", _ANALYTICS),
    ("/api/cloudtalk", _CLOUDTALK),
    ("/api/admin/traffit", _TRAFFIT),
)

RETIRED_EXACT: dict[str, str] = {
    "/api/calls/webhook": _CLOUDTALK,
    "/api/calls/cloudtalk-status": _CLOUDTALK,
}


def retired_message(path: str) -> str | None:
    """Komunikat, gdy ``path`` należy do usuniętego modułu, inaczej ``None``."""
    if path in RETIRED_EXACT:
        return RETIRED_EXACT[path]
    for prefix, message in RETIRED_PREFIXES:
        if path == prefix or path.startswith(f"{prefix}/"):
            return message
    return None


async def _not_found_or_gone(request: Request, exc: Exception) -> Response:
    no_route_matched = "endpoint" not in request.scope
    message = retired_message(request.url.path) if no_route_matched else None
    if message is not None:
        return JSONResponse(status_code=410, content={"detail": message})
    assert isinstance(exc, (HTTPException, StarletteHTTPException))
    return await http_exception_handler(request, exc)


def install_retired_modules(app: FastAPI) -> None:
    app.add_exception_handler(404, _not_found_or_gone)
