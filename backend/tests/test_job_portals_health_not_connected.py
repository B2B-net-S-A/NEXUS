"""Runda 10 (R10-N12-5): włączony portal bez połączonego konta to nie `healthy`.

``resolve_state`` zna stan ``not_connected`` (publikacja odmawia 409),
a ``checks.job_portals`` pokazywał ``healthy`` przy pustej tabeli połączeń.
"""

from __future__ import annotations

from app.core.config import settings
from app.services import job_portals


def _enable_jjit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PORTAL_JJIT_ENABLED", True)
    monkeypatch.setattr(settings, "PORTAL_JJIT_API_URL", "https://api.example.test")
    monkeypatch.setattr(settings, "JJIT_OAUTH_CLIENT_ID", "client")
    monkeypatch.setattr(settings, "JJIT_OAUTH_CLIENT_SECRET", "secret-1")
    monkeypatch.setattr(
        settings, "JJIT_OAUTH_REDIRECT_URI", "https://app.example.test/cb"
    )


def test_enabled_portal_without_connected_account_is_degraded(monkeypatch):
    _enable_jjit(monkeypatch)
    assert job_portals.health_state(0, connected=False) == "degraded"


def test_enabled_portal_with_connected_account_is_healthy(monkeypatch):
    _enable_jjit(monkeypatch)
    assert job_portals.health_state(0, connected=True) == "healthy"


def test_portal_without_connection_model_ignores_the_flag(monkeypatch):
    monkeypatch.setattr(settings, "PORTAL_JJIT_ENABLED", False)
    monkeypatch.setattr(settings, "PORTAL_ROCKETJOBS_ENABLED", False)
    monkeypatch.setattr(settings, "PORTAL_PRACUJ_ENABLED", True)
    monkeypatch.setattr(settings, "PORTAL_PRACUJ_API_URL", "https://api.example.test")
    monkeypatch.setattr(settings, "PORTAL_PRACUJ_API_KEY", "secret-1")
    assert job_portals.health_state(0, connected=False) == "healthy"
