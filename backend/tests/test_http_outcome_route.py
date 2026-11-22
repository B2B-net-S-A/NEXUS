"""`http_outcome.route` to pełny szablon trasy, także z dołączonego routera.

Pomiar 19.11.2026: 4856 z 70 222 linii miało `route == ""`, w tym 106 żądań
dłuższych niż 5 s. FastAPI 0.141 nie kopiuje tras przy `include_router`,
tylko wstawia do `scope["route"]` trasę z pod-routera, której `path` nie ma
prefiksu: `@router.get("")` dawało `""`, a `/{id}` z różnych routerów zlewało
się w jedną pozycję rankingu wolnych tras.
"""

import logging
from types import SimpleNamespace

import httpx
from fastapi import APIRouter, FastAPI

from app.core.request_correlation import RequestCorrelationMiddleware, route_template


def _app() -> FastAPI:
    inner = APIRouter()

    @inner.get("")
    async def listing() -> dict:
        return {}

    @inner.get("/{item_id}/details")
    async def details(item_id: int) -> dict:
        return {}

    outer = APIRouter(prefix="/outer")
    outer.include_router(inner, prefix="/inner")

    app = FastAPI()
    app.include_router(inner, prefix="/api/things")
    app.include_router(outer, prefix="/api")

    @app.get("/api/direct/{slug}")
    async def direct(slug: str) -> dict:
        return {}

    app.add_middleware(RequestCorrelationMiddleware)
    return app


async def _logged_route(caplog, path: str) -> str:
    caplog.clear()
    with caplog.at_level(logging.INFO):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app()), base_url="http://t"
        ) as client:
            await client.get(path)
    record = next(r for r in caplog.records if r.getMessage() == "http_outcome")
    return record.route


async def test_root_of_included_router_is_not_empty(caplog) -> None:
    assert await _logged_route(caplog, "/api/things") == "/api/things"


async def test_included_route_keeps_prefix_and_param_names(caplog) -> None:
    assert (
        await _logged_route(caplog, "/api/things/5/details")
        == "/api/things/{item_id}/details"
    )


async def test_nested_include_keeps_every_prefix(caplog) -> None:
    assert (
        await _logged_route(caplog, "/api/outer/inner/7/details")
        == "/api/outer/inner/{item_id}/details"
    )


async def test_route_declared_on_app_is_unchanged(caplog) -> None:
    assert await _logged_route(caplog, "/api/direct/abc") == "/api/direct/{slug}"


async def test_unmatched_path_is_not_logged_verbatim(caplog) -> None:
    assert await _logged_route(caplog, "/api/missing/123") == "unmatched-route"


def test_relative_route_without_context_falls_back_to_path_without_ids() -> None:
    # Gdyby FastAPI przestało podawać pełny szablon: ścieżka z nazwami
    # parametrów w miejscu wartości, nigdy pusty napis ani identyfikator.
    relative = APIRouter()

    @relative.get("/{item_id}/details")
    async def details(item_id: int) -> dict:
        return {}

    scope = {
        "path": "/api/things/5/details",
        "path_params": {"item_id": 5},
        "route": relative.routes[0],
    }
    assert route_template(scope) == "/api/things/{item_id}/details"

    empty = SimpleNamespace(path="", path_regex=None)
    assert route_template({"path": "/api/things", "route": empty}) == "/api/things"
