"""Traffit wyłączony na stałe (decyzja Artura 14.10.2026), kod usunięty 08.11.2026.

Te testy pilnują strażnika i flag oraz tego, co zostało: jednej trasy odczytu
statusu i sondy `checks.traffit`. Pełna ścieżka HTTP z logowaniem admina jest
w `test_fix48_ws08_admin_traffit_http.py` (wymaga Postgresa).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import admin_traffit
from app.core.config import Settings, settings
from app.services.traffit_retired import (
    TRAFFIT_RETIRED_MESSAGE,
    TRAFFIT_RETIRED_ON,
    TraffitRetiredError,
    refuse_traffit,
)
from tests.test_uptime_probe_health_checks import _payload, requires_jq
from tests.test_uptime_probe_health_checks import _run as _run_probe

MESSAGE = (
    "Traffit jest wyłączony od 14.10.2026 — NEXUS nie importuje już danych z Traffita."
)


# ── Strażnik i flagi ─────────────────────────────────────────────────────────


def test_guard_refuses_with_the_decision_message() -> None:
    assert TRAFFIT_RETIRED_MESSAGE == MESSAGE
    assert TRAFFIT_RETIRED_ON.isoformat() == "2026-10-14"
    with pytest.raises(TraffitRetiredError) as exc:
        refuse_traffit("test")
    assert str(exc.value) == MESSAGE
    assert exc.value.entry == "test"
    # Nie `RuntimeError`: `TraffitConfig.from_env()` zgłasza brak sekretów jako
    # RuntimeError i wołający łapią go jako „pomiń bieg” — wyłączenie nie może
    # się pod to podszyć.
    assert not isinstance(exc.value, RuntimeError)


def test_traffit_flags_stay_off_even_when_env_turns_them_on(monkeypatch) -> None:
    monkeypatch.setenv("TRAFFIT_SYNC_ENABLED", "true")
    monkeypatch.setenv("CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED", "true")
    fresh = Settings()
    assert fresh.TRAFFIT_SYNC_ENABLED is False
    assert fresh.CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED is False

    explicit = Settings(
        TRAFFIT_SYNC_ENABLED=True, CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED=True
    )
    assert explicit.TRAFFIT_SYNC_ENABLED is False
    assert explicit.CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED is False


# ── Moduł tras: został tylko odczyt statusu ──────────────────────────────────


def test_only_the_status_route_survives() -> None:
    routes = sorted(
        (sorted(route.methods), route.path) for route in admin_traffit.router.routes
    )
    assert routes == [(["GET"], "/sync/status")]


# ── Status i health: odczyt zostaje, bez łączenia się z Traffitem ────────────


class _FakeDb:
    async def execute(self, *_args, **_kwargs):
        return []

    async def scalar(self, *_args, **_kwargs):
        return 0


@pytest.mark.asyncio
async def test_status_payload_says_traffit_is_retired(monkeypatch) -> None:
    from app.services.traffit_status import read_traffit_status

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENABLED", True)
    body = await read_traffit_status(_FakeDb())
    assert body["enabled"] is False
    assert body["retired_on"] == "2026-10-14"
    assert body["retired_message"] == MESSAGE


@pytest.mark.asyncio
async def test_health_reports_traffit_disabled_without_reading_the_watermark(
    monkeypatch,
) -> None:
    """Flaga „włączona” i sekrety ustawione: stary kod szedł do bazy po
    `__daily__` (i bez bazy dawał `degraded`). Teraz stała wartość."""
    from app.main import app

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENABLED", True)
    monkeypatch.setenv("TRAFFIT_TENANT", "fikcyjny")
    monkeypatch.setenv("TRAFFIT_CLIENT_SECRET", "sekret")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        response = await ac.get("/api/health")

    assert response.json()["checks"]["traffit"] == "disabled"


@requires_jq
def test_disabled_traffit_check_does_not_page(tmp_path: Path) -> None:
    """`disabled` nie otwiera alarmu w uptime-probe (najwyżej ostrzeżenie,
    jak dotychczasowe `unconfigured`)."""
    code, outputs, annotations = _run_probe(tmp_path, _payload(traffit="disabled"))
    assert code == 0
    assert outputs.get("fail") == "0"
    assert not [a for a in annotations if a.startswith("::error") and "traffit" in a]
