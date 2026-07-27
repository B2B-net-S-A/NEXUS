"""Audyt M7 PR-02 (P0.3): DYNAREPORTER_MODE=read_only egzekwuje read-only.

Dotąd read_only nie przechwytywało mutacji — tylko ``off`` dawało 410, a
read_only puszczało POST/PUT/PATCH/DELETE (split-brain: „archiwum", które nadal
przyjmuje zapisy). Teraz każda metoda mutująca na ``/api/dynareporter`` daje 409
``DYNAREPORTER_READ_ONLY``, chyba że ścieżka jest zwolniona (mindy / read-marker /
upload) albo operator włączył break-glass.

Middleware ``LegacyStatsDeprecationMiddleware`` odpala PRZED auth, więc testujemy
bez logowania — 409 przychodzi zanim guard roli zdąży odpowiedzieć.
"""

from __future__ import annotations

import re

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import (
    _DYNAREPORTER_MUTATING_METHODS,
    _dynareporter_write_exempt,
    app,
)


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


def _dyna_write_routes() -> list[tuple[str, str]]:
    """Wszystkie zarejestrowane mutujące trasy ``/api/dynareporter``."""
    from tests._route_introspection import iter_api_routes

    out: set[tuple[str, str]] = set()
    for path, route in iter_api_routes(app):
        methods = getattr(route, "methods", None) or set()
        if not path.startswith("/api/dynareporter"):
            continue
        for m in methods & _DYNAREPORTER_MUTATING_METHODS:
            out.add((m, path))
    return sorted(out)


def _concrete(path: str) -> str:
    """{param} → '1' — middleware patrzy na string ścieżki, nie na routing."""
    return re.sub(r"\{[^}]+\}", "1", path)


@pytest.mark.asyncio
async def test_read_only_blocks_every_report_write(client, monkeypatch):
    """Enumeracja: każda mutująca trasa DR (poza zwolnioną) → 409 przy read_only.

    To bramka anty-regresyjna: nowa niezabezpieczona trasa write DR automatycznie
    zostanie tu wychwycona, bo iterujemy po realnie zarejestrowanych trasach.
    """
    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "read_only")
    monkeypatch.setattr(settings, "DYNAREPORTER_WRITE_BREAKGLASS", False)

    routes = _dyna_write_routes()
    assert routes, "nie znaleziono żadnych mutujących tras DR — regresja setupu"

    offenders: list[str] = []
    for method, path in routes:
        if _dynareporter_write_exempt(path, method):
            continue
        resp = await client.request(method, _concrete(path), json={})
        code = None
        if resp.headers.get("content-type", "").startswith("application/json"):
            code = resp.json().get("code")
        if resp.status_code != 409 or code != "DYNAREPORTER_READ_ONLY":
            offenders.append(f"{method} {path} -> {resp.status_code} (code={code})")
    assert not offenders, f"read_only nie zablokowało mutacji: {offenders}"


@pytest.mark.asyncio
async def test_read_only_allows_get(client, monkeypatch):
    """GET nie jest blokowany — 409 dotyczy tylko metod mutujących."""
    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "read_only")
    resp = await client.get("/api/dynareporter/competitions/winners")
    assert resp.status_code != 409


@pytest.mark.asyncio
async def test_breakglass_lets_writes_through(client, monkeypatch):
    """Break-glass zdejmuje blokadę — mutacja przechodzi middleware (dalej trafia
    w auth/guard, NIE w 409 read-only)."""
    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "read_only")
    monkeypatch.setattr(settings, "DYNAREPORTER_WRITE_BREAKGLASS", True)
    resp = await client.post("/api/dynareporter/board-dashboard/monthly", json={})
    assert resp.status_code != 409, (
        f"break-glass powinien przepuścić do auth, dostał {resp.status_code}"
    )


@pytest.mark.asyncio
async def test_mindy_exempt_from_read_only(client, monkeypatch):
    """mindy/* (LLM, stateless — nie tworzy danych raportowych) nie jest 409."""
    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "read_only")
    monkeypatch.setattr(settings, "DYNAREPORTER_WRITE_BREAKGLASS", False)
    resp = await client.post("/api/dynareporter/mindy/commentary", json={})
    assert resp.status_code != 409


@pytest.mark.asyncio
async def test_notification_read_marker_exempt(client, monkeypatch):
    """Self-scoped read-marker powiadomień konkursu nie jest blokowany."""
    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "read_only")
    monkeypatch.setattr(settings, "DYNAREPORTER_WRITE_BREAKGLASS", False)
    resp = await client.patch("/api/dynareporter/competitions/notifications/1/read")
    assert resp.status_code != 409


@pytest.mark.asyncio
async def test_off_mode_takes_precedence_with_410(client, monkeypatch):
    """off ma pierwszeństwo nad read_only — 410 (wygaszone) na mutacji, nie 409."""
    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "off")
    resp = await client.post("/api/dynareporter/board-dashboard/monthly", json={})
    assert resp.status_code == 410
