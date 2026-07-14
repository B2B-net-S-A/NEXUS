"""DynaReporter B.3 — Cutover: redirect dla legacy reports.dynaminds.pl deep-linków.

Po cutoverze reports.dynaminds.pl → CNAME → nexus.dynaminds.pl. Deep-linki
typu reports.dynaminds.pl/body-leasing albo /sales muszą zostać
przekierowane na odpowiednie nexus.dynaminds.pl/dynareporter/<moduł>.

Pierwszy etap cutoveru zwraca tymczasowe 307 do skonsolidowanych ekranów. Po
zatwierdzeniu parity status może zostać zmieniony na 308.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter()


# Mapping starych URL DynaReporter → nowych w Nexusie.
LEGACY_PATH_MAP = {
    "/login": "/login",  # global login
    "/dashboard": "/insights?tab=rekrutacja",
    "/body-leasing": "/insights?tab=rekrutacja",
    "/rekrutacja": "/insights?tab=rekrutacja",
    "/placements": "/insights?tab=rekrutacja",
    "/competitions": "/insights?tab=rekrutacja",
    "/sales": "/insights?tab=klienci",
    "/delivery-lead": "/insights?tab=klienci",
    "/clients": "/insights?tab=klienci",
    "/mrr": "/insights?tab=klienci",
    "/finances": "/insights?tab=zarzad",
    "/przetargi": "/insights?tab=zarzad",
    "/board": "/insights?tab=zarzad",
    "/sales-mgmt": "/insights?tab=klienci",
    "/mindy": "/dynareporter/mindy",
    "/chat": "/dynareporter/mindy",
    "/upload": "/candidates/bulk-import",
    "/admin": "/settings?tab=administracja",
}


@router.get("/_legacy/{path:path}", include_in_schema=False)
async def legacy_redirect(path: str, request: Request) -> RedirectResponse:
    """307 redirect dla starych URL DynaReportera.

    Mountowany pod prefix `/api/dynareporter/_legacy/<old_path>`. Cloudflare
    Page Rule może wskazywać reports.dynaminds.pl/<X> →
    nexus.dynaminds.pl/api/dynareporter/_legacy/<X>, ale prostsze
    rozwiązanie: po cutoverze user otwiera bezpośrednio nexus URL via
    sidebar Nexusa. Ten redirect to "safety net" dla zewnętrznych
    deep-linków (emaile, bookmarki).
    """
    # Normalize leading slash
    p = f"/{path.lstrip('/')}"
    # Dokładny match
    if p in LEGACY_PATH_MAP:
        return RedirectResponse(url=LEGACY_PATH_MAP[p], status_code=307)
    # Prefix match — np. /body-leasing/2026 → /dynareporter/body-leasing
    for legacy_prefix, new_prefix in LEGACY_PATH_MAP.items():
        if p.startswith(legacy_prefix + "/"):
            return RedirectResponse(url=new_prefix, status_code=307)
    # Fallback — landing page
    return RedirectResponse(url="/insights?tab=rekrutacja", status_code=307)
