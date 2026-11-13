"""Limit ``@limiter.limit`` liczy się per TRASA, nie per adres URL.

Pentest stagingu 13.11.2026: slowapi 0.1.10 domyślnie ma ``key_style="url"``,
więc kubełek był osobny dla każdej wartości parametru ścieżki. 35 różnych
tokenów na ``GET /api/public/b2b-sign/{token}`` dało 35 × 404 i zero 429, ten
sam adres — 5 × 429 po 30 zapytaniach. Każda trasa z tokenem albo id w ścieżce
była w praktyce bez limitu, a zgadywanie tokenów — bez hamulca.

Skutek uboczny zmiany: trasa za logowaniem z ``{id}`` i kluczem po IP dzieliła
dotąd kubełek per biuro i per id; teraz dzieliłaby JEDEN kubełek na całe biuro
(NAT). Dlatego takie trasy mają klucz po użytkowniku — pilnuje tego strażnik
na dole pliku.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

from app.core.rate_limit import client_ip_key, limiter


def _probe_app() -> FastAPI:
    # Budowana RAZ: każde udekorowanie dopisuje limit do tej samej nazwy funkcji
    # w ``limiter._route_limits``, więc druga aplikacja liczyłaby podwójnie.
    from slowapi import _rate_limit_exceeded_handler

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/probe-a/{token}")
    @limiter.limit("3/minute")
    async def probe_a(token: str, request: Request):
        return {"ok": True}

    @app.get("/probe-b/{token}")
    @limiter.limit("3/minute")
    async def probe_b(token: str, request: Request):
        return {"ok": True}

    return app


_PROBE_APP = _probe_app()


@pytest.fixture
def client():
    was_enabled = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    try:
        yield TestClient(_PROBE_APP)
    finally:
        limiter.reset()
        limiter.enabled = was_enabled


def test_limiter_counts_per_endpoint():
    assert limiter._key_style == "endpoint"


def test_rotating_path_tokens_share_one_bucket(client):
    """Seria różnych tokenów z jednego adresu wpada w limit trasy."""
    statuses = [client.get(f"/probe-a/token-{i}").status_code for i in range(4)]

    assert statuses == [200, 200, 200, 429]


def test_different_routes_keep_separate_buckets(client):
    """Kubełek jest per funkcja trasy: wyczerpanie jednej nie blokuje drugiej."""
    for i in range(3):
        assert client.get(f"/probe-a/{i}").status_code == 200

    assert client.get("/probe-a/x").status_code == 429
    assert client.get("/probe-b/x").status_code == 200


# Trasy anonimowe (link z tokenem, wywołanie zwrotne bota) nie mają użytkownika,
# więc klucz po IP jest tam jedynym możliwym.
_ANONYMOUS_PREFIXES = ("/api/public/", "/api/integrations/")


def _limited_routes():
    from fastapi.routing import _iter_routes_with_context

    from app.main import app

    for original, context in _iter_routes_with_context(app.routes):
        endpoint = (context.endpoint if context else None) or getattr(
            original, "endpoint", None
        )
        if endpoint is None:
            continue
        name = f"{endpoint.__module__}.{endpoint.__name__}"
        path = (context.path if context else None) or original.path
        for lim in limiter._route_limits.get(name, []):
            yield path, name, lim


def test_logged_in_routes_with_path_params_are_not_limited_per_office_ip():
    """Biuro wychodzi jednym adresem — klucz po IP na trasie z ``{id}`` za
    logowaniem to jeden kubełek na wszystkich, np. ``pipeline-scores`` przy
    każdym otwarciu rekrutacji (30/min na całą firmę)."""
    offenders = sorted(
        {
            f"{path} ({name})"
            for path, name, lim in _limited_routes()
            if "{" in path
            and not path.startswith(_ANONYMOUS_PREFIXES)
            and lim.key_func is client_ip_key
        }
    )

    assert offenders == [], (
        "Trasa za logowaniem z parametrem w ścieżce ma limit po IP biura; "
        "dodaj key_func=user_or_ip_key:\n" + "\n".join(offenders)
    )


def test_guard_sees_the_limited_routes():
    """Strażnik bez tras nic nie sprawdza — upewnij się, że je widzi."""
    paths = {path for path, _name, _lim in _limited_routes()}

    assert "/api/auth/login" in paths
    assert "/api/jobs/{job_id}/pipeline-scores" in paths
