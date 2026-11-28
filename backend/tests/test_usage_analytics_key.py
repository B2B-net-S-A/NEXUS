"""Klucz PostHog w sondzie `/api/health/live` tylko przy fladze i poprawnym formacie."""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.usage_analytics import usage_analytics_key

# Fikcyjny klucz w formacie projektu PostHog — nie istnieje.
KEY = "phc_" + "A1b2C3d4" * 5


def _settings(enabled: bool, key: str) -> SimpleNamespace:
    return SimpleNamespace(USAGE_ANALYTICS_ENABLED=enabled, POSTHOG_PROJECT_KEY=key)


def test_key_goes_out_only_with_the_flag_on():
    assert usage_analytics_key(_settings(True, KEY)) == KEY
    assert usage_analytics_key(_settings(False, KEY)) is None


@pytest.mark.parametrize(
    "key",
    [
        "",
        "   ",
        # Klucz osobisty ma odczyt danych projektu: nigdy do przeglądarki.
        "phx_" + "A1b2C3d4" * 5,
        "phc_short",
        KEY + "\n" + KEY,
        KEY + "<script>",
    ],
)
def test_a_malformed_or_personal_key_never_reaches_the_browser(key):
    assert usage_analytics_key(_settings(True, key)) is None


def test_surrounding_whitespace_from_the_vault_is_ignored():
    assert usage_analytics_key(_settings(True, f"  {KEY}\n")) == KEY


async def test_live_probe_carries_the_key_only_when_enabled(monkeypatch):
    from app.core.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "POSTHOG_PROJECT_KEY", KEY)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        monkeypatch.setattr(settings, "USAGE_ANALYTICS_ENABLED", False)
        off = (await client.get("/api/health/live")).json()
        monkeypatch.setattr(settings, "USAGE_ANALYTICS_ENABLED", True)
        on = (await client.get("/api/health/live")).json()

    assert off["usageAnalytics"] is None
    assert on["usageAnalytics"] == KEY
