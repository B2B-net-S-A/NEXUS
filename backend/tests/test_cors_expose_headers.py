"""FE-01: przeglądarka musi móc odczytać ``X-Export-Truncated`` przez CORS.

Bez tego nagłówka na liście ``Access-Control-Expose-Headers`` frontend na
innym originie niż API nigdy nie widzi informacji o obciętym eksporcie
klientów i pokazuje częściowy plik jak kompletny.
"""

from __future__ import annotations

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
