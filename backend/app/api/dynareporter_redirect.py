"""DynaReporter B.3 — Cutover: redirect dla legacy reports.dynaminds.pl deep-linków.

Po cutoverze reports.dynaminds.pl → CNAME → nexus.dynaminds.pl. Deep-linki
typu reports.dynaminds.pl/body-leasing albo /sales muszą zostać
przekierowane na odpowiednie nexus.dynaminds.pl/dynareporter/<moduł>.

Endpoint zwraca 301 dla starych ścieżek. CF proxy z CNAME + redirect tu —
pełne zachowanie linków.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter()


# Mapping starych URL DynaReporter → nowych w Nexusie.
LEGACY_PATH_MAP = {
    "/login": "/login",  # global login
    "/dashboard": "/dynareporter",
    "/body-leasing": "/dynareporter/body-leasing",
    "/sales": "/dynareporter/sales",
    "/delivery-lead": "/dynareporter/delivery-lead",
    "/placements": "/dynareporter/placements",
    "/clients": "/dynareporter/clients-mrr",
    "/mrr": "/dynareporter/clients-mrr",
    "/finances": "/dynareporter/clients-mrr",
    "/competitions": "/dynareporter/competitions",
    "/przetargi": "/dynareporter/przetargi",
    "/board": "/dynareporter/board",
    "/sales-mgmt": "/dynareporter/sales-mgmt",
    "/mindy": "/dynareporter/mindy",
    "/chat": "/dynareporter/mindy",
    "/upload": "/dynareporter/admin/upload",
    "/admin": "/dynareporter/admin/upload",
}


@router.get("/_legacy/{path:path}", include_in_schema=False)
async def legacy_redirect(path: str, request: Request) -> RedirectResponse:
    """301 redirect dla starych URL DynaReportera.

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
        return RedirectResponse(url=LEGACY_PATH_MAP[p], status_code=301)
    # Prefix match — np. /body-leasing/2026 → /dynareporter/body-leasing
    for legacy_prefix, new_prefix in LEGACY_PATH_MAP.items():
        if p.startswith(legacy_prefix + "/"):
            return RedirectResponse(url=new_prefix, status_code=301)
    # Fallback — landing page
    return RedirectResponse(url="/dynareporter", status_code=302)
