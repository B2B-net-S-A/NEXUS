"""Produkcyjne `/openapi.json`, `/docs` i `/redoc` nie mogą być publiczne.

Zweryfikowane na żywej produkcji przy audycie: `/openapi.json` → HTTP 200,
1 392 735 bajtów, 747 ścieżek, 876 schematów. FastAPI emituje blok `security`
tylko dla operacji niosących zależność bearer, więc opublikowana specyfikacja
była maszynowo czytelnym spisem endpointów BEZ tokena wraz z kształtem ich
żądań — cała faza rekonesansu wydana za jednego anonimowego GET-a, wobec
systemu z ~49 tys. profili kandydatów. Host jest gray-cloud (`server: uvicorn`,
brak `cf-ray`), więc nie ma warstwy kompensacyjnej na brzegu.

`/docs` i `/redoc` i tak renderowały się pusto — `SecurityHeadersMiddleware`
wysyła `default-src 'none'`, co blokuje bundle z CDN-a i inline'owy bootstrap.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.main import app

BACKEND = Path(__file__).resolve().parents[1]


def test_doc_routes_absent_outside_debug() -> None:
    paths = {getattr(r, "path", None) for r in app.routes}
    exposed = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"} & paths
    if settings.DEBUG:
        # W dev-ie mają BYĆ — inaczej poprawka byłaby po prostu usunięciem funkcji.
        assert "/docs" in paths
        return
    assert not exposed, (
        f"na produkcji te trasy muszą zniknąć, a wciąż są: {sorted(exposed)}"
    )


def test_schema_can_still_be_built_in_process() -> None:
    """Trasa znika, METODA zostaje — testy analytics/M365 budują z niej schemat."""
    schema = app.openapi()
    assert schema["info"]["title"] == "Nexus ATS"
    assert schema["paths"], "schemat musi się nadal budować w procesie"


def test_gate_reads_the_debug_flag_not_a_hardcoded_constant() -> None:
    src = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert "_DOCS_ENABLED = settings.DEBUG" in src
    assert 'openapi_url="/openapi.json" if _DOCS_ENABLED else None' in src


def test_csp_comment_no_longer_claims_we_never_serve_html() -> None:
    """Ta przesłanka była nieprawdziwa i to ona kosztowała puste `/docs`.

    Aplikacja serwuje HTML z widoków wydruku kontraktu i CV; te doklejają WŁASNY
    nagłówek CSP, a `setdefault` im ustępuje. Komentarz mówiący coś innego uczy
    następnego czytelnika, że ten middleware HTML-a nie dotyczy.
    """
    src = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert "tight because we don't serve HTML here" not in src
