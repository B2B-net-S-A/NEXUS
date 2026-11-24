"""Sampler śladów Sentry backendu (limit spanów organizacji, 17.11.2026).

Funkcja czysta: dostaje ``sampling_context`` w kształcie, jaki buduje integracja
ASGI sentry-sdk 2.x, i zwraca prawdopodobieństwo. Bez sieci, bazy i SDK.
"""

from __future__ import annotations

import pytest

import app.main as main
from app.main import _traces_sampler


def _ctx(path: str, parent_sampled: bool | None = None) -> dict:
    return {
        "asgi_scope": {"type": "http", "path": path},
        "parent_sampled": parent_sampled,
        "transaction_context": {"op": "http.server"},
    }


@pytest.mark.parametrize(
    "path",
    ["/api/health", "/api/health/live", "/api/health/deep", "/health"],
)
def test_health_probes_are_never_traced(path: str) -> None:
    # Sonda Dockera co 15 s, uptime-probe i Grafana — ślad niczego nie mówi.
    assert _traces_sampler(_ctx(path)) == 0.0
    assert _traces_sampler(_ctx(path, parent_sampled=True)) == 0.0


def test_unsampled_browser_trace_is_not_resampled_by_backend() -> None:
    # Przeglądarka próbkuje 1% i wysyła `sentry-trace` z flagą 0: backend
    # nie może dorzucać swoich 10% do pozostałych 99% żądań.
    assert _traces_sampler(_ctx("/api/jobs", parent_sampled=False)) == 0.0


def test_sampled_browser_trace_continues_in_backend() -> None:
    assert _traces_sampler(_ctx("/api/jobs", parent_sampled=True)) == 1.0


def test_request_without_parent_uses_configured_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Webhooki i integracje nie niosą `sentry-trace`: zostaje stawka ze zmiennej.
    monkeypatch.setattr(main, "_TRACES_SAMPLE_RATE", 0.1)
    assert _traces_sampler(_ctx("/api/webhooks/m365")) == 0.1


def test_context_without_asgi_scope_uses_configured_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "_TRACES_SAMPLE_RATE", 0.1)
    assert _traces_sampler({"parent_sampled": None}) == 0.1


def test_browser_trace_headers_pass_cors() -> None:
    # Przeglądarka dokleja `sentry-trace` i `baggage` do każdego żądania API od
    # pierwszego, bez czekania na sondę (frontend/src/lib/telemetry-capability.ts,
    # 24.11.2026). Bez nich w `allow_headers` preflight odrzuca żądanie i każdy
    # ekran kończy się „Network Error”.
    cors = next(
        m for m in main.app.user_middleware if m.cls.__name__ == "CORSMiddleware"
    )
    allowed = {header.lower() for header in cors.kwargs["allow_headers"]}
    assert {"sentry-trace", "baggage"} <= allowed
