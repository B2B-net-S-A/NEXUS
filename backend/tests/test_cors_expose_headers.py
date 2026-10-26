"""FE-01: przeglądarka musi móc odczytać ``X-Export-Truncated`` przez CORS.

Bez tego nagłówka na liście ``Access-Control-Expose-Headers`` frontend na
innym originie niż API nigdy nie widzi informacji o obciętym eksporcie
klientów i pokazuje częściowy plik jak kompletny.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

_EXTENSION_ORIGIN = "chrome-extension://" + "a" * 32


async def test_export_truncated_header_is_exposed_to_browsers() -> None:
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/health/live", headers={"Origin": _EXTENSION_ORIGIN}
        )
    exposed = {
        h.strip().lower()
        for h in response.headers.get("access-control-expose-headers", "").split(",")
    }
    assert "x-export-truncated" in exposed
    assert "content-disposition" in exposed


# ── Nagłówki ustawiane przez trasy dla frontu ───────────────────────────────
#
# Globalny ``CORSMiddleware`` NADPISUJE ``Access-Control-Expose-Headers``
# z odpowiedzi trasy (Starlette: ``headers.update(self.simple_headers)``).
# Trasa może więc wpisać sobie dowolną listę — przeglądarka zobaczy tylko tę
# z ``main.py``. Dlatego każdy nagłówek wystawiany przez trasę musi być też
# na liście globalnej: inaczej np. Generator Umów nie dostaje id zapisanego
# wiersza i drugie „Pobierz DOCX” zakłada nowy wpis z nowym numerem.


def _global_cors_kwargs() -> dict:
    from app.main import app

    for middleware in app.user_middleware:
        if middleware.cls is CORSMiddleware:
            return dict(middleware.kwargs)
    raise AssertionError("brak CORSMiddleware w app.main")


def _exposed(response) -> set[str]:
    return {
        h.strip().lower()
        for h in response.headers.get("access-control-expose-headers", "").split(",")
        if h.strip()
    }


async def test_contract_generator_ids_reach_browser_through_global_cors() -> None:
    from app.api.b2b_contract_generator import _docx_response

    kwargs = _global_cors_kwargs()
    probe = FastAPI()

    @probe.get("/docx")
    async def docx():
        return _docx_response(b"docx", "1/2026", generated_id=7)

    probe.add_middleware(CORSMiddleware, **kwargs)
    origin = kwargs["allow_origins"][0]

    async with AsyncClient(
        transport=ASGITransport(app=probe), base_url="http://test"
    ) as client:
        response = await client.get("/docx", headers={"Origin": origin})

    assert response.headers["x-generated-contract-id"] == "7"
    exposed = _exposed(response)
    assert "x-generated-contract-id" in exposed
    assert "x-contract-number" in exposed


def _route_exposed_headers() -> dict[str, set[str]]:
    """Nagłówki z literałów ``"Access-Control-Expose-Headers": "…"`` w ``app/``."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    found: dict[str, set[str]] = {}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "Access-Control-Expose-Headers"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    names = {h.strip() for h in value.value.split(",") if h.strip()}
                    found.setdefault(str(path.relative_to(root)), set()).update(names)
    return found


def test_every_route_exposed_header_is_on_global_cors_list() -> None:
    route_headers = _route_exposed_headers()
    assert route_headers, "strażnik nie znalazł żadnej trasy — zmieniony wzorzec?"
    global_list = {h.lower() for h in _global_cors_kwargs()["expose_headers"]}
    missing = {
        path: sorted(h for h in names if h.lower() not in global_list)
        for path, names in route_headers.items()
    }
    missing = {path: names for path, names in missing.items() if names}
    assert not missing, (
        "Te nagłówki trasy wystawiają frontowi, ale globalny CORS je nadpisuje — "
        f"dopisz je do expose_headers w app/main.py: {missing}"
    )
